from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

try:
    from astrbot.api import logger as astrbot_logger
except Exception:
    import logging as _logging
    astrbot_logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[拟人化日程]"

try:
    from astrbot.core.agent.message import TextPart
except Exception:
    class TextPart:  # type: ignore
        """Fallback TextPart representation when AstrBot core is not in local Python environment."""

        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text
try:
    from ..base import BaseFeatureModule
    from ...utils.time_utils import (
        get_current_time_str,
        get_today_str,
        get_weekday_cn,
        parse_time_str,
        seconds_until_next_run,
        time_to_minutes,
    )
except (ImportError, ValueError):
    from modules.base import BaseFeatureModule
    from utils.time_utils import (
        get_current_time_str,
        get_today_str,
        get_weekday_cn,
        parse_time_str,
        seconds_until_next_run,
        time_to_minutes,
    )
from .model import DailySchedule, DailyScheduleItem, ScheduleSegment
from .prompt import (
    build_schedule_generation_prompt,
    format_injected_schedule_context,
    parse_schedule_llm_response,
)

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest
    from astrbot.api.star import Context
    from astrbot.core.config.astrbot_config import AstrBotConfig

DEFAULT_SEGMENTS = [
    {
        "id": "morning_early",
        "name": "清晨苏醒与晨练",
        "start": "06:00",
        "end": "08:30",
    },
    {
        "id": "morning_work",
        "name": "上午工作/学习",
        "start": "08:30",
        "end": "12:00",
    },
    {
        "id": "lunch_rest",
        "name": "午休与用餐",
        "start": "12:00",
        "end": "14:00",
    },
    {
        "id": "afternoon_work",
        "name": "下午工作/日常",
        "start": "14:00",
        "end": "18:00",
    },
    {
        "id": "evening_leisure",
        "name": "傍晚娱乐与晚餐",
        "start": "18:00",
        "end": "22:00",
    },
    {
        "id": "night_sleep",
        "name": "夜间就寝休息",
        "start": "22:00",
        "end": "06:00",
    },
]


