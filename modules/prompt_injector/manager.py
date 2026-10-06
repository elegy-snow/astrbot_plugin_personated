from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any, Dict, List, Optional

try:
    from astrbot.api import logger as astrbot_logger
except Exception:
    import logging as _logging
    astrbot_logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[拟人化提示词]"

try:
    from astrbot.core.agent.message import TextPart
except Exception:
    class TextPart:  # type: ignore
        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text

try:
    from ..base import BaseFeatureModule
except (ImportError, ValueError):
    from modules.base import BaseFeatureModule

from .model import UmoPromptRule, parse_umo_details

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest
    from astrbot.api.star import Context
    from astrbot.core.config.astrbot_config import AstrBotConfig


class PromptInjectorManager(BaseFeatureModule):
    """Manager for targeted group & private conversation prompt injection."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict,
        logger: logging.Logger,
    ) -> None:
        super().__init__(context, config, logger)
        self._lock = asyncio.Lock()
        self._rules: Dict[str, UmoPromptRule] = {}
        self._observed_umos: Dict[str, Dict[str, Any]] = {}

        # Resolve storage path: data/plugin_data/astrbot_plugin_personated/umo_prompt_rules.json
        base_data_dir = Path("data/plugin_data/astrbot_plugin_personated")
        base_data_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = base_data_dir / "umo_prompt_rules.json"

    # --------------------------------------------------------------------------
    # Configuration Properties
    # --------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the targeted UMO prompt injector is globally enabled."""
        val = self.get_config_val("umo_prompt_injector_enabled")
        return bool(val) if val is not None else True

    @enabled.setter
    def enabled(self, val: bool) -> None:
        self.config["umo_prompt_injector_enabled"] = bool(val)
        if hasattr(self.config, "save_config"):
            try:
                self.config.save_config()
            except Exception as e:
                self.logger.warning("Failed to save config: %s", e)

    @property
    def default_inject_mode(self) -> str:
        """Default injection mode for new rules."""
        return str(self.get_config_val("umo_prompt_default_mode", "system_prompt"))

    # --------------------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------------------

    async def initialize(self) -> None:
        """Load saved UMO prompt rules from storage or initial config."""
        self._load_from_storage()
        astrbot_logger.info(
            f"{LOG_TAG} 会话专属提示词管理器初始化完成，共载入 {len(self._rules)} 条专属规则（全局启用状态: {self.enabled}）"
        )

    async def terminate(self) -> None:
        """Clean up resources on plugin reload or shutdown."""
        self._save_to_storage()
        astrbot_logger.info(f"{LOG_TAG} 会话专属提示词管理器已安全注销。")

    # --------------------------------------------------------------------------
    # Event Observation & UMO Tracking
    # --------------------------------------------------------------------------

    def observe_event(self, event: Any) -> None:
        """Record runtime event details into discovered UMOs pool."""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo:
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parsed = parse_umo_details(umo)

        # Retrieve sender / group name if present
        title = ""
        group_id = ""
        if hasattr(event, "get_group_id"):
            try:
                gid = event.get_group_id()
                if gid and isinstance(gid, (str, int)) and not hasattr(gid, "_mock_name"):
                    group_id = str(gid)
            except Exception:
                pass

        chat_type = parsed.get("chat_type")
        if chat_type == "group":
            message_obj = getattr(event, "message_obj", None)
            group = getattr(message_obj, "group", None)
            gname = getattr(group, "group_name", None)
            if gname and isinstance(gname, str) and not hasattr(gname, "_mock_name"):
                title = gname
        else:
            if hasattr(event, "get_sender_name"):
                try:
                    sname = event.get_sender_name()
                    if sname and isinstance(sname, str) and not hasattr(sname, "_mock_name"):
                        title = sname
                except Exception:
                    pass

        if not title and hasattr(event, "get_sender_name"):
            try:
                sname = event.get_sender_name()
                if sname and isinstance(sname, str) and not hasattr(sname, "_mock_name"):
                    title = sname
            except Exception:
                pass

        if not title:
            title = parsed["display_badge"]

        self._observed_umos[umo] = {
            "umo": umo,
            "title": title,
            "platform": parsed["platform"],
            "platform_name_cn": parsed["platform_name_cn"],
            "chat_type": parsed["chat_type"],
            "chat_type_text": parsed["chat_type_text"],
            "target_id": parsed["target_id"],
            "group_id": group_id or parsed["group_id"],
            "display_badge": parsed["display_badge"],
            "last_active": now_str,
            "source": "实时监听",
        }

    # --------------------------------------------------------------------------
    # LLM Request Context Injection
    # --------------------------------------------------------------------------

    async def inject_prompt_context(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> bool:
        """Check if current event's UMO matches any prompt rule, and inject it into LLM request.

        Returns:
            bool: True if a rule was matched and injected, False otherwise.
        """
        # Always observe incoming UMO for discovery
        self.observe_event(event)

        if not self.enabled:
            return False

        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo:
            return False

        rule = self._rules.get(umo)
        if not rule or not rule.enabled or not rule.prompt.strip():
            return False

        prompt_text = rule.prompt.strip()
        mode = rule.inject_mode or self.default_inject_mode

        if mode == "extra_user_content":
            if hasattr(req, "extra_user_content_parts"):
                req.extra_user_content_parts.append(TextPart(text=prompt_text))
            else:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + prompt_text
        elif mode == "prepend_system":
            req.system_prompt = prompt_text + "\n\n" + (req.system_prompt or "")
        else:
            # Default: append to system_prompt
            req.system_prompt = (req.system_prompt or "") + "\n\n" + prompt_text

        astrbot_logger.info(
            f"{LOG_TAG} 匹配到专属提示词规则【{rule.name}】(UMO: {umo})，已成功注入 {len(prompt_text)} 字提示词（模式: {mode}）"
        )
        return True

    # --------------------------------------------------------------------------
    # Discover Conversations from AstrBot
    # --------------------------------------------------------------------------

    async def _fetch_umo_aliases_from_db(self, umos: List[str]) -> Dict[str, Dict[str, str]]:
        """Fetch auto_name (group name or sender nickname) and user_alias from AstrBot's DB."""
        alias_data: Dict[str, Dict[str, str]] = {}

        # 1. Try context.db or db_helper
        try:
            db_helper = getattr(self.context, "db", None)
            if not db_helper:
                core_life = getattr(self.context, "_core_lifecycle", None)
                if core_life:
                    db_helper = getattr(core_life, "db", None) or getattr(core_life, "db_helper", None)

            if db_helper and hasattr(db_helper, "get_umo_aliases"):
                fn = getattr(db_helper, "get_umo_aliases")
                if callable(fn):
                    res = fn(umos if umos else None)
                    if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                        aliases = await res
                        for a in aliases:
                            u = str(getattr(a, "umo", "") or "").strip()
                            if u:
                                alias_data[u] = {
                                    "auto_name": str(getattr(a, "auto_name", "") or "").strip(),
                                    "user_alias": str(getattr(a, "user_alias", "") or "").strip(),
                                }
                        if alias_data:
                            return alias_data
        except Exception as e:
            self.logger.debug("Failed to query get_umo_aliases via db_helper: %s", e)

        # 2. Try direct sqlite query on data/astrbot.db
        db_path = Path("data/astrbot.db")
        if db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT umo, auto_name, user_alias FROM umo_aliases")
                rows = cursor.fetchall()
                conn.close()
                for row in rows:
                    u = str(row[0] or "").strip()
                    if u:
                        alias_data[u] = {
                            "auto_name": str(row[1] or "").strip(),
                            "user_alias": str(row[2] or "").strip(),
                        }
            except Exception as e:
                self.logger.debug("Direct sqlite query on umo_aliases failed: %s", e)

        return alias_data

    async def discover_conversations(self) -> List[Dict[str, Any]]:
        """Fetch conversations from AstrBot's '数据与日志-对话' and merge with observed ones.

        Resolves:
            - Group chats: UMO and 群名称 (group name)
            - Private chats: UMO and 对话人昵称 (sender nickname)
        """
        discovered: Dict[str, Dict[str, Any]] = {}

        # 1. Attempt to fetch from AstrBot's ConversationManager
        try:
            conv_mgr = getattr(self.context, "conversation_manager", None)
            if conv_mgr and hasattr(conv_mgr, "get_filtered_conversations"):
                fn = getattr(conv_mgr, "get_filtered_conversations")
                if callable(fn):
                    res = fn(
                        page=1,
                        page_size=200,
                        include_history=False,
                    )
                    if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                        convs, _ = await res
                        for conv in convs:
                            u = str(getattr(conv, "user_id", "") or "").strip()
                            if not u:
                                continue
                            parsed = parse_umo_details(u)
                            t_title = str(getattr(conv, "title", "") or "").strip()
                            ts = getattr(conv, "updated_at", 0)
                            time_str = ""
                            if ts and isinstance(ts, (int, float)) and ts > 0:
                                try:
                                    time_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                                except Exception:
                                    time_str = str(ts)

                            discovered[u] = {
                                "umo": u,
                                "raw_title": t_title,
                                "platform": parsed["platform"],
                                "platform_name_cn": parsed["platform_name_cn"],
                                "chat_type": parsed["chat_type"],
                                "chat_type_text": parsed["chat_type_text"],
                                "target_id": parsed["target_id"],
                                "group_id": parsed["group_id"],
                                "last_active": time_str or "历史记录",
                                "source": "AstrBot 对话数据库",
                            }
        except Exception as e:
            astrbot_logger.warning(f"{LOG_TAG} 通过 conversation_manager 获取会话历史异常: {e}")

        # 2. Attempt direct SQLite query on data/astrbot.db if available
        db_path = Path("data/astrbot.db")
        if db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT DISTINCT user_id, platform_id, title, updated_at "
                    "FROM conversations "
                    "ORDER BY updated_at DESC LIMIT 150"
                )
                rows = cursor.fetchall()
                conn.close()

                for row in rows:
                    u = str(row[0] or "").strip()
                    if not u:
                        continue
                    if u not in discovered:
                        parsed = parse_umo_details(u)
                        t_title = str(row[2] or "").strip()
                        raw_time = row[3]
                        time_str = str(raw_time) if raw_time else "历史记录"

                        discovered[u] = {
                            "umo": u,
                            "raw_title": t_title,
                            "platform": parsed["platform"],
                            "platform_name_cn": parsed["platform_name_cn"],
                            "chat_type": parsed["chat_type"],
                            "chat_type_text": parsed["chat_type_text"],
                            "target_id": parsed["target_id"],
                            "group_id": parsed["group_id"],
                            "last_active": time_str,
                            "source": "AstrBot 数据库",
                        }
                    elif not discovered[u].get("raw_title") and row[2]:
                        discovered[u]["raw_title"] = str(row[2]).strip()
            except Exception as e:
                self.logger.debug("Direct sqlite query on conversations failed: %s", e)

        # 3. Query umo_aliases table to get official auto_name (群名称/对话人昵称) and user_alias
        all_umos = list(discovered.keys()) + list(self._observed_umos.keys())
        alias_map = await self._fetch_umo_aliases_from_db(all_umos)

        # 4. Merge in-memory observed UMOs
        for u, info in self._observed_umos.items():
            if u not in discovered:
                discovered[u] = {
                    "umo": u,
                    "raw_title": info.get("title", ""),
                    "platform": info.get("platform", "unknown"),
                    "platform_name_cn": info.get("platform_name_cn", "未知"),
                    "chat_type": info.get("chat_type", "unknown"),
                    "chat_type_text": info.get("chat_type_text", "未知"),
                    "target_id": info.get("target_id", ""),
                    "group_id": info.get("group_id", ""),
                    "last_active": info.get("last_active", "实时活跃"),
                    "source": "实时监听",
                }
            else:
                if info.get("last_active"):
                    discovered[u]["last_active"] = info["last_active"]
                if not discovered[u].get("raw_title") and info.get("title"):
                    discovered[u]["raw_title"] = info["title"]

        # 5. Build final formatted items with resolved chat_name (群名称或私聊人昵称)
        result: List[Dict[str, Any]] = []
        for u, item in discovered.items():
            parsed = parse_umo_details(u)
            alias_entry = alias_map.get(u, {})
            auto_name = alias_entry.get("auto_name", "").strip()
            user_alias = alias_entry.get("user_alias", "").strip()
            raw_title = item.get("raw_title", "").strip()

            # Determine best human-readable name:
            # 群聊 -> 群名称 (例如 "AstrBot 官方交流群")
            # 私聊 -> 对话人昵称 (例如 "张三")
            chat_name = user_alias or auto_name or raw_title
            if not chat_name or chat_name == u:
                if item["chat_type"] == "group":
                    chat_name = f"群聊 ({item['group_id'] or parsed['target_id']})"
                elif item["chat_type"] == "private":
                    chat_name = f"私聊用户 ({parsed['target_id']})"
                else:
                    chat_name = parsed["display_badge"]

            item["chat_name"] = chat_name
            item["auto_name"] = auto_name
            item["user_alias"] = user_alias
            item["display_badge"] = parsed["display_badge"]

            # Annotate with rule status
            rule = self._rules.get(u)
            item["has_rule"] = rule is not None
            item["rule_enabled"] = rule.enabled if rule else False
            item["rule_name"] = rule.name if rule else ""
            item["rule_prompt_preview"] = (rule.prompt[:60] + "...") if (rule and len(rule.prompt) > 60) else (rule.prompt if rule else "")
            item["rule_inject_mode"] = rule.inject_mode if rule else "system_prompt"

            result.append(item)

        # Sort: configured rules first, then by last_active descending
        result.sort(key=lambda x: (not x["has_rule"], x.get("last_active", "")), reverse=False)
        astrbot_logger.info(
            f"{LOG_TAG} 成功从 AstrBot '数据与日志-对话' 及别名表中抓取并识别出 {len(result)} 个会话（解析群名称与对话人昵称完成）"
        )
        return result

    # --------------------------------------------------------------------------
    # Persistence
    # --------------------------------------------------------------------------

    def _load_from_storage(self) -> None:
        """Read saved rules from local JSON file."""
        if not self._storage_path.exists():
            # Check if initial rules exist in plugin config
            cfg_rules = self.get_config_val("umo_prompt_rules")
            if isinstance(cfg_rules, list):
                for item in cfg_rules:
                    if isinstance(item, dict) and item.get("umo"):
                        rule = UmoPromptRule.from_dict(item)
                        self._rules[rule.umo] = rule
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("umo"):
                            rule = UmoPromptRule.from_dict(item)
                            self._rules[rule.umo] = rule
                elif isinstance(data, dict):
                    for _, item in data.items():
                        if isinstance(item, dict) and item.get("umo"):
                            rule = UmoPromptRule.from_dict(item)
                            self._rules[rule.umo] = rule
        except Exception as e:
            astrbot_logger.warning(f"{LOG_TAG} 读取提示词规则存储异常: {e}")

    def _save_to_storage(self) -> None:
        """Persist rules to disk and sync with config."""
        try:
            data = [rule.to_dict() for rule in self._rules.values()]
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Sync to AstrBot plugin config
            self.config["umo_prompt_rules"] = data
            if hasattr(self.config, "save_config"):
                try:
                    self.config.save_config()
                except Exception as e:
                    self.logger.warning("Failed to invoke save_config(): %s", e)
        except Exception as e:
            astrbot_logger.error(f"{LOG_TAG} 保存提示词规则异常: {e}", exc_info=True)

    # --------------------------------------------------------------------------
    # Rule Management (CRUD)
    # --------------------------------------------------------------------------

    def get_all_rules(self) -> List[Dict[str, Any]]:
        """Return list of all configured UMO prompt rules."""
        return [rule.to_dict() for rule in self._rules.values()]

    def get_rule(self, umo: str) -> Optional[UmoPromptRule]:
        """Get single rule by UMO."""
        return self._rules.get(str(umo).strip())

    def save_rule(self, rule_data: Dict[str, Any]) -> UmoPromptRule:
        """Save or update a UMO prompt rule."""
        umo = str(rule_data.get("umo", "")).strip()
        if not umo:
            raise ValueError("UMO 不能为空")

        existing = self._rules.get(umo)
        now_str = datetime.datetime.now().isoformat()

        rule = UmoPromptRule(
            umo=umo,
            name=str(rule_data.get("name") or (existing.name if existing else "")).strip(),
            prompt=str(rule_data.get("prompt", "")).strip(),
            enabled=bool(rule_data.get("enabled", True)),
            inject_mode=str(rule_data.get("inject_mode") or self.default_inject_mode).strip(),
            group_id=str(rule_data.get("group_id", "")).strip(),
            chat_type=str(rule_data.get("chat_type", "")).strip(),
            platform=str(rule_data.get("platform", "")).strip(),
            created_at=existing.created_at if existing else now_str,
            updated_at=now_str,
        )

        self._rules[umo] = rule
        self._save_to_storage()
        astrbot_logger.info(
            f"{LOG_TAG} 成功保存会话专属提示词规则: 【{rule.name}】(UMO: {umo}, 提示词字数: {len(rule.prompt)}, 状态: {'启用' if rule.enabled else '禁用'})"
        )
        return rule

    def delete_rule(self, umo: str) -> bool:
        """Delete a UMO prompt rule."""
        umo_str = str(umo).strip()
        if umo_str in self._rules:
            deleted = self._rules.pop(umo_str)
            self._save_to_storage()
            astrbot_logger.info(f"{LOG_TAG} 已删除会话专属提示词规则: 【{deleted.name}】(UMO: {umo_str})")
            return True
        return False

    def toggle_rule(self, umo: str, enabled: Optional[bool] = None) -> bool:
        """Toggle or explicitly set enabled status for a rule."""
        umo_str = str(umo).strip()
        rule = self._rules.get(umo_str)
        if not rule:
            return False

        if enabled is None:
            rule.enabled = not rule.enabled
        else:
            rule.enabled = bool(enabled)

        rule.updated_at = datetime.datetime.now().isoformat()
        self._save_to_storage()
        astrbot_logger.info(
            f"{LOG_TAG} 切换会话规则【{rule.name}】状态 -> {'启用' if rule.enabled else '禁用'}"
        )
        return rule.enabled
