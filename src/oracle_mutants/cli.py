"""Command line: oracle-mutants run <task-dir>."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .operators import MEDIUM, STRONG, WEAK
from .oracle import OracleError, load_oracle_job, run_oracle
from .probe import probe
from .report import summarize, write
from .runner import Report, execute, plan
from .task import TaskError, load_task
from .verifier import VerifierError, build_image, run_verifier


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="oracle-mutants", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="mutate one task's reference outputs and re-run its verifier")
    r.add_argument("task", type=Path, help="task directory containing task.toml")
    r.add_argument("--oracle-job", type=Path, help="reuse an existing Harbor oracle job/trial directory")
    r.add_argument("--out", type=Path, default=Path("runs"), help="output directory (default: ./runs)")
    r.add_argument("--max-mutants", type=int, default=40)
    r.add_argument("--max-files", type=int, default=6, help="files sampled inside each directory artifact")
    r.add_argument("--severity", default="strong,medium,weak", help="comma list of severities to run")
    r.add_argument("--workers", type=int, default=4, help="verifier containers to run in parallel")
    r.add_argument("--dry-run", action="store_true", help="list the mutants without running anything in Docker")
    r.add_argument("--probe", action="store_true",
                   help="for each accepted nudged number, widen the change until the verifier rejects it")
    s = sub.add_parser("summarize", help="combine the report.json files under a runs directory into one table")
    s.add_argument("runs", type=Path, help="directory containing <task>/report.json")
    args = p.parse_args(argv)
    if args.cmd == "summarize":
        print(summarize(args.runs))
        return 0
    return _run(args)


def _run(args) -> int:
    try:
        task = load_task(args.task)
    except TaskError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = args.out / task.slug
    severities = {s.strip() for s in args.severity.split(",")} & {STRONG, MEDIUM, WEAK}
    try:
        if args.oracle_job:
            oracle = load_oracle_job(args.oracle_job)
        else:
            print(f"[1/4] running the reference solution of {task.name} with Harbor ...", flush=True)
            oracle = run_oracle(task, out / "jobs")
        print(f"      oracle reward {oracle.reward}; exported: {', '.join(a.source for a in oracle.artifacts)}")
        if oracle.reward < 1.0:
            print("error: the reference solution does not pass its own verifier; nothing to compare against", file=sys.stderr)
            return 3
        skipped: list[str] = []
        mutants = plan(task, oracle, args.max_files, args.max_mutants, severities, skipped)
        for line in skipped:
            print(f"      skip {line}")
        if args.dry_run:
            for m in mutants:
                print(f"{m.variant.severity:6} {m.variant.operator:20} {m.container_path}  {m.variant.description}")
            return 0
        print("[2/4] building the verifier image from tests/ ...", flush=True)
        image = build_image(task)
        print("[3/4] re-verifying the untouched reference outputs ...", flush=True)
        baseline = run_verifier(image, task, oracle.artifacts)
        if baseline.reward != oracle.reward:
            print(f"error: re-verification gave {baseline.reward}, Harbor gave {oracle.reward}. "
                  "This setup does not reproduce the verifier faithfully.\n" + baseline.output_tail, file=sys.stderr)
            return 4
        print(f"[4/4] running {len(mutants)} mutants with {args.workers} workers ...", flush=True)
        t0 = time.time()

        def progress(o):
            mark = "ACCEPTED" if o.survived else ("no-reward" if o.result.reward is None else "rejected")
            print(f"      {mark:9} {o.mutant.variant.severity:6} {o.mutant.variant.operator:18} {o.mutant.container_path}", flush=True)

        outcomes = execute(task, oracle, image, mutants, args.workers, progress)
        if args.probe:
            for o in outcomes:
                o.probe = probe(task, oracle, image, o)
                if o.probe:
                    print(f"      probe {o.mutant.container_path}: {o.probe.summary()}", flush=True)
        report = Report(task, oracle, baseline, outcomes, skipped)
        js, md = write(report, out)
        survivors = sum(o.survived for o in outcomes)
        print(f"\n{survivors} of {len(outcomes)} mutants accepted ({time.time() - t0:.0f}s). Report: {md}")
        return 1 if any(o.survived and o.mutant.variant.severity == STRONG for o in outcomes) else 0
    except (OracleError, VerifierError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
