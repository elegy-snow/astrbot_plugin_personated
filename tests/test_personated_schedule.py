import datetime
import unittest

from utils.time_utils import (
    get_today_str,
    get_weekday_cn,
    is_time_in_range,
    parse_time_str,
    seconds_until_next_run,
    time_to_minutes,
)
from modules.schedule.model import DailySchedule, DailyScheduleItem, ScheduleSegment
from modules.schedule.prompt import (
    build_schedule_generation_prompt,
    format_injected_schedule_context,
    parse_schedule_llm_response,
)


class TestTimeUtils(unittest.TestCase):
    def test_parse_time_str(self):
        t1 = parse_time_str("00:00")
        self.assertEqual(t1.hour, 0)
        self.assertEqual(t1.minute, 0)

        t2 = parse_time_str("04:30")
        self.assertEqual(t2.hour, 4)
        self.assertEqual(t2.minute, 30)

        t3 = parse_time_str("23:59")
        self.assertEqual(t3.hour, 23)
        self.assertEqual(t3.minute, 59)

        with self.assertRaises(ValueError):
            parse_time_str("24:00")
        with self.assertRaises(ValueError):
            parse_time_str("12:60")
        with self.assertRaises(ValueError):
            parse_time_str("invalid")

    def test_is_time_in_range_normal(self):
        # 08:30 -> 12:00
        start = parse_time_str("08:30")
        end = parse_time_str("12:00")

        self.assertTrue(is_time_in_range(parse_time_str("08:30"), start, end))
        self.assertTrue(is_time_in_range(parse_time_str("10:15"), start, end))
        self.assertFalse(is_time_in_range(parse_time_str("12:00"), start, end, inclusive_end=False))
        self.assertTrue(is_time_in_range(parse_time_str("12:00"), start, end, inclusive_end=True))
        self.assertFalse(is_time_in_range(parse_time_str("08:29"), start, end))
        self.assertFalse(is_time_in_range(parse_time_str("12:01"), start, end))

    def test_is_time_in_range_cross_midnight(self):
        # 22:00 -> 06:00
        start = parse_time_str("22:00")
        end = parse_time_str("06:00")

        self.assertTrue(is_time_in_range(parse_time_str("22:00"), start, end))
        self.assertTrue(is_time_in_range(parse_time_str("23:30"), start, end))
        self.assertTrue(is_time_in_range(parse_time_str("00:00"), start, end))
        self.assertTrue(is_time_in_range(parse_time_str("03:15"), start, end))
        self.assertTrue(is_time_in_range(parse_time_str("05:59"), start, end))
        self.assertFalse(is_time_in_range(parse_time_str("06:00"), start, end, inclusive_end=False))
        self.assertTrue(is_time_in_range(parse_time_str("06:00"), start, end, inclusive_end=True))
        self.assertFalse(is_time_in_range(parse_time_str("14:00"), start, end))
        self.assertFalse(is_time_in_range(parse_time_str("21:59"), start, end))

    def test_seconds_until_next_run(self):
        # Current time 03:00, target 04:00 -> exactly 3600 seconds
        now = datetime.datetime(2026, 5, 3, 3, 0, 0)
        diff = seconds_until_next_run("04:00", now)
        self.assertEqual(diff, 3600.0)

        # Current time 05:00, target 04:00 -> next day 04:00 (23 hours = 82800 s)
        now2 = datetime.datetime(2026, 5, 3, 5, 0, 0)
        diff2 = seconds_until_next_run("04:00", now2)
        self.assertEqual(diff2, 23 * 3600.0)


class TestScheduleModels(unittest.TestCase):
    def test_daily_schedule_find_active_item(self):
        items = [
            DailyScheduleItem(
                id="morning",
                name="早晨",
                start="07:00",
                end="12:00",
                activity="晨读中",
                state="精神饱满",
            ),
            DailyScheduleItem(
                id="night",
                name="夜间",
                start="22:00",
                end="07:00",
                activity="熟睡中",
                state="深度放松",
            ),
        ]
        schedule = DailySchedule(
            date="2026-05-03",
            weekday="日",
            persona_id="test_persona",
            generated_at="2026-05-03T04:00:00",
            provider_used="test_provider",
            items=items,
        )

        # 09:30 should match morning
        act = schedule.find_active_item(datetime.time(9, 30))
        self.assertIsNotNone(act)
        self.assertEqual(act.id, "morning")

        # 23:45 should match night
        act_night = schedule.find_active_item(datetime.time(23, 45))
        self.assertIsNotNone(act_night)
        self.assertEqual(act_night.id, "night")

        # 03:30 should also match night (cross-midnight)
        act_night_early = schedule.find_active_item(datetime.time(3, 30))
        self.assertIsNotNone(act_night_early)
        self.assertEqual(act_night_early.id, "night")

        # 15:00 should not match any
        act_none = schedule.find_active_item(datetime.time(15, 0))
        self.assertIsNone(act_none)

    def test_serialization(self):
        item = DailyScheduleItem("id1", "时段1", "08:00", "12:00", "办公", "专注")
        sched = DailySchedule("2026-05-03", "日", "p1", "iso", "prov", [item])
        d = sched.to_dict()
        restored = DailySchedule.from_dict(d)
        self.assertEqual(restored.date, "2026-05-03")
        self.assertEqual(len(restored.items), 1)
        self.assertEqual(restored.items[0].name, "时段1")


