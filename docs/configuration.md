# Configuration reference

All personal settings belong in the private browser profile, or in the ignored root `config.yaml` when using the optional Python exporter. Public host defaults live in `config.example.yaml`; keep its personal fields empty. Omitted settings use the defaults below. Unknown keys, duplicate YAML keys, invalid types, unsafe YAML tags, empty category lists, and malformed identifiers are rejected with a message naming the setting. Run `python -m reader validate` to check a local private file, or `python -m reader --config config.example.yaml validate` for public host defaults. Never publish the private file.

Browser settings can be entered through the form or imported from a JSON-compatible YAML profile exported by the form or `python -m reader export-profile`. Ordinary YAML syntax is supported by Python; convert it with the exporter before browser import. The optional `_reader_cache` section contains private resolved metadata and is ignored by Python's configuration parser.

## Research settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `categories` | `[hep-ph, hep-th]` | Nonempty list of unique arXiv category codes. Syntactic validation accepts codes such as `math.AG`, `cs.LG`, `astro-ph`, `hep-th`; a nonexistent code produces a feed error at collection time. |
| `inspire_author_id` | `null` | Your numeric INSPIRE author record ID, INSPIRE ID, or BAI. `null` disables automatic personal bibliography tracking. |
| `followed_authors` | `[]` | List of author mappings, described below. |
| `tracked_publications` | `[]` | List of identifier mappings, described below. |

A followed-author entry must have a nonempty `name`. Optional `inspire_id` is accepted for compatibility but ignored for highlighting. Optional `aliases` is a list of explicit alternate spellings. Example:

```yaml
followed_authors:
  - name: Edward Witten
    inspire_id: E.Witten.1
    aliases: [Ed Witten, E. Witten]
```

Followed authors are matched directly against the arXiv author list, without INSPIRE author lookups. A surname is sufficient: `name: Witten` matches `Edward Witten` and `E. Witten`. Full names and aliases also work. Matching ignores case and punctuation, handles `Surname, Given` ordering, and requires complete trailing name tokens: `Chen` does not match `Cheng` or `Chen Li`. Compound surnames such as `de Sitter` are supported. All people with a matching surname are highlighted. Matches are provisional name matches, not verified identities. Existing optional `inspire_id` fields remain accepted for compatibility but do not affect highlighting.

A tracked-publication entry contains **exactly one** key:

```yaml
tracked_publications:
  - arxiv: '2301.12345'       # Versions are accepted and normalized away.
  - arxiv: hep-th/9711200    # Legacy IDs supported.
  - doi: 10.1103/PhysRevLett.19.1264
  - inspire: '451647'       # Literature record, not author record.
```

These are resolved through INSPIRE to discover equivalent arXiv, DOI, and record identifiers. If multiple entries identify the same paper, their groups are combined. Your own paper may simultaneously count as an additional tracked publication. Unresolved arXiv/DOI targets still match their explicit identifier.

## Display

| `display` key | Default | Allowed values |
| --- | --- | --- |
| `title` | `My arXiv reader` | Nonempty text, maximum 120 characters. |
| `abstracts_expanded` | `false` | Boolean. |
| `citation_details_expanded` | `false` | Boolean. |
| `show_replacements` | `true` | Boolean; users can toggle it in the interface. |
| `default_sort` | `announcement` | `announcement`, `title`, `citations`. |

Public display defaults come from the host file; imported private display preferences can override the visitor's title and expansion defaults locally. Reading history/bookmarks are independent browser settings. Search applies to the selected date, or all captured dates when that option is selected. In all-dates mode, repeated papers are shown once using their latest announcement in the archive.

## Updates

These settings control the host collector or private Python run, not the public visitor's browser. Browser bibliographies have a one-day local cache and an explicit refresh button.

| `updates` key | Default | Meaning |
| --- | --- | --- |
| `recheck_days` | `30` | Refresh window in calendar days; integer 1–3650. |
| `metadata_ttl_hours` | `24` | Successful response/result cache lifetime; integer 1–720. |
| `missing_ttl_hours` | `6` | Missing-record/result retry interval; integer 1–720. |
| `max_papers_per_run` | `400` | Maximum papers attempted each run; integer 1–10000. |
| `bibliography_check` | `true` | Enable conservative arXiv HTML bibliography identifier checks. |
| `max_bibliographies_per_run` | `20` | HTML check budget; integer 1–1000. Use `bibliography_check: false` to disable. |
| `user_agent` | `arxiv-daily-reader/1.0 (personal research reader)` | Nonempty single-line HTTP identification. Optionally include a contact address you are comfortable making public. |

Large category lists may exceed the request budget; increase it only within reasonable run time and source-service limits. Requests are serial: at least 3.1 seconds apart across arXiv hosts and 0.4 seconds apart for INSPIRE. Retries respect `Retry-After`, use backoff, and defer long waits to the next scheduled run. A host that remains unavailable after retries is not hammered for every remaining paper. Missing HTTP 404 results are cached too.

RSS responses cache for one hour, HTML identifier extracts for seven days, and missing HTML for one day. The archive itself has no expiry; unused HTTP cache entries older than 90 days are pruned from the current data tree (Git history remains).

### Private keyword filters

Add this to private `config.yaml`, or enter one keyword/phrase per line under **My private settings** on the website:

```yaml
keywords:
  terms:
    - conformal bootstrap
    - dark matter
  scope: title_abstract
```

Use `scope: title` for titles only, or `title_abstract` for titles and abstracts. Matching is case-insensitive literal substring matching (no regex); any listed term is sufficient. Phrases must occur within a single title or abstract. For example, `spin` also matches `spinning`. The listing shows which keywords matched. Enable **Followed keywords** to filter, and use the existing AND/OR control to combine it with authors, citations, bookmarks, and unread status. With no terms, this filter matches no papers.

Keyword preferences stay in the browser and are included in private configuration imports/exports. To import a YAML edit, run `python -m reader export-profile --settings-only` and import the resulting private-profile.yaml. Keep `keywords.terms` empty in public config.example.yaml; publication guards reject personal keyword lists.
