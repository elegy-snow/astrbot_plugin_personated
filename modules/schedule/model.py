from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional

try:
    from ...utils.time_utils import is_time_in_range, parse_time_str
except (ImportError, ValueError):
    from utils.time_utils import is_time_in_range, parse_time_str


@dataclass
class ScheduleSegment:
    """Configured time segment for schedule generation."""

    id: str
    name: str
    start: str  # 24h format HH:MM
    end: str    # 24h format HH:MM

    def contains(self, target: datetime.time) -> bool:
        """Check if target time is within this segment's [start, end) range."""
        try:
            start_t = parse_time_str(self.start)
            end_t = parse_time_str(self.end)
            return is_time_in_range(target, start_t, end_t, inclusive_end=False)
        except Exception:
            return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleSegment:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "未命名时间段")),
            start=str(data.get("start", "00:00")),
            end=str(data.get("end", "00:00")),
        )


@dataclass
class DailyScheduleItem:
    """A generated schedule entry for a specific time segment."""

    id: str
    name: str
    start: str
    end: str
    activity: str
    state: str

    def contains(self, target: datetime.time) -> bool:
        """Check if target time falls within this scheduled item."""
        try:
            start_t = parse_time_str(self.start)
            end_t = parse_time_str(self.end)
            return is_time_in_range(target, start_t, end_t, inclusive_end=False)
        except Exception:
            return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DailyScheduleItem:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            start=str(data.get("start", "")),
            end=str(data.get("end", "")),
            activity=str(data.get("activity", "日常活动中")),
            state=str(data.get("state", "平静沉稳")),
        )


@dataclass
class DailySchedule:
    """The generated daily schedule for a specific date."""

    date: str  # YYYY-MM-DD
    weekday: str
    persona_id: str
    generated_at: str
    provider_used: str
    items: List[DailyScheduleItem] = field(default_factory=list)

    def find_active_item(
        self,
        target_time: datetime.time | None = None,
    ) -> Optional[DailyScheduleItem]:
        """Find the schedule item currently in effect for the given time."""
        if target_time is None:
            target_time = datetime.datetime.now().time()

        for item in self.items:
            if item.contains(target_time):
                return item
        return None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "weekday": self.weekday,
            "persona_id": self.persona_id,
            "generated_at": self.generated_at,
            "provider_used": self.provider_used,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> DailySchedule:
        items = [
            DailyScheduleItem.from_dict(item_data)
            for item_data in data.get("items", [])
            if isinstance(item_data, dict)
        ]
        return cls(
            date=str(data.get("date", "")),
            weekday=str(data.get("weekday", "")),
            persona_id=str(data.get("persona_id", "")),
            generated_at=str(data.get("generated_at", "")),
            provider_used=str(data.get("provider_used", "")),
            items=items,
        )
