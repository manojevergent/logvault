"""Reconcile the six review documents with candidate 7f2ac46-fix4.

Documentation only. Inserts a top banner (so the stale 78fb0a7 header cannot be
mistaken for the current candidate), then appends the authoritative
reconciliation section and, for three documents, their targeted update.
Refuses to double-apply.
"""

import pathlib

DOCS = pathlib.Path(r"E:\last9_web_app\docs")
EV = pathlib.Path(
    r"E:\last9_web_app-p1\release-artifacts\evidence-final-7f2ac46-fix4"
)
FILES = [
    "RELEASE_1_INDEPENDENT_REVIEW_REPORT.md",
    "RELEASE_1_INDEPENDENT_REVIEW_PACKAGE.md",
    "RELEASE_1_REVIEW_FINDINGS.md",
    "RELEASE_1_INDEPENDENT_RISK_REGISTER.md",
    "RELEASE_1_REVIEW_CHECKLIST.md",
    "RELEASE_1_GATE_B_EVIDENCE_REGISTER.md",
]
EXTRAS = {
    "RELEASE_1_INDEPENDENT_RISK_REGISTER.md": "doc-risk-7f2ac46.md",
    "RELEASE_1_REVIEW_CHECKLIST.md": "doc-checklist-7f2ac46.md",
    "RELEASE_1_GATE_B_EVIDENCE_REGISTER.md": "doc-gateb-7f2ac46.md",
}

BANNER = (EV / "doc-banner.md").read_text(encoding="utf-8").rstrip("\n")
SHARED = (EV / "doc-reconcile-7f2ac46.md").read_text(encoding="utf-8")
BANNER_SENTINEL = "Authoritative candidate: `7f2ac46`"
SECTION_SENTINEL = "## Authoritative candidate reconciliation - 7f2ac46-fix4"


def main() -> None:
    for name in FILES:
        path = DOCS / name
        text = path.read_text(encoding="utf-8")

        if BANNER_SENTINEL not in text:
            head, sep, rest = text.partition("\n")
            text = head + "\n\n" + BANNER + "\n" + (sep + rest if sep else "")
            print(f"banner   {name}")
        else:
            print(f"banner already present {name}")

        if SECTION_SENTINEL not in text:
            extra = ""
            if name in EXTRAS:
                extra = "\n" + (EV / EXTRAS[name]).read_text(encoding="utf-8")
            text = text.rstrip("\n") + "\n" + SHARED + extra
            print(f"section  {name}")
        else:
            print(f"section already present {name}")

        path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
