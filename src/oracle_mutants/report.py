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
                "behaviour": o.behaviour,
                "behaviour_diff": o.behaviour_diff or None,
                "behaviour_size": o.behaviour_size or None,
                "probe": ({"steps": [{"step": label, "reward": reward} for label, reward in o.probe.steps],
                           "summary": o.probe.summary()} if o.probe else None),
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
    checked = [o for o in survivors if o.behaviour]
    missed = sorted((o for o in checked if o.behaviour == "output changed"), key=lambda o: -o.behaviour_largest)
    if checked:
        lines += [(f"Behaviour check: {len(missed)} of {len(checked)} accepted mutants change the program's output. "
                   "The rest write exactly the reference output (or the same JSON data), so there was nothing to catch."), ""]
    if missed:
        lines += ["## Output changed, verifier still gave full reward — likely gaps", "",
                  ("Largest change first. A change of a fraction of a percent is usually inside a tolerance; "
                   "tens of percent is not."), ""]
        for o in missed:
            m = o.mutant
            lines += [f"### `{m.container_path}` — {m.variant.operator}", "", m.variant.description, "",
                      *([f"Output change: {o.behaviour_size}.", ""] if o.behaviour_size else []),
                      "```diff", m.diff(), "```", "", "What the program now writes:", "", "```diff", o.behaviour_diff, "```", ""]
    if checked:
        same = [o for o in checked if o.behaviour != "output changed"]
        if same:
            lines += ["## Accepted but behaviour unchanged (equivalent on this input)", ""]
            lines += [f"- `{o.mutant.container_path}` {o.mutant.variant.operator}, {o.mutant.variant.description} — {o.behaviour}"
                      for o in same]
            lines.append("")
        survivors = [o for o in survivors if not o.behaviour]
    for sev in (STRONG, MEDIUM, WEAK):
        group = [o for o in survivors if o.mutant.variant.severity == sev]
        if not group:
            continue
        lines += [f"## Accepted {sev} mutants — {VERDICT[sev]}", ""]
        for o in group:
            m = o.mutant
            lines += [f"### `{m.container_path}` — {m.variant.operator}", "", m.variant.description, ""]
            if o.probe:
                lines += [f"Tolerance probe: {o.probe.summary()}.", ""]
            lines += ["```diff", m.diff(), "```", ""]
    if r.skipped:
        shown = r.skipped[:20]
        lines += ["## Skipped", ""] + [f"- {s}" for s in shown]
        if len(r.skipped) > len(shown):
            lines.append(f"- ... and {len(r.skipped) - len(shown)} more unchanged input files")
    lines += ["", ("_A mutant is **accepted** when the verifier still awards full reward. Strong mutants are almost "
                   "never correct answers; medium and weak ones need a human to judge whether the task allows them._")]
    return "\n".join(lines) + "\n"


def summarize(runs: Path) -> str:
    """Markdown table over every <task>/report.json below `runs`."""
    rows = []
    for path in sorted(runs.rglob("report.json")):
        d = json.loads(path.read_text())
        surv = [r for r in d["results"] if r["survived"]]
        sev = Counter(r["severity"] for r in surv)
        rows.append((d["task"], d["mutants"], len(surv), sev[STRONG], sev[MEDIUM], sev[WEAK],
                     ", ".join(sorted({f"{r['operator']}" for r in surv if r["severity"] == STRONG})) or "-"))
    head = ["| Task | Mutants | Accepted | Strong | Medium | Weak | Strong operators accepted |", "|---|---:|---:|---:|---:|---:|---|"]
    body = [f"| {t} | {m} | {a} | {s} | {md} | {w} | {ops} |" for t, m, a, s, md, w, ops in rows]
    total = f"\n{len(rows)} tasks, {sum(r[1] for r in rows)} mutants, {sum(r[2] for r in rows)} accepted ({sum(r[3] for r in rows)} strong)."
    return "\n".join(head + body) + total
