from oracle_mutants.pyast import apply, sites

SRC = '''"""Collector (mod 26), keeps sessions while age < limit."""
LABEL = "ä < ö"  # 10 < 20


def collect(sessions, watermark, limit=20):
    """Return the sessions to drop."""
    out = []
    for s in sessions:
        if watermark - s.end > limit:
            out.append(s)
    return out


def total(a, b):
    return max(a, b) + 1 if a == b else "%s" % a
'''


def by(op):
    return [s for s in sites(SRC) if s.operator == op]


def test_never_touches_docstrings_strings_or_comments():
    for s in sites(SRC):
        assert s.line not in (1, 2, 6), s


def test_relational_replacement_has_boundary_and_negation():
    ops = {(s.operator, s.description) for s in sites(SRC) if s.line == 9 and "comparison" in s.operator}
    assert ops == {("flip-comparison", "line 9: '>' -> '>='"), ("negate-comparison", "line 9: '>' -> '<='")}
    negated = next(s for s in by("negate-comparison") if s.line == 9)
    assert "if watermark - s.end <= limit:" in apply(SRC, negated)


def test_condition_to_constant_makes_a_never_true_branch():
    s = next(s for s in by("condition-to-constant") if s.line == 9 and s.replacement == "False")
    assert "        if False:\n" in apply(SRC, s)


def test_arithmetic_constant_and_call_swaps():
    assert any(s.description == "line 9: '-' -> '+'" for s in by("swap-arithmetic"))
    assert not any(s.line == 15 and "%" in s.description for s in by("swap-arithmetic"))  # string formatting
    assert any(s.description == "line 5: 20 -> 21" for s in by("off-by-one-constant"))
    swapped = apply(SRC, by("swap-call")[0])
    assert "return min(a, b) + 1" in swapped


def test_offsets_survive_non_ascii_lines():
    src = 'x = "äöü"; y = 1 if x == "ä" else 2\n'
    s = next(s for s in sites(src) if s.operator == "negate-comparison")
    assert apply(src, s) == 'x = "äöü"; y = 1 if x != "ä" else 2\n'


def test_unparseable_source_gives_no_sites():
    assert sites("def broken(:\n") == []


def test_formatting_arguments_are_not_values():
    src = "import json\nx = round(v * 3, 1)\njson.dump(d, f, indent=2)\ny = round(w, ndigits=2)\n"
    consts = {s.description for s in sites(src) if s.operator == "off-by-one-constant"}
    assert consts == {"line 2: 3 -> 4"}
