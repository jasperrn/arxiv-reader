from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
from urllib.error import HTTPError, URLError
import hashlib
import json
import subprocess
import sys
import unittest

from reader.arxiv import arxiv_id, merge_papers, parse_feed
from reader.build import build, validate_site
from reader.config import DEFAULTS, ConfigError, load_config
from reader.demo import DemoClient, TARGET, OTHER, rss
from reader.http import Client, FetchError, trim_inspire
from reader.inspire import (Inspire, combine_targets, match_authors, match_citations,
                            publication, text_identifiers)
from reader.pipeline import update
from reader.storage import read_json, write_json

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


class ConfigTests(TestCase):
    def load(self, value):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.yaml'
            p.write_text(value)
            return load_config(p)

    def test_working_example(self):
        self.assertEqual(load_config('config.example.yaml')['categories'], ['hep-ph', 'hep-th'])

    def test_defaults(self):
        self.assertEqual(self.load('{}')['updates']['recheck_days'], 30)

    def test_arbitrary_category_families(self):
        cfg = self.load('categories: [hep-ph, physics.optics, physics.acc-ph, astro-ph.CO, cs.LG, math.AG, econ.EM]')
        self.assertEqual(len(cfg['categories']), 7)

    def test_all_identifiers(self):
        cfg = self.load('inspire_author_id: E.Witten.1\ntracked_publications:\n - arxiv: hep-th/9711200v3\n - doi: 10.1234/example\n - inspire: 451647\nfollowed_authors:\n - name: Edward Witten\n   inspire_id: 1000\n   aliases: [Ed Witten]\n')
        self.assertEqual(cfg['followed_authors'][0]['inspire_id'], '1000')

    def test_invalid_settings(self):
        cases = ['categories: []', 'categories: [hep-th, hep-th]', 'categories: [not valid]', 'categories: null',
                 'catgories: [hep-th]', 'display: []', 'display: {abstracts_expanded: "false"}',
                 'updates: {recheck_days: 0}', 'updates: {max_papers_per_run: true}',
                 'inspire_author_id: "a OR b"', 'inspire_author_id: false', 'followed_authors: [Witten]',
                 'followed_authors: [{name: A, aliases: abc}]', 'tracked_publications: [{arxiv: nope}]',
                 'tracked_publications: [{inspire: 2, doi: "10.1234/a"}]', 'categories: [hep-th]\ncategories: [hep-ph]',
                 'updates: {typo: 3}', 'display: {default_sort: random}', 'tracked_publications: null', '']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.load(text)

    def test_unsafe_yaml(self):
        with self.assertRaises(ConfigError):
            self.load('!!python/object/apply:os.system [echo unsafe]')


