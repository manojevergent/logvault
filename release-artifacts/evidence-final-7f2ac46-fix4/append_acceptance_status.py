"""Append the non-production acceptance status to the four documents.

Documentation only. Refuses to double-apply. Preserves all earlier content.
"""

import pathlib

DOCS = pathlib.Path(r"E:\last9_web_app\docs")
EV = pathlib.Path(
    r"E:\last9_web_app-p1\release-artifacts\evidence-final-7f2ac46-fix4"
)

TARGETS = {
    "RELEASE_1_GATE_B_EVIDENCE_REGISTER.md": (
        "doc-gb08-attestation.md",
        "## GB-08 status review - 2026-11-15",
    ),
    "RELEASE_1_INDEPENDENT_REVIEW_REPORT.md": (
        "doc-acceptance-review.md",
        "## Non-production acceptance - 2026-11-15",
    ),
    "RELEASE_1_INDEPENDENT_RISK_REGISTER.md": (
        "doc-rk02-attestation.md",
        "## RK-02 status - 2026-11-15",
    ),
    "RELEASE_1_REVIEW_FINDINGS.md": (
        "doc-findings-acceptance.md",
        "## Integration evidence status - 2026-11-15",
    ),
}


def main() -> None:
    for name, (source, marker) in TARGETS.items():
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        if marker in text:
            print(f"skipped (already present) {name}")
            continue
        block = (EV / source).read_text(encoding="utf-8")
        path.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8", newline="\n")
        print(f"updated {name}")


if __name__ == "__main__":
    main()
