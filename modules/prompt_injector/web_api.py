from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

try:
    from astrbot.api import logger as astrbot_logger
except Exception:
    import logging as _logging
    astrbot_logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[拟人化提示词]"

try:
    from astrbot.api.web import error_response, json_response, request
except Exception:
    def json_response(data: Any, status_code: int = 200):
        return {"status": "ok", "data": data, "_code": status_code}

    def error_response(msg: str, status_code: int = 400):
        return {"status": "error", "message": msg, "_code": status_code}

    request = None  # type: ignore

if TYPE_CHECKING:
    from .manager import PromptInjectorManager

PLUGIN_NAME = "astrbot_plugin_personated"


class PromptInjectorWebApi:
    """Web API handlers for targeted UMO prompt injection management."""

    def __init__(self, manager: PromptInjectorManager, logger: logging.Logger) -> None:
        self.mgr = manager
        self.logger = logger

    def register_routes(self, context: Any) -> None:
        """Register Web API routes with AstrBot context."""
        if not hasattr(context, "register_web_api"):
            self.logger.warning("Context does not support register_web_api. Web API skipped.")
            return

        base_routes = [
            ("prompt-injector/config", self.get_config, ["GET"], "获取提示词注入全局配置"),
            ("prompt-injector/config/save", self.save_config, ["POST"], "保存提示词注入全局配置"),
            ("prompt-injector/rules", self.get_rules, ["GET"], "获取所有已配置的会话提示词规则"),
            ("prompt-injector/rule/save", self.save_rule, ["POST"], "添加或保存单条会话专属提示词规则"),
            ("prompt-injector/rule/delete", self.delete_rule, ["POST"], "删除指定会话提示词规则"),
            ("prompt-injector/rule/toggle", self.toggle_rule, ["POST"], "切换指定会话规则的启用状态"),
            ("prompt-injector/discovered-umos", self.get_discovered_umos, ["GET"], "从 AstrBot 数据与日志中抓取会话列表（含群名称/对话人昵称）"),
        ]

        # Register both with /{PLUGIN_NAME}/ prefix and short / prefix for bulletproof routing
        for path_part, handler, methods, desc in base_routes:
            for prefix in [f"/{PLUGIN_NAME}/", "/"]:
                full_route = f"{prefix}{path_part}"
                try:
                    context.register_web_api(full_route, handler, methods, desc)
                except Exception as e:
                    self.logger.warning("Failed to register Web API route %s: %s", full_route, e)

        astrbot_logger.info(f"{LOG_TAG} 成功注册 {len(base_routes)} 组专属提示词管理 Web API 路由")

    # --------------------------------------------------------------------------
    # Handlers
    # --------------------------------------------------------------------------

    async def get_config(self) -> Any:
        """GET /{PLUGIN_NAME}/prompt-injector/config"""
        rules = self.mgr.get_all_rules()
        enabled_count = sum(1 for r in rules if r.get("enabled"))
        return json_response(
            {
                "enabled": self.mgr.enabled,
                "default_inject_mode": self.mgr.default_inject_mode,
                "total_rules": len(rules),
                "enabled_rules": enabled_count,
            }
        )

    async def save_config(self) -> Any:
        """POST /{PLUGIN_NAME}/prompt-injector/config/save"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        enabled_val = payload.get("enabled")
        if enabled_val is not None:
            self.mgr.enabled = bool(enabled_val)

        mode_val = payload.get("default_inject_mode")
        if mode_val and isinstance(mode_val, str):
            self.mgr.config["umo_prompt_default_mode"] = mode_val.strip()
            if hasattr(self.mgr.config, "save_config"):
                try:
                    self.mgr.config.save_config()
                except Exception as e:
                    self.logger.warning("Failed to invoke save_config(): %s", e)

        astrbot_logger.info(
            f"{LOG_TAG} WebUI 保存全局配置: 全局启用={self.mgr.enabled}, 默认模式={self.mgr.default_inject_mode}"
        )
        return json_response({"saved": True, "message": "全局配置已保存！"})

    async def get_rules(self) -> Any:
        """GET /{PLUGIN_NAME}/prompt-injector/rules"""
        rules = self.mgr.get_all_rules()
        return json_response({"rules": rules, "count": len(rules)})

    async def save_rule(self) -> Any:
        """POST /{PLUGIN_NAME}/prompt-injector/rule/save"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("Payload must be a JSON object", 400)

        umo = str(payload.get("umo", "")).strip()
        if not umo:
            return error_response("UMO 不能为空", 400)

        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            return error_response("提示词内容不能为空", 400)

        try:
            rule = self.mgr.save_rule(payload)
            astrbot_logger.info(f"{LOG_TAG} WebUI 成功保存专属提示词规则: 【{rule.name}】(UMO: {umo})")
            return json_response(
                {
                    "saved": True,
                    "rule": rule.to_dict(),
                    "message": f"成功保存【{rule.name}】的专属提示词！",
                }
            )
        except Exception as e:
            astrbot_logger.error(f"{LOG_TAG} WebUI 保存专属规则异常: {e}")
            return error_response(f"保存规则失败: {e}", 500)

    async def delete_rule(self) -> Any:
        """POST /{PLUGIN_NAME}/prompt-injector/rule/delete"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        umo = str(payload.get("umo", "")).strip()
        if not umo and hasattr(request, "query"):
            umo = str(request.query.get("umo", "")).strip()

        if not umo:
            return error_response("未指定要删除的 UMO", 400)

        deleted = self.mgr.delete_rule(umo)
        astrbot_logger.info(f"{LOG_TAG} WebUI 删除专属提示词规则: UMO={umo}, 结果={deleted}")
        return json_response(
            {
                "deleted": deleted,
                "umo": umo,
                "message": f"已成功删除该会话规则" if deleted else "未找到该会话规则",
            }
        )

    async def toggle_rule(self) -> Any:
        """POST /{PLUGIN_NAME}/prompt-injector/rule/toggle"""
        if request is None:
            return error_response("Request context unavailable", 500)

        payload = await request.json(default={})
        umo = str(payload.get("umo", "")).strip()
        if not umo:
            return error_response("未指定 UMO", 400)

        enabled_target = payload.get("enabled")
        rule = self.mgr.get_rule(umo)
        if not rule:
            return error_response(f"未找到 UMO 为 '{umo}' 的规则", 404)

        new_status = self.mgr.toggle_rule(umo, enabled_target)
        astrbot_logger.info(f"{LOG_TAG} WebUI 切换会话【{rule.name}】状态 -> {'启用' if new_status else '禁用'}")
        return json_response(
            {
                "umo": umo,
                "enabled": new_status,
                "message": f"已{'启用' if new_status else '禁用'}【{rule.name}】的专属提示词",
            }
        )

    async def get_discovered_umos(self) -> Any:
        """GET /{PLUGIN_NAME}/prompt-injector/discovered-umos"""
        astrbot_logger.info(f"{LOG_TAG} WebUI 请求抓取 AstrBot '数据与日志-对话' 中的所有会话列表...")
        try:
            discovered = await self.mgr.discover_conversations()
            return json_response(
                {
                    "success": True,
                    "count": len(discovered),
                    "conversations": discovered,
                }
            )
        except Exception as e:
            astrbot_logger.error(f"{LOG_TAG} 抓取会话列表异常: {e}", exc_info=True)
            return error_response(f"抓取会话列表失败: {e}", 500)
