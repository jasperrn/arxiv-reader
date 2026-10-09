"""Serial requests, bounded retries, conditional HTTP caching, and negative caching."""
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path
from .storage import read_json, write_json

log = logging.getLogger(__name__)


def trim_inspire(text):
    """Store only the metadata used by the reader; discard contact details."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError('expected a JSON object')
        records = data.get('hits', {}).get('hits', []) if 'hits' in data else [data]
        for record in records:
            if 'metadata' not in record:
                continue
            metadata = record['metadata']
            record['metadata'] = {k: v for k, v in metadata.items() if k in
                                  {'control_number', 'titles', 'arxiv_eprints', 'dois', 'authors', 'references', 'ids', 'name'}}
            if 'authors' in record['metadata']:
                record['metadata']['authors'] = [{k: a[k] for k in ('full_name', 'record', 'alternative_names') if k in a}
                                                 for a in metadata['authors']]
        return json.dumps(data, ensure_ascii=False)
    except (ValueError, TypeError, AttributeError) as exc:
        raise FetchError(f'Invalid INSPIRE response: {exc}') from exc


class FetchError(RuntimeError):
    pass


class Client:
    def __init__(self, root, user_agent, timeout=30):
        self.root = Path(root)
        self.user_agent = user_agent
        self.timeout = timeout
        self.last = {}
        self.stale_urls = set()
        self.blocked_hosts = set()

    def get(self, url, ttl=86400, missing_ttl=21600, stale=True):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'arxiv.org', 'rss.arxiv.org', 'export.arxiv.org', 'inspirehep.net'}:
            raise FetchError(f'Refusing unexpected data URL: {url}')
        path = self.root / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        cached = read_json(path)
        now = time.time()
        if cached and now - cached['fetched'] < (missing_ttl if cached['status'] == 404 else ttl):
            return cached['body']
        if parsed.hostname in self.blocked_hosts:
            if cached and stale and cached['body'] is not None:
                self.stale_urls.add(url)
                return cached['body']
            raise FetchError(f'{parsed.hostname} is unavailable; further requests deferred until the next run')
        headers = {'User-Agent': self.user_agent}
        if cached:
            for k, h in [('etag', 'If-None-Match'), ('modified', 'If-Modified-Since')]:
                if cached.get(k):
                    headers[h] = cached[k]
        host = 'arxiv' if 'arxiv.org' in parsed.hostname else parsed.hostname
        delay = 3.1 if host == 'arxiv' else 0.4
        failure = None
        for attempt in range(3):
            time.sleep(max(0, delay - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            retry_after = 5 * 2**attempt
            try:
                with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                    body = response.read(8_000_001)
                    if len(body) > 8_000_000:
                        raise FetchError(f'Response exceeds 8 MB: {url}')
                    text = body.decode('utf-8')
                    if parsed.hostname == 'arxiv.org' and parsed.path.startswith('/html/'):
                        # Persist identifiers only, never redistribute cached full-text papers.
                        from .inspire import BibliographyParser, text_identifiers
                        from html import escape
                        parser = BibliographyParser()
                        parser.feed(text)
                        text = ''.join('<li class="ltx_bibitem">' + escape(' '.join(sorted(text_identifiers(item)))) + '</li>' for item in parser.items)
                    if parsed.hostname == 'inspirehep.net':
                        text = trim_inspire(text)
                    data = {'status': 200, 'body': text, 'fetched': time.time(),
                            'etag': response.headers.get('ETag'), 'modified': response.headers.get('Last-Modified')}
                write_json(path, data)
                return data['body']
            except HTTPError as exc:
                failure = exc
                exc.close()
                if exc.code == 304 and cached:
                    cached['fetched'] = time.time()
                    write_json(path, cached)
                    return cached['body']
                if exc.code == 404:
                    write_json(path, {'status': 404, 'body': None, 'fetched': time.time()})
                    return None
                if exc.code not in (429, 500, 502, 503, 504):
                    break
                value = exc.headers.get('Retry-After', '')
                try:
                    retry_after = max(retry_after, float(value))
                except ValueError:
                    try:
                        retry_after = max(retry_after, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError):
                        pass
                # Do not retry earlier than a long server-requested delay; defer to the next run.
                if retry_after > 60:
                    break
            except (URLError, TimeoutError, OSError, UnicodeError) as exc:
                failure = exc
            log.warning('Request failed (%s/3): %s: %s', attempt + 1, url, failure)
            if attempt < 2:
                time.sleep(retry_after)
        self.blocked_hosts.add(parsed.hostname)
        if cached and stale and cached['body'] is not None:
            self.stale_urls.add(url)
            log.warning('Using stale cached data: %s', url)
            return cached['body']
        raise FetchError(f'Cannot fetch {url}: {failure}')

    def json(self, url, **kwargs):
        body = self.get(url, **kwargs)
        if body is None:
            return None
        try:
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError('expected a JSON object')
            return result
        except ValueError as exc:
            raise FetchError(f'Invalid JSON from {url}: {exc}') from exc

    def prune(self, days=90):
        cutoff = time.time() - days * 86400
        for path in self.root.glob('*.json'):
            item = read_json(path)
            if item and item.get('fetched', 0) < cutoff:
                path.unlink()