class TestPromptAndParsing(unittest.TestCase):
    def test_build_prompt(self):
        segments = [
            ScheduleSegment("s1", "上午工作", "09:00", "12:00"),
            ScheduleSegment("s2", "晚上休息", "22:00", "07:00"),
        ]
        dt = datetime.datetime(2026, 5, 3, 10, 0, 0)
        sys_p, user_p = build_schedule_generation_prompt(
            persona_prompt="你是一位可爱的猫娘管家",
            segments=segments,
            dt=dt,
        )
        self.assertIn("可爱的猫娘管家", user_p)
        self.assertIn("2026-05-03", user_p)
        self.assertIn("上午工作", user_p)
        self.assertIn("晚上休息", user_p)

    def test_parse_json_markdown_wrapped(self):
        segments = [
            ScheduleSegment("s1", "上午工作", "09:00", "12:00"),
            ScheduleSegment("s2", "晚上休息", "22:00", "07:00"),
        ]
        raw_llm = """
Here is the schedule:
```json
[
  {
    "id": "s1",
    "name": "上午工作",
    "start": "09:00",
    "end": "12:00",
    "activity": "整理书房并准备咖啡",
    "state": "神采奕奕"
  },
  {
    "id": "s2",
    "name": "晚上休息",
    "start": "22:00",
    "end": "07:00",
    "activity": "盖好毛毯就寝",
    "state": "惬意安稳"
  }
]
```
Have a good day!
"""
        sched = parse_schedule_llm_response(
            raw_response=raw_llm,
            segments=segments,
            date_str="2026-05-03",
            weekday_str="日",
            persona_id="catgirl",
            provider_used="gpt-4o",
        )
        self.assertEqual(len(sched.items), 2)
        self.assertEqual(sched.items[0].activity, "整理书房并准备咖啡")
        self.assertEqual(sched.items[1].state, "惬意安稳")

    def test_format_injected_schedule_context(self):
        item = DailyScheduleItem("s1", "午休", "12:00", "14:00", "在沙发上小憩", "有些困倦但很舒服")
        ctx = format_injected_schedule_context(item, "12:30", "2026-05-03", "日")
        self.assertIn("在沙发上小憩", ctx)
        self.assertIn("午休", ctx)
        self.assertIn("12:30", ctx)


class DummyLLMResponse:
    def __init__(self, completion_text: str):
        self.completion_text = completion_text


class DummyProvider:
    pass


class DummyProviderManager:
    def __init__(self):
        self.providers = {"dummy_chat": DummyProvider()}

    async def get_provider_by_id(self, pid: str):
        return self.providers.get(pid)


class DummyPersonaManager:
    async def get_default_persona_v3(self, umo: str = ""):
        return {
            "name": "test_persona",
            "prompt": "你是一个勤劳开朗的AI助手，喜欢在清晨喝咖啡，中午午休。",
        }


class DummyContext:
    def __init__(self):
        self.provider_manager = DummyProviderManager()
        self.persona_manager = DummyPersonaManager()
        self.last_prompt = None
        self.last_provider_id = None
        self.mock_llm_result = """[
            {"id": "morning_work", "name": "上午工作", "start": "08:30", "end": "12:00", "activity": "编写代码中", "state": "专注"},
            {"id": "night_sleep", "name": "夜间休息", "start": "22:00", "end": "06:00", "activity": "进入待机睡眠状态", "state": "平稳"}
        ]"""

    async def get_current_chat_provider_id(self, umo: str = "") -> str:
        return "dummy_chat"

    async def llm_generate(self, *, chat_provider_id: str, prompt: str, system_prompt: str, **kwargs):
        self.last_provider_id = chat_provider_id
        self.last_prompt = prompt
        return DummyLLMResponse(self.mock_llm_result)


class DummyEvent:
    def __init__(self):
        self.unified_msg_origin = "dummy_umo_123"


