#!/usr/bin/env python3
"""Export LogVault saved searches and index targets into a portable bundle.

This is the counterpart to ``import_saved_searches.py``. It reads the source
instance over its API (no database access) and writes a JSON document that the
importer can replay into another instance.

Usage
-----
    python export_saved_searches.py \
        --base-url http://localhost:8000 \
        --email admin@example.com \
        --password '...' \
        --out saved-searches-bundle.json

    # or with a JWT
    python export_saved_searches.py ... --token "$TOKEN"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from import_saved_searches import _get_list, _request


def _login(base: str, email: str | None, password: str | None, token: str | None) -> str:
    if token:
        return token
    if not email or not password:
        raise SystemExit("provide --token, or --email and --password")
    status, body = _request(
        "POST", f"{base}/auth/login", body={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(f"login failed: HTTP {status} {body}")
    return body["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Source API base URL")
    parser.add_argument("--out", required=True, help="Where to write the bundle JSON")
    parser.add_argument("--email", help="Admin email (with --password)")
    parser.add_argument("--password", help="Admin password (with --email)")
    parser.add_argument("--token", help="Bearer token; skips the login call")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    token = _login(base, args.email, args.password, args.token)

    credentials = _get_list(base, "/credentials", token)
    indexes = _get_list(base, "/indexes", token)
    try:
        profiles = _get_list(base, "/s3-profiles", token, optional=True)
    except SystemExit:
        profiles = []
    templates = _get_list(base, "/templates", token)

    cred_by_id = {c["id"]: c for c in credentials}
    index_by_id = {i["id"]: i for i in indexes}
    profile_by_id = {p["id"]: p for p in profiles}

    def cred_label(cred_id):
        cred = cred_by_id.get(cred_id)
        return (cred or {}).get("label"), (cred or {}).get("org_slug")

    bundle = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": base,
        "credentials": [
            {
                "label": c.get("label"),
                "org_slug": c.get("org_slug"),
                "owner_scope": c.get("owner_scope"),
            }
            for c in credentials
        ],
        "index_targets": [],
        "saved_searches": [],
    }

    for idx in indexes:
        label, org = cred_label(idx.get("credential_id"))
        bundle["index_targets"].append(
            {
                "name": idx.get("name"),
                "region_code": idx.get("region_code"),
                "physical_index": idx.get("physical_index"),
                "description": idx.get("description"),
                "credential_label": label,
                "credential_org_slug": org,
            }
        )

    for tpl in templates:
        label, org = cred_label(tpl.get("credential_id"))
        idx = index_by_id.get(tpl.get("index_target_id"))
        profile = profile_by_id.get(tpl.get("s3_profile_id"))
        bundle["saved_searches"].append(
            {
                "name": tpl.get("name"),
                "phrases": tpl.get("phrases") or [],
                "ids": tpl.get("ids") or [],
                "exact_phrases": tpl.get("exact_phrases") or [],
                "exclude_phrases": tpl.get("exclude_phrases") or [],
                "exclude_exact_phrases": tpl.get("exclude_exact_phrases") or [],
                "message_types": tpl.get("message_types") or [],
                "aggregation": tpl.get("aggregation"),
                "customer": tpl.get("customer"),
                "region_code": tpl.get("region_code"),
                "credential_label": label,
                "credential_org_slug": org,
                "index_name": (idx or {}).get("name"),
                "index_region": (idx or {}).get("region_code"),
                "s3_profile_name": (profile or {}).get("name"),
            }
        )

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(
        f"wrote {args.out}: {len(bundle['credentials'])} credentials, "
        f"{len(bundle['index_targets'])} indexes, "
        f"{len(bundle['saved_searches'])} saved searches"
    )


if __name__ == "__main__":
    main()
