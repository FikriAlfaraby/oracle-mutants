"""Copy the run reports the README and docs quote from runs/ (ignored: it holds the containers' jobs) into
results/ (committed), with machine paths taken out, so every headline number can be checked from the repo.

    python3 scripts/export_results.py
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = ROOT / "results"
# a local checkout's absolute path, up to the folder that holds the projects
LOCAL = re.compile(r"/Users/[^/\"\s]+/Documents/Projects/(?:_upstream/)?")

# (folder under runs/, folder under results/): what each set backs
SETS = {
    "tb": "first-pass",  # README "Precision": 15 tasks, 165 mutants, 36 accepted (triage-notes.md)
    "recall": "recall-blind",  # recall-results.md: six tasks, 89 mutants, 42 accepted, none of the seven
    "v03-final": "final",  # recall-results.md "Final runs"; the session-window-debug gap
    "tbid-v03": "terminal-bench-id",  # terminal-bench-id's mutation check: 45 mutants, 0 accepted
}
SINGLE = {
    "word-count-weak/report.json": "examples/word-count-weak.json",
    "word-count-weak/report.md": "examples/word-count-weak.md",
    "foodstuff-beta-activity/report.json": "examples/foodstuff-beta-activity.json",
}


def clean(text: str) -> str:
    return LOCAL.sub("", text)


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(clean(src.read_text(encoding="utf-8")), encoding="utf-8")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    for source, target in SETS.items():
        for report in sorted((RUNS / source).glob("*/report.json")):
            copy(report, OUT / target / f"{report.parent.name}.json")
    # telecom-entity-resolution's first-pass run stopped before writing a report; its log has every verdict
    copy(RUNS / "tb" / "telecom-entity-resolution.log", OUT / "first-pass" / "telecom-entity-resolution.log")
    for source, target in SINGLE.items():
        copy(RUNS / source, OUT / target)
    left = [str(p.relative_to(ROOT)) for p in OUT.rglob("*") if p.is_file() and "/Users/" in p.read_text(encoding="utf-8")]
    if left:
        raise SystemExit(f"machine paths left in {left}")
    print(f"{OUT.relative_to(ROOT)}: {sum(1 for p in OUT.rglob('*') if p.is_file())} files")


if __name__ == "__main__":
    main()
