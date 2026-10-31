from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DraftChunk:
    """Represents a chunk of drafted text within a creative project."""

    text: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DraftChunk:
        if not isinstance(data, dict):
            return cls()
        return cls(
            text=str(data.get("text") or "").strip(),
            created_at=float(data.get("created_at") or time.time()),
        )


@dataclass
class CreativeProject:
    """Represents a creative work / story / bookshelf project."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    work_type: str = "短篇小说"
    status: str = "drafting"  # drafting, finished, paused
    premise: str = ""
    tone: str = "温柔"
    point_of_view: str = "第三人称有限视角"
    target_chars: int = 2000
    current_chars: int = 0
    draft_chunks: List[DraftChunk] = field(default_factory=list)
    secret: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "work_type": self.work_type,
            "status": self.status,
            "premise": self.premise,
            "tone": self.tone,
            "point_of_view": self.point_of_view,
            "target_chars": self.target_chars,
            "current_chars": self.current_chars,
            "draft_chunks": [c.to_dict() if isinstance(c, DraftChunk) else c for c in self.draft_chunks],
            "secret": self.secret,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreativeProject:
        chunks_data = data.get("draft_chunks") or []
        chunks: List[DraftChunk] = []
        if isinstance(chunks_data, list):
            for c in chunks_data:
                if isinstance(c, dict):
                    chunks.append(DraftChunk.from_dict(c))
                elif isinstance(c, DraftChunk):
                    chunks.append(c)

        chars = int(data.get("current_chars") or 0)
        if not chars and chunks:
            chars = sum(len(c.text) for c in chunks)

        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]).strip(),
            title=str(data.get("title") or "").strip(),
            work_type=str(data.get("work_type") or "短篇小说").strip(),
            status=str(data.get("status") or "drafting").strip(),
            premise=str(data.get("premise") or "").strip(),
            tone=str(data.get("tone") or "温柔").strip(),
            point_of_view=str(data.get("point_of_view") or "第三人称有限视角").strip(),
            target_chars=int(data.get("target_chars") or 2000),
            current_chars=chars,
            draft_chunks=chunks,
            secret=bool(data.get("secret", False)),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )
