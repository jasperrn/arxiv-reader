"""Incremental archive capture and fair, bounded metadata refresh."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from .arxiv import parse_feed, merge_papers
from .http import Client, FetchError
from .inspire import Inspire, publication, combine_targets, match_citations, match_authors, public_metadata
from .storage import read_json, write_json

log = logging.getLogger(__name__)


def fingerprint(config):
    # Display changes don't invalidate research metadata.
    fields = {k: config[k] for k in ('inspire_author_id', 'tracked_publications', 'followed_authors')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def resolve_targets(config, inspire, state, warnings):
    path = state / 'targets.json'
    previous = read_json(path, {})
    signature = fingerprint(config)
    targets = []
    complete = True
    if config['inspire_author_id']:
        try:
            targets += [publication(r, 'mine') for r in inspire.author_publications(config['inspire_author_id'])]
        except (FetchError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f'Your publications could not be refreshed: {exc}')
            complete = False
            if previous.get('signature') == signature:
                targets += [t for t in previous.get('targets', []) if 'mine' in t['groups']]
    for spec in config['tracked_publications']:
        try:
            record = inspire.paper(*next(iter(spec.items())))
            targets.append(publication(record, 'tracked', spec))
            if not record:
                warnings.append(f'Tracked publication not indexed by INSPIRE: {spec}; matching its supplied identifier only')
        except (FetchError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f'Tracked publication could not be resolved: {spec}: {exc}')
            complete = False
            targets.append(publication(None, 'tracked', spec))
            if previous.get('signature') == signature:
                targets += [t for t in previous.get('targets', []) if set(t['identifiers']) & set(targets[-1]['identifiers'])]
    followed = deepcopy(config['followed_authors'])
    for author in followed:
        if author.get('inspire_id'):
            try:
                author['resolved_id'] = inspire.resolve_author(author['inspire_id'])
            except (FetchError, KeyError, TypeError, ValueError) as exc:
                warnings.append(f'Followed author {author["name"]}: {exc}; exact-name matches remain provisional')
                complete = False
    targets = combine_targets(targets)
    write_json(path, {'signature': signature, 'targets': targets})
    return targets, followed, complete


def update(config, state='state', client=None, feed_files=None, recheck_all=False, now=None, public=False):
    state = Path(state)
    if public:
        if config['inspire_author_id'] or config['followed_authors'] or config['tracked_publications']:
            raise ValueError('Public collection requires an anonymous configuration. Use config.example.yaml.')
        prior_status = read_json(state / 'status.json', {})
        if any((state / name).exists() for name in ('days', 'cache', 'targets.json', 'status.json')) and not prior_status.get('public_mode'):
            raise ValueError('Refusing to reuse a personalized archive for public collection. Start with a clean public state directory.')
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    if public:
        write_json(state / 'status.json', prior_status | {
            'public_mode': True, 'last_attempt_at': stamp,
            'warnings': ['Collection is in progress or was interrupted; some metadata may be pending.']})
    warnings = []
    client = client or Client(state / 'cache', config['updates']['user_agent'])
    inspire = Inspire(client, config['updates'])
    archives = {p.stem: read_json(p) for p in (state / 'days').glob('*.json')}
    sources_ok = 0
    for category in config['categories']:
        try:
            if feed_files is not None:
                xml = Path(feed_files[category]).read_text(encoding='utf-8')
            else:
                xml = client.get('https://rss.arxiv.org/rss/' + category, ttl=3600, stale=False)
            if xml is None:
                raise FetchError('Feed not found; verify the category code')
            feed_day, papers = parse_feed(xml, category)
            if date.fromisoformat(feed_day) > now.date() + timedelta(days=1):
                raise ValueError(f'Feed announcement date is in the future: {feed_day}')
            day = archives.setdefault(feed_day, {'date': feed_day, 'papers': [], 'sources': {}})
            day['sources'][category] = {'feed_date': feed_day, 'captured_at': stamp, 'items': len(papers)}
            # Preserve earlier captures, including another category failing on this run.
            for paper in papers:
                target_day = archives.setdefault(paper['date'], {'date': paper['date'], 'papers': [], 'sources': {}})
                old = next((p for p in target_day['papers'] if p['id'] == paper['id']), None)
                if old:
                    for field in ('citation', 'metadata_checked_at', 'target_signature', 'followed', 'inspire_id', 'public_data'):
                        if field in old:
                            paper[field] = old[field]
                    previous_authors = {a['name']: a for a in old['authors']}
                    paper['authors'] = [previous_authors.get(a['name'], a) for a in paper['authors']]
                    paper['announcements'] = [a for a in old['announcements'] if a['category'] != category] + paper['announcements']
                    target_day['papers'].remove(old)
                target_day['papers'].append(paper)
            sources_ok += 1
        except (FetchError, ValueError, ET.ParseError, OSError, KeyError) as exc:
            message = f'{category} feed unavailable: {exc}'
            log.warning(message)
            warnings.append(message)
    # Persist announcements before slow metadata calls so a timeout cannot lose a daily capture.
    for captured in archives.values():
        write_json(state / 'days' / (captured['date'] + '.json'), captured)
    targets, followed, targets_complete = resolve_targets(config, inspire, state, warnings)
    signature = fingerprint(config)
    cutoff = (now - timedelta(days=config['updates']['recheck_days'])).date().isoformat()
    # Target changes re-evaluate all archived records, with the normal fair request budget.
    candidates = {}
    for day in archives.values():
        for paper in day['papers']:
            if paper.get('target_signature') != signature:
                paper['citation'] = {'status': 'unavailable', 'matches': [], 'checked_at': None,
                                     'reason': 'Configuration changed; citation check pending.'}
                paper['authors'] = match_authors(paper['authors'], {}, followed)
                paper['followed'] = any(a.get('followed') for a in paper['authors'])
            if recheck_all or day['date'] >= cutoff or paper.get('target_signature') != signature:
                candidates.setdefault(paper['id'], []).append(paper)
    pending = sorted(candidates.values(), key=lambda ps: min(p.get('metadata_checked_at', '') for p in ps))
    checked = 0
    target_version = hashlib.sha256(json.dumps(targets, sort_keys=True).encode()).hexdigest()

    def due(copies):
        previous = copies[-1].get('citation', {})
        last = previous.get('checked_at')
        interval = config['updates']['metadata_ttl_hours'] if previous.get('references_available') else config['updates']['missing_ttl_hours']
        return not (not recheck_all and last and all(p.get('target_signature') == signature for p in copies)
                    and previous.get('target_version') == target_version
                    and (now - datetime.fromisoformat(last)).total_seconds() < interval * 3600)

    work = [copies for copies in pending if due(copies)][:config['updates']['max_papers_per_run']]
    bib_order = sorted(work, key=lambda copies: copies[-1].get('citation', {}).get('bibliography_checked_at') or '')
    bib_ids = {copies[-1]['id'] for copies in bib_order[:config['updates']['max_bibliographies_per_run']]}
    for copies in work:
        paper = copies[-1]
        previous = paper.get('citation', {})
        checked += 1
        try:
            record = inspire.paper('arxiv', paper['id']) if public or targets or followed else None
            meta = record.get('metadata', {}) if record else {}
            bibliography = None
            bib_note = previous.get('bibliography')
            bib_stamp = previous.get('bibliography_checked_at')
            bib_succeeded = False
            if (public or targets) and config['updates']['bibliography_check'] and paper['id'] in bib_ids:
                bib_stamp = stamp
                try:
                    bibliography = client.get('https://arxiv.org/html/' + paper['id'], ttl=7*86400, missing_ttl=86400)
                    bib_note = 'HTML checked' if bibliography else 'HTML unavailable'
                    bib_succeeded = True
                except FetchError as exc:
                    bib_note = str(exc)
            result = match_citations(meta, targets, bibliography)
            # Keep earlier HTML evidence when its budget is not available on this run.
            if not bib_succeeded and previous.get('target_version') == target_version:
                existing = {m['publication']['key'] for m in result['matches']}
                for match in previous.get('matches', []):
                    if match['source'] == 'arXiv HTML bibliography' and match['publication']['key'] not in existing:
                        result['matches'].append(match)
                if result['matches'] and result['status'] not in ('confirmed', 'provisional'):
                    result['status'] = 'provisional'
            if not targets:
                result['reason'] = 'No tracked publications configured or resolved.'
            result.update(checked_at=stamp, bibliography=bib_note, bibliography_checked_at=bib_stamp, target_version=target_version,
                          targets_complete=targets_complete, stale=bool(getattr(client, 'stale_urls', set())))
            for copy in copies:
                if public:
                    generic = public_metadata(meta, bibliography)
                    if not bib_succeeded:
                        generic['evidence'] += [e for e in copy.get('public_data', {}).get('evidence', []) if e['source'] == 'arXiv HTML bibliography']
                    generic.update(checked_at=stamp, stale=result['stale'])
                    copy['public_data'] = generic
                copy['citation'] = result
                copy['authors'] = match_authors(copy['authors'], meta, followed)
                copy['followed'] = any(a.get('followed') for a in copy['authors'])
                copy['inspire_id'] = meta.get('control_number')
                copy['metadata_checked_at'] = stamp
                copy['target_signature'] = signature
        except (FetchError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f'{paper["id"]}: metadata refresh failed: {exc}')
            for copy in copies:
                copy['citation'] = copy['citation'] | {'stale': True, 'error': str(exc)}
                if public and 'public_data' in copy:
                    copy['public_data'] = copy['public_data'] | {'stale': True}
                copy['metadata_checked_at'] = stamp  # Fair scheduling; keep successful checked_at unchanged.
                copy['authors'] = match_authors(copy['authors'], {}, followed)
                copy['followed'] = any(a.get('followed') for a in copy['authors'])
        for copy in copies:
            write_json(state / 'days' / (copy['date'] + '.json'), archives[copy['date']])
    for day in archives.values():
        # Do not delete old categories from the archive when configuration changes.
        archive_categories = list(dict.fromkeys(config['categories'] + [a['category'] for p in day['papers'] for a in p['announcements']]))
        day['papers'] = merge_papers(day['papers'], archive_categories)
        write_json(state / 'days' / (day['date'] + '.json'), day)
    if getattr(client, 'stale_urls', set()):
        warnings.append(f'{len(client.stale_urls)} API responses used stale cache; previous evidence may be out of date.')
    status = {'updated_at': stamp, 'categories': config['categories'], 'warnings': warnings,
              'feeds_succeeded': sources_ok, 'feeds_expected': len(config['categories']),
              'papers_checked': checked, 'targets': len(targets), 'targets_complete': targets_complete,
              'public_mode': public,
              'archive_started': min(archives) if archives else None}
    write_json(state / 'status.json', status)
    if hasattr(client, 'prune'):
        client.prune()
    log.info('Captured %d/%d feeds; checked %d papers; %d warnings', sources_ok, len(config['categories']), checked, len(warnings))
    return status
