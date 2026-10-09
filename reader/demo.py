"""Synthetic fixtures processed through the real pipeline; never presented as live data."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse, parse_qs
from .build import build
from .config import DEFAULTS
from .pipeline import update
from .storage import read_json, write_json


def rss(category, day='Fri, 09 Oct 2026 00:00:00 -0400'):
    rows = [
        ('2610.00001', 'Precision amplitudes at the next frontier', 'Mira Chen, Alex Rivera', 'new' if category == 'hep-ph' else 'cross', 'We develop a systematic approach to higher-order scattering amplitudes. The construction connects unitarity methods with an efficient representation of infrared singularities.'),
        ('2610.00002', 'Geometry and symmetry in effective field theory', 'Alex Rivera, Samira Patel', 'cross' if category == 'hep-ph' else 'new', 'We investigate the geometric structure of effective field theories and identify symmetry constraints on their low-energy observables.'),
        ('2610.00003', 'Thermal correlators beyond the planar limit', 'Luca Rossi, Noor Ahmed', 'replace', 'We revisit thermal correlation functions at finite coupling and provide new consistency checks outside the planar approximation.'),
        ('2610.00004', 'A new perspective on dark-sector dynamics', 'Mira Chen, Daniel Kim', 'new', 'We study the evolution of a weakly coupled dark sector and derive observable consequences for cosmological structure formation.')]
    items = []
    from html import escape
    for identifier, title, names, kind, abstract in rows:
        items.append(f'<item><title>{escape(title)}</title><link>https://arxiv.org/abs/{identifier}</link><description>arXiv:{identifier}v1 Announce Type: {kind}\nAbstract: {escape(abstract)}</description><dc:creator>{names}</dc:creator><category>hep-ph</category><category>hep-th</category><pubDate>{day}</pubDate><arxiv:announce_type>{kind}</arxiv:announce_type></item>')
    return f'<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom"><channel><title>{category}</title><pubDate>{day}</pubDate>{"".join(items)}</channel></rss>'


TARGET = {'metadata': {'control_number': 100, 'titles': [{'title': 'A framework for scattering amplitudes (demo)'}], 'arxiv_eprints': [{'value': '2001.00001'}], 'dois': [{'value': '10.1234/demo'}]}}
OTHER = {'metadata': {'control_number': 200, 'titles': [{'title': 'Geometric methods in field theory (demo)'}], 'arxiv_eprints': [{'value': '2101.00002'}]}}


class DemoClient:
    stale_urls = set()

    def get(self, url, **kwargs):
        if '/rss/' in url:
            return rss(url.rsplit('/', 1)[-1])
        if '/html/2610.00002' in url:
            return '<section><p>Body mentions 2001.00001; not a citation.</p><li class="ltx_bibitem">Example reference arXiv:2101.00002</li></section>'
        return None

    def json(self, url, **kwargs):
        path = urlparse(url).path
        if path == '/api/authors/42':
            return {'metadata': {'control_number': 42}}
        if path == '/api/literature':
            return {'hits': {'total': 1, 'hits': [deepcopy(TARGET)]}}
        if path == '/api/literature/200':
            return deepcopy(OTHER)
        if path == '/api/arxiv/2610.00001':
            return {'metadata': {'control_number': 1001, 'authors': [{'full_name': 'Chen, Mira', 'record': {'$ref': 'https://inspirehep.net/api/authors/42'}}], 'references': [{'record': {'$ref': 'https://inspirehep.net/api/literature/100'}}, {'reference': {'arxiv_eprint': '2101.00002'}}]}}
        if path == '/api/arxiv/2610.00003':
            return {'metadata': {'control_number': 1003, 'references': [{'reference': {'arxiv_eprint': '1901.12345'}}]}}
        return None


def demo(output='site', *, public=False):
    cfg = deepcopy(DEFAULTS)
    cfg['display']['title'] = 'The daily reading list · DEMO'
    cfg['inspire_author_id'] = '42'
    cfg['followed_authors'] = [{'name': 'Mira Chen', 'inspire_id': '42'}]
    cfg['tracked_publications'] = [{'inspire': '200'}]
    if public:
        cfg['inspire_author_id'] = None
        cfg['followed_authors'] = []
        cfg['tracked_publications'] = []
    with TemporaryDirectory() as tmp:
        update(cfg, tmp, client=DemoClient(), now=datetime(2026, 10, 9, 12, tzinfo=timezone.utc), public=public)
        old = read_json(Path(tmp) / 'days/2026-10-09.json')
        old['date'] = '2026-10-08'
        old['papers'] = old['papers'][:1]
        for p in old['papers']:
            p['date'] = old['date']
        write_json(Path(tmp) / 'days/2026-10-08.json', old)
        status = read_json(Path(tmp) / 'status.json')
        status['archive_started'] = '2026-10-08'
        status['warnings'] = ['DEMONSTRATION ONLY: synthetic papers, authors and citation evidence; these are not real announcements.']
        write_json(Path(tmp) / 'status.json', status)
        return build(cfg, tmp, output, public=public)
