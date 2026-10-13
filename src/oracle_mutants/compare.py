"""Behaviour check for accepted mutants: does the mutant change what the program actually produces?

For tasks whose artifacts are code, an accepted mutant is either *equivalent* (the program still
writes exactly the reference output, so there was nothing for the verifier to catch) or a real miss
(the output changed and the verifier still gave full reward). This runs the task's own command in
the verifier image for the reference and for each accepted mutant, and diffs the file it writes.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from .oracle import OracleRun
from .runner import Mutant, plan
from .task import Task
from .verifier import run_command

SAME, SAME_DATA, CHANGED, NO_OUTPUT = "same output", "same data", "output changed", "no output"


@dataclass
class Behaviour:
    mutant: Mutant
    verdict: str
    diff: str


def accepted_mutants(task: Task, oracle: OracleRun, report_json: Path, max_files: int) -> list[Mutant]:
    """Rebuild the accepted mutants of an earlier run. Mutants are deterministic, so matching by id is exact."""
    data = json.loads(report_json.read_text())
    wanted = {(r["file"], r["operator"], r["description"]) for r in data["results"] if r["survived"]}
    every = plan(task, oracle, max_files, 10_000, {"strong", "medium", "weak"})
    found = [m for m in every if (m.container_path, m.variant.operator, m.variant.description) in wanted]
    missing = len(wanted) - len(found)
    if missing:
        raise ValueError(f"{missing} accepted mutants could not be rebuilt; was the run made with another --max-files?")
    return found


def compare(task: Task, oracle: OracleRun, image: str, mutants: list[Mutant], command: str, fetch: str,
            on_result=None) -> tuple[bytes, list[Behaviour]]:
    reference = run_command(image, task, oracle.artifacts, None, command, fetch)
    if reference.output_file is None:
        raise ValueError(f"the reference run did not write {fetch}:\n{reference.output_tail}")
    out = []
    for m in mutants:
        got = run_command(image, task, oracle.artifacts, {m.container_path: m.variant.data}, command, fetch).output_file
        if got is None:
            b = Behaviour(m, NO_OUTPUT, "")
        elif got == reference.output_file:
            b = Behaviour(m, SAME, "")
        elif _same_json(got, reference.output_file):
            b = Behaviour(m, SAME_DATA, "")
        else:
            b = Behaviour(m, CHANGED, _diff(reference.output_file, got))
        out.append(b)
        if on_result:
            on_result(b)
    return reference.output_file, out


def _same_json(a: bytes, b: bytes) -> bool:
    """Both parse as JSON and hold the same data: only formatting differs."""
    try:
        return json.loads(a) == json.loads(b)
    except ValueError:
        return False


def _diff(a: bytes, b: bytes, max_lines: int = 40) -> str:
    lines = list(difflib.unified_diff(a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines(),
                                      "reference output", "mutant output", n=2, lineterm=""))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more diff lines)"]
    return "\n".join(lines)


def to_markdown(task: Task, command: str, fetch: str, results: list[Behaviour]) -> str:
    changed = [b for b in results if b.verdict == CHANGED]
    lines = [f"# Behaviour check: {task.name}", "",
             f"Command `{command}`, output `{fetch}`, run in the verifier image for the reference and for every accepted mutant.",
             "",
             f"- Same output as the reference (equivalent, nothing to catch): **{sum(b.verdict == SAME for b in results)}**",
             f"- Same JSON data, only formatting differs: **{sum(b.verdict == SAME_DATA for b in results)}**",
             f"- Output changed, verifier still gave full reward: **{len(changed)}**",
             f"- Program wrote no output: **{sum(b.verdict == NO_OUTPUT for b in results)}**", ""]
    for b in results:
        m = b.mutant
        lines.append(f"- {b.verdict}: `{m.container_path}` {m.variant.operator}, {m.variant.description}")
    for b in changed:
        lines += ["", f"## `{b.mutant.container_path}` — {b.mutant.variant.description}", "",
                  "```diff", b.mutant.diff(), "```", "", "What the program now writes:", "", "```diff", b.diff, "```"]
    return "\n".join(lines) + "\n"
