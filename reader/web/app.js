'use strict';
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
const historyKey = 'arxiv-reader-history-v1';
let history = {read: {}, bookmarks: {}}, manifest, hostDisplay, papers = [], generation = 0;
const cache = new Map();
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
try { const saved = JSON.parse(localStorage.getItem(historyKey)); if (saved && saved.read && saved.bookmarks) history = saved; }
catch (_) { notice('Browser storage is unavailable. Reading history will last for this session only.'); }
function save() { try { localStorage.setItem(historyKey, JSON.stringify(history)); } catch (_) { notice('Could not save browser history. You can export it using the button below.'); } }
function link(text, url) { const a = node('a', text); a.href = url; return a; }
function external(text, url, id) { const a = link(text, url); a.target = '_blank'; a.rel = 'noopener noreferrer'; if (id) a.addEventListener('click', () => { history.read[id] = new Date().toISOString(); save(); render(); }); return a; }
async function json(url) { const response = await fetch(url); if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`); return response.json(); }
async function day(date) { if (!cache.has(date)) cache.set(date, await json(`data/${date}.json`)); return cache.get(date); }
async function selectDay() {
  const token = ++generation;
  $('papers').dataset.ready = 'false';
  $('papers').replaceChildren(node('p', 'Loading announcements…'));
  try {
    const dates = $('date').value === 'all' ? manifest.days.map(d => d.date) : [$('date').value];
    const loaded = [];
    // Sequential archive reads avoid flooding small hosts when browsing all dates.
    for (const date of dates) { if (token !== generation) return; loaded.push(await day(date)); }
    if (token !== generation) return;
    const unique = new Map();
    for (const d of loaded) for (const p of d.papers) if (!unique.has(p.id)) unique.set(p.id, p);
    papers = [...unique.values()];
    $('day-title').textContent = $('date').value === 'all' ? 'All archived announcements' : `Announcements · ${$('date').value}`;
    render();
    $('papers').dataset.ready = 'true';
  } catch (error) { if (token === generation) { papers = []; $('papers').replaceChildren(node('p', `Unable to load this listing. ${error.message} — reload to retry.`, 'empty')); } }
}
function citationMatches(p) { return (p.citation?.matches || []).filter(m => $('provisional').checked || m.status === 'confirmed'); }
function visible(p) {
  if (manifest.personalization === 'browser' && ReaderProfile.categories().length && !p.categories.some(c => ReaderProfile.categories().includes(c))) return false;
  const query = $('search').value.trim().toLocaleLowerCase();
  if (query && ![p.title, p.abstract, p.id, ...p.authors.map(a => a.name)].join(' ').toLocaleLowerCase().includes(query)) return false;
  if (!$('replacements').checked && p.announcements.every(a => a.type.startsWith('replace'))) return false;
  const matches = citationMatches(p);
  const values = {mine: matches.some(m => m.publication.groups.includes('mine')), tracked: matches.some(m => m.publication.groups.includes('tracked')),
    followed: p.authors.some(a => a.followed), bookmarked: !!history.bookmarks[p.id], unread: !history.read[p.id]};
  const chosen = Object.keys(values).filter(k => $(k).checked);
  return !chosen.length || ($('combine').value === 'all' ? chosen.every(k => values[k]) : chosen.some(k => values[k]));
}
function toggleButton(text, active, action) { const b = node('button', text); b.type = 'button'; b.setAttribute('aria-pressed', String(active)); b.addEventListener('click', action); return b; }
function renderPaper(p, index) {
  const read = !!history.read[p.id], bookmarked = !!history.bookmarks[p.id];
  const article = node('article', undefined, read ? 'read' : ''); article.dataset.id = p.id;
  const top = node('div', undefined, 'paper-top'); top.append(node('span', `[${index + 1}]`, 'number'), external(`arXiv:${p.id}`, `https://arxiv.org/abs/${p.id}`, p.id), external('PDF', `https://arxiv.org/pdf/${p.id}`, p.id));
  if (p.inspire_id) top.append(external('INSPIRE', `https://inspirehep.net/literature/${p.inspire_id}`));
  const actions = node('span', undefined, 'actions');
  actions.append(toggleButton(bookmarked ? 'Bookmarked' : 'Bookmark', bookmarked, () => { if (bookmarked) delete history.bookmarks[p.id]; else history.bookmarks[p.id] = new Date().toISOString(); save(); render(); }),
    toggleButton(read ? 'Read' : 'Mark read', read, () => { if (read) delete history.read[p.id]; else history.read[p.id] = new Date().toISOString(); save(); render(); }));
  top.append(actions); article.append(top);
  const title = node('h3'); title.append(external(p.title, `https://arxiv.org/abs/${p.id}`, p.id)); article.append(title);
  const authors = node('p', undefined, 'authors');
  p.authors.forEach((a, i) => { if (i) authors.append(document.createTextNode(', ')); const e = node(a.followed ? 'mark' : 'span', a.name); if (a.followed) { e.title = a.match === 'confirmed' ? `Confirmed INSPIRE author ${a.inspire_id}` : 'Name or surname matched in the arXiv author list; identity not verified'; e.tabIndex = 0; e.setAttribute('aria-label', `${a.name}. ${e.title}`); } authors.append(e); });
  article.append(authors);
  const meta = node('div', undefined, 'meta');
  for (const a of p.announcements) meta.append(node('span', `${a.category} · ${a.type}`, 'badge'));
  if ($('date').value === 'all') meta.append(node('span', p.date));
  const c = p.citation || {status: 'unavailable', matches: []};
  const labels = {unconfigured: 'Private citation tracking not configured', confirmed: 'Confirmed citation', provisional: 'Provisional citation', checked: 'No tracked citation detected', unavailable: 'Citation data unavailable'};
  meta.append(node('span', labels[c.status] || 'Citation data unavailable', `badge ${c.status}`));
  if (c.stale) meta.append(node('span', 'Refresh pending · previous evidence', 'badge provisional'));
  if (p.authors.some(a => a.followed)) meta.append(node('span', 'Followed author', 'badge'));
  article.append(meta);
  const abstract = node('details', undefined, 'abstract'); abstract.open = manifest.display.abstracts_expanded;
  abstract.append(node('summary', 'Abstract'), node('p', p.abstract)); article.append(abstract);
  const detail = node('details', undefined, 'citation-detail'); detail.open = manifest.display.citation_details_expanded;
  detail.append(node('summary', `Citation details${c.matches.length ? ` · ${c.matches.length} tracked publication${c.matches.length === 1 ? '' : 's'}` : ''}`));
  detail.append(node('p', c.reason || 'Not checked yet.', 'evidence'));
  if (c.checked_at) detail.append(node('p', `Last checked: ${new Date(c.checked_at).toLocaleString()}${c.bibliography ? ` · ${c.bibliography}` : ''}`, 'evidence'));
  if (c.bibliography_checked_at) detail.append(node('p', `Last HTML bibliography attempt: ${new Date(c.bibliography_checked_at).toLocaleString()}`, 'evidence'));
  if (c.targets_complete === false) detail.append(node('p', 'The tracked publication list could not be fully refreshed; results may be incomplete.', 'evidence'));
  const list = node('ul');
  for (const m of c.matches) {
    const item = node('li'); item.append(node('span', `${m.status} · ${m.publication.groups.includes('mine') ? 'my work' : 'tracked paper'} — `, 'evidence'), node('strong', m.publication.title));
    const links = node('div'); for (const l of m.publication.links) { if (links.childNodes.length) links.append(' · '); if (/^https:\/\/(inspirehep\.net|arxiv\.org|doi\.org)\//.test(l.url)) links.append(external(l.label, l.url)); }
    item.append(links, node('div', `Evidence: ${m.source}; ${m.matched_identifiers.join(', ')}`, 'evidence'));
    if (m.excerpt) item.append(node('p', m.excerpt, 'evidence')); list.append(item);
  }
  detail.append(list); article.append(detail); return article;
}
function render() {
  let selected = (manifest.personalization === 'browser' ? papers.map(ReaderProfile.apply) : papers).filter(visible);
  if ($('sort').value === 'title') selected.sort((a, b) => a.title.localeCompare(b.title));
  if ($('sort').value === 'citations') selected.sort((a, b) => citationMatches(b).length - citationMatches(a).length);
  $('count').textContent = `${selected.length} of ${papers.length} papers`;
  $('papers').replaceChildren(...(selected.length ? selected.map(renderPaper) : [node('p', 'No papers match this selection. Try another date or adjust the filters.', 'empty')]));
}
async function init() {
  try {
    manifest = await json('data/index.json');
    hostDisplay = {...manifest.display};
    $('categories').textContent = `${manifest.categories.join(' + ')} · New submissions, cross-lists and replacements`;
    $('sort').value = manifest.display.default_sort; $('replacements').checked = manifest.display.show_replacements;
    $('updated').textContent = `Last update: ${manifest.status.updated_at ? new Date(manifest.status.updated_at).toLocaleString() : 'not yet captured'}`;
    const coverage = $('coverage');
    coverage.append(node('p', `Archive begins ${manifest.status.archive_started || 'with the first successful capture'}. Only captured announcement dates are available. Missing dates may be weekends, holidays, or missed captures; historical completeness is not claimed. Category feeds are combined in your configured order, preserving each feed’s order and labels.`));
    const incomplete = manifest.days.filter(d => manifest.categories.some(c => !d.categories_captured.includes(c)));
    if (incomplete.length) coverage.append(node('p', `Partial category coverage: ${incomplete.map(d => d.date).join(', ')}`));
    if (manifest.status.warnings?.length) { const list = node('ul'); for (const warning of manifest.status.warnings) list.append(node('li', warning)); coverage.append(list); notice('Some sources could not be refreshed. Open “Archive coverage & citation status” for details.'); }
    const options = manifest.days.map(d => { const o = node('option', `${d.date} · ${d.count} papers`); o.value = d.date; return o; });
    const all = node('option', 'All archived dates'); all.value = 'all';
    $('date').replaceChildren(...options, all);
    $('date').addEventListener('change', selectDay);
    for (const id of ['search', 'sort', 'mine', 'tracked', 'followed', 'bookmarked', 'unread', 'combine', 'provisional', 'replacements']) $(id).addEventListener(id === 'search' ? 'input' : 'change', render);
    $('expand').addEventListener('click', () => { manifest.display.abstracts_expanded = true; document.querySelectorAll('.abstract').forEach(e => e.open = true); });
    $('collapse').addEventListener('click', () => { manifest.display.abstracts_expanded = false; document.querySelectorAll('.abstract').forEach(e => e.open = false); });
    $('export').addEventListener('click', () => { const url = URL.createObjectURL(new Blob([JSON.stringify(history, null, 2)], {type: 'application/json'})); const a = link('', url); a.download = 'arxiv-reader-history.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
    $('import').addEventListener('change', async event => { try {
      const file = event.target.files[0]; if (!file) return; if (file.size > 2000000) throw new Error('File is larger than 2 MB');
      const data = JSON.parse(await file.text());
      for (const field of ['read', 'bookmarks']) {
        if (!data[field] || typeof data[field] !== 'object' || Array.isArray(data[field])) throw new Error('Expected read and bookmarks objects');
        for (const [id, stamp] of Object.entries(data[field])) { if (!/^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})$/.test(id) || typeof stamp !== 'string' || !Number.isFinite(Date.parse(stamp))) throw new Error('Invalid paper ID or timestamp'); }
      }
      history = {read: {...history.read, ...data.read}, bookmarks: {...history.bookmarks, ...data.bookmarks}}; save(); render(); notice('Reading history imported.');
    } catch (error) { notice(`Import failed: ${error.message}`); } });
    if (manifest.personalization === 'browser') {
      $('private-settings').hidden = false;
      await ReaderProfile.init(manifest.categories, () => {
        const prefs = ReaderProfile.display();
        document.title = typeof prefs.title === 'string' && prefs.title ? prefs.title : hostDisplay.title;
        document.querySelector('h1').textContent = document.title;
        for (const field of ['abstracts_expanded', 'citation_details_expanded']) manifest.display[field] = typeof prefs[field] === 'boolean' ? prefs[field] : hostDisplay[field];
        if (['announcement', 'title', 'citations'].includes(prefs.default_sort)) $('sort').value = prefs.default_sort;
        if (typeof prefs.show_replacements === 'boolean') $('replacements').checked = prefs.show_replacements;
        render();
      });
    }
    await selectDay();
  } catch (error) { $('papers').replaceChildren(node('p', `Unable to load the archive: ${error.message}. Serve the site over HTTP and reload to retry.`, 'empty')); }
}
init();
