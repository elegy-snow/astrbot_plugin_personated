# -*- coding: utf-8 -*-
"""Unit tests for NAI image companion bridge module."""
from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from modules.nai_bridge.bridge import NAIBridgeClient
from modules.nai_bridge.manager import NAIBridgeManager
from modules.nai_bridge.model import NAIBridgeConfig, NAIGenerationResult, PromptFormatMode
from modules.nai_bridge.prompt_format import (
    extract_positive_negative,
    format_prompt_for_backend,
    get_prompt_format_instruction,
    normalize_prompt_format,
)
from modules.nai_bridge.web_api import NAIBridgeWebApi


class TestPromptFormatUtils(unittest.TestCase):
    def test_normalize_prompt_format(self):
        self.assertEqual(normalize_prompt_format("nai"), "nai")
        self.assertEqual(normalize_prompt_format("NAI45"), "nai")
        self.assertEqual(normalize_prompt_format("natural_language"), "natural_language")
        self.assertEqual(normalize_prompt_format("自然语言"), "natural_language")
        self.assertEqual(normalize_prompt_format("traditional"), "traditional")
        self.assertEqual(normalize_prompt_format("unknown"), "traditional")

    def test_extract_positive_negative(self):
        pos, neg = extract_positive_negative("1girl, smiling")
        self.assertEqual(pos, "1girl, smiling")
        self.assertEqual(neg, "")

        pos, neg = extract_positive_negative("Positive prompt: 1girl, cute Negative prompt: bad hands, blurry")
        self.assertEqual(pos, "1girl, cute")
        self.assertEqual(neg, "bad hands, blurry")

    def test_format_prompt_for_backend_nai(self):
        prepared, neg = format_prompt_for_backend(
            prompt="1girl, {masterpiece}",
            mode="nai",
            fixed_positive="solo",
            fixed_negative="lowres",
            scene_hint="afternoon study, quiet",
        )
        self.assertIn("solo", prepared)
        self.assertIn("afternoon study, quiet", prepared)
        self.assertIn("1girl, {masterpiece}", prepared)
        self.assertEqual(neg, "lowres")

    def test_format_prompt_for_backend_natural(self):
        prepared, neg = format_prompt_for_backend(
            prompt="smiling under cherry blossom tree",
            mode="natural_language",
            fixed_positive="anime girl",
            fixed_negative="ugly, deformed",
        )
        self.assertIn("A high quality illustration depicting", prepared)
        self.assertIn("Avoid ugly, deformed", prepared)
        self.assertIsNone(neg)

    def test_format_instruction(self):
        inst_nai = get_prompt_format_instruction("nai")
        self.assertIn("NovelAI 4/4.5", inst_nai)
        inst_nat = get_prompt_format_instruction("natural_language")
        self.assertIn("自然语言描述", inst_nat)


