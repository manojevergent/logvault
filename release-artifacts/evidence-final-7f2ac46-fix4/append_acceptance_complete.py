"""Append the completed candidate acceptance to the four documents."""

import pathlib

DOCS = pathlib.Path(r"E:\last9_web_app\docs")
EV = pathlib.Path(
    r"E:\last9_web_app-p1\release-artifacts\evidence-final-7f2ac46-fix4"
)

TARGETS = {
    "RELEASE_1_GATE_B_EVIDENCE_REGISTER.md": (
        "doc-gb08-closure.md",
        "## GB-08 closure - 2026-11-15T15:00Z",
    ),
    "RELEASE_1_INDEPENDENT_REVIEW_REPORT.md": (
        "doc-acceptance-complete.md",
        "## Non-production acceptance - COMPLETE",
    ),
    "RELEASE_1_INDEPENDENT_RISK_REGISTER.md": (
        "doc-rk02-closure.md",
        "## RK-02 closure - 2026-11-15T15:00Z",
    ),
    "RELEASE_1_REVIEW_FINDINGS.md": (
        "doc-findings-integration-verified.md",
        "## Integration evidence verified - 2026-11-15T15:00Z",
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
