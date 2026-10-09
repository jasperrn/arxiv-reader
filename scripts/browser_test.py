#!/usr/bin/env python3
"""Actual Chrome DOM/integration tests using only the Python standard library."""
import argparse
import json
from html.parser import HTMLParser
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

SMOKE = r'''
const assert = (value, message) => { if (!value) throw new Error(message); };
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
// Observe completion instead of sleeping: Chrome's virtual clock can advance
// through a timer while a File.text() read is still pending on real I/O.
function waitForDOM(predicate) {
  if (predicate()) return Promise.resolve();
  return new Promise(resolve => {
    const observer = new MutationObserver(() => {
      if (predicate()) { observer.disconnect(); resolve(); }
    });
    observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true});
  });
}
async function loaded() {
  for (let i = 0; i < 100; i++) { if (document.querySelector('#papers').dataset.ready === 'true' && document.querySelector('#count').textContent.includes('papers')) return; await pause(50); }
  throw new Error('App did not finish rendering');
}
async function runTests() {
 await loaded();
 assert(!document.body.textContent.includes('Unable to load'), 'Application load error');
 assert(document.querySelector('h1').textContent.length > 0, 'Title missing');
 assert(document.documentElement.scrollWidth <= window.innerWidth + 1, 'Horizontal overflow on mobile');
 assert(!window.browserErrors.length, window.browserErrors.join('\n'));
 TEST_BODY
 const result = document.createElement('pre'); result.id = 'browser-results'; result.dataset.success = 'true'; result.textContent = 'PASS: browser integration checks'; document.body.append(result);
}
runTests().catch(error => { const result = document.createElement('pre'); result.id = 'browser-results'; result.dataset.success = 'false'; result.textContent = error.stack; document.body.append(result); });
'''
FULL = r'''
 const count = () => document.querySelectorAll('article').length;
 const change = (id, value) => { const e = document.getElementById(id); if (e.type === 'checkbox') e.checked = value; else e.value = value; e.dispatchEvent(new Event(e.type === 'search' ? 'input' : 'change')); };
 assert(count() === 4, 'Demo must contain four deduplicated papers');
 assert(document.querySelectorAll('mark').length === 2, 'Followed author highlighting missing');
 change('mine', true); assert(count() === 1, 'My citations filter');
 change('tracked', true); assert(count() === 1, 'AND filters');
 change('combine', 'any'); assert(count() === 2, 'OR filters');
 change('provisional', false); assert(count() === 1, 'Confirmed-only filter');
 change('mine', false); change('tracked', false); change('provisional', true);
 change('combine', 'all'); change('followed', true); assert(count() === 2, 'Followed author filter'); change('followed', false);
 change('replacements', false); assert(count() === 3, 'Replacement filtering'); change('replacements', true);
 change('search', 'thermal'); assert(count() === 1, 'Text search'); change('search', '');
 change('sort', 'title'); assert(document.querySelector('h3').textContent.startsWith('A new'), 'Title sorting');
 change('sort', 'citations'); assert(document.querySelector('article').dataset.id === '2610.00001', 'Citation sorting');
 document.getElementById('expand').click(); assert([...document.querySelectorAll('.abstract')].every(e => e.open), 'Expand abstracts');
 document.getElementById('collapse').click(); assert([...document.querySelectorAll('.abstract')].every(e => !e.open), 'Collapse abstracts');
 const citation = document.querySelector('.citation-detail'); citation.open = true;
 assert(citation.textContent.includes('A framework for scattering'), 'Exact cited publication missing');
 const first = document.querySelector('article'); first.querySelector('.actions button').click();
 change('bookmarked', true); assert(count() === 1, 'Bookmark filter');
 assert(JSON.parse(localStorage.getItem('arxiv-reader-history-v1')).bookmarks['2610.00001'], 'Bookmark not persisted');
 document.querySelector('.actions button:nth-child(2)').click();
 change('unread', true); assert(count() === 0, 'Read tracking');
 change('unread', false); change('bookmarked', false);
 assert(JSON.parse(localStorage.getItem('arxiv-reader-history-v1')).read['2610.00001'], 'Reading history not persisted');
 change('date', '2026-10-08'); await loaded(); assert(count() === 1, 'Previous announcement date');
 change('date', 'all'); await loaded(); assert(count() === 4, 'All-date deduplication');
 if (window.testProfile) {
   assert(!document.getElementById('private-settings').hidden, 'Private settings form missing');
   document.getElementById('profile-clear').click();
   assert(!localStorage.getItem(`arxiv-reader-profile-v1:${location.pathname}`), 'Private settings not cleared');
   assert(document.querySelectorAll('mark').length === 0, 'Old author highlights survived clearing');
   change('mine', true); assert(count() === 0, 'Old citation matches survived clearing'); change('mine', false);
   const transfer = new DataTransfer(); transfer.items.add(new File([JSON.stringify(window.testProfile)], 'private-profile.yaml', {type:'application/yaml'}));
   const input = document.getElementById('profile-import'); input.files = transfer.files; input.dispatchEvent(new Event('change'));
   await waitForDOM(() => /^(Private configuration imported locally\.|Import failed:)/.test(document.getElementById('profile-status').textContent));
   assert(document.getElementById('profile-author').value === '42', 'Private file import failed: ' + document.getElementById('profile-status').textContent);
   change('mine', true); assert(count() === 1, 'Private citation matching after import'); change('mine', false);
   assert(window.requestedURLs.every(url => url.startsWith('data/')), 'Private import unexpectedly contacted an external service');
 }
 assert(!window.browserErrors.length, window.browserErrors.join('\n'));
'''


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class BrowserResult(HTMLParser):
    """Extract the assertion before Chrome's unrelated desktop-service stderr."""
    def __init__(self, dom):
        super().__init__()
        self.active = False
        self.success = False
        self.messages = []
        self.feed(dom)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'pre' and attrs.get('id') == 'browser-results':
            self.active = True
            self.success = attrs.get('data-success') == 'true'

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.messages.append(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--site', default='site')
    parser.add_argument('--profile-fixture', type=Path, help='Synthetic private profile for public-mode browser tests')
    parser.add_argument('--smoke', action='store_true', help='Validate real site without demo-specific assertions')
    parser.add_argument('--screenshots', default=None)
    args = parser.parse_args()
    chrome = next((shutil.which(p) for p in ('google-chrome', 'chromium', 'chromium-browser') if shutil.which(p)), None)
    if not chrome:
        raise SystemExit('Browser checks require Chrome or Chromium; install one or use the GitHub Actions test workflow.')
    with tempfile.TemporaryDirectory(prefix='arxiv-browser-') as tmp:
        root = Path(tmp)
        # A subpath detects accidental absolute asset/data paths on GitHub Pages.
        site = root / 'reader'
        shutil.copytree(args.site, site)
        index = (site / 'index.html').read_text()
        index = index.replace('<script src="app.js" defer></script>', '<script src="errors.js"></script><script src="app.js" defer></script><script src="checks.js" defer></script>')
        (site / 'index.html').write_text(index)
        setup = "window.browserErrors=[];window.addEventListener('error',e=>window.browserErrors.push(e.message));window.addEventListener('unhandledrejection',e=>window.browserErrors.push(String(e.reason)));"
        if args.profile_fixture:
            fixture = json.loads(args.profile_fixture.read_text())
            setup += 'window.testProfile=' + json.dumps(fixture) + ';window.testProfile._reader_cache.updated_at=new Date().toISOString();localStorage.setItem(`arxiv-reader-profile-v1:${location.pathname}`, JSON.stringify(window.testProfile));'
        setup += "window.requestedURLs=[];const originalFetch=window.fetch;window.fetch=(url,...args)=>{window.requestedURLs.push(String(url));return originalFetch(url,...args);};"
        (site / 'errors.js').write_text(setup)
        (site / 'checks.js').write_text(SMOKE.replace('TEST_BODY', '' if args.smoke else FULL))
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        except PermissionError as exc:
            raise SystemExit('Browser checks blocked: this environment forbids local sockets. Run this command on your computer or in GitHub Actions.') from exc
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for width in (1280, 390):
                command = [chrome, '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking',
                           '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', f'--user-data-dir={root / ("profile-" + str(width))}',
                           f'--window-size={width},1000', '--virtual-time-budget=15000', '--dump-dom']
                if args.screenshots:
                    dest = Path(args.screenshots).resolve()
                    dest.mkdir(parents=True, exist_ok=True)
                    command.append(f'--screenshot={dest / (str(width) + ".png")}')
                command.append(f'http://127.0.0.1:{server.server_port}/reader/')
                result = subprocess.run(command, text=True, capture_output=True, timeout=60)
                outcome = BrowserResult(result.stdout)
                if result.returncode or not outcome.success:
                    print(result.stdout[-5000:])
                    print(result.stderr[-3000:])
                    detail = ''.join(outcome.messages) or 'No completion result: browser checks did not finish within the execution budget.'
                    raise SystemExit(f'Browser tests failed at {width}px (Chrome exit {result.returncode}):\n{detail}')
                print(f'PASS: Chrome {width}px, repository subpath, ' + ('smoke checks' if args.smoke else 'filters, search, sorting, citations, history, dates, responsive layout'))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
