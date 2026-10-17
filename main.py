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
    import astrbot.api.message_components as Comp
except Exception:
    try:
        import astrbot.core.message.components as Comp
    except Exception:
        Comp = None  # type: ignore

try:
    from astrbot.core.message.message_event_result import MessageChain
except Exception:
    MessageChain = None  # type: ignore

try:
    from astrbot.api import logger
except Exception:
    import logging as _logging
    logger = _logging.getLogger("astrbot.plugin.astrbot_plugin_personated")

LOG_TAG = "[拟人化日程]"

try:
    from .modules.schedule.manager import ScheduleManager
    from .modules.schedule.web_api import ScheduleWebApi
    from .modules.prompt_injector.manager import PromptInjectorManager
    from .modules.prompt_injector.web_api import PromptInjectorWebApi
    from .modules.nai_bridge.manager import NAIBridgeManager
    from .modules.nai_bridge.web_api import NAIBridgeWebApi
    from .utils.time_utils import get_current_time_str, get_today_str, get_weekday_cn
except (ImportError, ValueError):
    from modules.schedule.manager import ScheduleManager
    from modules.schedule.web_api import ScheduleWebApi
    from modules.prompt_injector.manager import PromptInjectorManager
    from modules.prompt_injector.web_api import PromptInjectorWebApi
    from modules.nai_bridge.manager import NAIBridgeManager
    from modules.nai_bridge.web_api import NAIBridgeWebApi
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
        # 1. 拟人化作息日程系统
        self.schedule_manager = ScheduleManager(self.context, self.config, self.logger)
        self.web_api = ScheduleWebApi(self.schedule_manager, self.logger)
        self.web_api.register_routes(self.context)

        # 2. 会话专属提示词注入系统 (特定群聊/私聊)
        self.prompt_injector_mgr = PromptInjectorManager(self.context, self.config, self.logger)
        self.prompt_injector_api = PromptInjectorWebApi(self.prompt_injector_mgr, self.logger)
        self.prompt_injector_api.register_routes(self.context)

        # 3. NAI 生图伴侣直连联动系统
        self.nai_manager = NAIBridgeManager(
            self.context, self.config, self.logger, schedule_manager=self.schedule_manager
        )
        self.nai_api = NAIBridgeWebApi(self.nai_manager, self.logger)
        self.nai_api.register_routes(self.context)

    async def initialize(self) -> None:
        """插件初始化，加载模块与启动定时任务。"""
        logger.info(f"{LOG_TAG} 正在启动拟人化日程后台服务与调度器...")
        await self.schedule_manager.initialize()
        await self.prompt_injector_mgr.initialize()
        logger.info(f"{LOG_TAG} 插件服务初始化完成，当前处于就绪状态。")

    async def terminate(self) -> None:
        """插件卸载/重载清理。"""
        logger.info(f"{LOG_TAG} 正在卸载插件并停止后台定时任务...")
        await self.schedule_manager.terminate()
        await self.prompt_injector_mgr.terminate()
        logger.info(f"{LOG_TAG} 插件已安全卸载。")

    # --------------------------------------------------------------------------
    # LLM 请求拦截钩子：动态注入日程状态与专属提示词
    # --------------------------------------------------------------------------

    @filter.on_llm_request()
    async def on_llm_request_hook(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """在调用大模型前，注入角色当前时段日程以及特定群聊/私聊的专属提示词。"""
        # 1. 注入当前时段日程与人设状态
        try:
            await self.schedule_manager.inject_schedule_context(event, req)
        except Exception as e:
            logger.error(f"{LOG_TAG} 注入日程状态异常: {e}", exc_info=True)

        # 2. 注入针对当前会话 (群聊/私聊 UMO) 的个性化专属提示词
        try:
            await self.prompt_injector_mgr.inject_prompt_context(event, req)
        except Exception as e:
            logger.error(f"[拟人化提示词] 注入会话专属提示词异常: {e}", exc_info=True)

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

    # --------------------------------------------------------------------------
    # 指令组：特定群聊/私聊专属提示词注入交互 (/umo)
    # --------------------------------------------------------------------------

    @filter.command_group("umo", alias={"会话提示词", "提示词注入", "umo_inject"})
    def umo_group():
        """特定群聊/私聊提示词注入管理指令组"""
        pass

    @umo_group.command("info", alias={"当前", "查看"})
    async def umo_info(self, event: AstrMessageEvent) -> None:
        """查看当前群聊/私聊的 UMO、会话标识与专属提示词配置"""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        self.prompt_injector_mgr.observe_event(event)

        from modules.prompt_injector.model import parse_umo_details
        parsed = parse_umo_details(umo)

        rule = self.prompt_injector_mgr.get_rule(umo)
        lines = [
            f"🏷️ 【当前会话专属信息】",
            f"会话类型：{parsed['chat_type_text']}",
            f"消息平台：{parsed['platform_name_cn']} ({parsed['platform']})",
            f"目标 ID：{parsed['target_id'] or '无'}" + (f"（群号: {parsed['group_id']}）" if parsed['group_id'] else ""),
            f"完整 UMO：{umo}",
            "━" * 20,
        ]

        if rule:
            status_text = "🟢 已启用" if rule.enabled else "🔴 已禁用"
            lines.append(f"规则名称：{rule.name}")
            lines.append(f"生效状态：{status_text}（注入模式: {rule.inject_mode}）")
            lines.append(f"专属提示词（共 {len(rule.prompt)} 字）：\n{rule.prompt}")
        else:
            lines.append("专属提示词：当前会话暂未配置专属提示词。")
            lines.append("💡 发送 `/umo set <提示词>` 可立即为当前会话设置个性化提示词。")

        logger.info(f"[拟人化提示词] 用户查询当前会话信息: UMO={umo}")
        yield event.plain_result("\n".join(lines))

    @umo_group.command("set", alias={"设置", "注入"})
    async def umo_set(self, event: AstrMessageEvent, prompt: str) -> None:
        """为当前群聊/私聊设置专属提示词：/umo set <提示词内容>"""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo:
            yield event.plain_result("❌ 无法获取当前会话的 UMO 标识。")
            return

        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            yield event.plain_result("❌ 提示词内容不能为空！用法：`/umo set <个性化提示词>`")
            return

        from modules.prompt_injector.model import parse_umo_details
        parsed = parse_umo_details(umo)

        # 尝试获取群名或昵称作为规则名
        rule_name = ""
        msg_obj = getattr(event, "message_obj", None)
        grp = getattr(msg_obj, "group", None)
        if grp and hasattr(grp, "group_name") and grp.group_name:
            rule_name = str(grp.group_name)
        elif hasattr(event, "get_sender_name") and event.get_sender_name():
            rule_name = str(event.get_sender_name())
        if not rule_name:
            rule_name = parsed["display_badge"]

        rule = self.prompt_injector_mgr.save_rule({
            "umo": umo,
            "name": rule_name,
            "prompt": prompt_text,
            "enabled": True,
            "inject_mode": self.prompt_injector_mgr.default_inject_mode,
            "group_id": parsed["group_id"],
            "chat_type": parsed["chat_type"],
            "platform": parsed["platform"],
        })

        logger.info(f"[拟人化提示词] 指令设置专属提示词: 【{rule.name}】(UMO: {umo})")
        yield event.plain_result(
            f"✅ 已成功为当前【{parsed['chat_type_text']}】设置专属提示词！\n"
            f"名称：{rule.name}\n"
            f"UMO：{umo}\n"
            f"提示词字数：{len(prompt_text)} 字\n"
            f"后续在此会话中聊天时，将自动注入此提示词。"
        )

    @umo_group.command("setumo")
    async def umo_set_by_id(self, event: AstrMessageEvent, target_umo: str, prompt: str) -> None:
        """显式指定 UMO 设置提示词：/umo setumo <target_umo> <提示词>"""
        u = str(target_umo or "").strip()
        p = str(prompt or "").strip()
        if not u or not p:
            yield event.plain_result("❌ 用法：`/umo setumo <target_umo> <提示词>`")
            return

        from modules.prompt_injector.model import parse_umo_details
        parsed = parse_umo_details(u)

        rule = self.prompt_injector_mgr.save_rule({
            "umo": u,
            "name": parsed["display_badge"],
            "prompt": p,
            "enabled": True,
            "inject_mode": self.prompt_injector_mgr.default_inject_mode,
            "group_id": parsed["group_id"],
            "chat_type": parsed["chat_type"],
            "platform": parsed["platform"],
        })

        yield event.plain_result(
            f"✅ 已成功为指定 UMO 设置专属提示词！\n"
            f"UMO：{u}\n"
            f"标识：{parsed['display_badge']}\n"
            f"提示词字数：{len(p)} 字"
        )

    @umo_group.command("list", alias={"列表"})
    async def umo_list(self, event: AstrMessageEvent) -> None:
        """列出所有已配置专属提示词的会话规则"""
        rules = self.prompt_injector_mgr.get_all_rules()
        if not rules:
            yield event.plain_result("📋 当前尚未配置任何特定群聊/私聊专属提示词。\n可使用 `/umo set <提示词>` 为当前会话设置，或在 WebUI 面板中配置。")
            return

        lines = [f"📋 【已配置会话专属提示词列表（共 {len(rules)} 个）】："]
        for idx, r in enumerate(rules, 1):
            status = "🟢" if r.get("enabled") else "🔴"
            p_snippet = r.get("prompt", "")[:35] + ("..." if len(r.get("prompt", "")) > 35 else "")
            lines.append(f"{idx}. {status} 【{r.get('name')}】")
            lines.append(f"   UMO: {r.get('umo')}")
            lines.append(f"   提示词: {p_snippet}")

        lines.append("\n💡 输入 `/umo info` 查看当前会话，或在 WebUI 面板中进行可视化增删改查。")
        yield event.plain_result("\n".join(lines))

    @umo_group.command("toggle", alias={"开关"})
    async def umo_toggle(self, event: AstrMessageEvent) -> None:
        """切换当前会话专属提示词的启用/禁用状态"""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        rule = self.prompt_injector_mgr.get_rule(umo)
        if not rule:
            yield event.plain_result("❌ 当前会话尚未配置专属提示词，无法切换开关。")
            return

        new_status = self.prompt_injector_mgr.toggle_rule(umo)
        status_text = "🟢 启用" if new_status else "🔴 禁用"
        yield event.plain_result(f"已成功将当前会话专属提示词状态切换为：{status_text}")

    @umo_group.command("clear", alias={"清除", "删除"})
    async def umo_clear(self, event: AstrMessageEvent) -> None:
        """删除当前群聊/私聊的专属提示词规则"""
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        rule = self.prompt_injector_mgr.get_rule(umo)
        if not rule:
            yield event.plain_result("当前会话未配置专属提示词，无需清除。")
            return

        self.prompt_injector_mgr.delete_rule(umo)
        yield event.plain_result(f"✅ 已成功清除当前会话（{rule.name}）的专属提示词。")

    # --------------------------------------------------------------------------
    # NAI 生图伴侣直连联动指令与 LLM 工具 (pc_generate_photo / /nai)
    # --------------------------------------------------------------------------

    @filter.command_group("nai", alias={"生图", "画图"})
    def nai_group(self) -> None:
        """NAI 生图伴侣直连联动命令组"""
        pass

    @nai_group.command("status", alias={"状态", "检测"})
    async def nai_status_cmd(self, event: AstrMessageEvent) -> None:
        """检查与 astrbot_plugin_nai_image 插件的伴侣直连就绪状态"""
        status = self.nai_manager.bridge_client.get_status()
        details = status.get("details", {})
        active_sched = self.nai_manager.get_active_schedule_scene_hint()

        lines = [
            "🎨 【NAI 生图伴侣直连状态】",
            f"• 联动功能开关: {'🟢 开启' if self.nai_manager.config.enabled else '🔴 关闭'}",
            f"• 插件安装状态: {'✅ 已安装' if status.get('installed') else '❌ 未检测到 (astrbot_plugin_nai_image)'}",
            f"• 生图能力可用: {'🟢 就绪可用' if status.get('available') else '🟡 不可用 (' + status.get('message', '') + ')'}",
            f"• 提示词组织模式: {self.nai_manager.config.prompt_format} (NAI 4.5 tag / 自然语言)",
            f"• 默认画面比例: {self.nai_manager.config.default_size}",
            f"• 当前联动日程情境: {active_sched or '（当前时段无特定活动）'}",
        ]
        if details.get("generation_count") is not None:
            lines.append(f"• 直连历史出图次数: {details.get('generation_count')} 次")

        lines.append("\n💡 提示：您可以使用 `/nai draw <描述>` 直接测试出图，或在聊天中触发 `pc_generate_photo` 工具。")
        yield event.plain_result("\n".join(lines))

    @nai_group.command("draw", alias={"生成", "拍照", "自拍"})
    async def nai_draw_cmd(self, event: AstrMessageEvent, prompt: str) -> None:
        """使用 NAI 伴侣直连生成图片并发送"""
        if not prompt or not prompt.strip():
            yield event.plain_result("请输入要生成的画面提示词或场景描述，如：`/nai draw 1girl, smiling, outdoor`")
            return

        yield event.plain_result("🎨 正在通过 NAI 伴侣直连通道生成图片，请稍候...")

        session_key = str(getattr(event, "unified_msg_origin", "") or "")
        res = await self.nai_manager.generate_image(
            prompt=prompt.strip(),
            workflow_kind="selfie",
            session_key=session_key,
        )

        if not res.success or not res.image_path:
            yield event.plain_result(f"❌ 生图失败：{res.note or '未知原因'}")
            return

        # Send image via AstrBot message chain
        yield event.image_result(res.image_path)

    @filter.llm_tool(name="pc_generate_photo")
    async def pc_generate_photo(
        self,
        event: AstrMessageEvent,
        prompt: str,
        kind: str = "selfie",
        size: str = "",
        caption: str = "",
    ) -> str:
        """主链模型调用生图工具：在用户明确要求画图、自拍、拍照、展示生活或穿搭时生成图片。

        Args:
            prompt(string): 画面描述或 NovelAI 英文标签 tags
            kind(string): 图片类型，可选 selfie(自拍/人像)、text2img(普通文生图)、sticker(表情包)
            size(string): 画面尺寸或宽高比，如 portrait(竖图)、square(方图)、landscape(横图)
            caption(string): 随图发送的角色台词或配文
        """
        if not self.nai_manager.config.enabled:
            return "生图失败：NAI 伴侣直连生图已在当前插件配置中关闭。"

        session_key = str(getattr(event, "unified_msg_origin", "") or "")
        res = await self.nai_manager.generate_image(
            prompt=prompt,
            workflow_kind=kind or "selfie",
            session_key=session_key,
            size=size,
            include_schedule_scene=True,
        )

        if not res.success or not res.image_path:
            return f"生图失败：{res.note or '生成服务未返回有效图片'}"

        # Send image and optional caption to chat
        try:
            if Comp and hasattr(Comp, "Image") and MessageChain:
                msg_chain = [Comp.Image.fromFileSystem(res.image_path)]
                if caption and caption.strip() and hasattr(Comp, "Plain"):
                    msg_chain.insert(0, Comp.Plain(caption.strip() + "\n"))
                await event.send(MessageChain(msg_chain))
            else:
                # Fallback to event result if MessageChain or Comp not available
                img_res = event.image_result(res.image_path)
                if caption and caption.strip():
                    await event.send(event.plain_result(caption.strip()))
                await event.send(img_res)
            return f"图片已生成并已直接发送给用户。成图路径: {res.image_path}。请根据情境进行简要自然回应。"
        except Exception as e:
            logger.error(f"发送生图结果异常: {e}", exc_info=True)
            return f"图片已生成，但在发送到会话时遇到异常: {e}"