class DummyProviderRequest:
    def __init__(self):
        self.system_prompt = "Base system prompt"
        self.extra_user_content_parts = []


class TestScheduleManager(unittest.IsolatedAsyncioTestCase):
    async def test_manager_generate_and_inject(self):
        import logging
        from modules.schedule.manager import ScheduleManager

        ctx = DummyContext()
        config = {
            "daily_generate_time": "04:00",
            "schedule_provider_id": "",  # test fallback to conversation provider
            "inject_context_enabled": True,
            "inject_mode": "extra_user_content",
            "schedule_segments": [
                {"id": "morning_work", "name": "上午工作", "start": "08:30", "end": "12:00"},
                {"id": "night_sleep", "name": "夜间休息", "start": "22:00", "end": "06:00"},
            ],
        }
        logger = logging.getLogger("test_logger")
        mgr = ScheduleManager(ctx, config, logger)
        await mgr.initialize()

        # Generate schedule for today
        schedule = await mgr.generate_today_schedule(force=True)
        self.assertEqual(len(schedule.items), 2)
        self.assertEqual(schedule.provider_used, "dummy_chat")
        self.assertEqual(schedule.persona_id, "test_persona")
        self.assertEqual(schedule.items[0].activity, "编写代码中")

        # Test injection during morning_work at 09:15
        dt_morning = datetime.datetime.now().replace(hour=9, minute=15)
        # Mock datetime or test active item find
        item = schedule.find_active_item(dt_morning.time())
        self.assertIsNotNone(item)
        self.assertEqual(item.id, "morning_work")

        # Test context injection into dummy request
        req = DummyProviderRequest()
        event = DummyEvent()
        await mgr.inject_schedule_context(event, req, dt=dt_morning)
        # Verify req.extra_user_content_parts contains injected content
        self.assertTrue(len(req.extra_user_content_parts) > 0)
        self.assertIn("【角色当前作息与实时状态】", req.extra_user_content_parts[0].text)

        # Test status
        status = mgr.get_status_info()
        self.assertEqual(status["daily_generate_time"], "04:00")
        self.assertEqual(status["segments_count"], 2)

        await mgr.terminate()


class MockRequest:
    def __init__(self, data: dict = None, query: dict = None):
        self._data = data or {}
        self.query = query or {}

    async def json(self, default=None):
        return self._data


