from oracle_mutants.operators import mutate, shifted
from oracle_mutants.probe import Probe, _ladder


def nudge(path, data):
    return next(v for v in mutate(path, data) if v.operator == "nudge-number")


def test_text_nudge_rebuilds_at_any_step():
    v = nudge("/r/a.csv", b"Answers\n86\n180\n")
    assert v.value == "86"
    assert v.rebuild(5) == b"Answers\n91\n180\n"


def test_json_nudge_rebuilds_relative_for_decimals():
    v = nudge("/r/a.json", b'{"score": 0.5, "n": 3}')
    assert v.value == "0.5"
    assert b'"score": 1.0' in v.rebuild(1.0)


def test_shifted_keeps_padding_and_decimals():
    assert shifted("007", 5) == "012"
    assert shifted("2.50", 1.0) == "5.00"
    assert shifted("0.00", 10.0) == "10.00"


def test_ladder_by_token_type():
    assert _ladder("86")[0] == ("+2", 2)
    assert _ladder("0.97")[0][0] == "+100%"
    assert _ladder("0.00")[0][0] == "0 -> 1"


def test_probe_summary():
    assert Probe([("+2", 0.0)], first="+1").summary().startswith("accepted +1, rejected +2")
    assert "looks unchecked" in Probe([("+2", 1.0), ("+1000", 1.0)]).summary()
