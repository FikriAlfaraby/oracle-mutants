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
    flips = by_op(vs, "flip-comparison")
    assert flips and all(b"# if x == 1: comment" in v.data for v in flips)
    assert any(b"if x != 10" in v.data for v in flips)
    assert any(b"x <= 3" in v.data for v in flips)
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