class TestNAIBridgeClient(unittest.TestCase):
    def test_resolve_api_via_sys_modules(self):
        fake_api = SimpleNamespace(
            status=lambda: {"enabled": True, "token_configured": True},
            capability_status=lambda owner: {"installed": True, "enabled": True, "available": True, "reason": "ready"},
        )
        mod_name = "astrbot_plugin_nai_image.main"
        previous = sys.modules.get(mod_name)
        sys.modules[mod_name] = SimpleNamespace(get_nai_image_api=lambda: fake_api)

        try:
            client = NAIBridgeClient(context=None)
            api = client.resolve_api(force_refresh=True)
            self.assertIs(api, fake_api)

            status = client.get_status()
            self.assertTrue(status["installed"])
            self.assertTrue(status["available"])
            self.assertEqual(status["reason"], "ready")
        finally:
            if previous is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = previous

    def test_resolve_api_via_context_star_registry(self):
        fake_api = SimpleNamespace(
            status=lambda: {"enabled": True},
            capability_status=lambda owner: {"installed": True, "available": True},
        )
        mock_star = SimpleNamespace(extension_api=fake_api)
        mock_context = SimpleNamespace(
            get_registered_star=lambda name: mock_star if name == "astrbot_plugin_nai_image" else None,
            get_all_stars=lambda: [mock_star],
        )

        client = NAIBridgeClient(context=mock_context)
        api = client.resolve_api(force_refresh=True)
        self.assertIs(api, fake_api)

    def test_uninstalled_status(self):
        client = NAIBridgeClient(context=None)
        client.resolve_api = lambda force_refresh=False: None

        status = client.get_status()
        self.assertFalse(status["installed"])
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "not_installed_or_unloaded")

    def test_generate_delegates_to_companion_api(self):
        received_req = {}

        class FakeApi:
            async def generate_for_companion(self, owner, request):
                received_req.update(request)
                return {
                    "handled": True,
                    "backend": "NAI 生图",
                    "image_path": "/tmp/test.png",
                    "note": "生成完成",
                    "metadata": {"trace": "test-123"},
                }

        client = NAIBridgeClient(context=None)
        client.resolve_api = lambda force_refresh=False: FakeApi()

        async def run_gen():
            return await client.generate({"prompt_text": "1girl", "workflow_kind": "selfie"})

        res = asyncio.run(run_gen())
        self.assertTrue(res["success"])
        self.assertEqual(res["image_path"], "/tmp/test.png")
        self.assertEqual(received_req.get("workflow_kind"), "selfie")


class TestNAIBridgeManager(unittest.TestCase):
    def test_manager_generate_with_schedule_context(self):
        # Mock ScheduleManager with active segment
        mock_seg = SimpleNamespace(id="morning", name="早读", activity="正在阳台晨读英语", state="精力充沛")
        mock_today = SimpleNamespace(find_active_item=lambda: mock_seg)
        mock_sched_mgr = SimpleNamespace(today_schedule=mock_today)

        # Mock BridgeClient
        captured_payload = {}
        class MockBridgeClient:
            def __init__(self, ctx):
                pass
            def get_status(self):
                return {"installed": True, "available": True}
            async def generate(self, payload):
                captured_payload.update(payload)
                return {
                    "handled": True,
                    "success": True,
                    "image_path": "/path/to/pic.png",
                    "note": "ok",
                    "metadata": {},
                }

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            mgr = NAIBridgeManager(
                context=None,
                config={"nai_link_enabled": True, "nai_prompt_format": "nai"},
                logger_=MagicMock(),
                schedule_manager=mock_sched_mgr,
                data_dir=Path(td),
            )
            mgr.bridge_client = MockBridgeClient(None)

            async def run_mgr_gen():
                return await mgr.generate_image(
                    prompt="smile, looking at viewer",
                    workflow_kind="selfie",
                )

            res = asyncio.run(run_mgr_gen())
            self.assertTrue(res.success)
            self.assertEqual(res.image_path, "/path/to/pic.png")
            # Verify schedule context was injected
            self.assertIn("正在阳台晨读英语", captured_payload["prompt_text"])
            self.assertIn("精力充沛", captured_payload["prompt_text"])


class TestNAIBridgeWebApi(unittest.TestCase):
    def test_web_api_routes(self):
        routes = []
        mock_context = SimpleNamespace(
            register_web_api=lambda r, h, m, d: routes.append((r, m))
        )
        mgr = SimpleNamespace(
            bridge_client=SimpleNamespace(get_status=lambda: {"installed": True}),
            get_active_schedule_scene_hint=lambda: "reading",
            config=NAIBridgeConfig(),
        )
        api = NAIBridgeWebApi(mgr, MagicMock())
        api.register_routes(mock_context)

        route_paths = [r[0] for r in routes]
        self.assertIn("/astrbot_plugin_personated/nai-bridge/status", route_paths)
        self.assertIn("/nai-bridge/status", route_paths)
        self.assertIn("/nai-bridge/config", route_paths)
        self.assertIn("/nai-bridge/test-generate", route_paths)


if __name__ == "__main__":
    unittest.main()
