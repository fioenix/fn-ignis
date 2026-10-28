# Spec 020 synthetic pre-feature baseline

Captured at checkout `8b9dfb0faf73d6d6a51147b420e86988b43b5b98`, before source changes.
All values are synthetic. There is no account, caller store, browser, API or credential capture.

- `tiktok-prepare.json`: actual default tactical preparation using the unit helper; fixed UUIDs and clock. The loopback URL and tab script are explicitly marked mock transport placeholders. They do not prove relay behavior.
- `tiktok-receipt.json`: actual staged validator and submitted outward receipt, including unknown metrics, query lineage, sanitized content link and cached replay equality.
- `submit-cancel-schemas.json`: actual FastMCP public input schemas, with exactly 53 tools observed.
- `{day,week,month}-created.json` and `{day,week,month}-seen.json`: real comparators using the existing period and seen-axis unit helpers. YouTube and TikTok each have one known equal collection path across both periods. Created has complete daily coverage; seen has one successful snapshot in each period and explicit matching cadence. Both retain their actual response shape. These are characterization fixtures; the pre-feature implementation does not yet enforce collection-path comparability.

Regenerate from the checkout, using the owner's shared venv without changing it:

```sh
PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/python tests/fixtures/meta_host_browser_baseline/capture.py
PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/python tests/fixtures/meta_host_browser_baseline/capture.py --check
```

The script blocks dotenv and secrets-file settings sources before importing Ignis.
It writes only these nine JSON files; `--check` compares without writing. Existing
`tests/fixtures/watchlist_period_created_baseline/` is not regenerated or modified.
