# Data sources, evidence, and limitations

These design decisions were checked against official documentation before implementation.

## arXiv announcements

The [RSS specification](https://info.arxiv.org/help/rss_specifications.html) defines channel and item `pubDate`, author/category fields, and `announce_type`. The reader uses `https://rss.arxiv.org/rss/CATEGORY` with serial requests. It retains the original local calendar announcement date, not the collector's date, and records `new`, `cross`, `replace`, and `replace-cross` per source category. The primary merged order is category configuration order followed by the feed's own item positions. There is no single canonical total order across separate category feeds.

Snapshots are captured to `days/YYYY-MM-DD.json`. Repeated runs merge the same date and base arXiv identifier without making duplicate entries. Captured dates can be browsed indefinitely. If one feed fails, successfully collected categories are retained and partial coverage is visible. Missing/invalid dates or announcement types fail visibly rather than being guessed.

The [Atom search API](https://info.arxiv.org/help/api/user-manual.html) exposes submission/update dates and search order. Those fields do not reconstruct the exact historical announcement date, historical cross-list events, replacement announcements, or per-category announcement order. Accordingly, this reader does **not** claim to backfill daily announcements from Atom, RSS, or a guessed weekday conversion. A new instance starts with the available feed, and downtime longer than feed availability can leave gaps. There is no guaranteed public API for reconstructing the entire original announcement stream. Saved, genuine RSS snapshots can be imported. Archive coverage notices make these limits explicit.

Empty feeds (including weekends/holidays) are retained as observed empty dates. An absent date is unknown coverage, not automatically zero submissions. The site does not pretend it can distinguish every missed feed from an arXiv holiday.

The [arXiv API terms](https://info.arxiv.org/help/api/tou.html) require serial legacy-API requests spaced by at least three seconds. The collector spaces arXiv requests by 3.1 seconds, caches responses, links to PDFs, and does not mirror PDFs or full-text articles. Author/abstract strings are rendered as text, not trusted HTML. TeX notation is preserved as text; a math-rendering dependency is intentionally omitted.

## INSPIRE-HEP

The [official REST API documentation](https://github.com/inspirehep/rest-api-doc) documents numeric records, `/api/arxiv/…`, `/api/doi/…`, structured searches, pagination, and limits. The [official record schema](https://github.com/inspirehep/inspire-schemas/blob/master/inspire_schemas/records/hep.yml) defines reference and author fields. No API key is required.

On the public site, the visitor's configured author identifier is resolved directly in their browser (or by the optional private Python profile exporter). Publications are retrieved with a search on the linked `authors.record.$ref`, with all result pages visited. Additional papers are resolved to literature records and equivalent identifiers. The public collector resolves incoming arXiv papers to INSPIRE literature records and publishes generic reference evidence. The browser matches that evidence to the visitor's private target list. Requests are conservatively spaced below INSPIRE's documented rate limit.

| Label | Evidence |
| --- | --- |
| Confirmed | A structured INSPIRE reference has a matching literature record ID, arXiv ID, or DOI. |
| Provisional | An explicit identifier is found in an INSPIRE raw reference or in an arXiv HTML bibliography item. |
| No tracked citation detected | Nonempty INSPIRE reference metadata was checked, but no configured target matched. References may still be incomplete. |
| Citation data unavailable | References are missing/empty, the record is not indexed, or no successful check exists. This is not a negative citation claim. |

A citation can be provisionally detected while INSPIRE references are unavailable. Match details show that distinction, source, identifier, target title/links, and check time. If refresh fails, previous evidence is retained and marked stale; an incomplete target refresh is also reported. Successful reference metadata is not assumed complete or error-free. INSPIRE updates may lag by days or longer, and coverage outside HEP is variable. The default recheck window is 30 days; older records need a manual recheck if metadata arrives later. Citation checks reflect INSPIRE's/current HTML's latest available version, not necessarily the specific version first announced on an archived date.

INSPIRE currently limits a search to 10,000 results. If an author's bibliography exceeds that, the reader explicitly reports the limit instead of silently claiming a complete personal bibliography. Users with exceptionally large collaboration publication lists would need to extend the query-partitioning strategy. API/schema changes, withdrawn records, unresolved identifiers, duplicate INSPIRE records, and name changes can all affect recall.

## Additional bibliography check

When enabled and within the configured per-run budget, the collector requests `https://arxiv.org/html/ID` and inspects only elements with arXiv's `ltx_bibitem` class. It does **not** treat mentions in the body text as citations. Matching is based on exact explicit identifiers, with version/case normalization, rather than fuzzy titles or author surnames.

Not every paper has HTML. Some bibliographies omit arXiv IDs/DOIs, use unexpected markup, or contain ambiguous punctuation; such citations can be missed. The checker does not download/execute TeX, unpack source archives, or run PDF OCR. HTML-derived evidence remains provisional even when the identifier is clear. Only extracted identifiers are cached; original HTML/full text is discarded. The HTML budget means some papers may rely exclusively on INSPIRE metadata in a given run.

## Hosting

GitHub's [custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) specifies artifact upload, Pages/OIDC permissions, and deployment environments. This repository follows that mechanism. The archive is saved to Git **before** uploading the deployment artifact, so artifact/cache retention does not determine the life of the archive.

[Scheduled Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) can be delayed or dropped at high load, and inactive public repositories can have schedules disabled after 60 days. Scheduling is therefore best-effort, not a guarantee of historical completeness. The three off-hour runs reduce transient-failure exposure. The Pages website and ordinary scholarly metadata are public; visitor configurations and personalized matching results stay in their browsers. Bookmarks and reading history are local browser data, so clearing browser storage removes them unless exported.
