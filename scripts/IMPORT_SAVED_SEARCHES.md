# Import saved searches and indexes into another LogVault instance

The production instance is on AWS and is not reachable from here. This folder
contains a portable bundle and an import script that you can run from the prod
host (or any machine that can reach the prod API).

## Files

| File | Purpose |
|---|---|
| `tmp/saved-searches-bundle.json` | 4 credentials, 6 index targets, 68 saved searches exported from this instance. **Not committed** (contains customer names and filter phrases). |
| `scripts/import_saved_searches.py` | Stdlib-only importer. Logs in, creates missing indexes, maps credentials/profiles by name, then creates/updates/skips saved searches. |

## Run it

Copy the bundle and the script to the prod host (or a bastion with access to
the prod API), then:

```bash
# 1. Dry run first. Nothing is written.
python3 import_saved_searches.py \
  --base-url http://localhost:8000 \
  --email admin@example.com \
  --password '...' \
  --bundle saved-searches-bundle.json \
  --dry-run

# 2. Real import. Existing names are skipped by default.
python3 import_saved_searches.py \
  --base-url http://localhost:8000 \
  --email admin@example.com \
  --password '...' \
  --bundle saved-searches-bundle.json
```

If the prod instance uses SSO and you already have a JWT, pass `--token "$TOKEN"`
instead of `--email`/`--password`.

### Options

| Flag | Meaning |
|---|---|
| `--on-conflict skip` | Leave an existing saved search with the same name untouched. **Default.** |
| `--on-conflict update` | Overwrite the existing saved search with the exported version. |
| `--on-conflict copy` | Import as `<name> (imported)`, leaving the existing one alone. |
| `--no-create-indexes` | Do not create missing index targets; saved searches keep an empty source. |
| `--dry-run` | Print the plan without writing. |

## What gets mapped, and what cannot

- **Indexes** are matched by `(name, region)`. Missing ones are created. If the
  index's credential label is not in prod, the index is created without a
  credential — set it in the UI afterwards.
- **Credentials** are matched by label (then org slug). They are **not**
  created: a credential needs a Last9 refresh token, which is a secret and is
  not in the bundle. If prod lacks a label, the saved search is created with no
  remembered source; create the credential first, or edit the saved search
  afterwards.
- **S3 profiles** are matched by name. A missing profile leaves the saved
  search's destination empty.
- **Saved searches** carry phrases, IDs, exact/exclude phrases, message types,
  aggregation, customer, and remembered region. Names are unique, so the
  conflict mode above decides what happens.

## If you prefer SQL

The bundle is a plain JSON document. If you would rather load it directly into
the prod database, the tables are `filter_templates`, `index_targets`, and
`last9_credentials` (the last one only for name/id mapping). The API path is
safer because it runs the same validation the UI does and writes the audit log.