class TestScheduleWebApi(unittest.IsolatedAsyncioTestCase):
    async def test_web_api_endpoints(self):
        import logging
        from modules.schedule.manager import ScheduleManager
        from modules.schedule.web_api import ScheduleWebApi
        import modules.schedule.web_api as web_api_mod

        ctx = DummyContext()
        config = {
            "daily_generate_time": "04:00",
            "schedule_provider_id": "dummy_chat",
            "inject_context_enabled": True,
            "inject_mode": "extra_user_content",
            "schedule_segments": [
                {"id": "morning_work", "name": "上午工作", "start": "08:30", "end": "12:00"},
                {"id": "night_sleep", "name": "夜间休息", "start": "22:00", "end": "06:00"},
            ],
        }
        logger = logging.getLogger("test_web_api")
        mgr = ScheduleManager(ctx, config, logger)
        await mgr.initialize()

        api = ScheduleWebApi(mgr, logger)

        # 1. Test get_config
        cfg_resp = await api.get_config()
        # In mock environment, returns {"status": "ok", "data": {...}} or direct dict
        data = cfg_resp.get("data") if isinstance(cfg_resp, dict) and "data" in cfg_resp else cfg_resp
        self.assertEqual(data["daily_generate_time"], "04:00")
        self.assertEqual(len(data["schedule_segments"]), 2)

        # 2. Test save_config with valid payload
        valid_payload = {
            "daily_generate_time": "05:30",
            "schedule_provider_id": "custom_provider",
            "inject_context_enabled": True,
            "inject_mode": "system_prompt",
            "schedule_segments": [
                {"id": "seg_1", "name": "早操", "start": "06:00", "end": "07:30"},
                {"id": "seg_2", "name": "自习", "start": "07:30", "end": "12:00"},
            ],
        }
        web_api_mod.request = MockRequest(valid_payload)
        save_resp = await api.save_config()
        save_data = save_resp.get("data") if isinstance(save_resp, dict) and "data" in save_resp else save_resp
        self.assertTrue(save_data.get("saved"))
        self.assertEqual(mgr.daily_generate_time, "05:30")
        self.assertEqual(mgr.schedule_provider_id, "custom_provider")
        self.assertEqual(mgr.inject_mode, "system_prompt")
        self.assertEqual(len(mgr.schedule_segments), 2)

        # 3. Test save_config with invalid time format
        invalid_payload = {
            "daily_generate_time": "25:00",
            "schedule_segments": [{"id": "s1", "name": "测试", "start": "08:00", "end": "09:00"}],
        }
        web_api_mod.request = MockRequest(invalid_payload)
        err_resp = await api.save_config()
        self.assertEqual(err_resp.get("_code"), 400)

        # 4. Test generate_today
        gen_resp = await api.generate_today()
        gen_data = gen_resp.get("data") if isinstance(gen_resp, dict) and "data" in gen_resp else gen_resp
        self.assertTrue(gen_data.get("success"))
        self.assertIn("schedule", gen_data)

        # 5. Test get_today
        today_resp = await api.get_today()
        today_data = today_resp.get("data") if isinstance(today_resp, dict) and "data" in today_resp else today_resp
        self.assertIn("date", today_data)
        self.assertIn("today_schedule", today_data)

        # 6. Test update_item
        update_payload = {
            "id": "seg_1",
            "activity": "正在跑步机上慢跑",
            "state": "充满活力",
        }
        web_api_mod.request = MockRequest(update_payload)
        up_resp = await api.update_item()
        up_data = up_resp.get("data") if isinstance(up_resp, dict) and "data" in up_resp else up_resp
        self.assertTrue(up_data.get("updated"))
        self.assertEqual(up_data["item"]["activity"], "正在跑步机上慢跑")

        # 7. Test save_full_schedule (custom date)
        target_date = "2026-05-20"
        full_schedule_payload = {
            "date": target_date,
            "weekday": "三",
            "persona_id": "test_persona",
            "provider_used": "custom_provider",
            "items": [
                {
                    "id": "item_1",
                    "name": "晨间漫步",
                    "start": "07:00",
                    "end": "08:00",
                    "activity": "在公园散步看日出",
                    "state": "神清气爽",
                },
                {
                    "id": "item_2",
                    "name": "夜间阅读",
                    "start": "21:00",
                    "end": "22:30",
                    "activity": "阅读侦探小说",
                    "state": "沉浸平静",
                },
            ],
        }
        web_api_mod.request = MockRequest(full_schedule_payload)
        save_full_resp = await api.save_full_schedule()
        save_full_data = save_full_resp.get("data") if isinstance(save_full_resp, dict) and "data" in save_full_resp else save_full_resp
        self.assertTrue(save_full_data.get("saved"))

        # 8. Test get_schedule_detail
        web_api_mod.request = MockRequest(query={"date": target_date})
        detail_resp = await api.get_schedule_detail()
        detail_data = detail_resp.get("data") if isinstance(detail_resp, dict) and "data" in detail_resp else detail_resp
        self.assertTrue(detail_data.get("found"))
        self.assertEqual(detail_data["date"], target_date)
        self.assertEqual(len(detail_data["schedule"]["items"]), 2)
        self.assertEqual(detail_data["schedule"]["items"][0]["activity"], "在公园散步看日出")

        # 9. Test get_dates
        dates_resp = await api.get_dates()
        dates_data = dates_resp.get("data") if isinstance(dates_resp, dict) and "data" in dates_resp else dates_resp
        self.assertIn("dates", dates_data)
        date_records = dates_data["dates"]
        found_target = any(d["date"] == target_date for d in date_records)
        self.assertTrue(found_target)

        # 10. Test generate_for_date
        gen_date = "2026-06-01"
        web_api_mod.request = MockRequest({"date": gen_date})
        gen_date_resp = await api.generate_for_date()
        gen_date_data = gen_date_resp.get("data") if isinstance(gen_date_resp, dict) and "data" in gen_date_resp else gen_date_resp
        self.assertTrue(gen_date_data.get("success"))
        self.assertEqual(gen_date_data["schedule"]["date"], gen_date)

        # 11. Test delete_for_date
        web_api_mod.request = MockRequest({"date": target_date})
        del_resp = await api.delete_for_date()
        del_data = del_resp.get("data") if isinstance(del_resp, dict) and "data" in del_resp else del_resp
        self.assertTrue(del_data.get("deleted"))

        # Verify deletion in get_schedule_detail
        web_api_mod.request = MockRequest(query={"date": target_date})
        detail_after_del = await api.get_schedule_detail()
        detail_after_data = detail_after_del.get("data") if isinstance(detail_after_del, dict) and "data" in detail_after_del else detail_after_del
        self.assertFalse(detail_after_data.get("found"))

        await mgr.terminate()


if __name__ == "__main__":
    unittest.main()
