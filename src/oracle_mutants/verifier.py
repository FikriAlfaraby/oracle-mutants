"""Re-run a separate-mode verifier in a fresh container against (possibly mutated) artifacts.

This mirrors Harbor's separate verifier mode: the verifier image is built from the
task's tests/ directory, the declared artifacts are copied in at their original
absolute paths, and /tests/test.sh writes the reward to /logs/verifier.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .oracle import ExportedArtifact
from .task import Task


@dataclass
class VerifierResult:
    reward: float | None       # None when the verifier produced no reward (crash, timeout)
    timed_out: bool
    output_tail: str


class VerifierError(Exception):
    pass


def build_image(task: Task) -> str:
    tag = f"oracle-mutants/{task.slug.lower()}:verifier"
    proc = subprocess.run(["docker", "build", "-q", "-t", tag, str(task.tests_dir)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise VerifierError(f"docker build of {task.tests_dir} failed:\n{proc.stderr[-3000:]}")
    return tag


def run_verifier(image: str, task: Task, artifacts: list[ExportedArtifact],
                 overrides: dict[str, bytes] | None = None, timeout: float | None = None) -> VerifierResult:
    """overrides maps an absolute container file path to replacement bytes."""
    overrides = overrides or {}
    timeout = timeout or task.verifier_timeout
    with tempfile.TemporaryDirectory(prefix="om-") as tmp:
        tmp = Path(tmp)
        logs = tmp / "logs"
        logs.mkdir()
        logs.chmod(0o777)
        staged = _stage(tmp / "stage", artifacts, overrides)
        name = f"om-{uuid.uuid4().hex[:12]}"
        env_args = [arg for k, v in task.verifier_env.items() for arg in ("-e", f"{k}={v}")]
        create = subprocess.run(["docker", "create", "--name", name, "-v", f"{logs}:/logs/verifier", *env_args,
                                 image, "bash", "/tests/test.sh"], capture_output=True, text=True)
        if create.returncode != 0:
            raise VerifierError(f"docker create failed: {create.stderr[-2000:]}")
        try:
            for art, host in staged:
                if art.is_dir:
                    dest = art.source.rstrip("/") + "/"
                    _cp(f"{host}/.", f"{name}:{dest}")
                else:
                    _cp(str(host), f"{name}:{art.source}")
            timed_out = False
            try:
                run = subprocess.run(["docker", "start", "-a", name], capture_output=True, text=True, timeout=timeout + 30)
                output = (run.stdout + run.stderr)[-4000:]
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                subprocess.run(["docker", "kill", name], capture_output=True)
                output = (str(exc.stdout or "") + str(exc.stderr or ""))[-4000:]
            return VerifierResult(_reward(logs), timed_out, output)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _cp(src: str, dst: str) -> None:
    proc = subprocess.run(["docker", "cp", src, dst], capture_output=True, text=True)
    if proc.returncode != 0:
        raise VerifierError(f"docker cp {src} {dst} failed: {proc.stderr.strip()}")


def _stage(stage: Path, artifacts: list[ExportedArtifact], overrides: dict[str, bytes]) -> list[tuple[ExportedArtifact, Path]]:
    stage.mkdir()
    staged = []
    for i, art in enumerate(artifacts):
        dest = stage / str(i)
        if art.is_dir:
            shutil.copytree(art.host_path, dest, symlinks=True)
            prefix = art.source.rstrip("/") + "/"
            for path, data in overrides.items():
                if path.startswith(prefix):
                    target = dest / path[len(prefix):]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
        else:
            shutil.copy2(art.host_path, dest)
            if art.source in overrides:
                dest.write_bytes(overrides[art.source])
        staged.append((art, dest))
    return staged


def _reward(logs: Path) -> float | None:
    txt, js = logs / "reward.txt", logs / "reward.json"
    try:
        if txt.is_file() and txt.read_text().strip():
            return float(txt.read_text().strip())
        if js.is_file():
            data = json.loads(js.read_text())
            if isinstance(data, dict):
                return float(data.get("reward", next(iter(data.values()))))
            return float(data)
    except (ValueError, StopIteration):
        return None
    return None