class ScheduleManager(BaseFeatureModule):
    """Manages the personated daily schedule system.

    Handles scheduled daily generation, LLM provider fallback, persona retrieval,
    local JSON persistence, and prompt injection into active conversation requests.
    """

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict,
        logger: logging.Logger,
    ) -> None:
        super().__init__(context, config, logger)

        self._scheduler_task: Optional[asyncio.Task] = None
        self._current_schedule: Optional[DailySchedule] = None
        self._schedules_history: Dict[str, dict] = {}
        self._storage_path: Path = self._resolve_storage_path()
        self._lock = asyncio.Lock()

    def _resolve_storage_path(self) -> Path:
        """Resolve the storage directory under AstrBot plugin_data."""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            base_data = Path(get_astrbot_data_path())
        except Exception:
            base_data = Path("data")

        plugin_data_dir = base_data / "plugin_data" / "astrbot_plugin_personated"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        return plugin_data_dir / "daily_schedules.json"

    # --------------------------------------------------------------------------
    # Configuration getters
    # --------------------------------------------------------------------------

    @property
    def daily_generate_time(self) -> str:
        """HH:MM time string for daily schedule generation."""
        val = str(self.get_config_val("daily_generate_time", "04:00")).strip()
        try:
            parse_time_str(val)
            return val
        except ValueError:
            self.logger.warning(
                "Invalid daily_generate_time '%s' in config; falling back to '04:00'",
                val,
            )
            return "04:00"

    @property
    def schedule_provider_id(self) -> str:
        """Designated LLM provider ID for schedule generation, if any."""
        return str(self.get_config_val("schedule_provider_id", "")).strip()

    @property
    def inject_context_enabled(self) -> bool:
        """Whether to inject active schedule into LLM conversation context."""
        return bool(self.get_config_val("inject_context_enabled", True))

    @property
    def inject_mode(self) -> str:
        """Context injection mode: 'extra_user_content' or 'system_prompt'."""
        mode = str(self.get_config_val("inject_mode", "extra_user_content")).strip()
        return mode if mode in ["extra_user_content", "system_prompt"] else "extra_user_content"

    @property
    def schedule_segments(self) -> List[ScheduleSegment]:
        """Parsed list of configured daily ScheduleSegments."""
        raw_list = self.get_config_val("schedule_segments", DEFAULT_SEGMENTS)
        if not isinstance(raw_list, list) or len(raw_list) == 0:
            raw_list = DEFAULT_SEGMENTS

        segments: List[ScheduleSegment] = []
        for item in raw_list:
            if isinstance(item, dict):
                try:
                    seg = ScheduleSegment.from_dict(item)
                    # Validate start and end time format
                    parse_time_str(seg.start)
                    parse_time_str(seg.end)
                    segments.append(seg)
                except Exception as e:
                    self.logger.warning("Skipping invalid segment definition %r: %s", item, e)

        if not segments:
            segments = [ScheduleSegment.from_dict(item) for item in DEFAULT_SEGMENTS]

        return segments

    @property
    def custom_prompt_template(self) -> str:
        """Custom prompt template for schedule generation, if configured."""
        tmpl = self.get_config_val("custom_prompt_template")
        if tmpl and isinstance(tmpl, str) and tmpl.strip():
            return tmpl.strip()
        return ""

    # --------------------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the schedule manager and start the background scheduler."""
        self._load_from_storage()

        # Check if today's schedule is missing and past generation time
        today_str = get_today_str()
        if today_str in self._schedules_history:
            try:
                self._current_schedule = DailySchedule.from_dict(
                    self._schedules_history[today_str]
                )
                astrbot_logger.info(
                    f"{LOG_TAG} 成功加载今日（{today_str}）已存日程，共 {len(self._current_schedule.items)} 个时段"
                )
            except Exception as e:
                astrbot_logger.warning(f"{LOG_TAG} 从缓存恢复今日日程失败: {e}")

        # Start background timer task
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(),
            name="personated_schedule_timer",
        )
        astrbot_logger.info(
            f"{LOG_TAG} 日程后台调度器已启动。每日自动生成时刻: {self.daily_generate_time}，划分时段数: {len(self.schedule_segments)}"
        )

    async def terminate(self) -> None:
        """Stop background tasks and clean up resources."""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        astrbot_logger.info(f"{LOG_TAG} 日程管理器后台任务已停止。")

    # --------------------------------------------------------------------------
    # Background Scheduler Loop
    # --------------------------------------------------------------------------

    async def _scheduler_loop(self) -> None:
        """Continuous background loop triggering daily schedule generation."""
        # Initial check on startup: if today's schedule is missing and current time >= daily_generate_time
        try:
            await asyncio.sleep(2.0)  # Brief pause to let AstrBot core finish initialization
            now = datetime.datetime.now()
            today_str = get_today_str(now)
            gen_time = parse_time_str(self.daily_generate_time)

            now_minutes = time_to_minutes(now.time())
            gen_minutes = time_to_minutes(gen_time)

            if today_str not in self._schedules_history and now_minutes >= gen_minutes:
                astrbot_logger.info(
                    f"{LOG_TAG} 启动检查: 今日（{today_str}）尚未生成日程且已过生成时刻 {self.daily_generate_time}，立即触发生成..."
                )
                await self.generate_today_schedule(force=False)
        except asyncio.CancelledError:
            return
        except Exception as e:
            astrbot_logger.error(f"{LOG_TAG} 启动检查异常: {e}", exc_info=True)

        while True:
            try:
                wait_seconds = seconds_until_next_run(self.daily_generate_time)
                astrbot_logger.info(
                    f"{LOG_TAG} 计划任务休眠中：距离下次日程自动生成（{self.daily_generate_time}）还有约 {wait_seconds / 3600.0:.1f} 小时 ({int(wait_seconds)} 秒)"
                )
                await asyncio.sleep(wait_seconds)

                # Time reached, generate today's schedule
                astrbot_logger.info(f"{LOG_TAG} 触发定时任务：到达每日时刻 {self.daily_generate_time}，正在生成今日作息...")
                await self.generate_today_schedule(force=True)

                # Sleep 60 seconds to ensure we do not re-trigger within the same minute
                await asyncio.sleep(60.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                astrbot_logger.error(f"{LOG_TAG} 调度循环出现异常: {e}，60秒后自动重试", exc_info=True)
                await asyncio.sleep(60.0)

    # --------------------------------------------------------------------------
    # Persistence
    # --------------------------------------------------------------------------

    def _load_from_storage(self) -> None:
        """Read saved schedules from disk."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._schedules_history = data
        except Exception as e:
            self.logger.warning("Failed to load schedules storage from %s: %s", self._storage_path, e)

    def _save_to_storage(self) -> None:
        """Persist schedules to disk."""
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(self._schedules_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error("Failed to write schedules to %s: %s", self._storage_path, e)

    # --------------------------------------------------------------------------
    # Persona & Model Resolution
    # --------------------------------------------------------------------------

    async def get_persona_prompt(self, umo: str = "") -> tuple[str, str]:
        """Retrieve active persona prompt and persona ID.

        Returns:
            tuple (persona_id, persona_prompt_text)
        """
        persona_id = "default"
        prompt_text = ""

        try:
            if hasattr(self.context, "persona_manager") and self.context.persona_manager:
                pm = self.context.persona_manager
                # Attempt to get default persona
                persona = None
                if hasattr(pm, "get_default_persona_v3"):
                    persona = await pm.get_default_persona_v3(umo=umo)

                if persona:
                    persona_id = str(persona.get("name") or persona.get("persona_id") or "default")
                    prompt_text = str(
                        persona.get("prompt")
                        or persona.get("system_prompt")
                        or ""
                    )
        except Exception as e:
            self.logger.warning("Failed to resolve persona from persona_manager: %s", e)

        if not prompt_text:
            prompt_text = "你是一个亲切、真诚、善解人意且拥有丰富生活细节的伙伴。"

        return persona_id, prompt_text

    async def resolve_provider_id(self, umo: str = "") -> str:
        """Resolve the LLM provider ID: designated provider or fallback to conversation provider."""
        designated = self.schedule_provider_id
        if designated:
            # Check if designated provider actually exists
            try:
                prov = await self.context.provider_manager.get_provider_by_id(designated)
                if prov is not None:
                    return designated
                else:
                    self.logger.warning(
                        "Designated schedule provider '%s' not found. Falling back...",
                        designated,
                    )
            except Exception as e:
                self.logger.warning("Error looking up provider '%s': %s", designated, e)

        # Fallback: conversation's active chat provider
        try:
            if hasattr(self.context, "get_current_chat_provider_id"):
                chat_id = await self.context.get_current_chat_provider_id(umo)
                if chat_id:
                    return chat_id
        except Exception as e:
            self.logger.warning("Failed to get current chat provider id: %s", e)

        # Fallback: scan available providers in provider_manager
        try:
            pm = self.context.provider_manager
            if hasattr(pm, "providers") and pm.providers:
                # Pick first active chat provider
                for pid, p in pm.providers.items():
                    return pid
        except Exception:
            pass

        return ""

    # --------------------------------------------------------------------------
    # Schedule Generation
    # --------------------------------------------------------------------------

    async def generate_today_schedule(
        self,
        force: bool = False,
        dt: datetime.datetime | None = None,
        umo: str = "",
    ) -> DailySchedule:
        """Generate today's schedule using the resolved LLM provider and persona."""
        async with self._lock:
            if dt is None:
                dt = datetime.datetime.now()

            date_str = get_today_str(dt)
            weekday_str = get_weekday_cn(dt)

            if not force and date_str in self._schedules_history:
                try:
                    self._current_schedule = DailySchedule.from_dict(
                        self._schedules_history[date_str]
                    )
                    return self._current_schedule
                except Exception:
                    pass

            segments = self.schedule_segments
            persona_id, persona_prompt = await self.get_persona_prompt(umo)
            provider_id = await self.resolve_provider_id(umo)

            if not provider_id:
                astrbot_logger.warning(f"{LOG_TAG} 未检测到可用的 LLM 模型提供者，使用保底模板生成日程")
                fallback = self._create_fallback_schedule(
                    date_str, weekday_str, persona_id, segments
                )
                self._current_schedule = fallback
                self._schedules_history[date_str] = fallback.to_dict()
                self._save_to_storage()
                return fallback

            sys_prompt, user_prompt = build_schedule_generation_prompt(
                persona_prompt=persona_prompt,
                segments=segments,
                dt=dt,
                template=self.custom_prompt_template,
            )

            astrbot_logger.info(
                f"{LOG_TAG} 正在请求大模型 [{provider_id}] 为今日（{date_str}）生成拟人化日程（当前人设: {persona_id}）..."
            )

            try:
                llm_resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=user_prompt,
                    system_prompt=sys_prompt,
                )

                response_text = llm_resp.completion_text if hasattr(llm_resp, "completion_text") else str(llm_resp)
                schedule = parse_schedule_llm_response(
                    raw_response=response_text,
                    segments=segments,
                    date_str=date_str,
                    weekday_str=weekday_str,
                    persona_id=persona_id,
                    provider_used=provider_id,
                )

                self._current_schedule = schedule
                self._schedules_history[date_str] = schedule.to_dict()
                self._save_to_storage()

                astrbot_logger.info(
                    f"{LOG_TAG} 今日（{date_str}）日程已成功生成并持久化！共 {len(schedule.items)} 个时段，模型: {provider_id}"
                )
                return schedule

            except Exception as e:
                astrbot_logger.error(f"{LOG_TAG} 大模型生成今日日程异常: {e}，启用拟人化默认保底作息模板", exc_info=True)
                fallback = self._create_fallback_schedule(
                    date_str, weekday_str, persona_id, segments
                )
                self._current_schedule = fallback
                self._schedules_history[date_str] = fallback.to_dict()
                self._save_to_storage()
                return fallback

    def _create_fallback_schedule(
        self,
        date_str: str,
        weekday_str: str,
        persona_id: str,
        segments: List[ScheduleSegment],
    ) -> DailySchedule:
        """Create a reasonable default fallback schedule when LLM generation is unavailable."""
        items: List[DailyScheduleItem] = []
        for seg in segments:
            items.append(
                DailyScheduleItem(
                    id=seg.id,
                    name=seg.name,
                    start=seg.start,
                    end=seg.end,
                    activity=f"正处于【{seg.name}】时段，处理相关事务与日常休闲",
                    state="精神状态良好，自然平和",
                )
            )
        return DailySchedule(
            date=date_str,
            weekday=weekday_str,
            persona_id=persona_id,
            generated_at=datetime.datetime.now().isoformat(),
            provider_used="fallback_default",
            items=items,
        )

    # --------------------------------------------------------------------------
    # Context Injection
    # --------------------------------------------------------------------------

    async def inject_schedule_context(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
        dt: Optional[datetime.datetime] = None,
    ) -> None:
        """Inject the current matching schedule item into the LLM conversation request.

        Args:
            event: The incoming message event.
            req: ProviderRequest being assembled.
            dt: Optional explicit datetime, defaults to current system time.
        """
        if not self.inject_context_enabled:
            return

        now = dt if dt is not None else datetime.datetime.now()
        today_str = get_today_str(now)

        # Check if we have today's schedule ready
        if self._current_schedule is None or self._current_schedule.date != today_str:
            if today_str in self._schedules_history:
                try:
                    self._current_schedule = DailySchedule.from_dict(
                        self._schedules_history[today_str]
                    )
                except Exception:
                    pass

            if self._current_schedule is None or self._current_schedule.date != today_str:
                # Lazy generate
                umo = getattr(event, "unified_msg_origin", "")
                await self.generate_today_schedule(force=False, dt=now, umo=umo)

        if not self._current_schedule:
            return

        active_item = self._current_schedule.find_active_item(now.time())
        if not active_item:
            return

        current_time_str = get_current_time_str(now)
        weekday_str = get_weekday_cn(now)

        injected_text = format_injected_schedule_context(
            item=active_item,
            current_time_str=current_time_str,
            date_str=today_str,
            weekday_str=weekday_str,
        )

        if self.inject_mode == "extra_user_content":
            # Append as TextPart into extra_user_content_parts (recommended)
            if hasattr(req, "extra_user_content_parts"):
                req.extra_user_content_parts.append(TextPart(text=injected_text))
            else:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + injected_text
        else:
            # Append to system_prompt
            req.system_prompt = (req.system_prompt or "") + "\n\n" + injected_text

        astrbot_logger.info(
            f"{LOG_TAG} 对话时段匹配成功，已注入拟人化状态 -> 【{active_item.name}】活动: {active_item.activity} | 心情: {active_item.state} (模式: {self.inject_mode})"
        )

    # --------------------------------------------------------------------------
    # Status & Inspection Helpers
    # --------------------------------------------------------------------------

    def get_status_info(self) -> dict:
        """Return diagnostic status information about the schedule system."""
        now = datetime.datetime.now()
        today_str = get_today_str(now)
        active_item = self._current_schedule.find_active_item(now.time()) if self._current_schedule else None

        return {
            "current_time": get_current_time_str(now),
            "date": today_str,
            "weekday": f"星期{get_weekday_cn(now)}",
            "daily_generate_time": self.daily_generate_time,
            "seconds_until_next_run": seconds_until_next_run(self.daily_generate_time, now),
            "schedule_provider_id": self.schedule_provider_id or "(自动回退对话模型)",
            "inject_context_enabled": self.inject_context_enabled,
            "inject_mode": self.inject_mode,
            "segments_count": len(self.schedule_segments),
            "today_generated": self._current_schedule is not None and self._current_schedule.date == today_str,
            "active_segment": active_item.to_dict() if active_item else None,
            "today_schedule": self._current_schedule.to_dict() if self._current_schedule else None,
        }

    # --------------------------------------------------------------------------
    # Date-based Schedule CRUD Operations
    # --------------------------------------------------------------------------

    def get_available_dates(self) -> List[Dict[str, Any]]:
        """Return a sorted list of all dates that currently have saved schedules."""
        dates = []
        for d_str, data in sorted(self._schedules_history.items(), key=lambda x: x[0], reverse=True):
            if isinstance(data, dict):
                items = data.get("items", [])
                dates.append(
                    {
                        "date": d_str,
                        "weekday": data.get("weekday", ""),
                        "items_count": len(items) if isinstance(items, list) else 0,
                        "provider_used": data.get("provider_used", ""),
                        "generated_at": data.get("generated_at", ""),
                    }
                )
        return dates

    def get_schedule_by_date(self, date_str: str) -> Optional[DailySchedule]:
        """Retrieve a specific date's schedule."""
        if date_str in self._schedules_history:
            try:
                return DailySchedule.from_dict(self._schedules_history[date_str])
            except Exception as e:
                astrbot_logger.warning(f"{LOG_TAG} 解析日期 {date_str} 的日程存档失败: {e}")
        return None

    def save_schedule_for_date(self, schedule: DailySchedule) -> None:
        """Persist or update a schedule for a specific date."""
        self._schedules_history[schedule.date] = schedule.to_dict()
        if schedule.date == get_today_str():
            self._current_schedule = schedule
        self._save_to_storage()
        astrbot_logger.info(f"{LOG_TAG} 日程数据持久化保存成功 (日期: {schedule.date}, 时段数: {len(schedule.items)})")

    def delete_schedule_for_date(self, date_str: str) -> bool:
        """Delete a saved schedule for a specific date."""
        if date_str in self._schedules_history:
            del self._schedules_history[date_str]
            if self._current_schedule and self._current_schedule.date == date_str:
                self._current_schedule = None
            self._save_to_storage()
            astrbot_logger.info(f"{LOG_TAG} 已删除日期 {date_str} 的日程存档")
            return True
        return False

    async def generate_schedule_for_date(
        self,
        date_str: str,
        force: bool = True,
        umo: str = "",
    ) -> DailySchedule:
        """Generate a schedule for a specified date (past, today, or future)."""
        try:
            target_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            target_dt = datetime.datetime.now()

        astrbot_logger.info(f"{LOG_TAG} 开始为指定日期（{date_str}）生成拟人化日程...")
        return await self.generate_today_schedule(force=force, dt=target_dt, umo=umo)
