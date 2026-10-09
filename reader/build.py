"""Static build: relative URLs work at a GitHub Pages repository subpath."""
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from importlib.resources import files
from pathlib import Path
import shutil
from .arxiv import merge_papers
from .storage import read_json, write_json


def build(config, state='state', output='site', *, public=False):
    if public and (config['inspire_author_id'] or config['followed_authors'] or config['tracked_publications']):
        raise ValueError('Use an anonymous configuration for a public build.')
    state, output = Path(state), Path(output)
    if output.resolve() == state.resolve() or output.resolve() in state.resolve().parents:
        raise ValueError('Site output must not contain the state directory')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'data').mkdir(exist_ok=True)
    # Remove only previously generated daily payloads, not arbitrary output contents.
    for p in (output / 'data').glob('????-??-??.json'):
        p.unlink()
    archive = []
    if public and not read_json(state / 'status.json', {}).get('public_mode'):
        raise ValueError('Public builds require an archive produced by update --public.')
    for path in sorted((state / 'days').glob('*.json'), reverse=True):
        day = deepcopy(read_json(path))
        day['papers'] = merge_papers(day['papers'], config['categories'])
        if public:
            safe_papers = []
            for paper in day['papers']:
                allowed = ('id', 'version', 'title', 'abstract', 'categories', 'date', 'announcements', 'inspire_id', 'public_data')
                safe = {key: paper[key] for key in allowed if key in paper}
                safe['authors'] = [{'name': a['name']} for a in paper['authors']]
                safe['citation'] = {'status': 'unavailable', 'matches': [], 'reason': 'Configure citation tracking privately in this browser.'}
                safe_papers.append(safe)
            day = {'date': day['date'], 'sources': day['sources'], 'papers': safe_papers}
        archive.append({'date': day['date'], 'count': len(day['papers']),
                        'categories_captured': sorted(day['sources'])})
        write_json(output / 'data' / path.name, day)
    status = read_json(state / 'status.json', {'warnings': ['No data captured yet. Run the update command.']})
    manifest = {'schema': 1, 'personalization': 'browser' if public else 'precomputed', 'display': config['display'], 'categories': config['categories'],
                'days': archive, 'status': status, 'built_at': datetime.now(timezone.utc).isoformat()}
    write_json(output / 'data' / 'index.json', manifest)
    assets = files('reader').joinpath('web')
    for name in ('app.js', 'profile.js', 'style.css'):
        (output / name).write_text(assets.joinpath(name).read_text(encoding='utf-8'), encoding='utf-8')
    template = assets.joinpath('index.html').read_text(encoding='utf-8')
    (output / 'index.html').write_text(template.replace('{{TITLE}}', escape(config['display']['title'])), encoding='utf-8')
    (output / '.nojekyll').touch()
    return manifest


def validate_site(output='site'):
    output = Path(output)
    index = read_json(output / 'data/index.json')
    if not index or index.get('schema') != 1:
        raise ValueError('Missing or unsupported site manifest')
    for name in ('index.html', 'app.js', 'profile.js', 'style.css'):
        if not (output / name).is_file():
            raise ValueError(f'Missing site asset {name}')
    for item in index['days']:
        day = read_json(output / 'data' / (item['date'] + '.json'))
        if not day or len(day['papers']) != item['count']:
            raise ValueError(f'Invalid day payload: {item["date"]}')
        ids = [p['id'] for p in day['papers']]
        if len(ids) != len(set(ids)):
            raise ValueError(f'Duplicate papers in {item["date"]}')
        for p in day['papers']:
            if p['date'] != day['date'] or not p['title'] or not p['announcements']:
                raise ValueError(f'Invalid announcement: {p["id"]}')
    return len(index['days'])
