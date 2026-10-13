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
    with tempfile.TemporaryDirectory(prefix="om-") as tmp:
        logs = Path(tmp) / "logs"
        timed_out, output, _ = _run(image, task, artifacts, overrides or {}, ["bash", "/tests/test.sh"],
                                    timeout or task.verifier_timeout, Path(tmp), logs)
        return VerifierResult(_reward(logs), timed_out, output)


@dataclass
class CommandResult:
    output_file: bytes | None  # the fetched file, None when the command did not write it
    timed_out: bool
    output_tail: str


def run_command(image: str, task: Task, artifacts: list[ExportedArtifact], overrides: dict[str, bytes] | None,
                command: str, fetch: str, timeout: float | None = None) -> CommandResult:
    """Run `command` in the verifier image with the (possibly mutated) artifacts and return the file at `fetch`.
    Used to tell an equivalent mutant (same output as the reference) from one the verifier failed to notice."""
    with tempfile.TemporaryDirectory(prefix="om-") as tmp:
        timed_out, output, fetched = _run(image, task, artifacts, overrides or {}, ["bash", "-c", command],
                                          timeout or task.verifier_timeout, Path(tmp), Path(tmp) / "logs", fetch)
        return CommandResult(fetched, timed_out, output)


def _run(image: str, task: Task, artifacts: list[ExportedArtifact], overrides: dict[str, bytes], argv: list[str],
         timeout: float, tmp: Path, logs: Path, fetch: str | None = None) -> tuple[bool, str, bytes | None]:
    logs.mkdir()
    logs.chmod(0o777)
    staged = _stage(tmp / "stage", artifacts, overrides)
    name = f"om-{uuid.uuid4().hex[:12]}"
    env_args = [arg for k, v in task.verifier_env.items() for arg in ("-e", f"{k}={v}")]
    create = subprocess.run(["docker", "create", "--name", name, "-v", f"{logs}:/logs/verifier", *env_args, image, *argv],
                            capture_output=True, text=True)
    if create.returncode != 0:
        raise VerifierError(f"docker create failed: {create.stderr[-2000:]}")
    try:
        for art, host in staged:
            if art.is_dir:
                _cp(f"{host}/.", f"{name}:{art.source.rstrip('/')}/")
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
        fetched = None
        if fetch:
            out = tmp / "fetched"
            if subprocess.run(["docker", "cp", f"{name}:{fetch}", str(out)], capture_output=True).returncode == 0 and out.is_file():
                fetched = out.read_bytes()
        return timed_out, output, fetched
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
