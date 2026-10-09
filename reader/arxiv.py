"""RSS snapshots are announcement records, never a fabricated historical API."""
from datetime import date
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import re
import xml.etree.ElementTree as ET
from .config import ARXIV


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(value)
    return unescape(''.join(parser.parts)).strip()


def arxiv_id(value):
    value = re.sub(r'^(?:https?://arxiv.org/(?:abs|pdf)/|arXiv:|oai:arXiv.org:)', '', value.strip(), flags=re.I)
    value = re.sub(r'\.pdf$', '', value)
    if not ARXIV.fullmatch(value):
        raise ValueError(f'Invalid arXiv identifier: {value!r}')
    return re.sub(r'v\d+$', '', value)


def local(element, name):
    return next((e.text or '' for e in element if e.tag.split('}')[-1] == name), '')


def announcement_date(value):
    try:
        # Retain the feed's local calendar date, not the collector's UTC date.
        return parsedate_to_datetime(value).date().isoformat()
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Invalid or absent RSS announcement date: {value!r}') from exc


def parse_feed(xml, category):
    root = ET.fromstring(xml)
    channel = root.find('channel')
    if channel is None:
        raise ValueError('Expected an arXiv RSS 2.0 channel')
    day = announcement_date(local(channel, 'pubDate'))
    papers = []
    for position, item in enumerate(channel.findall('item')):
        identifier = arxiv_id(local(item, 'link') or local(item, 'guid'))
        description = plain(local(item, 'description'))
        kind = local(item, 'announce_type').strip()
        if kind not in ('new', 'cross', 'replace', 'replace-cross'):
            raise ValueError(f'{identifier}: missing or unknown announce_type {kind!r}')
        item_day = announcement_date(local(item, 'pubDate') or local(channel, 'pubDate'))
        cats = [e.text for e in item.findall('category') if e.text]
        if category not in cats:
            continue
        abstract = re.sub(r'^.*?Abstract:\s*', '', description, count=1, flags=re.S)
        version = re.search(r'arXiv:\s*\S+?v(\d+)\b', description)
        names = [n.strip() for n in plain(local(item, 'creator')).split(',') if n.strip()]
        papers.append({'id': identifier, 'version': int(version[1]) if version else None,
                       'title': plain(local(item, 'title')), 'abstract': abstract,
                       'authors': [{'name': n} for n in names], 'categories': cats,
                       'date': item_day, 'announcements': [{'category': category, 'type': kind, 'position': position}],
                       'citation': {'status': 'unavailable', 'matches': [], 'checked_at': None,
                                    'reason': 'Not checked yet'}})
    return day, papers


def merge_papers(papers, categories):
    """Stable first occurrence, with per-category ordering/type retained."""
    result = {}
    for paper in papers:
        if not set(paper['categories']).intersection(categories):
            continue
        key = arxiv_id(paper['id'])
        if key not in result:
            result[key] = paper | {'id': key, 'announcements': list(paper['announcements']),
                                    'categories': list(paper['categories'])}
        else:
            previous = result[key]
            for announcement in paper['announcements']:
                if announcement not in previous['announcements']:
                    previous['announcements'].append(announcement)
            previous['categories'] = list(dict.fromkeys(previous['categories'] + paper['categories']))
    order = {c: i for i, c in enumerate(categories)}
    return sorted(result.values(), key=lambda p: min((order.get(a['category'], 999), a['position']) for a in p['announcements']))
