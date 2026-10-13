"""Pick mutants across a task's artifacts, run the verifier on each, and collect the survivors."""

from __future__ import annotations

import difflib
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from .operators import MEDIUM, STRONG, WEAK, Variant, kind_of, mutate
from .oracle import ExportedArtifact, OracleRun
from .task import Task
from .verifier import VerifierResult, run_verifier

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build", "target", ".next"}
KIND_ORDER = {"json": 0, "text": 1, "code": 2, "binary": 3}
SEVERITY_ORDER = {STRONG: 0, MEDIUM: 1, WEAK: 2}
MAX_FILE_BYTES = 20 * 1024 * 1024


@dataclass
class Mutant:
    container_path: str
    variant: Variant
    original: bytes

    @property
    def id(self) -> str:
        return f"{self.container_path}::{self.variant.operator}::{self.variant.description}"

    def diff(self, max_lines: int = 24) -> str:
        if kind_of(self.container_path, self.original) == "binary":
            return f"(binary) {len(self.original)} -> {len(self.variant.data)} bytes"
        a = self.original.decode("utf-8", "replace").splitlines()
        b = self.variant.data.decode("utf-8", "replace").splitlines()
        lines = list(difflib.unified_diff(a, b, "reference", "mutant", n=1, lineterm=""))
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more diff lines)"]
        return "\n".join(lines)


@dataclass
class Outcome:
    mutant: Mutant
    result: VerifierResult
    probe: object | None = None  # probe.Probe, filled in by --probe
    behaviour: str | None = None  # compare verdict, filled in by --compare
    behaviour_diff: str = ""
    behaviour_size: str = ""
    behaviour_largest: float = 0.0

    @property
    def survived(self) -> bool:
        return self.result.reward is not None and self.result.reward >= 1.0


@dataclass
class Report:
    task: Task
    oracle: OracleRun
    baseline: VerifierResult
    outcomes: list[Outcome] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def candidate_files(art: ExportedArtifact, task_exclude: tuple[str, ...], max_files: int,
                    skip_hashes: frozenset[str] = frozenset(), skipped: list[str] | None = None) -> list[tuple[str, Path]]:
    """(container path, host path) pairs to mutate inside one artifact. Files whose hash is in
    `skip_hashes` are dropped before the `max_files` cap so the budget goes to files the solution wrote."""
    if not art.is_dir:
        if _sha(art.host_path) in skip_hashes:
            _note(skipped, art.source)
            return []
        return [(art.source, art.host_path)]
    files = []
    base = art.host_path
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            host = Path(dirpath) / fn
            rel = host.relative_to(base).as_posix()
            if any(fnmatch(rel, pat) or fnmatch(fn, pat) for pat in task_exclude):
                continue
            if host.is_symlink() or host.stat().st_size > MAX_FILE_BYTES or host.stat().st_size == 0:
                continue
            container_path = art.source.rstrip("/") + "/" + rel
            if _sha(host) in skip_hashes:
                _note(skipped, container_path)
                continue
            files.append((container_path, host))
    files.sort(key=lambda f: (KIND_ORDER[kind_of(f[0], f[1].read_bytes()[:8192])], f[0]))
    return files[:max_files]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _note(skipped: list[str] | None, container_path: str) -> None:
    if skipped is not None:
        skipped.append(f"{container_path}: identical to a file shipped in environment/ (an input, not an answer)")


def shipped_input_hashes(task: Task) -> set[str]:
    """Hashes of every file the task ships in environment/. An artifact identical to one of these
    is an untouched input, not an answer, so mutating it says nothing about the verifier."""
    hashes = set()
    env = task.root / "environment"
    if env.is_dir():
        for path in env.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE_BYTES:
                hashes.add(_sha(path))
    return hashes


def plan(task: Task, oracle: OracleRun, max_files: int, max_mutants: int, severities: set[str],
         skipped: list[str] | None = None, per_operator: int = 3) -> list[Mutant]:
    excludes = {a.source: a.exclude for a in task.artifacts}
    inputs = frozenset(shipped_input_hashes(task))
    mutants: list[Mutant] = []
    for art in oracle.artifacts:
        for container_path, host in candidate_files(art, excludes.get(art.source, ()), max_files, inputs, skipped):
            data = host.read_bytes()
            for v in mutate(container_path, data, per_operator):
                if v.severity in severities:
                    mutants.append(Mutant(container_path, v, data))
    mutants.sort(key=lambda m: SEVERITY_ORDER[m.variant.severity])  # stable: keeps file order within a severity
    return mutants[:max_mutants]


def execute(task: Task, oracle: OracleRun, image: str, mutants: list[Mutant], workers: int,
            on_result=None) -> list[Outcome]:
    def one(m: Mutant) -> Outcome:
        out = Outcome(m, run_verifier(image, task, oracle.artifacts, {m.container_path: m.variant.data}))
        if on_result:
            on_result(out)
        return out

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, mutants))
