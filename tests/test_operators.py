import json

from oracle_mutants.operators import MEDIUM, STRONG, WEAK, kind_of, mutate


def ops(variants):
    return {(v.operator, v.severity) for v in variants}


def by_op(variants, name):
    return [v for v in variants if v.operator == name]


def test_kind_detection():
    assert kind_of("/app/out.json", b'{"a": 1}') == "json"
    assert kind_of("/app/run.py", b"print(1)") == "code"
    assert kind_of("/app/results.txt", b"x: 1") == "text"
    assert kind_of("/app/model.pt", b"\x00\x01\x02") == "binary"


def test_never_returns_the_original_and_never_duplicates():
    data = b"a: 1\nb: 2\n"
    vs = mutate("/app/r.txt", data)
    assert all(v.data != data for v in vs)
    assert len({v.data for v in vs}) == len(vs)


def test_text_records():
    data = "Efficiency: 0.97\nVolumetric factor: 33.00\nGravimetric: 17\n".encode()
    vs = mutate("/app/results.txt", data)
    assert ("empty", STRONG) in ops(vs)
    assert ("truncate-half", STRONG) in ops(vs)
    assert ("numbers-to-zero", STRONG) in ops(vs)
    assert ("duplicate-record", MEDIUM) in ops(vs)
    assert ("swap-records", WEAK) in ops(vs)
    half = by_op(vs, "truncate-half")[0].data.decode()
    assert half.startswith("Efficiency: 0.97\nVolumetric factor: 33.00") and "Gravimetric" not in half
    nudged = by_op(vs, "nudge-number")[0].data.decode()
    assert "Efficiency: 1.46" in nudged  # 0.97 * 1.5 keeps two decimals


def test_csv_keeps_header():
    data = b"id,score\n1,10\n2,20\n3,30\n4,40\n"
    half = by_op(mutate("/app/out.csv", data), "truncate-half")[0].data.decode()
    assert half.splitlines() == ["id,score", "1,10", "2,20", ""] or half.splitlines()[:3] == ["id,score", "1,10", "2,20"]
    zero = by_op(mutate("/app/out.csv", data), "numbers-to-zero")[0].data.decode()
    assert zero.splitlines()[0] == "id,score"


def test_integer_nudge_is_off_by_one():
    vs = mutate("/app/count.txt", b"total 41\n")
    assert by_op(vs, "nudge-number")[0].data == b"total 42\n"


def test_json_object_and_nested_list():
    doc = {"clusters": [{"id": 1, "members": ["a", "b"]}, {"id": 2, "members": ["c"]}], "score": 0.5}
    vs = mutate("/app/output.json", json.dumps(doc, indent=2).encode())
    names = ops(vs)
    assert ("empty-container", STRONG) in names
    assert ("drop-key", MEDIUM) in names
    assert ("numbers-to-zero", STRONG) in names
    half = [json.loads(v.data) for v in by_op(vs, "truncate-half")]
    assert any(len(h.get("clusters", [])) == 1 for h in half)


def test_invalid_json_falls_back_to_text():
    vs = mutate("/app/output.json", b"not json\nsecond line\n")
    assert ("truncate-half", STRONG) in ops(vs)


def test_code_mutants_skip_comments():
    src = b"# if x == 1: comment\ndef f(x):\n    if x == 10:\n        return True\n    return x < 3\n"
    vs = mutate("/app/f.py", src)
    flips = by_op(vs, "flip-comparison") + by_op(vs, "negate-comparison")
    assert flips and all(b"# if x == 1: comment" in v.data for v in flips)
    assert any(b"if x != 10" in v.data for v in by_op(vs, "negate-comparison"))
    assert any(b"x <= 3" in v.data for v in by_op(vs, "flip-comparison"))
    assert any(b"return False" in v.data for v in by_op(vs, "flip-boolean"))
    assert any(b"x == 11" in v.data for v in by_op(vs, "off-by-one-constant"))


def test_binary_mutants():
    data = bytes(range(256))
    vs = mutate("/app/model.safetensors", data)
    assert ("truncate-half", STRONG) in ops(vs)
    assert ("corrupt-bytes", STRONG) in ops(vs)
    assert len(by_op(vs, "corrupt-bytes")[0].data) == len(data)


def test_empty_file_has_no_empty_mutant():
    assert by_op(mutate("/app/x.txt", b""), "empty") == []


def test_nudge_prefers_a_standalone_value_over_dates_and_ids():
    line = b"INSERT INTO runs(id, created_at, hours) VALUES ('run-00001', '2026-10-13T03:15:22Z', 24);\n"
    nudged = by_op(mutate("/app/out/w.sql", line), "nudge-number")[0].data
    assert b", 25);" in nudged and b"'2026-10-13" in nudged and b"run-00001" in nudged


def test_nudge_keeps_zero_padding():
    nudged = by_op(mutate("/app/out/ids.txt", b"00007\n00008\n"), "nudge-number")[0].data
    assert nudged.startswith(b"00008\n")


def test_code_operators_skip_docstrings_strings_and_comments():
    src = b'''"""Shift letters (mod 26) when k < n."""
LABEL = "x < y"  # 10 < 20
def shift(c, k):
    return (c + k) % 26 if k > 0 else c
'''
    vs = mutate("/app/cracker.py", src)
    lines = {v.description for v in vs if v.operator in ("flip-comparison", "off-by-one-constant")}
    assert lines == {"line 4: '>' -> '>='", "line 4: 26 -> 27", "line 4: 0 -> 1"}


def test_code_masking_for_c_like_sources():
    src = b'''// limit < 10
const char *s = "a < b"; char q = '<';
/* 26 > 3 */ if (n < 26) return 1;
'''
    vs = mutate("/app/x.c", src)
    descs = {v.description for v in vs if v.operator in ("flip-comparison", "off-by-one-constant")}
    assert descs == {"line 3: '<' -> '<='", "line 3: 26 -> 27"}


def test_nudge_skips_a_markup_header_when_a_real_value_follows():
    xml = b"<?xml version='1.0' encoding='utf-8'?>\n<score version=\"3.1\">\n<octave>4</octave>\n</score>\n"
    nudged = by_op(mutate("/app/score.musicxml", xml), "nudge-number")[0].data
    assert b"<octave>5</octave>" in nudged and b"version='1.0'" in nudged


def test_json_identifier_fields_are_labels_not_values():
    doc = b'{"clusters": [{"cluster_id": 1, "records": [{"id": 7}]}, {"cluster_id": 2, "score": 0.5}]}'
    vs = mutate("/app/out/c.json", doc)
    zeroed = by_op(vs, "numbers-to-zero")[0].data
    assert b'"cluster_id": 1' in zeroed and b'"id": 7' in zeroed and b'"score": 0' in zeroed
    assert by_op(vs, "nudge-number")[0].description.startswith("['clusters'][1]['score']")
    only_ids = mutate("/app/out/c.json", b'{"clusters": [{"cluster_id": 1}, {"cluster_id": 2}]}')
    assert not by_op(only_ids, "numbers-to-zero") and not by_op(only_ids, "nudge-number")
