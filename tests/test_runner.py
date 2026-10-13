from pathlib import Path

from oracle_mutants.operators import MEDIUM, STRONG, WEAK
from oracle_mutants.oracle import ExportedArtifact, OracleRun
from oracle_mutants.runner import candidate_files, plan
from oracle_mutants.task import Artifact, Task


def make_tree(tmp: Path) -> Path:
    root = tmp / "app"
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "index.js").write_text("module.exports = 1 == 1\n")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def f(x):\n    return x == 2\n")
    (root / "out.json").write_text('{"a": 1, "b": [1, 2, 3]}\n')
    (root / "notes.txt").write_text("one 1\ntwo 2\n")
    (root / "empty.txt").write_text("")
    return root


def test_candidate_files_skips_vendored_and_prefers_data(tmp_path):
    root = make_tree(tmp_path)
    files = candidate_files(ExportedArtifact("/app/", root, True), (), max_files=10)
    paths = [p for p, _ in files]
    assert "/app/node_modules/x/index.js" not in paths
    assert "/app/empty.txt" not in paths
    assert paths[0] == "/app/out.json"          # JSON before text before code
    assert paths.index("/app/notes.txt") < paths.index("/app/src/main.py")


def test_candidate_files_respects_exclude_and_cap(tmp_path):
    root = make_tree(tmp_path)
    files = candidate_files(ExportedArtifact("/app/", root, True), ("*.txt",), max_files=1)
    assert [p for p, _ in files] == ["/app/out.json"]


def test_plan_orders_by_severity_and_caps(tmp_path):
    root = make_tree(tmp_path)
    task = Task(tmp_path, "t", [Artifact("/app/")], "separate", 60.0)
    oracle = OracleRun(tmp_path, 1.0, [ExportedArtifact("/app/", root, True)])
    mutants = plan(task, oracle, max_files=10, max_mutants=5, severities={STRONG, MEDIUM, WEAK})
    assert len(mutants) == 5
    sev = [m.variant.severity for m in mutants]
    assert sev == sorted(sev, key=[STRONG, MEDIUM, WEAK].index)
    only_strong = plan(task, oracle, 10, 100, {STRONG})
    assert only_strong and all(m.variant.severity == STRONG for m in only_strong)


def test_plan_skips_untouched_inputs(tmp_path):
    (tmp_path / "environment" / "inputs").mkdir(parents=True)
    (tmp_path / "environment" / "inputs" / "portfolio.csv").write_text("id,n\n1,10\n2,20\n")
    out = tmp_path / "artifacts"
    out.mkdir()
    (out / "portfolio.csv").write_text("id,n\n1,10\n2,20\n")
    (out / "result.csv").write_text("id,total\n1,30\n")
    task = Task(tmp_path, "t", [Artifact("/app/inputs/portfolio.csv"), Artifact("/app/out/result.csv")], "separate", 60.0)
    oracle = OracleRun(tmp_path, 1.0, [ExportedArtifact("/app/inputs/portfolio.csv", out / "portfolio.csv", False),
                                       ExportedArtifact("/app/out/result.csv", out / "result.csv", False)])
    skipped: list[str] = []
    mutants = plan(task, oracle, 10, 100, {STRONG, MEDIUM, WEAK}, skipped)
    assert {m.container_path for m in mutants} == {"/app/out/result.csv"}
    assert skipped and "portfolio.csv" in skipped[0]


def test_file_budget_goes_to_files_the_solution_wrote(tmp_path):
    (tmp_path / "environment" / "app").mkdir(parents=True)
    out = tmp_path / "artifacts" / "app"
    out.mkdir(parents=True)
    for i in range(5):  # five untouched shipped files sort before the one the solution wrote
        (tmp_path / "environment" / "app" / f"a{i}.json").write_text(f'{{"n": {i}}}')
        (out / f"a{i}.json").write_text(f'{{"n": {i}}}')
    (out / "z_solution.py").write_text("def f(x):\n    return x > 3\n")
    task = Task(tmp_path, "t", [Artifact("/app/")], "separate", 60.0)
    oracle = OracleRun(tmp_path, 1.0, [ExportedArtifact("/app/", out, True)])
    skipped: list[str] = []
    mutants = plan(task, oracle, 1, 100, {STRONG, MEDIUM, WEAK}, skipped)
    assert mutants and {m.container_path for m in mutants} == {"/app/z_solution.py"}
    assert len(skipped) == 5


def test_unchanged_code_can_be_kept_in_play(tmp_path):
    (tmp_path / "environment" / "app").mkdir(parents=True)
    out = tmp_path / "artifacts" / "app"
    out.mkdir(parents=True)
    for d in (tmp_path / "environment" / "app", out):
        (d / "cli.py").write_text("def main(alert):\n    return 1 if alert else 0\n")
        (d / "data.csv").write_text("a,b\n1,2\n")
    task = Task(tmp_path, "t", [Artifact("/app/")], "separate", 60.0)
    oracle = OracleRun(tmp_path, 1.0, [ExportedArtifact("/app/", out, True)])
    assert plan(task, oracle, 10, 100, {STRONG, MEDIUM, WEAK}) == []
    kept = plan(task, oracle, 10, 100, {STRONG, MEDIUM, WEAK}, keep_unchanged_code=True)
    assert kept and {m.container_path for m in kept} == {"/app/cli.py"}
