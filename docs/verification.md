# Verification status

Local verification on 2026-10-09, Python 3.14.4 and PyYAML 6.0.3:

- **68 automated tests passed** using `python3 -m unittest discover -s tests -v`.
- Included the full feed → archive → INSPIRE/HTML evidence → static site pipeline using deterministic synthetic responses.
- Included real local Git bootstrap, archive commit/push to a temporary bare repository, and subsequent restore.
- Configuration validation passed for the checked-in example.
- Offline demonstration build passed; generated manifest and two day payloads passed `check-site`.
- Python source compiled successfully; an installable wheel was built successfully without network access.
- Both frontend JavaScript files passed syntax checks in JavaScriptCore. The private-profile matching logic was executed in JavaScriptCore with a minimal test DOM/storage: confirmed/provisional citation matching, arXiv surname/full-name author matching, settings clearing, and cached offline use passed. These checks are repeatable with `python scripts/check_profile_logic.py` and run in the unit suite when JavaScriptCore is installed. They are not a substitute for real browser/layout tests.
- Privacy regression tests verify that public collection rejects personal settings/state, public output strips personal fields, staged source excludes private files, and private exports have restrictive file permissions.
- The live collector was attempted and correctly reported network unavailability rather than pretending to fetch announcements. Its saved failure status can still be built into a valid empty/stale site.

## Checks requiring another environment

The execution sandbox denies socket creation and external DNS access. As a result:

- Live arXiv and INSPIRE responses could not be fetched from the collector in this environment. The API shapes and deployment design were checked against official documentation through the available documentation browser.
- Desktop/mobile Chrome integration tests were implemented and attempted, but **did not run**: the local HTTP server and Chrome both failed at sandbox socket restrictions. No visual/browser success is claimed.
- GitHub publishing was not performed: GitHub CLI and authenticated GitHub access are absent, and this workspace's `.git` placeholder is read-only. Source is ready for the publishing helper, which creates a separate staging checkout.

On a normal computer, install the Python requirements, then run:

```bash
python scripts/publish.py
```

This runs the local tests and browser checks, handles GitHub authentication, creates the public template repository, enables Pages, and starts the workflow. The GitHub test workflow repeats the Python tests on 3.11–3.14 and the full browser suite. The deployment workflow checks the real generated site in Chrome before deploying it. Check the completed Actions run and deployed URL before treating deployment as verified.

The generated local `site/` and `site-public/` directories are explicitly labelled synthetic demonstrations and are excluded from publication. For a real public preview, use the anonymous host configuration with `update --public` followed by `build --public`. Private local builds must not be deployed.
