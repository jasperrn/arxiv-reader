# Architecture

```
PUBLIC: config.example.yaml -> RSS + INSPIRE reference collection
                                       |
                                       v
                             public data Git branch
                                       |
                                 static site build
                                       |
                               public GitHub Pages
                                       |
                                       v
PRIVATE: browser settings + personal bibliography -> local matching/highlights
                     |
             private profile export/import
```

`reader/config.py` validates YAML and defaults. `reader/arxiv.py` parses dated RSS snapshots and deduplicates them. `reader/http.py` implements serial requests, rate limits, bounded retries, stale/negative/conditional caching, and removal of unnecessary contact/full-text data. `reader/inspire.py` extracts generic reference evidence and also supports the private Python matching/export workflow. `reader/pipeline.py` captures announcements and refreshes metadata with fair budgets.

`reader/build.py` builds a relative-URL static site. In public mode it emits only ordinary metadata and identifies the manifest's personalization mode as `browser`. It refuses personalized input state. `reader/web/profile.js` manages local configuration, optional direct INSPIRE bibliography lookups, private import/export, and local matching. `reader/web/app.js` renders the listing and filters, using text nodes for untrusted metadata. No personal settings are sent back to the host.

`reader/profile.py` optionally resolves a private bibliography in Python and writes a browser-importable JSON-compatible YAML file, useful when CORS or network policy blocks browser requests. No private config file is needed to build or operate the public website.

## Persistent public state

The `data` branch contains:

```
days/YYYY-MM-DD.json  # announcements and generic public_data reference/author metadata
cache/<sha256>.json  # general API/feed cache, not visitor lookups
targets.json         # empty target list in public mode
status.json          # public collector status and coverage
```

The public collector never resolves a visitor's bibliography. Its pipeline writes observations before slow metadata work, rechecks recent records, rotates request budgets, and distinguishes missing references from absent matches. The archive is committed before deployment. The data branch is serialized and never force-pushed; cache/artifact expiry does not determine archive lifetime.

A fresh template copy starts without a data branch. Switching from a private local archive to public mode requires a clean, separate state directory. Historical raw announcement order cannot be reconstructed from RSS or Atom if it was never captured.

## Browser state and size

The browser normally fetches only the selected date. All-dates mode fetches archived dates sequentially and retains the latest occurrence of each paper. Very large all-date views can consume substantial memory.

A visitor's profile and resolved bibliography live under `arxiv-reader-profile-v1:<path>`. Reading history uses `arxiv-reader-history-v1`, shared by reader instances on the same origin. Local data are private from other visitors but accessible to someone using the same browser profile. No service worker, analytics, backend user database, or automatic cloud synchronization is used.

The Python precomputed-personalization path is retained for local/private use and tests. Public workflows explicitly use `--public` and the anonymous host configuration.
