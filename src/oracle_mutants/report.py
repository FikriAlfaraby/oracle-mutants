"""Write the results as JSON (for tooling) and Markdown (for people and issue reports)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .operators import MEDIUM, STRONG, WEAK
from .runner import Report

VERDICT = {STRONG: "likely verifier gap", MEDIUM: "worth a look", WEAK: "often acceptable"}


def write(report: Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js, md = out_dir / "report.json", out_dir / "report.md"
    js.write_text(json.dumps(to_dict(report), indent=2))
    md.write_text(to_markdown(report))
    return js, md


def to_dict(r: Report) -> dict:
    return {
        "task": r.task.name,
        "task_dir": str(r.task.root),
        "oracle_reward": r.oracle.reward,
        "baseline_reward": r.baseline.reward,
        "mutants": len(r.outcomes),
        "survivors": sum(o.survived for o in r.outcomes),
        "skipped": r.skipped,
        "results": [
            {
                "file": o.mutant.container_path,
                "operator": o.mutant.variant.operator,
                "severity": o.mutant.variant.severity,
                "description": o.mutant.variant.description,
                "reward": o.result.reward,
                "timed_out": o.result.timed_out,
                "survived": o.survived,
                "diff": o.mutant.diff() if o.survived else None,
            }
            for o in r.outcomes
        ],
    }


def to_markdown(r: Report) -> str:
    total = len(r.outcomes)
    survivors = [o for o in r.outcomes if o.survived]
    by_sev = Counter(o.mutant.variant.severity for o in survivors)
    killed = sum(1 for o in r.outcomes if o.result.reward is not None and not o.survived)
    errored = sum(1 for o in r.outcomes if o.result.reward is None)
    lines = [
        f"# oracle-mutants: {r.task.name}",
        "",
        f"- Reference solution reward (Harbor oracle run): **{r.oracle.reward}**",
        f"- Same artifacts re-verified by oracle-mutants: **{r.baseline.reward}**",
        f"- Mutants run: **{total}** — rejected {killed}, accepted **{len(survivors)}**, no reward (crash/timeout) {errored}",
        f"- Accepted by severity: strong {by_sev[STRONG]}, medium {by_sev[MEDIUM]}, weak {by_sev[WEAK]}",
        "",
    ]
    if not survivors:
        lines.append("The verifier rejected every mutant. No gaps found by these operators.")
    for sev in (STRONG, MEDIUM, WEAK):
        group = [o for o in survivors if o.mutant.variant.severity == sev]
        if not group:
            continue
        lines += [f"## Accepted {sev} mutants — {VERDICT[sev]}", ""]
        for o in group:
            m = o.mutant
            lines += [f"### `{m.container_path}` — {m.variant.operator}", "", m.variant.description, "",
                      "```diff", m.diff(), "```", ""]
    if r.skipped:
        lines += ["## Skipped", ""] + [f"- {s}" for s in r.skipped]
    lines += ["", "_A mutant is **accepted** when the verifier still awards full reward. Strong mutants are almost "
              "never correct answers; medium and weak ones need a human to judge whether the task allows them._"]
    return "\n".join(lines) + "\n"
