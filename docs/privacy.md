# Public website, private personalization

The shared website is public and anyone can use it. It distributes ordinary arXiv announcement data and general INSPIRE/reference metadata. Your browser privately applies your choices to those data. There is no server-side user account or personalized page URL.

## Your private data

The settings form saves your author ID, followed authors, tracked papers, selected categories, and cached bibliography in localStorage under a path-specific key. Reading history/bookmarks are also local. The website does not upload these values to GitHub, the collector, or a database, and does not place them in URLs. Import uses the browser's File API, not a file-upload endpoint. Citation labels and followed-author highlights are computed after the public data arrive.

**Export private configuration** downloads JSON-compatible YAML containing your settings and optionally a resolved bibliography. Keep that file private. **Import private configuration** restores it on another browser or device. **Clear personal settings** removes the profile/bibliography from this browser; it does not delete exported files or your separate bookmarks/history.

The optional Python exporter reads local `config.yaml` and writes `private-profile.yaml`. Both are ignored by Git and excluded from the publishing helper. They are not GitHub Actions secrets because the public collector does not need them at all. Only anonymous host settings in `config.example.yaml` are published.

## Who can see what

| Party | Access |
| --- | --- |
| Other website visitors | Public papers and general metadata; their own locally computed results. |
| GitHub / site hosting | Public code, archive, web requests, and ordinary hosting access logs; not your entered settings. |
| INSPIRE | Your direct API queries when resolving your author/publication identifiers. Requests omit credentials and the referrer. |
| Someone with access to your browser profile/device | May read browser-local settings and history. LocalStorage is not encrypted storage. |
| Someone you give an exported private profile or screenshot to | Can see the private data in that file or screenshot. |

Use a trusted browser/device. Anyone able to modify the application JavaScript could change how it handles settings; only run trusted deployments. This is browser-local personalization, not a claim of anonymity from your network provider or INSPIRE.

## Public data safeguards

- Source staging uses an explicit allowlist and rejects nonempty destination directories, preventing stale private files from being included.
- `update --public` rejects nonempty personal settings and archives previously generated in private mode.
- `build --public` requires public-collector state and exports allowlisted paper fields. It strips precomputed personal matches and author highlights.
- The workflow's archive save rejects personal target lists and personal paper matches.
- Private exported profiles and personalized local builds are never included by the publishing helper.

No encryption/passphrase layer is necessary for this shared model: private settings are never part of the hosted payload in the first place. Private local Python builds remain available for offline use but must not be deployed as public sites.

## API and browser limits

INSPIRE lookups are direct browser requests and require its CORS behavior and your network policy to allow them. Live CORS availability could not be verified in the development sandbox. A failed lookup is visible; no proxy is used to silently send private settings elsewhere. Generate a resolved profile with `python -m reader export-profile` and import it if browser access is blocked. An imported resolved profile can perform local matching without an external request; refresh is available explicitly.

Clearing browser storage removes settings unless you exported a backup. Your browser does not synchronize these settings across devices automatically. Category preferences can select only categories already collected by the shared host; host a separate instance or ask the host to add categories for a wider selection.
