# arXiv daily reader

A public arXiv reading website that everyone can use, with **private, per-browser personalization**. Python and GitHub Actions collect ordinary announcements and reference metadata; GitHub Pages serves the website. Each visitor's citation matching, followed-author highlights, bookmarks, and reading history stay in their own browser.

No reader accounts, database server, analytics, paid services, or arXiv/INSPIRE API keys. The default public listing combines **hep-ph** and **hep-th**.

## How privacy works

- **Public:** application code, collected categories, paper metadata, ordinary author/reference identifiers, and the announcement archive.
- **Private to your browser:** your INSPIRE ID, followed-author choices, tracked-paper choices, resolved personal bibliography, citation-filter results, bookmarks, and reading history.
- **Not uploaded to this website or GitHub:** the settings you enter or import. Bibliography lookups go directly from your browser to INSPIRE, so INSPIRE receives those queries.
- `config.yaml` and `private-profile.yaml` are ignored by Git and excluded from the publication helper. Only the anonymous [`config.example.yaml`](config.example.yaml) is published. The public collector refuses personal settings or a previously personalized archive.

The site needs no shared password: two people can open the same URL and see different highlights based on their own local settings. Settings are not synchronized automatically between devices. Export/import a private configuration to move them. See [privacy details](docs/privacy.md).

## Use the website

1. Open **My private settings**.
2. Enter your INSPIRE author ID or author-profile URL.
3. Optionally add followed authors and extra tracked papers.
4. Choose **Save in this browser**.

Your publications are retrieved from INSPIRE and cached locally. Each listing is matched against that bibliography in your browser. **Export private configuration** downloads one private YAML-compatible file containing your settings and cached bibliography. **Import private configuration** reads it locally; it does not upload it.

Author entries use `Name | INSPIRE ID | alias; alias`, one per line. A name alone is accepted as a provisional identity match. Extra papers use `arxiv:ID`, `doi:DOI`, or `inspire:ID`, one per line. Category selection can narrow the categories collected by this particular website; the host can add further categories to its public configuration.

## Features

- New submissions, cross-lists, replacements, and replacement cross-lists, with original announcement dates and per-category positions/types.
- Deduplication by base arXiv identifier within a date. A later replacement can correctly appear on a later date.
- Exact cited-publication titles, identifier evidence, and links. Confirmed, provisional, checked-without-a-match, and unavailable states are distinct.
- Author highlighting using linked INSPIRE records where available; name-only matches remain provisional.
- Combined AND/OR filters, text search, sorting, collapsible abstracts/citation details, earlier dates, and an all-dates view.
- Browser-local read/bookmark history, with export/import.
- A persistent `data` Git branch holding ordinary public scholarly metadata; no dependence on expiring Actions artifacts for the archive.

**Archive coverage starts with collection.** RSS is not a complete historical archive. Missing references and missing matches are not evidence that a paper does not cite you. See [sources and limitations](docs/data-sources.md).

## Quick local preview

Requires Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m reader --output site demo --public
python -m http.server 8000 --directory site
```

Open **http://localhost:8000**. The demo uses clearly labelled synthetic announcements. On Windows, activate with `.venv\Scripts\activate` instead.

To collect real public data, stop the server with Ctrl+C and run:

```bash
python -m reader --config config.example.yaml update --public
python -m reader --config config.example.yaml build --public
python -m reader check-site
python -m http.server 8000 --directory site
```

The public configuration's `inspire_author_id` must be `null`, and followed/extra paper lists must stay empty. Anyone using the site supplies those privately through the settings form instead.

## Private configuration file and offline fallback

The settings form is the easiest way to configure the public site. If you prefer ordinary YAML or your browser cannot reach INSPIRE because of networking/CORS restrictions, use the optional Python exporter:

```bash
cp config.example.yaml config.yaml
# Edit the ignored config.yaml with your personal settings.
python -m reader validate
python -m reader export-profile
```

This retrieves your bibliography and writes **`private-profile.yaml`**. Import that file using **My private settings → Import private configuration**. The imported bibliography can be used without a browser API request. Use **Refresh my bibliography** later, or rerun the exporter and re-import.

To export only the settings without networking:

```bash
python -m reader export-profile --settings-only
```

That file lets the browser perform the bibliography lookup after import. Both export forms use JSON-compatible YAML, so the browser can parse them natively without a YAML library. Hand-written ordinary YAML is accepted by Python; convert it with the exporter before browser import. Do not commit or upload these private files.

A personal YAML example:

```yaml
categories: [hep-ph, hep-th]
inspire_author_id: YOUR_INSPIRE_AUTHOR_ID
followed_authors:
  - name: An Author
    inspire_id: '1234567'
tracked_publications:
  - arxiv: hep-th/9711200
