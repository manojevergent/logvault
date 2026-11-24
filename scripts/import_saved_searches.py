#!/usr/bin/env python3
"""Import LogVault saved searches and index targets into another instance.

The source instance is exported to a portable JSON bundle (see
``scripts/export_saved_searches.py`` or the SQL in the runbook). This script
reads that bundle and replays it against the target API. It needs no database
access, only an API URL and an admin login.

What it does
------------
1. Logs in to the target API (or uses ``--token``).
2. Creates any index targets that are missing (name + region is the key).
3. Maps credentials and S3 profiles by label/name, because database ids differ
   between instances. A missing credential is reported and the saved search is
   still created with no remembered source (it can be picked at run time).
4. Creates, updates, or skips saved searches by name, per ``--on-conflict``.

Usage
-----
    python import_saved_searches.py \
        --base-url https://logvault.internal.example.com \
        --email admin@example.com \
        --password '...' \
        --bundle saved-searches-bundle.json \
        --dry-run

    # after a clean dry run
    python import_saved_searches.py ... --on-conflict skip

    # or with a JWT instead of a password
    python import_saved_searches.py ... --token "$TOKEN"

Exit codes: 0 all good, 1 an error occurred (details printed).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def _request(
    method: str,
    url: str,
    token: str | None = None,
    body: Any = None,
    timeout: int = 60,
) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)}


def _fail(message: str, status: int | None = None, body: Any = None) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    if status is not None:
        print(f"  HTTP {status}", file=sys.stderr)
    if body is not None:
        print(f"  {json.dumps(body, indent=2)[:2000]}", file=sys.stderr)
    raise SystemExit(1)


def _get_list(
    base: str, path: str, token: str, optional: bool = False
) -> list[dict]:
    status, body = _request("GET", base + path, token)
    if status == 404 and optional:
        return []
    if status != 200:
        _fail(f"GET {path} failed", status, body)
    if not isinstance(body, list):
        _fail(f"GET {path} did not return a list", status, body)
    return body


def _unique_name(name: str, taken: set[str]) -> str:
    candidate = f"{name} (imported)"
    n = 2
    while candidate in taken:
        candidate = f"{name} (imported {n})"
        n += 1
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Target API base URL")
    parser.add_argument("--bundle", required=True, help="Bundle JSON exported from the source")
    parser.add_argument("--email", help="Admin email (with --password)")
    parser.add_argument("--password", help="Admin password (with --email)")
    parser.add_argument("--token", help="Bearer token; skips the login call")
    parser.add_argument(
        "--on-conflict",
        choices=("skip", "update", "copy"),
        default="skip",
        help="What to do when a saved search name already exists (default: skip)",
    )
    parser.add_argument(
        "--no-create-indexes",
        action="store_true",
        help="Do not create missing index targets; leave the saved search's source empty",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    with open(args.bundle, encoding="utf-8") as fh:
        bundle = json.load(fh)

    token = args.token
    if not token:
        if not (args.email and args.password):
            _fail("provide --token, or --email and --password")
        status, body = _request(
            "POST", base + "/auth/login", body={"email": args.email, "password": args.password}
        )
        if status != 200:
            _fail("login failed", status, body)
        token = body.get("access_token")
        if not token:
            _fail("login response did not contain access_token", status, body)

    credentials = _get_list(base, "/credentials", token)
    indexes = _get_list(base, "/indexes", token)
    templates = _get_list(base, "/templates", token)
    try:
        s3_profiles = _get_list(base, "/s3-profiles", token, optional=True)
    except SystemExit:
        s3_profiles = []

    cred_by_label: dict[str, int] = {}
    cred_by_org: dict[str, int] = {}
    for cred in credentials:
        cred_by_label.setdefault(cred.get("label"), cred["id"])
        cred_by_org.setdefault(cred.get("org_slug"), cred["id"])

    index_by_key: dict[tuple[str, str], int] = {
        (idx.get("name"), idx.get("region_code")): idx["id"] for idx in indexes
    }
    s3_by_name: dict[str, int] = {p.get("name"): p["id"] for p in s3_profiles}
    tpl_by_name: dict[str, int] = {t.get("name"): t["id"] for t in templates}

    created_indexes = 0
    skipped_indexes = 0
    created_searches = 0
    updated_searches = 0
    skipped_searches = 0
    errors: list[str] = []
    warnings: list[str] = []

    def resolve_credential(row: dict) -> int | None:
        label = row.get("credential_label")
        org = row.get("credential_org_slug")
        if label and label in cred_by_label:
            return cred_by_label[label]
        if org and org in cred_by_org:
            return cred_by_org[org]
        return None

    # 1. Index targets -------------------------------------------------------
    for idx in bundle.get("index_targets", []):
        key = (idx.get("name"), idx.get("region_code"))
        if key in index_by_key:
            skipped_indexes += 1
            continue
        if args.no_create_indexes:
            warnings.append(f"index missing and not created: {key[0]} ({key[1]})")
            continue
        payload = {
            "name": idx.get("name"),
            "region_code": idx.get("region_code"),
            "physical_index": idx.get("physical_index"),
            "description": idx.get("description"),
            "credential_id": resolve_credential(idx),
        }
        if args.dry_run:
            print(f"[dry-run] create index {key[0]} ({key[1]})")
            created_indexes += 1
            continue
        status, body = _request("POST", base + "/indexes", token, payload)
        if status in (200, 201):
            index_by_key[key] = body["id"]
            created_indexes += 1
            print(f"created index {key[0]} ({key[1]}) -> id {body['id']}")
        elif status == 409:
            # Someone created it between our read and write; re-read and map.
            refreshed = _get_list(base, "/indexes", token)
            index_by_key = {
                (i.get("name"), i.get("region_code")): i["id"] for i in refreshed
            }
            if key in index_by_key:
                skipped_indexes += 1
            else:
                errors.append(f"index conflict but not found: {key[0]} ({key[1]})")
        else:
            errors.append(f"index {key[0]} ({key[1]}): HTTP {status} {body}")

    # 2. Saved searches ------------------------------------------------------
    for tpl in bundle.get("saved_searches", []):
        name = tpl.get("name")
        cred_id = resolve_credential(tpl)
        if cred_id is None:
            warnings.append(f"{name}: credential not found, saved without a source")
        index_key = (tpl.get("index_name"), tpl.get("index_region"))
        index_id = index_by_key.get(index_key)
        if index_id is None and index_key[0]:
            warnings.append(f"{name}: index not found ({index_key[0]} / {index_key[1]})")
        s3_id = s3_by_name.get(tpl.get("s3_profile_name"))

        payload = {
            "name": name,
            "phrases": tpl.get("phrases") or [],
            "ids": tpl.get("ids") or [],
            "exact_phrases": tpl.get("exact_phrases") or [],
            "exclude_phrases": tpl.get("exclude_phrases") or [],
            "exclude_exact_phrases": tpl.get("exclude_exact_phrases") or [],
            "message_types": tpl.get("message_types") or [],
            "aggregation": tpl.get("aggregation"),
            "customer": tpl.get("customer"),
            "region_code": tpl.get("region_code"),
            "credential_id": cred_id,
            "index_target_id": index_id,
            "s3_profile_id": s3_id,
        }

        existing = tpl_by_name.get(name)
        if existing is not None:
            if args.on_conflict == "skip":
                skipped_searches += 1
                continue
            if args.on_conflict == "update":
                if args.dry_run:
                    print(f"[dry-run] update saved search {name} (id {existing})")
                    updated_searches += 1
                    continue
                status, body = _request(
                    "PUT", f"{base}/templates/{existing}", token, payload
                )
                if status == 200:
                    updated_searches += 1
                    print(f"updated saved search {name}")
                else:
                    errors.append(f"update {name}: HTTP {status} {body}")
                continue
            # copy
            payload["name"] = _unique_name(name, set(tpl_by_name))
            name = payload["name"]

        if args.dry_run:
            print(f"[dry-run] create saved search {name}")
            created_searches += 1
            continue
        status, body = _request("POST", base + "/templates", token, payload)
        if status in (200, 201):
            tpl_by_name[name] = body["id"]
            created_searches += 1
            print(f"created saved search {name} -> id {body['id']}")
        else:
            errors.append(f"create {name}: HTTP {status} {body}")

    print()
    print(
        "indexes:   "
        f"created {created_indexes}, skipped {skipped_indexes}"
    )
    print(
        "searches:  "
        f"created {created_searches}, updated {updated_searches}, skipped {skipped_searches}"
    )
    if warnings:
        print(f"warnings:  {len(warnings)}")
        for warning in warnings[:20]:
            print(f"  - {warning}")
        if len(warnings) > 20:
            print(f"  ... and {len(warnings) - 20} more")
    if errors:
        print(f"errors:    {len(errors)}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
