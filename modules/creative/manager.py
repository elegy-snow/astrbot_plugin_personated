from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..base import BaseFeatureModule
from .model import CreativeProject, DraftChunk

if TYPE_CHECKING:
    from astrbot.api.star import Context
    from astrbot.core.config.astrbot_config import AstrBotConfig


class CreativeManager(BaseFeatureModule):
    """Manages the creative writing and bookshelf system."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict,
        logger: logging.Logger,
    ) -> None:
        super().__init__(context, config, logger)
        self._storage_path = self._resolve_storage_path()
        self._projects: Dict[str, CreativeProject] = {}
        self._load_from_storage()
        self.logger.info("[创作与书架系统] 初始化完成，加载了 %d 个创作项目", len(self._projects))

    @property
    def enabled(self) -> bool:
        """Check if creative writing and bookshelf system is enabled in config."""
        return bool(self.get_config_val("creative_enabled", True))

    def _resolve_storage_path(self) -> Path:
        """Resolve the storage directory under AstrBot plugin_data."""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            base_data = Path(get_astrbot_data_path())
        except Exception:
            base_data = Path("data")

        plugin_data_dir = base_data / "plugin_data" / "astrbot_plugin_personated"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        return plugin_data_dir / "creative_projects.json"

    def _load_from_storage(self) -> None:
        """Read saved creative projects from disk."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._projects = {
                        pid: CreativeProject.from_dict(proj_data)
                        for pid, proj_data in data.items()
                    }
                elif isinstance(data, list):
                    self._projects = {
                        proj_data["id"]: CreativeProject.from_dict(proj_data)
                        for proj_data in data
                        if isinstance(proj_data, dict) and "id" in proj_data
                    }
        except Exception as e:
            self.logger.error("加载创作项目失败: %s", e)

    def _save_to_storage(self) -> None:
        """Persist creative projects to disk."""
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                data = {pid: project.to_dict() for pid, project in self._projects.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error("保存创作项目失败: %s", e)

    def save_project(self, project: CreativeProject) -> None:
        """Add or update a creative project."""
        project.updated_at = time.time()
        # Recalculate character count
        project.current_chars = sum(len(c.text) for c in project.draft_chunks)
        self._projects[project.id] = project
        self._save_to_storage()

    def get_project(self, project_id: str) -> Optional[CreativeProject]:
        """Retrieve a creative project by ID."""
        return self._projects.get(project_id)

    def list_projects(self) -> List[CreativeProject]:
        """List all creative projects sorted by updated_at descending."""
        return sorted(self._projects.values(), key=lambda p: p.updated_at, reverse=True)

    def delete_project(self, project_id: str) -> bool:
        """Delete a creative project by ID."""
        if project_id in self._projects:
            del self._projects[project_id]
            self._save_to_storage()
            return True
        return False

    def find_projects_by_selector(self, selector: str) -> List[CreativeProject]:
        """Find matching creative projects by title, ID or ordinal."""
        eligible = [
            p for p in self.list_projects()
            if p.status in {"drafting", "finished"} and any(c.text.strip() for c in p.draft_chunks)
        ]
        val = selector.strip()
        if not val:
            return eligible

        folded = val.casefold()
        exact = [
            p for p in eligible
            if folded in {p.id.casefold(), p.title.casefold()}
        ]
        if exact:
            return exact

        contains = [
            p for p in eligible
            if folded in p.title.casefold() or p.title.casefold() in folded
        ]
        if contains:
            return contains

        number_match = re.fullmatch(r"(?:第\s*)?(\d+)(?:\s*(?:个|篇|项))?", val)
        if number_match:
            index = int(number_match.group(1)) - 1
            if 0 <= index < len(eligible):
                return [eligible[index]]

        return []
