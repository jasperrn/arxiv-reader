"""Strict, dependency-light configuration validation."""
from copy import deepcopy
from pathlib import Path
import re
import yaml


class ConfigError(ValueError):
    pass


DEFAULTS = {
    'categories': ['hep-ph', 'hep-th'], 'inspire_author_id': None,
    'followed_authors': [], 'tracked_publications': [],
    'display': {'title': 'My arXiv reader', 'abstracts_expanded': False,
                'citation_details_expanded': False, 'show_replacements': True,
                'default_sort': 'announcement'},
    'updates': {'recheck_days': 30, 'metadata_ttl_hours': 24, 'missing_ttl_hours': 6,
                'max_papers_per_run': 400, 'bibliography_check': True,
                'max_bibliographies_per_run': 20,
                'user_agent': 'arxiv-daily-reader/1.0 (personal research reader)'}}
ARXIV = re.compile(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$')
AUTHOR = re.compile(r'(?:[1-9]\d*|INSPIRE-\d+|[A-Za-z][A-Za-z0-9_.-]*\.\d+)$')


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ConfigError(f'Duplicate or non-text configuration key: {key!r}')
        result[key] = loader.construct_object(v, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def check(condition, message):
    if not condition:
        raise ConfigError(message)


def keys(value, allowed, location):
    check(isinstance(value, dict), f'{location} must be a mapping')
    check(not (set(value) - set(allowed)), f'{location}: unknown keys {set(value) - set(allowed)}')


def author_id(value, location):
    check(not isinstance(value, bool) and isinstance(value, (str, int)) and
          bool(AUTHOR.fullmatch(str(value))), f'{location}: use a numeric INSPIRE author ID, INSPIRE-... ID, or BAI')
    return str(value)


def load_config(path='config.yaml'):
    try:
        raw = yaml.load(Path(path).read_text(encoding='utf-8'), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f'Cannot read {path}: {exc}') from exc
    if isinstance(raw, dict):
        raw.pop('_reader_cache', None)  # Optional private browser export; never used by the collector.
    keys(raw, DEFAULTS, 'config')
    cfg = deepcopy(DEFAULTS)
    cfg.update(raw)
    for section in ('display', 'updates'):
        keys(raw.get(section, {}), DEFAULTS[section], section)
        cfg[section] = DEFAULTS[section] | raw.get(section, {})
    cats = cfg['categories']
    check(isinstance(cats, list) and len(cats) > 0, 'categories must be a nonempty list')
    check(all(isinstance(c, str) and re.fullmatch(r'[a-z][a-z-]*(?:\.[A-Za-z][A-Za-z0-9-]*)?', c) for c in cats),
          'categories must contain arXiv codes such as hep-ph or math.AG')
    check(len(set(cats)) == len(cats), 'categories must not contain duplicates')
    if cfg['inspire_author_id'] is not None:
        cfg['inspire_author_id'] = author_id(cfg['inspire_author_id'], 'inspire_author_id')
    check(isinstance(cfg['followed_authors'], list), 'followed_authors must be a list')
    for i, a in enumerate(cfg['followed_authors']):
        loc = f'followed_authors[{i}]'
        keys(a, ('name', 'inspire_id', 'aliases'), loc)
        check(isinstance(a.get('name'), str) and bool(a['name'].strip()), f'{loc}.name is required')
        if 'inspire_id' in a:
            a['inspire_id'] = author_id(a['inspire_id'], loc + '.inspire_id')
        aliases = a.get('aliases', [])
        check(isinstance(aliases, list) and all(isinstance(n, str) and n.strip() for n in aliases),
              f'{loc}.aliases must be a list of names')
    check(isinstance(cfg['tracked_publications'], list), 'tracked_publications must be a list')
    for i, p in enumerate(cfg['tracked_publications']):
        loc = f'tracked_publications[{i}]'
        keys(p, ('arxiv', 'doi', 'inspire'), loc)
        check(len(p) == 1, f'{loc}: specify exactly one of arxiv, doi, inspire')
        kind, value = next(iter(p.items()))
        check(not isinstance(value, bool) and isinstance(value, (str, int)), f'{loc}: invalid identifier')
        value = str(value)
        valid = (kind == 'arxiv' and ARXIV.fullmatch(value) or
                 kind == 'doi' and re.fullmatch(r'10\.\d{4,9}/\S+', value) or
                 kind == 'inspire' and re.fullmatch(r'[1-9]\d*', value))
        check(valid, f'{loc}: invalid {kind} identifier {value!r}')
        p[kind] = value
    d, u = cfg['display'], cfg['updates']
    check(isinstance(d['title'], str) and 0 < len(d['title'].strip()) <= 120, 'display.title must be 1–120 characters')
    check(d['default_sort'] in ('announcement', 'title', 'citations'), 'display.default_sort must be announcement, title, or citations')
    for key in ('abstracts_expanded', 'citation_details_expanded', 'show_replacements'):
        check(type(d[key]) is bool, f'display.{key} must be true or false')
    check(type(u['bibliography_check']) is bool, 'updates.bibliography_check must be true or false')
    for key, maximum in [('recheck_days', 3650), ('metadata_ttl_hours', 720), ('missing_ttl_hours', 720),
                         ('max_papers_per_run', 10000), ('max_bibliographies_per_run', 1000)]:
        check(type(u[key]) is int and 1 <= u[key] <= maximum, f'updates.{key} must be an integer from 1 to {maximum}')
    check(isinstance(u['user_agent'], str) and u['user_agent'].strip() and '\n' not in u['user_agent'] and '\r' not in u['user_agent'],
          'updates.user_agent must be nonempty single-line text')
    return cfg
