"""The numbers the README and docs quote, recomputed from the reports committed in results/."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TEXT = " ".join(
    " ".join(p.read_text(encoding="utf-8").split()) for p in (ROOT / "README.md", ROOT / "docs" / "recall-results.md")
)
SIZE = re.compile(r"(\d+) values? changed; largest: (\S+) (\S+) -> (\S+) \(([\d.]+)%\)")


def reports(folder: str) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((RESULTS / folder).glob("*.json"))]


def says(text: str) -> None:
    assert text in TEXT, text


def test_no_machine_paths():
    assert not [p for p in RESULTS.rglob("*") if p.is_file() and "/Users/" in p.read_text(encoding="utf-8")]


def test_first_pass_totals():
    found = reports("first-pass")
    log = (RESULTS / "first-pass" / "telecom-entity-resolution.log").read_text(encoding="utf-8")
    verdicts = re.findall(r"^\s+(ACCEPTED|rejected)\s", log, re.MULTILINE)
    tasks = len(found) + 1
    mutants = sum(r["mutants"] for r in found) + len(verdicts)
    accepted = sum(r["survivors"] for r in found) + verdicts.count("ACCEPTED")
    assert (tasks, mutants, accepted) == (15, 165, 36)
    says(f"First pass: {tasks} tasks, {mutants} mutants, {accepted} accepted")


def test_blind_recall_run():
    found = reports("recall-blind")
    assert (len(found), sum(r["mutants"] for r in found), sum(r["survivors"] for r in found)) == (6, 89, 42)
    says("Six tasks, 89 mutants, 42 accepted")


def test_final_cargo_run():
    cargo = json.loads((RESULTS / "final" / "cargo-flight-dispatch.json").read_text(encoding="utf-8"))
    changed = [r for r in cargo["results"] if r["survived"] and r["behaviour"] == "output changed"]
    sizes = [SIZE.match(r["behaviour_size"]).groups() for r in changed]
    summary_only = [s for s in sizes if s[0] == "1" and s[1].startswith("summary.")]
    plan = [s for s in sizes if s[1].startswith("legs[")]
    assert (cargo["mutants"], cargo["survivors"], len(changed)) == (169, 59, 13)
    assert (len(plan), len(summary_only)) == (10, 3) and max(float(s[4]) for s in summary_only) <= 0.2
    says("169 mutants, 59 accepted, 13 change the output: 10 change the flight plan's legs and 3 only a summary total")


def test_session_window_gap():
    session = json.loads((RESULTS / "final" / "session-window-debug.json").read_text(encoding="utf-8"))
    swaps = [
        r
        for r in session["results"]
        if r["file"].endswith("merger.py")
        and r["survived"]
        and r["reward"] == 1.0
        and ("max() -> min()" in r["description"] or "min() -> max()" in r["description"])
    ]
    assert len(swaps) == 2


def test_terminal_bench_id_tasks():
    found = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (RESULTS / "terminal-bench-id").glob("*.json")}
    assert {k: (v["mutants"], v["survivors"]) for k, v in found.items()} == {
        "weton-jawa": (17, 0),
        "rekap-penjualan-kasir": (13, 0),
        "ejaan-lama-dedup": (15, 0),
    }


def test_examples():
    weak = json.loads((RESULTS / "examples" / "word-count-weak.json").read_text(encoding="utf-8"))
    food = json.loads((RESULTS / "examples" / "foodstuff-beta-activity.json").read_text(encoding="utf-8"))
    assert (weak["mutants"], weak["survivors"]) == (10, 8) and (food["mutants"], food["survivors"]) == (8, 0)
    says("Report: results/examples/word-count-weak.md")
