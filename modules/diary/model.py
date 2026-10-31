from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional


@dataclass
class ContinuityThread:
    """Represents a narrative continuity thread spanning across days."""

    motif: str = ""
    status: str = ""
    next_hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "motif": self.motif,
            "status": self.status,
            "next_hint": self.next_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ContinuityThread:
        if not isinstance(data, dict):
            return cls()
        return cls(
            motif=str(data.get("motif") or "").strip(),
            status=str(data.get("status") or "").strip(),
            next_hint=str(data.get("next_hint") or "").strip(),
        )


@dataclass
class DailyDiaryEntry:
    """Represents a single generated diary entry."""

    date: str  # YYYY-MM-DD
    generated_at: str
    summary: str
    body: str
    share_seed: str = ""
    tags: List[str] = field(default_factory=list)
    diary_form: str = "auto"
    evidence: List[dict[str, str]] = field(default_factory=list)
    continuity_thread: ContinuityThread = field(default_factory=ContinuityThread)
    dream_fragments: List[dict[str, Any]] = field(default_factory=list)
    story_plan: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    persona_id: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "body": self.body,
            "share_seed": self.share_seed,
            "tags": list(self.tags),
            "diary_form": self.diary_form,
            "evidence": list(self.evidence),
            "continuity_thread": (
                self.continuity_thread.to_dict()
                if isinstance(self.continuity_thread, ContinuityThread)
                else self.continuity_thread
            ),
            "dream_fragments": list(self.dream_fragments),
            "story_plan": dict(self.story_plan),
            "raw": self.raw,
            "persona_id": self.persona_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyDiaryEntry:
        raw_thread = data.get("continuity_thread")
        thread = (
            ContinuityThread.from_dict(raw_thread)
            if isinstance(raw_thread, dict)
            else ContinuityThread()
        )
        return cls(
            date=str(data.get("date") or "").strip(),
            generated_at=str(data.get("generated_at") or "").strip(),
            summary=str(data.get("summary") or "").strip(),
            body=str(data.get("body") or "").strip(),
            share_seed=str(data.get("share_seed") or "").strip(),
            tags=[str(t).strip() for t in data.get("tags", []) if str(t).strip()],
            diary_form=str(data.get("diary_form") or "auto").strip(),
            evidence=[
                dict(e)
                for e in data.get("evidence", [])
                if isinstance(e, dict)
            ],
            continuity_thread=thread,
            dream_fragments=[
                dict(f)
                for f in data.get("dream_fragments", [])
                if isinstance(f, dict)
            ],
            story_plan=dict(data.get("story_plan", {})) if isinstance(data.get("story_plan"), dict) else {},
            raw=str(data.get("raw") or ""),
            persona_id=str(data.get("persona_id") or "default").strip(),
        )