```

Replace placeholder IDs with real ones. All personal fields are documented in [configuration reference](docs/configuration.md). The exporter retains resolved bibliography information in an optional `_reader_cache` section; Python ignores that section when reading settings.

## Publish to GitHub

After installing Python requirements, run:

```bash
python scripts/publish.py
```

The helper validates the anonymous host configuration, tests the project, guides GitHub authentication, creates a **public `arxiv-reader` template repository**, uploads only approved source files, enables GitHub Actions as the Pages source, and starts deployment. It excludes your private configuration, profile exports, local state, and generated sites. It never force-pushes.

Git is required. On Linux x86-64/ARM64, a missing GitHub CLI is downloaded from its official release and checked against its published SHA-256 checksum. Other platforms should install [GitHub CLI](https://cli.github.com/) first. Chrome or Chromium runs the browser checks.

- Change the repository name with `--name my-daily-arxiv`.
- Resume an interrupted creation with `--resume YOUR-USERNAME/arxiv-reader` for that same repository.
- If local browser execution is unavailable, use `--skip-browser-check`; GitHub's test workflow still runs the full suite and deployment runs browser smoke checks.
- Existing repository names cause creation to stop, rather than overwriting them.

Follow the printed Actions link and wait for **deploy** to succeed. Its environment link is the public reader URL, usually `https://YOUR-USERNAME.github.io/arxiv-reader/`. Then import your private profile or enter your settings in the browser. No personal settings are needed by the workflow and no repository secrets are required.

### Manual setup / template copies

1. Use **Use this template → Create a new repository**, or upload the approved source files including `.github/workflows`. Do **not** upload `config.yaml`, `private-profile.yaml`, `state/`, or a personalized local build.
2. Keep **Include all branches** unchecked when copying a template, so the new instance starts its own archive.
3. In **Settings → Pages → Source**, select **GitHub Actions**.
4. Run **Actions → Update and publish reader → Run workflow**; enable workflows first if GitHub asks.
5. Enable **Template repository** in **Settings → General** if you want others to copy it. The helper does this automatically.

The host may edit public category/display/update defaults in `config.example.yaml`, leaving all personal fields empty. Visitors do not need their own repository to use this shared public website.

## Updates, storage, and recovery

The workflow runs at **05:23, 11:23, and 17:23 UTC** every day and supports manual execution. It captures announcements, rechecks general citation metadata, commits the public archive/cache, builds the site, validates it, and deploys. The archive is saved before deployment, so deployment failure does not lose collected listings.

Default budgets: a 30-day recheck window, 400 papers and 20 HTML bibliography checks per run. Unchecked/least-recently-attempted records receive priority. Successful response caches last 24 hours, missing-record caches six hours. HTML checks have their own rotating budget. Each visitor's bibliography is cached separately in that visitor's browser.

GitHub schedules are best-effort and can be delayed; inactive public repositories can have schedules disabled after 60 days. Monitor the site's timestamp and Actions runs. Recheck older records with the manual workflow's `recheck_all` input, or:

```bash
python -m reader --config config.example.yaml update --public --recheck-all
```

To browse the hosted public archive locally, clone its data branch into `state` in a fresh source checkout:

```bash
git clone --branch data --single-branch https://github.com/YOU/arxiv-reader.git state
python -m reader --config config.example.yaml build --public
```

Recover damaged day files from earlier `data` branch commits. Corrupt files are not silently discarded. Daily listings are never automatically deleted; unused HTTP cache entries older than 90 days are pruned from the current tree. Git history remains available.

Saved genuine RSS snapshots can be imported from `CATEGORY.xml` files:

```bash
python -m reader --config config.example.yaml update --public --feed-dir saved-feeds
```

This preserves snapshot dates; it is not a historical-feed retrieval API.

For private local use, Python still supports `update` and `build` without `--public`, using your local `config.yaml` for precomputed personalization. **Do not deploy that output.** Public collection/building refuses to reuse personalized state. Use a separate `--state` directory when switching modes.

## Tests

```bash
python -m unittest discover -s tests -v
python -m reader --config config.example.yaml validate
python -m reader --output site-public demo --public
python -m reader --output site-public check-site
python scripts/browser_test.py --site site-public --profile-fixture tests/fixtures/browser-profile.json
```

Tests cover matching, configuration validation, duplicate/category handling, caches, delays/outages, the full pipeline, a Git archive round trip, and the privacy boundary between private settings and public artifacts. Browser tests exercise local profiles, citation/author matching, settings clearing/import, filters, sorting, history, mobile layout, and repository subpaths. They require an environment that permits local sockets and Chrome. See [verification status](docs/verification.md).

The only Python runtime dependency is PyYAML. The browser has no framework, build system, analytics, external fonts, or CDN scripts. See [architecture](docs/architecture.md) and [contribution notes](CONTRIBUTING.md).

## License and sources

Code is [MIT licensed](LICENSE). Source metadata retains its own terms; this does not relicense papers. PDFs remain on arXiv. HTML is reduced to bibliography identifiers before caching.

This independent reader follows the official [arXiv RSS specification](https://info.arxiv.org/help/rss_specifications.html), [arXiv API manual](https://info.arxiv.org/help/api/user-manual.html), [arXiv API terms](https://info.arxiv.org/help/api/tou.html), [INSPIRE API documentation](https://github.com/inspirehep/rest-api-doc), and [GitHub Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