class ArxivTests(TestCase):
    def test_normalize_identifiers(self):
        for value in ('arXiv:2601.12345v2', 'https://arxiv.org/abs/2601.12345v3', '2601.12345'):
            self.assertEqual(arxiv_id(value), '2601.12345')
        self.assertEqual(arxiv_id('https://arxiv.org/pdf/hep-th/9711200v2.pdf'), 'hep-th/9711200')

    def test_dates_types_and_order(self):
        day, papers = parse_feed(rss('hep-ph'), 'hep-ph')
        self.assertEqual(day, '2026-10-09')
        self.assertEqual([p['announcements'][0]['type'] for p in papers], ['new', 'cross', 'replace', 'new'])
        self.assertEqual(papers[0]['version'], 1)
        self.assertNotIn('Announce Type', papers[0]['abstract'])
        self.assertEqual(papers[0]['authors'][0]['name'], 'Mira Chen')

    def test_dedup_preserves_category_provenance(self):
        _, first = parse_feed(rss('hep-ph'), 'hep-ph')
        _, second = parse_feed(rss('hep-th'), 'hep-th')
        result = merge_papers(first + second, ['hep-ph', 'hep-th'])
        self.assertEqual(len(result), 4)
        self.assertEqual([a['type'] for a in result[0]['announcements']], ['new', 'cross'])
        self.assertEqual([p['id'] for p in result], [p['id'] for p in first])

    def test_category_filter(self):
        self.assertEqual(parse_feed(rss('hep-ph'), 'math.AG')[1], [])
        papers = parse_feed(rss('hep-ph'), 'hep-ph')[1]
        self.assertEqual(merge_papers(papers, ['math.AG']), [])

    def test_missing_dates_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed('<rss><channel><title>x</title></channel></rss>', 'hep-ph')

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(rss('hep-ph').replace('<arxiv:announce_type>new', '<arxiv:announce_type>unknown'), 'hep-ph')

    def test_empty_weekend_feed(self):
        xml = '<rss><channel><pubDate>Sat, 10 Oct 2026 00:00:00 -0400</pubDate></channel></rss>'
        self.assertEqual(parse_feed(xml, 'hep-th'), ('2026-10-10', []))

    def test_item_announcement_date(self):
        xml = rss('hep-th').replace('<pubDate>Fri, 09 Oct 2026 00:00:00 -0400</pubDate><arxiv:', '<pubDate>Thu, 08 Oct 2026 00:00:00 -0400</pubDate><arxiv:')
        self.assertEqual(parse_feed(xml, 'hep-th')[1][0]['date'], '2026-10-08')


class CitationTests(TestCase):
    def setUp(self):
        self.targets = [publication(TARGET, 'mine'), publication(OTHER, 'tracked')]

    def test_confirmed_linked_record(self):
        meta = {'references': [{'record': {'$ref': 'https://inspirehep.net/api/literature/100'}}]}
        result = match_citations(meta, self.targets)
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['matches'][0]['publication']['title'], 'A framework for scattering amplitudes (demo)')
        self.assertEqual(result['matches'][0]['publication']['groups'], ['mine'])

    def test_confirmed_structured_arxiv_and_doi(self):
        meta = {'references': [{'reference': {'arxiv_eprint': '2101.00002v3'}}, {'reference': {'dois': ['10.1234/DEMO']}}]}
        self.assertEqual(len(match_citations(meta, self.targets)['matches']), 2)

    def test_raw_reference_provisional(self):
        meta = {'references': [{'raw_refs': [{'value': 'See arXiv:2001.00001v3'}]}]}
        self.assertEqual(match_citations(meta, self.targets)['status'], 'provisional')

    def test_html_bibliography_only(self):
        html = '<p>Discussed in 2001.00001</p><ul><li class="ltx_bibitem"><span>Ref</span><a href="https://arxiv.org/abs/2101.00002">paper</a></li></ul>'
        result = match_citations({}, self.targets, html)
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['matches'][0]['publication']['groups'], ['tracked'])
        self.assertEqual(result['status'], 'provisional')
        self.assertFalse(result['references_available'])

    def test_no_substring_false_positive(self):
        self.assertNotIn('arxiv:2001.00001', text_identifiers('2001.000012 12001.00001 prefix2001.00001'))
        self.assertNotIn('doi:10.1234/demo', text_identifiers('10.1234/demo2'))

    def test_terminal_punctuation(self):
        self.assertIn('arxiv:2001.00001', text_identifiers('Ref. arXiv:2001.00001.'))

    def test_old_identifier(self):
        self.assertIn('arxiv:hep-th/9711200', text_identifiers('hep-th/9711200v2'))

    def test_missing_empty_and_no_match(self):
        for meta in ({}, {'references': []}):
            self.assertEqual(match_citations(meta, self.targets)['status'], 'unavailable')
        self.assertEqual(match_citations({'references': [{'reference': {'arxiv_eprint': '2000.12345'}}]}, self.targets)['status'], 'checked')

    def test_confirmed_wins_over_provisional(self):
        meta = {'references': [{'record': {'$ref': 'https://inspirehep.net/api/literature/100'}, 'raw_refs': [{'value': '2001.00001'}]}]}
        result = match_citations(meta, self.targets, '<li class="ltx_bibitem">2001.00001</li>')
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['status'], 'confirmed')

    def test_target_alias_groups(self):
        result = combine_targets([publication(TARGET, 'mine'), publication(None, 'tracked', {'arxiv': '2001.00001'})])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['groups'], ['mine', 'tracked'])
        self.assertTrue(result[0]['resolved'])


