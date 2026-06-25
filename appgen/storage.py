from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from appgen.models import PipelineRun


class ArtifactStore:
    """流水线产物持久化。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        path = self.workspace / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_run(self, run: PipelineRun) -> Path:
        run_dir = self.run_dir(run.id)
        path = run_dir / "run.json"
        path.write_text(
            run.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path

    def load_run(self, run_id: str) -> PipelineRun:
        path = self.run_dir(run_id) / "run.json"
        if not path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return PipelineRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[PipelineRun]:
        runs_root = self.workspace / "runs"
        if not runs_root.exists():
            return []
        results: list[PipelineRun] = []
        for child in sorted(runs_root.iterdir(), reverse=True):
            run_file = child / "run.json"
            if run_file.exists():
                results.append(PipelineRun.model_validate_json(run_file.read_text(encoding="utf-8")))
        return results

    def save_text(self, run: PipelineRun, name: str, content: str) -> Path:
        path = self.run_dir(run.id) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        run.artifacts[name] = str(path)
        return path

    def save_json(self, run: PipelineRun, name: str, data: dict[str, Any]) -> Path:
        return self.save_text(run, name, json.dumps(data, ensure_ascii=False, indent=2))

    def load_text(self, run_id: str, name: str) -> str:
        path = self._resolve_artifact_path(run_id, name)
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {run_id}/{name}")
        return path.read_text(encoding="utf-8")

    def _resolve_artifact_path(self, run_id: str, name: str) -> Path:
        return self.run_dir(run_id) / name

    def artifact_exists(self, run_id: str, name: str) -> bool:
        return self._resolve_artifact_path(run_id, name).exists()

    def list_dir(self, run_id: str, relative_dir: str) -> list[str]:
        base = self._resolve_artifact_path(run_id, relative_dir)
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(base))
            for p in base.rglob("*")
            if p.is_file()
        )
