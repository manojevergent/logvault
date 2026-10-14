from app.last9.escaping import esc


def test_escapes_regex_metacharacters():
    assert esc("a.b*c+d") == r"a\.b\*c\+d"
    assert esc("(x)[y]{z}") == r"\(x\)\[y\]\{z\}"
    assert esc("a|b\\c") == r"a\|b\\c"
    assert esc("^start$") == r"\^start\$"


def test_leaves_hyphens_literal():
    # §2.6 — hyphens are only special inside [...], not in alternation.
    assert esc("ID-AAA-123") == "ID-AAA-123"


def test_plain_text_unchanged():
    assert esc("GetEntitlements") == "GetEntitlements"