class AuthorTests(TestCase):
    def setUp(self):
        self.authors = [{'name': 'Mira Chen'}, {'name': 'M. Chen'}]
        self.followed = [{'name': 'Mira Chen', 'resolved_id': '42'}]
        self.meta = {'authors': [{'full_name': 'Chen, Mira', 'record': {'$ref': 'https://inspirehep.net/api/authors/42'}}]}

    def test_confirmed_id(self):
        authors = match_authors(self.authors, self.meta, self.followed)
        self.assertEqual(authors[0]['match'], 'confirmed')
        self.assertFalse(authors[1]['followed'])

    def test_name_only_is_provisional(self):
        self.assertEqual(match_authors(self.authors, {}, self.followed)[0]['match'], 'provisional')

    def test_known_different_id_not_highlighted(self):
        self.followed[0]['resolved_id'] = '123'
        self.assertFalse(match_authors(self.authors, self.meta, self.followed)[0]['followed'])

    def test_explicit_alias(self):
        self.followed[0]['aliases'] = ['M. Chen']
        self.assertEqual(match_authors(self.authors, {}, self.followed)[1]['match'], 'provisional')

    def test_id_without_name_guessing(self):
        self.followed[0]['name'] = 'A different spelling'
        self.assertEqual(match_authors(self.authors, self.meta, self.followed)[0]['match'], 'confirmed')


class InspireTests(TestCase):
    def test_pagination(self):
        client = mock.Mock()
        client.json.side_effect = [{'hits': {'total': 2, 'hits': [TARGET]}}, {'hits': {'total': {'value': 2}, 'hits': [OTHER]}}]
        results = Inspire(client, DEFAULTS['updates']).search('literature', 'a E.Witten.1')
        self.assertEqual(len(results), 2)
        self.assertIn('page=2', client.json.call_args[0][0])

    def test_large_query_not_silently_truncated(self):
        client = mock.Mock()
        client.json.return_value = {'hits': {'total': 10001, 'hits': []}}
        with self.assertRaises(FetchError):
            Inspire(client, DEFAULTS['updates']).search('literature', 'a x')

    def test_author_bai(self):
        client = mock.Mock()
        client.json.return_value = {'hits': {'total': 1, 'hits': [{'metadata': {'control_number': 42}}]}}
        self.assertEqual(Inspire(client, DEFAULTS['updates']).resolve_author('M.Chen.1'), '42')


class HttpTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = Client(self.tmp.name, 'tests')
        self.url = 'https://inspirehep.net/api/arxiv/2001.00001'

    def cache(self, body='{}', fetched=0, status=200):
        write_json(Path(self.tmp.name) / (hashlib.sha256(self.url.encode()).hexdigest() + '.json'),
                   {'body': body, 'fetched': fetched, 'status': status, 'etag': 'test'})

    def test_fresh_cache_avoids_request(self):
        import time
        self.cache(fetched=time.time())
        with mock.patch('reader.http.urlopen') as request:
            self.assertEqual(self.client.json(self.url), {})
            request.assert_not_called()

    def test_negative_cache(self):
        with mock.patch('reader.http.urlopen', side_effect=HTTPError(self.url, 404, 'missing', {}, None)) as request:
            self.assertIsNone(self.client.get(self.url))
            self.assertIsNone(self.client.get(self.url))
            self.assertEqual(request.call_count, 1)

    def test_stale_on_outage(self):
        self.cache()
        with mock.patch('reader.http.urlopen', side_effect=URLError('offline')), mock.patch('reader.http.time.sleep'):
            self.assertEqual(self.client.get(self.url), '{}')
            self.assertIn(self.url, self.client.stale_urls)

    def test_feed_failure_cannot_be_current_capture(self):
        self.cache()
        with mock.patch('reader.http.urlopen', side_effect=URLError('offline')), mock.patch('reader.http.time.sleep'):
            with self.assertRaises(FetchError):
                self.client.get(self.url, stale=False)

    def test_rate_limit_retry(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        response.__enter__.return_value.headers = {}
        with mock.patch('reader.http.urlopen', side_effect=[HTTPError(self.url, 429, 'rate limit', {'Retry-After': '7'}, None), response]), mock.patch('reader.http.time.sleep') as sleep:
            self.assertEqual(self.client.json(self.url), {})
            self.assertIn(mock.call(7.0), sleep.call_args_list)

    def test_long_retry_after_deferred(self):
        with mock.patch('reader.http.urlopen', side_effect=HTTPError(self.url, 429, 'rate limit', {'Retry-After': '100'}, None)) as request, mock.patch('reader.http.time.sleep'):
            with self.assertRaises(FetchError):
                self.client.get(self.url)
            self.assertEqual(request.call_count, 1)

    def test_etag_revalidation(self):
        self.cache()
        with mock.patch('reader.http.urlopen', side_effect=HTTPError(self.url, 304, 'not modified', {}, None)) as request:
            self.assertEqual(self.client.get(self.url), '{}')
            self.assertEqual(request.call_args[0][0].get_header('If-none-match'), 'test')

    def test_bibliography_cache_does_not_store_full_text(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'<p>PRIVATE FULL TEXT</p><li class="ltx_bibitem">Copyrighted prose 2001.00001</li>'
        response.__enter__.return_value.headers = {}
        with mock.patch('reader.http.urlopen', return_value=response):
            body = self.client.get('https://arxiv.org/html/2610.00001')
        self.assertNotIn('PRIVATE FULL TEXT', body)
        self.assertNotIn('Copyrighted prose', body)
        self.assertIn('2001.00001', body)

    def test_cached_metadata_excludes_contact_details(self):
        data = {'metadata': {'control_number': 42, 'emails': ['private@example.org'],
                             'authors': [{'full_name': 'A Researcher', 'emails': ['private@example.org']}]}}
        self.assertNotIn('private@example.org', trim_inspire(json.dumps(data)))

    def test_host_outage_defers_subsequent_requests(self):
        with mock.patch('reader.http.urlopen', side_effect=URLError('offline')) as request, mock.patch('reader.http.time.sleep'):
            for identifier in ('2001.00001', '2001.00002'):
                with self.assertRaises(FetchError):
                    self.client.get('https://inspirehep.net/api/arxiv/' + identifier)
            self.assertEqual(request.call_count, 3)

    def test_unexpected_host_rejected(self):
        with self.assertRaises(FetchError):
            self.client.get('https://example.org/arxiv')


class PipelineTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = deepcopy(DEFAULTS)
        self.cfg['inspire_author_id'] = '42'
        self.cfg['followed_authors'] = [{'name': 'Mira Chen', 'inspire_id': '42'}]
        self.cfg['tracked_publications'] = [{'inspire': '200'}]
        self.client = DemoClient()

    def update(self, **kwargs):
        return update(self.cfg, self.root / 'state', client=self.client, now=kwargs.pop('now', NOW), **kwargs)

    def papers(self):
        return read_json(self.root / 'state/days/2026-10-09.json')['papers']

    def test_complete_pipeline_and_site(self):
        status = self.update()
        self.assertEqual(status['feeds_succeeded'], 2)
        self.assertEqual([p['citation']['status'] for p in self.papers()], ['confirmed', 'provisional', 'checked', 'unavailable'])
        manifest = build(self.cfg, self.root / 'state', self.root / 'site')
        self.assertEqual(manifest['days'][0]['count'], 4)
        self.assertEqual(validate_site(self.root / 'site'), 1)

    def test_repeated_feed_does_not_duplicate_or_lose_highlights(self):
        self.update()
        self.update(now=NOW + timedelta(hours=1))
        papers = self.papers()
        self.assertEqual(len(papers), 4)
        self.assertEqual(len(papers[0]['announcements']), 2)
        self.assertEqual(papers[0]['authors'][0]['match'], 'confirmed')
        self.assertEqual(papers[0]['citation']['checked_at'], NOW.isoformat())

    def test_delayed_references_rechecked(self):
        self.update()
        original = self.client.json
        def delayed(url, **kwargs):
            if url.endswith('/arxiv/2610.00004'):
                return {'metadata': {'references': [{'record': {'$ref': 'https://inspirehep.net/api/literature/100'}}]}}
            return original(url, **kwargs)
        self.client.json = delayed
        self.update(now=NOW + timedelta(days=1))
        self.assertEqual(self.papers()[3]['citation']['status'], 'confirmed')

    def test_network_failures_preserve_archive(self):
        self.update()
        self.client.get = mock.Mock(side_effect=FetchError('offline'))
        self.client.json = mock.Mock(side_effect=FetchError('offline'))
        status = self.update(now=NOW + timedelta(days=1))
        self.assertEqual(status['feeds_succeeded'], 0)
        self.assertTrue(status['warnings'])
        self.assertEqual(self.papers()[0]['citation']['status'], 'confirmed')
        self.assertTrue(self.papers()[0]['citation']['stale'])

    def test_partial_category_outage(self):
        original = self.client.get
        self.client.get = lambda url, **kw: (_ for _ in ()).throw(FetchError('offline')) if url.endswith('/hep-th') else original(url, **kw)
        self.assertEqual(self.update()['feeds_succeeded'], 1)
        day = read_json(self.root / 'state/days/2026-10-09.json')
        self.assertEqual(list(day['sources']), ['hep-ph'])

    def test_fair_budget_eventually_covers_every_paper(self):
        self.cfg['updates']['max_papers_per_run'] = 1
        for n in range(4):
            self.update(now=NOW + timedelta(minutes=n))
        self.assertTrue(all(p.get('metadata_checked_at') for p in self.papers()))

    def test_bibliography_budget_rotates(self):
        self.cfg['updates']['max_bibliographies_per_run'] = 1
        for n in range(4):
            self.update(now=NOW + timedelta(days=n))
        self.assertTrue(all(p['citation'].get('bibliography_checked_at') for p in self.papers()))
        self.assertEqual(self.papers()[1]['citation']['status'], 'provisional')

    def test_previous_html_evidence_retained_between_budgeted_checks(self):
        self.update()
        self.cfg['updates']['max_bibliographies_per_run'] = 1
        self.update(now=NOW + timedelta(days=1))
        result = self.papers()[1]['citation']
        self.assertEqual(result['status'], 'provisional')
        self.assertEqual(result['bibliography_checked_at'], NOW.isoformat())

    def test_config_change_removes_old_citation_matches(self):
        self.update()
        self.cfg['inspire_author_id'] = None
        self.cfg['tracked_publications'] = []
        self.cfg['updates']['max_papers_per_run'] = 1
        self.update(now=NOW + timedelta(hours=1))
        self.assertTrue(all(not p['citation']['matches'] for p in self.papers()))

    def test_import_saved_feed(self):
        feeds = {}
        for category in self.cfg['categories']:
            path = self.root / (category + '.xml')
            path.write_text(rss(category))
            feeds[category] = path
        self.assertEqual(self.update(feed_files=feeds)['feeds_succeeded'], 2)

    def test_build_escapes_configuration(self):
        self.update()
        self.cfg['display']['title'] = '<script>alert(1)</script>'
        build(self.cfg, self.root / 'state', self.root / 'site')
        html = (self.root / 'site/index.html').read_text()
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;', html)

    def test_empty_site_valid(self):
        build(self.cfg, self.root / 'state', self.root / 'site')
        self.assertEqual(validate_site(self.root / 'site'), 0)

    def test_corrupt_archive_fails_visibly(self):
        path = self.root / 'state/days/2026-10-09.json'
        path.parent.mkdir(parents=True)
        path.write_text('not JSON')
        with self.assertRaisesRegex(ValueError, 'restore it'):
            self.update()


class ArchiveGitTests(TestCase):
    def test_token_is_scoped_and_never_written_to_command(self):
        import os
        import base64
        from scripts import archive
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'test-secret',
                'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'test.existing',
                'GIT_CONFIG_VALUE_0': 'retained'}, clear=True), \
                mock.patch.object(archive.subprocess, 'run') as run:
            archive.git('push', 'origin', 'HEAD:refs/heads/data', cwd='/tmp')
        args, kwargs = run.call_args
        self.assertNotIn('test-secret', repr(args))
        env = kwargs['env']
        self.assertNotIn('GITHUB_TOKEN', env)
        self.assertEqual(env['GIT_CONFIG_COUNT'], '3')
        self.assertEqual(env['GIT_CONFIG_VALUE_0'], 'retained')
        self.assertEqual(env['GIT_CONFIG_KEY_1'], 'http.https://github.com/.extraheader')
        self.assertEqual(env['GIT_CONFIG_VALUE_1'], '')
        self.assertEqual(env['GIT_CONFIG_KEY_2'], env['GIT_CONFIG_KEY_1'])
        encoded = env['GIT_CONFIG_VALUE_2'].split()[-1]
        self.assertEqual(base64.b64decode(encoded).decode(), 'x-access-token:test-secret')
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')

    def test_existing_checkout_header_is_reset_in_real_git_config(self):
        import os
        from scripts import archive
        with TemporaryDirectory() as tmp:
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            key = 'http.https://github.com/.extraheader'
            subprocess.run(['git', 'config', key, 'AUTHORIZATION: basic old'], cwd=tmp, check=True)
            with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'test-secret'}):
                values = archive.git('config', '--get-all', key, cwd=tmp, capture=True).splitlines()
            self.assertEqual(values[0], 'AUTHORIZATION: basic old')
            self.assertEqual(values[1], '')
            self.assertTrue(values[2].startswith('AUTHORIZATION: basic '))
            self.assertEqual(len(values), 3)
            # Process-only override leaves the checkout credential untouched.
            stored = subprocess.check_output(['git', 'config', '--local', '--get-all', key], cwd=tmp, text=True)
            self.assertEqual(stored.strip(), 'AUTHORIZATION: basic old')

    def test_http_request_sends_exactly_one_authorization_header(self):
        import os
        import base64
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from scripts import archive
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get_all('Authorization', []))
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-git-upload-pack-advertisement')
                self.end_headers()
                self.wfile.write(b'001e# service=git-upload-pack\n00000000')
            def log_message(self, *args):
                pass
        try:
            server = HTTPServer(('127.0.0.1', 0), Handler)
        except PermissionError:
            self.skipTest('Sandbox forbids listening sockets; HTTP regression runs in CI')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with TemporaryDirectory() as tmp:
                url = f'http://127.0.0.1:{server.server_port}'
                subprocess.run(['git', 'init', '-q', tmp], check=True)
                subprocess.run(['git', 'config', f'http.{url}/.extraheader',
                                'AUTHORIZATION: basic old'], cwd=tmp, check=True)
                with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'test-secret', 'GITHUB_SERVER_URL': url}):
                    archive.git('ls-remote', url + '/repo', cwd=tmp, capture=True)
                expected = 'AUTHORIZATION: basic ' + base64.b64encode(b'x-access-token:test-secret').decode()
                self.assertEqual(received, [[expected.split(': ', 1)[1]]])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_data_branch_roundtrip(self):
        script = str(Path('scripts/archive.py').resolve())
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args, cwd=None):
                return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout
            remote = root / 'remote.git'
            source = root / 'source'
            git('init', '--bare', str(remote))
            git('init', '-b', 'main', str(source))
            git('remote', 'add', 'origin', str(remote), cwd=source)
            state = root / 'state'
            for action in ('load', 'save'):
                if action == 'save':
                    write_json(state / 'days/2026-10-09.json', {'date': '2026-10-09'})
                result = subprocess.run([sys.executable, script, action, '--state', str(state)], cwd=source, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            restored = root / 'restored'
            result = subprocess.run([sys.executable, script, 'load', '--state', str(restored)], cwd=source, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(read_json(restored / 'days/2026-10-09.json')['date'], '2026-10-09')


class PublisherTests(TestCase):
    def test_bootstrap_verifies_and_extracts_only_cli(self):
        import io
        import os
        import tarfile
        from scripts import publish
        buffer = io.BytesIO()
        payload = b'fake executable for test'
        with tarfile.open(fileobj=buffer, mode='w:gz') as package:
            item = tarfile.TarInfo('gh_1.0_linux_amd64/bin/gh')
            item.size = len(payload)
            package.addfile(item, io.BytesIO(payload))
        body = buffer.getvalue()
        metadata = {'assets': [{'name': 'gh_1.0_linux_amd64.tar.gz', 'browser_download_url': 'https://github.com/archive'},
                               {'name': 'gh_1.0_checksums.txt', 'browser_download_url': 'https://github.com/checksums'}]}
        values = [json.dumps(metadata).encode(), (hashlib.sha256(body).hexdigest() + '  gh_1.0_linux_amd64.tar.gz').encode(), body]
        def response(*args, **kwargs):
            context = mock.MagicMock()
            context.__enter__.return_value.read.return_value = values.pop(0)
            return context
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'cli'
            dest.mkdir()
            with mock.patch.object(publish.shutil, 'which', return_value=None), mock.patch.object(publish.platform, 'machine', return_value='x86_64'), mock.patch.object(publish.platform, 'system', return_value='Linux'), mock.patch.object(publish, 'urlopen', side_effect=response), mock.patch.object(publish.tempfile, 'mkdtemp', return_value=str(dest)), mock.patch.object(publish, 'command') as execute, mock.patch.dict(os.environ):
                publish.ensure_github_cli()
                self.assertEqual((dest / 'gh').read_bytes(), payload)
                execute.assert_called_once_with(['gh', '--version'])

    def test_bootstrap_rejects_bad_checksum(self):
        from scripts import publish
        metadata = {'assets': [{'name': 'gh_1_linux_amd64.tar.gz', 'browser_download_url': 'https://github.com/archive'},
                               {'name': 'gh_1_checksums.txt', 'browser_download_url': 'https://github.com/checksums'}]}
        values = [json.dumps(metadata).encode(), b'bad  gh_1_linux_amd64.tar.gz', b'archive']
        def response(*args, **kwargs):
            context = mock.MagicMock()
            context.__enter__.return_value.read.return_value = values.pop(0)
            return context
        with mock.patch.object(publish.shutil, 'which', return_value=None), mock.patch.object(publish.platform, 'machine', return_value='x86_64'), mock.patch.object(publish.platform, 'system', return_value='Linux'), mock.patch.object(publish, 'urlopen', side_effect=response), mock.patch.object(publish, 'command') as execute:
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                publish.ensure_github_cli()
            execute.assert_not_called()


class PublicPrivacyTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = deepcopy(DEFAULTS)

    def collect(self):
        return update(self.cfg, self.root / 'state', client=DemoClient(), now=NOW, public=True)

    def test_public_pipeline_has_references_without_personal_matching(self):
        self.assertTrue(self.collect()['public_mode'])
        papers = read_json(self.root / 'state/days/2026-10-09.json')['papers']
        self.assertIn('inspire:100', papers[0]['public_data']['evidence'][0]['identifiers'])
        self.assertTrue(papers[0]['public_data']['references_available'])
        self.assertFalse(papers[0]['citation']['matches'])
        self.assertFalse(any(a.get('followed') for a in papers[0]['authors']))
        self.assertEqual(read_json(self.root / 'state/targets.json')['targets'], [])
        manifest = build(self.cfg, self.root / 'state', self.root / 'site', public=True)
        self.assertEqual(manifest['personalization'], 'browser')
        self.assertEqual(validate_site(self.root / 'site'), 1)

    def test_interrupted_public_collection_can_resume(self):
        client = DemoClient()
        client.json = mock.Mock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            update(self.cfg, self.root / 'state', client=client, now=NOW, public=True)
        self.assertTrue(read_json(self.root / 'state/status.json')['public_mode'])
        self.assertEqual(len(read_json(self.root / 'state/days/2026-10-09.json')['papers']), 4)
        self.assertTrue(self.collect()['public_mode'])

    def test_javascript_private_profile_logic(self):
        import ctypes.util
        if not (ctypes.util.find_library('javascriptcoregtk-4.1') or ctypes.util.find_library('javascriptcoregtk-6.0')):
            self.skipTest('JavaScriptCore unavailable; Chrome suite covers browser logic in CI')
        result = subprocess.run([sys.executable, 'scripts/check_profile_logic.py'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_collection_refuses_personal_settings(self):
        self.cfg['inspire_author_id'] = '123456'
        with self.assertRaisesRegex(ValueError, 'anonymous'):
            self.collect()

    def test_private_archive_cannot_be_republished_as_public(self):
        update(self.cfg, self.root / 'state', client=DemoClient(), now=NOW)
        with self.assertRaisesRegex(ValueError, 'personalized archive'):
            self.collect()
        with self.assertRaisesRegex(ValueError, 'Public builds require'):
            build(self.cfg, self.root / 'state', self.root / 'site', public=True)

    def test_public_build_strips_personal_fields(self):
        self.collect()
        path = self.root / 'state/days/2026-10-09.json'
        data = read_json(path)
        data['private_profile'] = 'PRIVATE_ONLY_SENTINEL'
        data['papers'][0]['private_profile'] = 'PRIVATE_ONLY_SENTINEL'
        data['papers'][0]['citation']['matches'] = [{'private': 'PRIVATE_ONLY_SENTINEL'}]
        data['papers'][0]['authors'][0].update(followed=True, private='PRIVATE_ONLY_SENTINEL')
        write_json(path, data)
        build(self.cfg, self.root / 'state', self.root / 'site', public=True)
        output = ''.join(p.read_text() for p in (self.root / 'site').rglob('*') if p.is_file())
        self.assertNotIn('PRIVATE_ONLY_SENTINEL', output)
        self.assertNotIn('target_signature', read_json(self.root / 'site/data/2026-10-09.json')['papers'][0])

    def test_source_staging_excludes_private_files(self):
        from scripts.publish import prepare
        staging = prepare(self.root / 'release')
        self.assertFalse((staging / 'config.yaml').exists())
        self.assertFalse((staging / 'private-profile.yaml').exists())
        self.assertIsNone(load_config(staging / 'config.example.yaml')['inspire_author_id'])
        with self.assertRaisesRegex(RuntimeError, 'empty directory'):
            prepare(staging)

    def test_offline_private_profile_export(self):
        from reader.profile import export_profile
        self.cfg['inspire_author_id'] = '123456'
        path = self.root / 'private.yaml'
        export_profile(self.cfg, path, settings_only=True)
        self.assertEqual(read_json(path)['inspire_author_id'], '123456')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_resolved_private_profile_export(self):
        from reader.profile import export_profile
        self.cfg['inspire_author_id'] = '42'
        path = self.root / 'private.yaml'
        with mock.patch('reader.profile.Client', return_value=DemoClient()):
            export_profile(self.cfg, path)
        self.assertEqual(len(read_json(path)['_reader_cache']['targets']), 1)
        self.assertEqual(load_config(path)['inspire_author_id'], '42')


if __name__ == '__main__':
    unittest.main()
