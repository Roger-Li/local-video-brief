from __future__ import annotations

from pathlib import Path


class StorageService:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        path = self.artifact_root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

