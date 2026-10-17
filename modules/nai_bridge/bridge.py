# -*- coding: utf-8 -*-
"""Bridge implementation to discover and communicate with astrbot_plugin_nai_image."""
from __future__ import annotations

import logging
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("astrbot_plugin_personated.nai_bridge")

_TARGET_PLUGIN_NAME = "astrbot_plugin_nai_image"
_TARGET_MODULES = (
    "data.plugins.astrbot_plugin_nai_image.main",
    "astrbot_plugin_nai_image.main",
)
_CACHE_TTL = 15.0  # seconds


class NAIBridgeClient:
    """Discovers astrbot_plugin_nai_image extension API and delegates companion requests."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self._cached_api: Any = None
        self._cache_expires_at: float = 0.0

    def resolve_api(self, force_refresh: bool = False) -> Any | None:
        """Resolve the live extension API exposed by astrbot_plugin_nai_image.

        Discovery sequence aligns with companion plugins:
        1. Query `get_nai_image_api` from sys.modules
        2. Query context.get_registered_star(_TARGET_PLUGIN_NAME).star_cls.extension_api
        3. Query context.get_all_stars() searching by plugin name or module name
        """
        now = time.monotonic()
        if not force_refresh and self._cached_api is not None and now < self._cache_expires_at:
            return self._cached_api

        api: Any = None

        # 1. Direct module-level getter (get_nai_image_api)
        for mod_name in _TARGET_MODULES:
            mod = sys.modules.get(mod_name)
            if mod:
                getter = getattr(mod, "get_nai_image_api", None)
                if callable(getter):
                    try:
                        api = getter()
                        if api is not None:
                            break
                    except Exception as e:
                        logger.debug("Failed calling get_nai_image_api on %s: %s", mod_name, e)

        # 2. AstrBot Star Registry
        if api is None and self.context is not None:
            get_star = getattr(self.context, "get_registered_star", None)
            if callable(get_star):
                try:
                    star = get_star(_TARGET_PLUGIN_NAME)
                    if star is not None:
                        instance = getattr(star, "star_cls", None) or star
                        api = getattr(instance, "extension_api", None)
                except Exception as e:
                    logger.debug("get_registered_star error: %s", e)

        # 3. AstrBot all stars search
        if api is None and self.context is not None:
            get_all = getattr(self.context, "get_all_stars", None)
            if callable(get_all):
                try:
                    for star in get_all() or []:
                        name = getattr(star, "name", "") or getattr(star, "root_dir_name", "")
                        if _TARGET_PLUGIN_NAME in str(name):
                            instance = getattr(star, "star_cls", None) or star
                            api = getattr(instance, "extension_api", None)
                            if api is not None:
                                break
                except Exception as e:
                    logger.debug("get_all_stars scan error: %s", e)

        # Update cache
        self._cached_api = api
        self._cache_expires_at = now + _CACHE_TTL
        return api

    def get_status(self) -> Dict[str, Any]:
        """Query NAI image companion bridge capability status."""
        api = self.resolve_api()
        if api is None:
            return {
                "installed": False,
                "enabled": False,
                "available": False,
                "reason": "not_installed_or_unloaded",
                "message": "未检测到 NAI 生图插件（astrbot_plugin_nai_image），请先安装并启用该插件。",
                "details": {},
            }

        getter = getattr(api, "capability_status", None)
        status_getter = getattr(api, "status", None)

        details: Dict[str, Any] = {}
        if callable(status_getter):
            try:
                details = status_getter()
            except Exception as e:
                logger.debug("Error calling status(): %s", e)

        if callable(getter):
            try:
                cap = getter(self)
                return {
                    "installed": bool(cap.get("installed", True)),
                    "enabled": bool(cap.get("enabled", True)),
                    "available": bool(cap.get("available", False)),
                    "reason": str(cap.get("reason", "unknown")),
                    "message": "NAI 生图插件已就绪" if cap.get("available") else f"不可用: {cap.get('reason')}",
                    "details": details,
                }
            except Exception as exc:
                logger.warning("Error calling capability_status: %s", exc)
                return {
                    "installed": True,
                    "enabled": True,
                    "available": False,
                    "reason": "capability_error",
                    "message": f"状态查询失败: {exc}",
                    "details": details,
                }

        # Fallback if only status() exists
        avail = bool(details.get("enabled", True) and details.get("token_configured", True))
        return {
            "installed": True,
            "enabled": bool(details.get("enabled", True)),
            "available": avail,
            "reason": "ready" if avail else "no_token",
            "message": "就绪" if avail else "未配置 Token",
            "details": details,
        }

    async def generate(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a companion generation request to the extension API.

        Expected request_payload structure:
        - prompt_text: str
        - prompt: str
        - workflow_kind: str ("selfie", "text2img", etc.)
        - session_key: str
        - style: str
        - size: str (ratio / size name)
        - negative: str
        - reference_image_paths: list of str
        """
        api = self.resolve_api()
        if api is None:
            return {
                "handled": False,
                "success": False,
                "backend": "NAI 生图",
                "image_path": "",
                "note": "未检测到 astrbot_plugin_nai_image 插件，请先安装并启用。",
            }

        generator = getattr(api, "generate_for_companion", None)
        if not callable(generator):
            return {
                "handled": False,
                "success": False,
                "backend": "NAI 生图",
                "image_path": "",
                "note": "目标插件的 extension_api 未提供 generate_for_companion 方法。",
            }

        try:
            res = await generator(self, request_payload)
            if not isinstance(res, dict):
                return {
                    "handled": False,
                    "success": False,
                    "backend": "NAI 生图",
                    "image_path": "",
                    "note": "生图插件返回了未知格式响应。",
                }

            image_path = str(res.get("image_path") or "")
            note = str(res.get("note") or "")
            handled = bool(res.get("handled", False))
            success = bool(image_path and handled)

            return {
                "handled": handled,
                "success": success,
                "backend": str(res.get("backend") or "NAI 生图"),
                "image_path": image_path,
                "note": note,
                "metadata": res.get("metadata") or {},
            }
        except Exception as exc:
            logger.exception("调用 NAI 生图插件异常: %s", exc)
            return {
                "handled": True,
                "success": False,
                "backend": "NAI 生图",
                "image_path": "",
                "note": f"调用 NAI 生图插件异常: {exc}",
            }
