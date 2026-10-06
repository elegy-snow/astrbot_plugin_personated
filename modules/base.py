from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from astrbot.api.star import Context
    from astrbot.core.config.astrbot_config import AstrBotConfig


class BaseFeatureModule:
    """Base class for feature modules in the aggregation plugin.

    Enables modular architecture so future features can be added cleanly.
    """

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict,
        logger: logging.Logger,
    ) -> None:
        self.context = context
        self.config = config
        self.logger = logger

    def get_config_val(self, key: str, default: Any = None) -> Any:
        """Safely retrieve configuration value."""
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return default

    async def initialize(self) -> None:
        """Asynchronous initialization hook called when the plugin is loaded."""
        pass

    async def terminate(self) -> None:
        """Asynchronous cleanup hook called when the plugin is unloaded."""
        pass
