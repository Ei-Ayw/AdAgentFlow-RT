"""In-memory artifact store."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from app.contracts.models import Artifact


class InMemoryArtifactStore:
    def __init__(self):
        self._artifacts: Dict[str, Artifact] = {}

    def put(self, artifact: Artifact) -> None:
        self._artifacts[artifact.artifact_id] = artifact

    def get(self, artifact_id: str) -> Optional[Artifact]:
        return self._artifacts.get(artifact_id)

    def require(self, artifact_id: str) -> Artifact:
        artifact = self.get(artifact_id)
        if artifact is None:
            raise KeyError(f"unknown artifact: {artifact_id}")
        return artifact

    def ids(self) -> List[str]:
        return sorted(self._artifacts)

    def invalidate(self, artifact_ids: Iterable[str]) -> None:
        for artifact_id in artifact_ids:
            artifact = self._artifacts.get(artifact_id)
            if artifact:
                artifact.validation_status = "invalidated"
