'use strict';
// Private settings are stored only on this browser. No requests send them to this site.
const ReaderProfile = (() => {
  const storageKey = `arxiv-reader-profile-v1:${location.pathname}`;
  const base = 'https://inspirehep.net/api/';
  let profile = {inspire_author_id: null, followed_authors: [], tracked_publications: [], categories: [], display: {}};
  let resolved = {targets: [], followed: [], updated_at: null};
  let changed = () => {}, revision = 0, lastRequest = 0, available = [];
  const sessionCache = new Map();
  let compiledProfile, compiledResolved, targetLookup = new Map(), targetCount = 0;
  function compile() {
    if (compiledProfile === profile && compiledResolved === resolved) return;
    const targets = combine([...resolved.targets.map(t => structuredClone(t)), ...profile.tracked_publications.map(t => target(null, 'tracked', t))]);
    targetLookup = new Map(); targetCount = targets.length;
    for (const t of targets) for (const id of t.identifiers) { if (!targetLookup.has(id)) targetLookup.set(id, []); targetLookup.get(id).push(t); }
    compiledProfile = profile; compiledResolved = resolved;
  }
  const $p = id => document.getElementById(id);
  const normalize = name => name.includes(',') ? normalize(name.split(',').slice(1).join(' ') + ' ' + name.split(',')[0]) : name.normalize('NFKD').toLowerCase().replace(/[^\p{L}\p{N}_\s]/gu, ' ').trim().replace(/\s+/g, ' ');
  const arxiv = value => String(value).trim().replace(/^https?:\/\/arxiv.org\/(abs|pdf)\//i, '').replace(/^arxiv:/i, '').replace(/\.pdf$/, '').replace(/v\d+$/, '');
  const doi = value => String(value).trim().replace(/^(https?:\/\/(dx\.)?doi.org\/|doi:\s*)/i, '').toLowerCase();
  const author = value => {
    value = String(value || '').trim().replace(/^https:\/\/inspirehep.net\/authors\//, '').replace(/\/$/, '');
    if (value && !/^(?:[1-9]\d*|INSPIRE-\d+|[A-Za-z][A-Za-z0-9_.-]*\.\d+)$/.test(value)) throw new Error('Use an INSPIRE author ID or author-profile URL.');
    return value || null;
  };
  const arxivPattern = /^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})$/;
  function status(message) { $p('profile-status').textContent = message; }
  function validate(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Configuration must be an object.');
    const cfg = {inspire_author_id: author(raw.inspire_author_id), followed_authors: raw.followed_authors || [],
      tracked_publications: raw.tracked_publications || [], categories: raw.categories || [], display: raw.display || {}};
    if (!Array.isArray(cfg.categories) || !cfg.categories.every(c => typeof c === 'string')) throw new Error('categories must be a list.');
    if (!Array.isArray(cfg.followed_authors) || !Array.isArray(cfg.tracked_publications)) throw new Error('Author and paper settings must be lists.');
    cfg.followed_authors = cfg.followed_authors.map(a => {
      if (typeof a?.name !== 'string' || !a.name.trim() || (a.aliases && (!Array.isArray(a.aliases) || !a.aliases.every(n => typeof n === 'string')))) throw new Error('Each followed author needs a name and optional list of aliases.');
      return {name: a.name.trim(), ...(a.inspire_id ? {inspire_id: author(a.inspire_id)} : {}), aliases: a.aliases || []};
    });
    cfg.tracked_publications = cfg.tracked_publications.map(t => {
      if (!t || Object.keys(t).length !== 1) throw new Error('Specify one identifier per tracked paper.');
      let [kind, value] = Object.entries(t)[0]; value = String(value);
      if (kind === 'arxiv') value = arxiv(value);
      if (kind === 'doi') value = doi(value);
      if (!(kind === 'arxiv' && arxivPattern.test(value) || kind === 'doi' && /^10\.\d{4,9}\/\S+$/.test(value) || kind === 'inspire' && /^[1-9]\d*$/.test(value))) throw new Error('Invalid tracked publication identifier.');
      return {[kind]: value};
    });
    if (!cfg.display || typeof cfg.display !== 'object' || Array.isArray(cfg.display)) throw new Error('display must be an object.');
    return cfg;
  }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify({...profile, _reader_cache: resolved})); }
    catch (_) { status('Settings are active, but browser storage is full or unavailable. Export your private configuration to keep it.'); }
  }
  function validateCache(value) {
    if (!value || !Array.isArray(value.targets) || !Array.isArray(value.followed)) throw new Error('Invalid cached bibliography.');
    for (const a of value.followed) {
      if (typeof a?.name !== 'string' || !a.name.trim() || (a.aliases && (!Array.isArray(a.aliases) || !a.aliases.every(n => typeof n === 'string'))) || (a.resolved_id && !/^\d+$/.test(String(a.resolved_id)))) throw new Error('Invalid cached author.');
    }
    for (const t of value.targets) {
      if (typeof t.key !== 'string' || typeof t.title !== 'string' || !Array.isArray(t.identifiers) || !t.identifiers.every(x => typeof x === 'string') || !Array.isArray(t.groups) || !t.groups.every(x => ['mine','tracked'].includes(x)) || !Array.isArray(t.links) || !t.links.every(l => typeof l.label === 'string' && typeof l.url === 'string')) throw new Error('Invalid cached publication.');
    }
    return value;
  }
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function api(path) {
    const url = base + path;
    if (sessionCache.has(url)) return sessionCache.get(url);
    for (let attempt = 0; attempt < 3; attempt++) {
      await pause(Math.max(0, 450 - (Date.now() - lastRequest))); lastRequest = Date.now();
      const response = await fetch(url, {credentials: 'omit', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(30000)});
      if (response.status === 404) return null;
      if (response.status === 429 || response.status >= 500) {
        let delay = Math.max(5 * 2 ** attempt, Number(response.headers.get('Retry-After')) || 0);
        if (delay > 60 || attempt === 2) throw new Error('INSPIRE is rate-limiting or temporarily unavailable. Try later.');
        await pause(delay * 1000); continue;
      }
      if (!response.ok) throw new Error(`INSPIRE returned HTTP ${response.status}.`);
      const data = await response.json(); sessionCache.set(url, data); return data;
    }
  }
  async function search(collection, query) {
    const records = [];
    for (let page = 1; ; page++) {
      const fields = collection === 'authors' ? 'control_number,ids,name' : 'control_number,titles,arxiv_eprints,dois';
      const data = await api(`${collection}?${new URLSearchParams({q: query, size: '250', page: String(page), fields})}`);
      if (!data?.hits || !Array.isArray(data.hits.hits)) throw new Error('Unexpected INSPIRE search response.');
      const total = typeof data.hits.total === 'number' ? data.hits.total : data.hits.total.value;
      if (total > 10000) throw new Error('INSPIRE limits searches to 10,000 records; this bibliography needs partitioning.');
      records.push(...data.hits.hits);
      if (records.length >= total) return records;
      if (!data.hits.hits.length) throw new Error('Incomplete INSPIRE search results.');
    }
  }
  async function resolveAuthor(identifier) {
    if (/^\d+$/.test(identifier)) {
      const data = await api('authors/' + identifier);
      if (!data?.metadata?.control_number) throw new Error('INSPIRE author record was not found.');
      return String(data.metadata.control_number);
    }
    const results = await search('authors', `ids.value:"${identifier}"`);
    if (results.length !== 1) throw new Error('Author identifier is missing or ambiguous; use its numeric record ID.');
    return String(results[0].metadata.control_number);
  }
  function target(record, group, fallback) {
    const m = record?.metadata || {}, ids = [];
    if (m.control_number) ids.push('inspire:' + m.control_number);
    for (const a of m.arxiv_eprints || []) ids.push('arxiv:' + arxiv(a.value));
    for (const d of m.dois || []) ids.push('doi:' + doi(d.value));
    if (fallback) { const [kind, value] = Object.entries(fallback)[0]; ids.push(kind + ':' + value); }
    const identifiers = [...new Set(ids)];
    if (!identifiers.length) throw new Error('Publication has no stable identifier.');
    return {key: identifiers[0], title: m.titles?.[0]?.title || identifiers[0], identifiers, groups: [group], resolved: !!record,
      links: identifiers.map(id => { const i = id.indexOf(':'), kind = id.slice(0, i), value = id.slice(i + 1); return {label: id,
        url: {inspire:'https://inspirehep.net/literature/', arxiv:'https://arxiv.org/abs/', doi:'https://doi.org/'}[kind] + value}; })};
  }
  function combine(targets) {
    const output = [];
    for (const t of targets) {
      const overlaps = output.filter(o => o.identifiers.some(id => t.identifiers.includes(id)));
      for (const other of overlaps) {
        t.identifiers = [...new Set([...t.identifiers, ...other.identifiers])];
        t.groups = [...new Set([...t.groups, ...other.groups])];
        if (!t.resolved && other.resolved) { t.title = other.title; t.links = other.links; t.key = other.key; t.resolved = true; }
        output.splice(output.indexOf(other), 1);
      }
      output.push(t);
    }
    return output;
  }
  async function refresh(force = false) {
    if (force) { revision++; sessionCache.clear(); }
    const ticket = revision;
    if (!profile.inspire_author_id && !profile.followed_authors.length && !profile.tracked_publications.length) {
      status('No personal settings configured. Settings you enter here stay in this browser.'); return;
    }
    if (!force && resolved.updated_at && Date.now() - Date.parse(resolved.updated_at) < 86400000) {
      status('Using your locally cached bibliography.'); changed(); return;
    }
    status('Resolving your bibliography directly with INSPIRE…');
    try {
      const targets = [], followed = JSON.parse(JSON.stringify(profile.followed_authors));
      if (profile.inspire_author_id) {
        const rid = await resolveAuthor(profile.inspire_author_id);
        for (const record of await search('literature', `authors.record.$ref:"${base}authors/${rid}"`)) targets.push(target(record, 'mine'));
      }
      for (const spec of profile.tracked_publications) {
        const [kind, value] = Object.entries(spec)[0];
        targets.push(target(await api((kind === 'inspire' ? 'literature' : kind) + '/' + value), 'tracked', spec));
      }
      if (ticket !== revision) return;
      resolved = {targets: combine(targets), followed, updated_at: new Date().toISOString()};
      persist(); changed(); status(`Private bibliography ready: ${resolved.targets.length} publications. Stored only in this browser.`);
    } catch (error) {
      if (ticket !== revision) return;
      changed(); status(`Could not refresh INSPIRE: ${error.message} Existing local data is retained. If the browser blocks cross-origin access, import a private profile generated with “python -m reader export-profile”.`);
    }
  }
  function apply(paper) {
    const p = {...paper, authors: paper.authors.map(a => ({name: a.name}))};
    const data = paper.public_data || {evidence: [], authors: [], references_available: false};
    compile();
    const found = new Map();
    for (const evidence of data.evidence) for (const id of evidence.identifiers) for (const t of targetLookup.get(id) || []) {
      if (!found.has(t.key) || evidence.status === 'confirmed') found.set(t.key, {publication: t, status: evidence.status, source: evidence.source,
        matched_identifiers: evidence.identifiers.filter(value => t.identifiers.includes(value)), excerpt: ''});
    }
    const matches = [...found.values()];
    const status = !targetCount ? 'unconfigured' : matches.some(m => m.status === 'confirmed') ? 'confirmed' : matches.length ? 'provisional' : data.references_available ? 'checked' : 'unavailable';
    const bibliographyPending = !!profile.inspire_author_id && !resolved.updated_at;
    const bibliographyOld = !!resolved.updated_at && Date.now() - Date.parse(resolved.updated_at) > 86400000;
    p.citation = {status, matches, checked_at: data.checked_at, stale: !!data.stale || bibliographyOld, targets_complete: !bibliographyPending,
      references_available: data.references_available, reason: targetCount ? (data.references_available ? 'Reference metadata checked locally; absence of a match is not proof of no citation.' : 'Reference metadata is missing or empty; indexing may be delayed.') : (profile.inspire_author_id ? 'Your personal bibliography is not available yet. Refresh it or import a resolved private profile.' : 'Add private settings to track citations to your publications.')};
    const names = profile.followed_authors.flatMap(f => [f.name, ...(f.aliases || [])]).map(normalize).filter(Boolean);
    for (const a of p.authors) {
      const name = normalize(a.name);
      if (names.some(n => name === n || name.endsWith(' ' + n))) Object.assign(a, {followed: true, match: 'provisional'});
    }
    return p;
  }
  function fill() {
    $p('profile-author').value = profile.inspire_author_id || '';
    $p('profile-categories').value = profile.categories.join(', ');
    $p('profile-followed').value = profile.followed_authors.map(a => [a.name, a.inspire_id || '', (a.aliases || []).join('; ')].join(' | ').replace(/(\s*\|\s*)+$/, '')).join('\n');
    $p('profile-tracked').value = profile.tracked_publications.map(t => { const [k,v] = Object.entries(t)[0]; return k + ':' + v; }).join('\n');
  }
  function formSettings() {
    const cfg = {...profile, inspire_author_id: $p('profile-author').value,
      categories: $p('profile-categories').value.split(',').map(s => s.trim()).filter(Boolean),
      followed_authors: $p('profile-followed').value.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
        const [name, id, aliases] = line.split('|').map(s => s.trim()); return {name, ...(id ? {inspire_id:id} : {}), aliases: aliases ? aliases.split(';').map(s => s.trim()).filter(Boolean) : []}; }),
      tracked_publications: $p('profile-tracked').value.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
        const match = line.match(/^(arxiv|doi|inspire):\s*(.+)$/i); if (!match) throw new Error('Use arxiv:ID, doi:DOI, or inspire:ID, one per line.'); return {[match[1].toLowerCase()]:match[2]}; })};
    const valid = validate(cfg);
    if (valid.categories.some(c => !available.includes(c))) throw new Error(`This instance currently collects ${available.join(', ')}. Choose from these or host another instance with more categories.`);
    return valid;
  }
  async function init(categories, callback) {
    available = categories; changed = callback;
    try { const saved = JSON.parse(localStorage.getItem(storageKey)); if (saved) { profile = validate(saved); if (saved._reader_cache) resolved = validateCache(saved._reader_cache); } } catch (_) { status('Stored settings could not be read. Import a backup or enter them again.'); }
    fill();
    $p('profile-form').addEventListener('submit', event => { event.preventDefault(); try { profile = formSettings(); revision++; resolved = {targets: [], followed: [], updated_at: null}; persist(); changed(); refresh(); } catch (e) { status(e.message); } });
    $p('profile-refresh').addEventListener('click', () => refresh(true));
    $p('profile-export').addEventListener('click', () => { const body = JSON.stringify({...profile, categories: profile.categories.length ? profile.categories : available, _reader_cache: resolved}, null, 2); const url = URL.createObjectURL(new Blob([body], {type:'application/yaml'})); const a = document.createElement('a'); a.href = url; a.download = 'private-profile.yaml'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
    $p('profile-import').addEventListener('change', async event => {
      try {
        const file = event.target.files[0]; if (!file) return; if (file.size > 20_000_000) throw new Error('Configuration exceeds 20 MB.');
        let raw; try { raw = JSON.parse(await file.text()); } catch (_) { throw new Error('Use an exported browser configuration (JSON-compatible YAML), or generate one from ordinary YAML with “python -m reader export-profile”.'); }
        const nextProfile = validate(raw), nextResolved = raw._reader_cache ? validateCache(raw._reader_cache) : {targets:[],followed:[],updated_at:null};
        profile = nextProfile; resolved = nextResolved; revision++; persist(); fill(); changed(); status('Private configuration imported locally.');
        // Imported cached profiles work offline; refreshing is an explicit action if desired.
        if (!raw._reader_cache) refresh();
      } catch (error) { status(`Import failed: ${error.message}`); }
      event.target.value = '';
    });
    $p('profile-clear').addEventListener('click', () => { revision++; profile = {inspire_author_id:null,followed_authors:[],tracked_publications:[],categories:[],display:{}}; resolved={targets:[],followed:[],updated_at:null}; sessionCache.clear(); try {localStorage.removeItem(storageKey);} catch (_) {} fill(); changed(); status('Personal settings and cached bibliography cleared from this browser.'); });
    changed(); refresh();
  }
  return {init, apply, categories: () => profile.categories, display: () => profile.display};
})();
