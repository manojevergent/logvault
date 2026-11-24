"""Append the local rehearsal evidence to the Gate B register."""

import pathlib

DOCS = pathlib.Path(r"E:\last9_web_app\docs")
EV = pathlib.Path(
    r"E:\last9_web_app-p1\release-artifacts\evidence-final-7f2ac46-fix4"
)
TARGET = DOCS / "RELEASE_1_GATE_B_EVIDENCE_REGISTER.md"
MARKER = "## Local rehearsal evidence - 2026-11-15T15:30Z"

block = (EV / "doc-local-rehearsal.md").read_text(encoding="utf-8")
text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("already present")
else:
    TARGET.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8", newline="\n")
    print("updated", TARGET.name)
