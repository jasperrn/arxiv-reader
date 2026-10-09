# Contributing

Use Python 3.11+ and install `requirements.txt`. Run the unit suite and browser checks from the README before submitting a pull request. Network-dependent data collection is not required for tests; use the deterministic demonstration client or explicit fixtures.

Keep the project small: prefer the standard library, avoid a frontend build tool unless justified, and keep personal preferences in browser-local settings or ignored `config.yaml`, never in published source. Public host settings belong in `config.example.yaml`. New data sources must retain evidence and error states, obey rate limits, and avoid treating missing metadata as a confirmed negative result.

Never commit credentials, local browser exports, full-text papers, or personal test data. Keep source changes on `main` and archive updates on `data`. For parser bugs, add a small redacted fixture and a regression test. Document any API limitations that a change cannot resolve.
