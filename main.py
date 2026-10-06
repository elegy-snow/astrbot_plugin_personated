from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Ensure the plugin directory is in sys.path for robust resolution in all loader modes
_plugin_dir = str(Path(__file__).resolve().parent)
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

try:
    from astrbot.api import logger
except Exception:
    import logging as _logging
    logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[拟人化日程]"

try:
    from .modules.schedule.manager import ScheduleManager
    from .modules.schedule.web_api import ScheduleWebApi
    from .utils.time_utils import get_current_time_str, get_today_str, get_weekday_cn
except (ImportError, ValueError):
    from modules.schedule.manager import ScheduleManager
    from modules.schedule.web_api import ScheduleWebApi
    from utils.time_utils import get_current_time_str, get_today_str, get_weekday_cn

if TYPE_CHECKING:
    from astrbot.core.config.astrbot_config import AstrBotConfig


class PersonatedPlugin(Star):
    """拟人化综合伴侣插件 (Personated Companion Plugin)

    功能集合插件：
    - 拟人化日程系统：每日定时根据人设生成作息日程，并在相应时段内将实时状态自然注入到每次对话中。
    - 预留后续扩展模块接口。
    """

    def __init__(self, context: Context, config: AstrBotConfig | dict) -> None:
        super().__init__(context, config)
        self.config = config
        logger.info(f"{LOG_TAG} 插件开始实例化并加载配置...")
        self.schedule_manager = ScheduleManager(self.context, self.config, self.logger)
        self.web_api = ScheduleWebApi(self.schedule_manager, self.logger)
        self.web_api.register_routes(self.context)

    async def initialize(self) -> None:
        """插件初始化，加载模块与启动定时任务。"""
        logger.info(f"{LOG_TAG} 正在启动拟人化日程后台服务与调度器...")
        await self.schedule_manager.initialize()
        logger.info(f"{LOG_TAG} 插件服务初始化完成，当前处于就绪状态。")

    async def terminate(self) -> None:
        """插件卸载/重载清理。"""
        logger.info(f"{LOG_TAG} 正在卸载插件并停止后台定时任务...")
        await self.schedule_manager.terminate()
        logger.info(f"{LOG_TAG} 插件已安全卸载。")

    # --------------------------------------------------------------------------
    # LLM 请求拦截钩子：动态注入日程状态
    # --------------------------------------------------------------------------

    @filter.on_llm_request()
    async def on_llm_request_hook(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """在调用大模型前，将角色当前时段的日程及状态注入到请求上下文中。"""
        try:
            await self.schedule_manager.inject_schedule_context(event, req)
        except Exception as e:
            logger.error(f"{LOG_TAG} 注入日程状态异常: {e}", exc_info=True)

    # --------------------------------------------------------------------------
    # 指令组：日程管理交互
    # --------------------------------------------------------------------------

    @filter.command_group("schedule", alias={"日程"})
    def schedule_group():
        """拟人化日程管理指令组"""
        pass

    @schedule_group.command("view", alias={"查看"})
    async def view_schedule(self, event: AstrMessageEvent) -> None:
        """查看今日日程列表与当前活动状态"""
        now = datetime.datetime.now()
        today_str = get_today_str(now)
        time_str = get_current_time_str(now)
        weekday_str = get_weekday_cn(now)
        logger.info(f"{LOG_TAG} 用户触发指令 /schedule view (日期: {today_str})")

        schedule = self.schedule_manager._current_schedule
        if not schedule or schedule.date != today_str:
            # 尝试即时生成
            logger.info(f"{LOG_TAG} 今日日程不存在，通过查看指令触发即时生成...")
            yield event.plain_result(f"正在为今日（{today_str}）生成日程，请稍候...")
            umo = getattr(event, "unified_msg_origin", "")
            schedule = await self.schedule_manager.generate_today_schedule(force=False, dt=now, umo=umo)

        if not schedule or not schedule.items:
            logger.warning(f"{LOG_TAG} 今日日程尚未生成，提示用户手动刷新")
            yield event.plain_result(f"今日（{today_str}）尚未生成日程，可通过 `/schedule refresh` 手动触发生成。")
            return

        active_item = schedule.find_active_item(now.time())

        lines = [
            f"📅 【今日拟人化日程】",
            f"日期：{schedule.date} 星期{schedule.weekday}（当前时间：{time_str}）",
            f"人设：{schedule.persona_id} | 生成模型：{schedule.provider_used}",
            "━" * 20,
        ]

        for idx, item in enumerate(schedule.items, 1):
            is_current = active_item and active_item.id == item.id
            prefix = "👉 [当前] " if is_current else f"{idx}. "
            lines.append(f"{prefix}【{item.name}】({item.start} ~ {item.end})")
            lines.append(f"   活动：{item.activity}")
            lines.append(f"   状态：{item.state}")
            lines.append("")

        if active_item:
            lines.append(f"💡 当前正处于【{active_item.name}】，对话时会自动带入此状态。")
        else:
            lines.append("💡 当前时间暂未落在任何已定义的日程时间段内。")

        yield event.plain_result("\n".join(lines).strip())

    @schedule_group.command("refresh", alias={"重新生成", "刷新"})
    async def refresh_schedule(self, event: AstrMessageEvent) -> None:
        """立即重新生成今日的日程安排"""
        logger.info(f"{LOG_TAG} 用户触发指令 /schedule refresh，准备重新生成今日日程")
        yield event.plain_result("正在重新生成今日的拟人化日程，请稍候...")
        umo = getattr(event, "unified_msg_origin", "")
        schedule = await self.schedule_manager.generate_today_schedule(force=True, umo=umo)

        if schedule and schedule.items:
            now = datetime.datetime.now()
            active_item = schedule.find_active_item(now.time())
            active_desc = f"（当前时段：【{active_item.name}】 - {active_item.activity}）" if active_item else ""
            logger.info(f"{LOG_TAG} 用户指令刷新日程成功，生成了 {len(schedule.items)} 个时段")
            yield event.plain_result(
                f"✅ 今日日程重新生成成功！共生成 {len(schedule.items)} 个时段安排。\n"
                f"{active_desc}\n"
                f"输入 `/schedule view` 可查看完整日程详情。"
            )
        else:
            logger.error(f"{LOG_TAG} 用户指令刷新日程失败")
            yield event.plain_result("❌ 日程生成失败，请检查模型连接与 AstrBot 日志。")

    @schedule_group.command("status", alias={"状态"})
    async def status_schedule(self, event: AstrMessageEvent) -> None:
        """查看日程系统运行状态与配置"""
        logger.info(f"{LOG_TAG} 用户触发指令 /schedule status 查看运行状态")
        status = self.schedule_manager.get_status_info()
        next_hours = status["seconds_until_next_run"] / 3600.0

        active_str = "无"
        if status["active_segment"]:
            seg = status["active_segment"]
            active_str = f"【{seg['name']}】({seg['start']} ~ {seg['end']}) - {seg['activity']}"

        msg = (
            f"⚙️ 【日程系统运行状态】\n"
            f"当前时间：{status['date']} {status['weekday']} {status['current_time']}\n"
            f"每日生成时刻：{status['daily_generate_time']}（距下次触发约 {next_hours:.1f} 小时）\n"
            f"指定生成模型：{status['schedule_provider_id']}\n"
            f"对话上下文注入：{'已启用' if status['inject_context_enabled'] else '已禁用'}（模式：{status['inject_mode']}）\n"
            f"已划分时间段数：{status['segments_count']} 个\n"
            f"今日日程状态：{'已就绪' if status['today_generated'] else '未就绪'}\n"
            f"当前生效活动：{active_str}"
        )
        yield event.plain_result(msg)

    @schedule_group.command("segments", alias={"时间段"})
    async def list_segments(self, event: AstrMessageEvent) -> None:
        """查看当前已配置的时间段列表"""
        logger.info(f"{LOG_TAG} 用户触发指令 /schedule segments 查看时间段划分")
        segments = self.schedule_manager.schedule_segments
        lines = [f"📋 【当前日程时间段划分（共 {len(segments)} 个）】："]
        for idx, seg in enumerate(segments, 1):
            lines.append(f"{idx}. ID: {seg.id}")
            lines.append(f"   名称: {seg.name}")
            lines.append(f"   范围: {seg.start} ~ {seg.end}")
        lines.append("\n可在插件可视化面板中自定义调整时间段与增减条目。")
        yield event.plain_result("\n".join(lines))
