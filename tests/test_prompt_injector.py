import asyncio
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from modules.prompt_injector.model import UmoPromptRule, parse_umo_details
from modules.prompt_injector.manager import PromptInjectorManager
from modules.prompt_injector.web_api import PromptInjectorWebApi


class TestUmoParsingAndModel(unittest.TestCase):
    def test_parse_umo_qq_group(self):
        umo = "aiocqhttp:GroupMessage:123456789"
        res = parse_umo_details(umo)
        self.assertEqual(res["platform"], "aiocqhttp")
        self.assertEqual(res["chat_type"], "group")
        self.assertEqual(res["chat_type_text"], "群聊")
        self.assertEqual(res["group_id"], "123456789")
        self.assertEqual(res["target_id"], "123456789")
        self.assertIn("QQ (OneBot)", res["platform_name_cn"])
        self.assertIn("123456789", res["display_badge"])

    def test_parse_umo_qq_friend(self):
        umo = "aiocqhttp:FriendMessage:987654321"
        res = parse_umo_details(umo)
        self.assertEqual(res["platform"], "aiocqhttp")
        self.assertEqual(res["chat_type"], "private")
        self.assertEqual(res["chat_type_text"], "私聊")
        self.assertEqual(res["group_id"], "")
        self.assertEqual(res["target_id"], "987654321")
        self.assertIn("用户 987654321", res["display_badge"])

    def test_parse_umo_telegram_group(self):
        umo = "telegram:GroupMessage:-10012345678"
        res = parse_umo_details(umo)
        self.assertEqual(res["platform"], "telegram")
        self.assertEqual(res["chat_type"], "group")
        self.assertEqual(res["group_id"], "-10012345678")

    def test_parse_umo_webchat(self):
        umo = "webchat:FriendMessage:web-user-abc"
        res = parse_umo_details(umo)
        self.assertEqual(res["platform"], "webchat")
        self.assertEqual(res["chat_type"], "webchat")
        self.assertEqual(res["target_id"], "web-user-abc")

    def test_parse_umo_empty(self):
        res = parse_umo_details("")
        self.assertEqual(res["platform"], "unknown")
        self.assertEqual(res["chat_type"], "unknown")
        self.assertEqual(res["group_id"], "")

    def test_rule_model_serialization(self):
        rule = UmoPromptRule(
            umo="aiocqhttp:GroupMessage:55667788",
            name="二次元交流群",
            prompt="请以傲娇口吻交流",
            enabled=True,
            inject_mode="system_prompt",
        )
        self.assertEqual(rule.group_id, "55667788")
        self.assertEqual(rule.chat_type, "group")
        self.assertEqual(rule.platform, "aiocqhttp")

        d = rule.to_dict()
        self.assertEqual(d["umo"], "aiocqhttp:GroupMessage:55667788")
        self.assertEqual(d["name"], "二次元交流群")
        self.assertEqual(d["group_id"], "55667788")
        self.assertEqual(d["chat_type_text"], "群聊")

        rule2 = UmoPromptRule.from_dict(d)
        self.assertEqual(rule2.umo, rule.umo)
        self.assertEqual(rule2.name, rule.name)
        self.assertEqual(rule2.prompt, rule.prompt)
        self.assertEqual(rule2.enabled, rule.enabled)


class TestPromptInjectorManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage_file = Path(self.test_dir) / "umo_prompt_rules.json"

        self.mock_context = MagicMock()
        self.mock_context.conversation_manager = None
        self.mock_context.db = None
        self.mock_context._core_lifecycle = None
        self.mock_config = {
            "umo_prompt_injector_enabled": True,
            "umo_prompt_default_mode": "system_prompt",
            "umo_prompt_rules": [],
        }
        self.mock_logger = MagicMock()

        self.mgr = PromptInjectorManager(self.mock_context, self.mock_config, self.mock_logger)
        self.mgr._storage_path = self.storage_file

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_crud_and_persistence(self):
        await self.mgr.initialize()
        self.assertEqual(len(self.mgr.get_all_rules()), 0)

        # 1. Save rule
        rule_data = {
            "umo": "aiocqhttp:GroupMessage:123456",
            "name": "技术讨论群",
            "prompt": "你是一名资深Python架构师，回答要求干练直接。",
            "enabled": True,
            "inject_mode": "system_prompt",
        }
        saved_rule = self.mgr.save_rule(rule_data)
        self.assertEqual(saved_rule.umo, "aiocqhttp:GroupMessage:123456")
        self.assertEqual(saved_rule.name, "技术讨论群")
        self.assertEqual(len(self.mgr.get_all_rules()), 1)

        # Verify disk persistence
        self.assertTrue(self.storage_file.exists())
        with open(self.storage_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertEqual(len(disk_data), 1)
            self.assertEqual(disk_data[0]["umo"], "aiocqhttp:GroupMessage:123456")

        # 2. Toggle rule
        new_status = self.mgr.toggle_rule("aiocqhttp:GroupMessage:123456")
        self.assertFalse(new_status)
        rule = self.mgr.get_rule("aiocqhttp:GroupMessage:123456")
        self.assertFalse(rule.enabled)

        self.mgr.toggle_rule("aiocqhttp:GroupMessage:123456", True)
        self.assertTrue(self.mgr.get_rule("aiocqhttp:GroupMessage:123456").enabled)

        # 3. Reload from storage
        new_mgr = PromptInjectorManager(self.mock_context, self.mock_config, self.mock_logger)
        new_mgr._storage_path = self.storage_file
        await new_mgr.initialize()
        self.assertEqual(len(new_mgr.get_all_rules()), 1)
        self.assertEqual(new_mgr.get_rule("aiocqhttp:GroupMessage:123456").name, "技术讨论群")

        # 4. Delete rule
        deleted = new_mgr.delete_rule("aiocqhttp:GroupMessage:123456")
        self.assertTrue(deleted)
        self.assertEqual(len(new_mgr.get_all_rules()), 0)

    async def test_llm_request_injection_modes(self):
        await self.mgr.initialize()

        # Add rule
        self.mgr.save_rule({
            "umo": "aiocqhttp:GroupMessage:9999",
            "name": "测试群",
            "prompt": "【专属设定】请始终使用古文诗意语气作答。",
            "enabled": True,
            "inject_mode": "system_prompt",
        })

        mock_event = MagicMock()
        mock_event.unified_msg_origin = "aiocqhttp:GroupMessage:9999"

        # 1. system_prompt mode (append)
        req = MagicMock()
        req.system_prompt = "You are a helpful assistant."
        injected = await self.mgr.inject_prompt_context(mock_event, req)
        self.assertTrue(injected)
        self.assertIn("You are a helpful assistant.", req.system_prompt)
        self.assertIn("【专属设定】请始终使用古文诗意语气作答。", req.system_prompt)

        # 2. prepend_system mode
        self.mgr.save_rule({
            "umo": "aiocqhttp:GroupMessage:9999",
            "name": "测试群",
            "prompt": "【置顶设定】禁止透露Bot身份。",
            "enabled": True,
            "inject_mode": "prepend_system",
        })
        req2 = MagicMock()
        req2.system_prompt = "Original base prompt."
        await self.mgr.inject_prompt_context(mock_event, req2)
        self.assertTrue(req2.system_prompt.startswith("【置顶设定】禁止透露Bot身份。"))

        # 3. extra_user_content mode
        self.mgr.save_rule({
            "umo": "aiocqhttp:GroupMessage:9999",
            "name": "测试群",
            "prompt": "【附加内容】请关注提问中的技术细节。",
            "enabled": True,
            "inject_mode": "extra_user_content",
        })
        req3 = MagicMock()
        req3.extra_user_content_parts = []
        req3.system_prompt = "Base prompt"
        await self.mgr.inject_prompt_context(mock_event, req3)
        self.assertEqual(len(req3.extra_user_content_parts), 1)
        self.assertIn("【附加内容】", req3.extra_user_content_parts[0].text)

        # 4. Disabled rule does not inject
        self.mgr.toggle_rule("aiocqhttp:GroupMessage:9999", False)
        req4 = MagicMock()
        req4.system_prompt = "Base"
        injected4 = await self.mgr.inject_prompt_context(mock_event, req4)
        self.assertFalse(injected4)
        self.assertEqual(req4.system_prompt, "Base")

        # 5. Non-matching UMO does not inject
        mock_event_other = MagicMock()
        mock_event_other.unified_msg_origin = "aiocqhttp:FriendMessage:8888"
        req5 = MagicMock()
        req5.system_prompt = "Base"
        injected5 = await self.mgr.inject_prompt_context(mock_event_other, req5)
        self.assertFalse(injected5)

    async def test_discover_conversations_with_names(self):
        await self.mgr.initialize()

        # Simulate event observations:
        # Group event with group name
        grp_event = MagicMock()
        grp_event.unified_msg_origin = "aiocqhttp:GroupMessage:777888"
        grp_event.get_group_id.return_value = "777888"
        grp_event.message_obj = MagicMock()
        grp_event.message_obj.group.group_name = "AstrBot 开发交流大群"
        self.mgr.observe_event(grp_event)

        # Private event with sender nickname
        pvt_event = MagicMock()
        pvt_event.unified_msg_origin = "aiocqhttp:FriendMessage:112233"
        pvt_event.message_obj = None
        pvt_event.get_sender_name.return_value = "测试好友小明"
        self.mgr.observe_event(pvt_event)

        # Discover
        discovered = await self.mgr.discover_conversations()
        self.assertGreaterEqual(len(discovered), 2)

        # Verify group item
        grp_item = next((d for d in discovered if d["umo"] == "aiocqhttp:GroupMessage:777888"), None)
        self.assertIsNotNone(grp_item)
        self.assertEqual(grp_item["chat_name"], "AstrBot 开发交流大群")
        self.assertEqual(grp_item["chat_type"], "group")
        self.assertEqual(grp_item["group_id"], "777888")

        # Verify private item
        pvt_item = next((d for d in discovered if d["umo"] == "aiocqhttp:FriendMessage:112233"), None)
        self.assertIsNotNone(pvt_item)
        self.assertEqual(pvt_item["chat_name"], "测试好友小明")
        self.assertEqual(pvt_item["chat_type"], "private")


class TestPromptInjectorWebApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_context = MagicMock()
        self.mock_context.conversation_manager = None
        self.mock_context.db = None
        self.mock_context._core_lifecycle = None
        self.mock_config = {
            "umo_prompt_injector_enabled": True,
            "umo_prompt_default_mode": "system_prompt",
            "umo_prompt_rules": [],
        }
        self.mock_logger = MagicMock()

        self.mgr = PromptInjectorManager(self.mock_context, self.mock_config, self.mock_logger)
        self.mgr._storage_path = Path(self.test_dir) / "umo_prompt_rules.json"
        self.api = PromptInjectorWebApi(self.mgr, self.mock_logger)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_api_routes_and_handlers(self):
        # 1. Register routes
        self.api.register_routes(self.mock_context)
        self.assertTrue(self.mock_context.register_web_api.called)

        # 2. Get config
        cfg_resp = await self.api.get_config()
        self.assertEqual(cfg_resp["data"]["enabled"], True)
        self.assertEqual(cfg_resp["data"]["total_rules"], 0)

        # 3. Add a rule via manager
        self.mgr.save_rule({
            "umo": "aiocqhttp:GroupMessage:888999",
            "name": "游戏开黑群",
            "prompt": "【游戏助手】回答简洁幽默。",
            "enabled": True,
        })

        # 4. Get rules
        rules_resp = await self.api.get_rules()
        self.assertEqual(rules_resp["data"]["count"], 1)
        self.assertEqual(rules_resp["data"]["rules"][0]["umo"], "aiocqhttp:GroupMessage:888999")

        # 5. Discover UMOs
        discover_resp = await self.api.get_discovered_umos()
        self.assertTrue(discover_resp["data"]["success"])


if __name__ == "__main__":
    unittest.main()
