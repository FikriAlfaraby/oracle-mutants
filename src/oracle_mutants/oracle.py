"""Run a task's reference solution once with Harbor and collect the artifacts it exported."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .task import Task


@dataclass(frozen=True)
class ExportedArtifact:
    source: str        # path inside the container
    host_path: Path    # where Harbor copied it on the host
    is_dir: bool


@dataclass
class OracleRun:
    trial_dir: Path
    reward: float
    artifacts: list[ExportedArtifact]


class OracleError(Exception):
    pass


def run_oracle(task: Task, jobs_dir: Path, harbor: str = "harbor") -> OracleRun:
    # Harbor resolves a relative jobs dir against the compose project directory when it copies
    # directory artifacts out, so always hand it an absolute path.
    jobs_dir = jobs_dir.resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    before = set(jobs_dir.iterdir())
    proc = subprocess.run([harbor, "run", "-p", str(task.root), "-a", "oracle", "-o", str(jobs_dir)],
                          capture_output=True, text=True, check=False)
    new_jobs = sorted(set(jobs_dir.iterdir()) - before)
    if not new_jobs:
        raise OracleError(f"harbor produced no job directory.\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return load_oracle_job(new_jobs[-1])


def load_oracle_job(job_dir: Path) -> OracleRun:
    """Accept a Harbor job directory or a single trial directory from an earlier oracle run."""
    job_dir = job_dir.resolve()
    if (job_dir / "artifacts" / "manifest.json").is_file():
        trial = job_dir
    else:
        trials = [p for p in job_dir.iterdir() if (p / "artifacts" / "manifest.json").is_file()]
        if len(trials) != 1:
            raise OracleError(f"expected exactly one trial with artifacts in {job_dir}, found {len(trials)}")
        trial = trials[0]
    reward = _read_reward(trial / "verifier")
    manifest = json.loads((trial / "artifacts" / "manifest.json").read_text())
    exported = []
    for entry in manifest:
        if entry.get("status") != "ok" or entry.get("source", "").startswith("/logs/"):
            continue
        host = trial / entry["destination"]
        exported.append(ExportedArtifact(entry["source"], host, entry.get("type") == "directory" or host.is_dir()))
    if not exported:
        if reward < 1.0:
            raise OracleError(f"the reference solution failed its own verifier (reward {reward}) and wrote no "
                              f"artifacts; see {trial / 'agent'} and {trial / 'trial.log'}")
        raise OracleError(f"the oracle run in {trial} exported no artifacts")
    return OracleRun(trial, reward, exported)


def _read_reward(verifier_dir: Path) -> float:
    txt, js = verifier_dir / "reward.txt", verifier_dir / "reward.json"
    if txt.is_file() and txt.read_text().strip():
        return float(txt.read_text().strip())
    if js.is_file():
        data = json.loads(js.read_text())
        if isinstance(data, dict):
            return float(data.get("reward", next(iter(data.values()))))
        return float(data)
    raise OracleError(f"no reward file in {verifier_dir}")
