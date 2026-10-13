"""Read the parts of a Harbor / Terminal-Bench task that matter for mutation testing."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    source: str                      # absolute path inside the agent container, e.g. /app/results.txt
    exclude: tuple[str, ...] = ()

    @property
    def is_dir(self) -> bool:
        return self.source.endswith("/")


@dataclass
class Task:
    root: Path
    name: str
    artifacts: list[Artifact]
    verifier_mode: str
    verifier_timeout: float
    verifier_env: dict[str, str] = field(default_factory=dict)
    gpus: int = 0

    @property
    def slug(self) -> str:
        return self.root.name

    @property
    def tests_dir(self) -> Path:
        return self.root / "tests"


class TaskError(Exception):
    pass


def load_task(root: Path) -> Task:
    root = root.resolve()
    toml_path = root / "task.toml"
    if not toml_path.is_file():
        raise TaskError(f"{root} has no task.toml")
    cfg = tomllib.loads(toml_path.read_text())
    verifier = cfg.get("verifier", {})
    mode = verifier.get("environment_mode", "shared")
    if mode != "separate":
        raise TaskError(
            f"{root.name}: verifier runs in shared mode. oracle-mutants needs "
            "environment_mode = \"separate\" with declared artifacts (Terminal-Bench 4.0 format)."
        )
    raw = cfg.get("artifacts", [])
    if not raw:
        raise TaskError(f"{root.name}: no artifacts declared, nothing to mutate")
    artifacts = []
    for item in raw:
        if isinstance(item, str):
            artifacts.append(Artifact(item))
        else:
            artifacts.append(Artifact(item["source"], tuple(item.get("exclude", []))))
    if not (root / "tests" / "Dockerfile").is_file():
        raise TaskError(f"{root.name}: tests/Dockerfile missing; separate-mode verifiers build from it")
    return Task(
        root=root,
        name=cfg.get("task", {}).get("name", root.name),
        artifacts=artifacts,
        verifier_mode=mode,
        verifier_timeout=float(verifier.get("timeout_sec", 600.0)),
        verifier_env={k: str(v) for k, v in verifier.get("env", {}).items()},
        gpus=int(cfg.get("environment", {}).get("gpus", 0) or 0),
    )
