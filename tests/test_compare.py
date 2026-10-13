from oracle_mutants.compare import _diff, _same_json


def test_same_json_ignores_formatting_only():
    assert _same_json(b'{"a": 1, "b": [1, 2]}', b'{\n   "a": 1,\n   "b": [\n      1,\n      2\n   ]\n}\n')
    assert not _same_json(b'{"a": 1}', b'{"a": 2}')
    assert not _same_json(b"not json", b"not json ")


def test_diff_shows_changed_lines():
    d = _diff(b"fuel 10\ntime 5\n", b"fuel 11\ntime 5\n")
    assert "-fuel 10" in d and "+fuel 11" in d
