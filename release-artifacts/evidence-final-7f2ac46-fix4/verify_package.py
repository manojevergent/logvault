"""Independent verification of the 7f2ac46-fix4 package (Python hashlib).

Deliberately a separate implementation from the PowerShell Get-FileHash used to
generate the file. Exits non-zero on any discrepancy.
"""

import hashlib
import json
import pathlib
import sys

PKG = pathlib.Path(
    r"E:\last9_web_app-p1\release-artifacts\release-1-final-7f2ac46-fix4"
)
EXPECTED_COMMIT = "7f2ac468e21de16e2feee9f2bd81b8fe0669c89b"
EXPECTED_WORKER = "sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb"
EXPECTED_API = "sha256:78f7f987cf3bc5074e6f3aeb9b08c3816bf4e18d7ddb57b3b4772de21c6396bb"

failures = []


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    manifest = (PKG / "checksums.sha256").read_text(encoding="ascii")
    entries = {}
    for line in manifest.splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        entries[name.strip()] = digest.strip()

    present = {p.name for p in PKG.iterdir() if p.is_file()}
    uncovered = present - set(entries) - {"checksums.sha256", "CHECKSUMS_SHA256.txt"}
    missing = set(entries) - present
    if uncovered:
        failures.append(f"files not covered by checksums: {sorted(uncovered)}")
    if missing:
        failures.append(f"checksum entries with no file: {sorted(missing)}")

    for name, expected in sorted(entries.items()):
        actual = sha256(PKG / name)
        if actual != expected:
            failures.append(f"checksum mismatch: {name} expected={expected} actual={actual}")

    manifest_hash = sha256(PKG / "checksums.sha256")
    recorded = (PKG / "CHECKSUMS_SHA256.txt").read_text(encoding="ascii").split()[0].strip()
    if manifest_hash != recorded:
        failures.append(
            f"manifest hash mismatch: recomputed={manifest_hash} recorded={recorded}"
        )

    data = json.loads((PKG / "build-manifest.json").read_text(encoding="utf-8"))
    if data["git_commit_full"] != EXPECTED_COMMIT:
        failures.append(f"manifest commit is {data['git_commit_full']}")
    if data["images"]["worker"] != EXPECTED_WORKER:
        failures.append(f"manifest worker digest is {data['images']['worker']}")
    if data["images"]["api"] != EXPECTED_API:
        failures.append(f"manifest api digest is {data['images']['api']}")

    print(f"package              : {PKG.name}")
    print(f"files present        : {len(present)}")
    print(f"checksum entries     : {len(entries)}")
    print(f"uncovered files      : {sorted(present - set(entries))}")
    print(f"checksums.sha256     : {manifest_hash}")
    print(f"recorded manifest hash: {recorded}")
    print(f"commit in manifest   : {data['git_commit_full']}")
    print(f"worker digest        : {data['images']['worker']}")
    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nPASS: every checksum, the manifest self-hash and the manifest identity verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
