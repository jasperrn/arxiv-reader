"""INSPIRE identifiers, paginated author bibliographies, and evidence-based matching."""
from copy import deepcopy
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlencode, quote
from .arxiv import arxiv_id
from .http import FetchError

BASE = 'https://inspirehep.net/api/'


def doi_id(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi.org/|doi:\s*)', '', value.strip(), flags=re.I).lower()


def record_id(value):
    return str(value).rstrip('/').split('/')[-1]


def identifiers(metadata):
    values = set()
    if metadata.get('control_number'):
        values.add('inspire:' + str(metadata['control_number']))
    for item in metadata.get('arxiv_eprints', []):
        try:
            values.add('arxiv:' + arxiv_id(item['value']))
        except (ValueError, KeyError):
            pass
    for item in metadata.get('dois', []):
        values.add('doi:' + doi_id(item['value']))
    return values


def publication(record, group, fallback=None):
    meta = record.get('metadata', {}) if record else {}
    ids = identifiers(meta)
    if fallback:
        kind, value = next(iter(fallback.items()))
        ids.add(kind + ':' + (arxiv_id(value) if kind == 'arxiv' else doi_id(value) if kind == 'doi' else str(value)))
    if not ids:
        raise FetchError('INSPIRE publication has no stable identifier')
    rid = meta.get('control_number')
    key = ('inspire:' + str(rid)) if rid else sorted(ids)[0]
    links = []
    for value in sorted(ids):
        kind, identifier = value.split(':', 1)
        prefix = {'inspire': 'https://inspirehep.net/literature/', 'arxiv': 'https://arxiv.org/abs/', 'doi': 'https://doi.org/'}[kind]
        links.append({'label': kind + ':' + identifier, 'url': prefix + quote(identifier, safe='/')})
    return {'key': key, 'identifiers': sorted(ids), 'groups': [group],
            'title': meta.get('titles', [{}])[0].get('title', key), 'links': links,
            'resolved': bool(meta)}


def combine_targets(targets):
    result = []
    for target in targets:
        overlaps = [t for t in result if set(t['identifiers']) & set(target['identifiers'])]
        item = deepcopy(target)
        for other in overlaps:
            item['identifiers'] = sorted(set(item['identifiers'] + other['identifiers']))
            item['groups'] = sorted(set(item['groups'] + other['groups']))
            if other['resolved'] and not item['resolved']:
                item.update({k: other[k] for k in ('key', 'title', 'links', 'resolved')})
            result.remove(other)
        result.append(item)
    return result


class Inspire:
    def __init__(self, client, updates):
        self.client = client
        self.kwargs = {'ttl': updates['metadata_ttl_hours'] * 3600,
                       'missing_ttl': updates['missing_ttl_hours'] * 3600}

    def search(self, collection, query):
        page, records = 1, []
        while True:
            url = BASE + collection + '?' + urlencode({'q': query, 'size': 250, 'page': page, 'fields': 'control_number,titles,arxiv_eprints,dois' if collection == 'literature' else 'control_number,ids,name'})
            result = self.client.json(url, **self.kwargs)
            if not result or 'hits' not in result:
                raise FetchError(f'Invalid INSPIRE search response for {query}')
            hits = result['hits']['hits']
            total = result['hits']['total']
            total = total['value'] if isinstance(total, dict) else total
            if total > 10000:
                raise FetchError(f'INSPIRE query exceeds 10,000 results ({query}); partitioning is required')
            records.extend(hits)
            if len(records) >= total:
                return records
            if not hits:
                raise FetchError(f'Incomplete INSPIRE pagination for {query}')
            page += 1

    def resolve_author(self, identifier):
        if str(identifier).isdigit():
            result = self.client.json(BASE + 'authors/' + str(identifier), **self.kwargs)
            if result:
                return str(result['metadata']['control_number'])
            raise FetchError(f'INSPIRE author {identifier} does not exist')
        results = self.search('authors', 'ids.value:"' + identifier + '"')
        if len(results) != 1:
            raise FetchError(f'Author identifier {identifier!r} resolved to {len(results)} records; use a numeric author record ID')
        return str(results[0]['metadata']['control_number'])

    def author_publications(self, identifier):
        rid = self.resolve_author(identifier)
        return self.search('literature', f'authors.record.$ref:"{BASE}authors/{rid}"')

    def paper(self, kind, identifier):
        endpoint = 'literature' if kind == 'inspire' else kind
        return self.client.json(BASE + endpoint + '/' + quote(str(identifier), safe='/'), **self.kwargs)


def normalize_name(value):
    if ',' in value:
        surname, given = value.split(',', 1)
        value = given + ' ' + surname
    return ' '.join(re.sub(r'[^\w\s]', ' ', unicodedata.normalize('NFKD', value).casefold()).split())


