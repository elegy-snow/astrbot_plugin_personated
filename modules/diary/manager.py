from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..base import BaseFeatureModule
from .model import DailyDiaryEntry

if TYPE_CHECKING:
    from astrbot.api.star import Context
    from astrbot.core.config.astrbot_config import AstrBotConfig


class DiaryManager(BaseFeatureModule):
    """Manages diary entries and persistence."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict,
        logger: logging.Logger,
    ) -> None:
        super().__init__(context, config, logger)
        self._storage_path = self._resolve_storage_path()
        self._entries: Dict[str, DailyDiaryEntry] = {}
        self._load_from_storage()
        self.logger.info("[日记系统] 初始化完成，加载了 %d 条日记", len(self._entries))

    @property
    def enabled(self) -> bool:
        """Check if diary system is enabled in config."""
        return bool(self.get_config_val("diary_enabled", True))

    def _resolve_storage_path(self) -> Path:
        """Resolve the storage directory under AstrBot plugin_data."""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            base_data = Path(get_astrbot_data_path())
        except Exception:
            base_data = Path("data")

        plugin_data_dir = base_data / "plugin_data" / "astrbot_plugin_personated"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        return plugin_data_dir / "diary_entries.json"

    def _load_from_storage(self) -> None:
        """Read saved diaries from disk."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._entries = {
                        date: DailyDiaryEntry.from_dict(entry_data)
                        for date, entry_data in data.items()
                    }
        except Exception as e:
            self.logger.error("加载日记失败: %s", e)

    def _save_to_storage(self) -> None:
        """Persist diaries to disk."""
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                data = {date: entry.to_dict() for date, entry in self._entries.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error("保存日记失败: %s", e)

    def add_entry(self, entry: DailyDiaryEntry) -> None:
        """Add or update a diary entry."""
        self._entries[entry.date] = entry
        self._save_to_storage()

    def get_entry(self, date: str) -> Optional[DailyDiaryEntry]:
        """Retrieve a diary entry by date."""
        return self._entries.get(date)

    def list_entries(self) -> List[DailyDiaryEntry]:
        """List all diary entries, sorted by date descending."""
        return sorted(self._entries.values(), key=lambda e: e.date, reverse=True)

    def delete_entry(self, date: str) -> None:
        """Delete a diary entry by date."""
        if date in self._entries:
            del self._entries[date]
            self._save_to_storage()