def match_authors(authors, metadata, followed):
    """Never infer a record ID from initials or from surname-only similarity."""
    linked = {}
    for item in metadata.get('authors', []):
        name = normalize_name(item.get('full_name', ''))
        rid = record_id(item.get('record', {}).get('$ref', ''))
        if name and rid:
            linked.setdefault(name, set()).add(rid)
    result = []
    for author in authors:
        current = {'name': author['name'], 'followed': False}
        normalized = normalize_name(author['name'])
        candidates = linked.get(normalized, set())
        for follow in followed:
            rid = follow.get('resolved_id')
            name_match = normalized in {normalize_name(n) for n in [follow['name']] + follow.get('aliases', [])}
            if rid and str(rid) in candidates and len(candidates) == 1:
                current.update(followed=True, match='confirmed', inspire_id=str(rid))
                break
            if name_match and not (rid and candidates and str(rid) not in candidates):
                current.update(followed=True, match='provisional')
        result.append(current)
    return result


def text_identifiers(text):
    """Explicit identifier boundaries; titles and surnames are not citation evidence."""
    result = set()
    for match in re.finditer(r'(?<![\w.])(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?!\w|\.\d)', text):
        try:
            result.add('arxiv:' + arxiv_id(match[0]))
        except ValueError:
            pass
    for match in re.finditer(r'10\.\d{4,9}/[^\s<>"{}]+', text, flags=re.I):
        result.add('doi:' + doi_id(match[0].rstrip('.,;)]')))
    return result


class BibliographyParser(HTMLParser):
    """Collect only arXiv HTML bibliography items, never mentions in body text."""
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.depth:
            if tag not in ('br', 'img', 'hr', 'meta', 'link', 'input', 'wbr', 'source'):
                self.depth += 1
            if attrs.get('href'):
                self.parts.append(attrs['href'])
        elif 'ltx_bibitem' in attrs.get('class', '').split():
            self.depth = 1
            self.parts = []

    def handle_endtag(self, tag):
        if self.depth and tag not in ('br', 'img', 'hr', 'meta', 'link', 'input', 'wbr', 'source'):
            self.depth -= 1
            if not self.depth:
                self.items.append(' '.join(self.parts))

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def reference_evidence(metadata, bibliography=None):
    evidence = []
    for ref in metadata.get('references', []):
        ids = set()
        rid = ref.get('record', {}).get('$ref')
        if rid:
            ids.add('inspire:' + record_id(rid))
        structured = ref.get('reference', {})
        for kind, field in [('arxiv', 'arxiv_eprint'), ('doi', 'dois')]:
            values = structured.get(field, [])
            if isinstance(values, str):
                values = [values]
            for value in values:
                try:
                    ids.add(kind + ':' + (arxiv_id(value) if kind == 'arxiv' else doi_id(value)))
                except ValueError:
                    pass
        evidence.append((ids, 'confirmed', 'INSPIRE reference metadata', ''))
        for raw in ref.get('raw_refs', []):
            text = raw.get('value', '')
            evidence.append((text_identifiers(text), 'provisional', 'INSPIRE unstructured reference', text[:400]))
    if bibliography is not None:
        parser = BibliographyParser()
        parser.feed(bibliography)
        for text in parser.items:
            evidence.append((text_identifiers(text), 'provisional', 'arXiv HTML bibliography', text[:400]))
    return evidence


def match_citations(metadata, targets, bibliography=None):
    evidence = reference_evidence(metadata, bibliography)
    matches = []
    for target in targets:
        options = [e for e in evidence if e[0].intersection(target['identifiers'])]
        if not options:
            continue
        options.sort(key=lambda e: e[1] != 'confirmed')
        ids, status, source, excerpt = options[0]
        matches.append({'publication': target, 'status': status, 'source': source,
                        'matched_identifiers': sorted(ids.intersection(target['identifiers'])), 'excerpt': excerpt})
    available = bool(metadata.get('references'))
    status = ('confirmed' if any(m['status'] == 'confirmed' for m in matches) else
              'provisional' if matches else 'checked' if available else 'unavailable')
    return {'status': status, 'matches': matches,
            'references_available': available,
            'reason': ('Reference metadata checked; absence of a match is not proof of no citation.' if available else
                       'INSPIRE references are unavailable or empty; indexing may be delayed.')}


def public_metadata(metadata, bibliography=None):
    """Ordinary scholarly metadata with no visitor's settings or match decisions."""
    return {
        'references_available': bool(metadata.get('references')),
        'evidence': [{'identifiers': sorted(ids), 'status': status, 'source': source}
                     for ids, status, source, _ in reference_evidence(metadata, bibliography) if ids],
        'authors': [{'name': a.get('full_name', ''), 'id': record_id(a.get('record', {}).get('$ref', ''))}
                    for a in metadata.get('authors', [])],
    }
