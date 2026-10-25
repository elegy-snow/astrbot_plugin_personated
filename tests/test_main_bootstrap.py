# -*- coding: utf-8 -*-
"""Bootstrap tests for the plugin entry point (main.py).

The plugin is loaded by AstrBot from ``data.plugins.astrbot_plugin_personated.main``,
so these tests stub the minimal AstrBot surface required to import ``main.py`` and
then assert two contracts that previously broke the plugin at load time:

1. ``pc_generate_photo`` is registered as an LLM tool with docstring parameter
   types in the ``name(type): description`` form required by ``@filter.llm_tool``.
2. The plugin repairs a deactivated / unowned LLM tool during ``initialize()``.
"""
from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "data.plugins.astrbot_plugin_personated.main"

registered_tools: list[dict] = []


def _parse_args_block(doc: str) -> list[dict]:
    """Parse a Google-style ``Args:`` block the way docstring_parser would."""
    params: list[dict] = []
    in_args = False
    for raw_line in doc.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^(Args|Arguments|参数)\s*:\s*$", line, re.IGNORECASE):
            in_args = True
            continue
        if not in_args:
            continue
        if re.match(r"^(Returns|Yields|Raises|Examples?)\s*:", line, re.IGNORECASE):
            break
        match = re.match(r"^(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)$", line)
        if match:
            params.append(
                {
                    "arg_name": match.group(1),
                    "type_name": (match.group(2) or "").strip() or None,
                    "description": match.group(3),
                }
            )
    return params


class _FakeGroup:
    """Command group stub exposing ``.command(...)`` decorators."""

    def __getattr__(self, item):
        def decorator_factory(*args, **kwargs):
            def decorator(fn):
                return fn

            return decorator

        return decorator_factory


class _FakeFilter:
    """Minimal stand-in for ``astrbot.api.event.filter``."""

    def __getattr__(self, item):
        if item == "llm_tool":

            def llm_tool(name: str | None = None, **kwargs):
                def decorator(fn):
                    tool_name = name or fn.__name__
                    params = _parse_args_block(fn.__doc__ or "")
                    for param in params:
                        if not param["type_name"]:
                            raise ValueError(
                                f"LLM 函数工具 {fn.__module__}_{tool_name} 的参数 "
                                f"{param['arg_name']} 缺少类型注释。"
                            )
                    registered_tools.append({"name": tool_name, "params": params})
                    return fn

                return decorator

            return llm_tool

        if item == "command_group":

            def command_group(*args, **kwargs):
                def decorator(fn):
                    return _FakeGroup()

                return decorator

            return command_group

        def passthrough(*args, **kwargs):
            def decorator(fn):
                return fn

            if args and callable(args[0]):
                return args[0]
            return decorator

        return passthrough


class _FakeStar:
    """Minimal stand-in for ``astrbot.api.star.Star``."""

    def __init__(self, context=None, config=None):
        import logging

        self.context = context
        self.config = config or {}
        self.logger = logging.getLogger("astrbot.plugin.astrbot_plugin_personated")


class _FakeTool:
    def __init__(self, name: str, active: bool = False, handler_module_path=None):
        self.name = name
        self.active = active
        self.handler_module_path = handler_module_path


class _FakeToolManager:
    def __init__(self, tools: list[_FakeTool]):
        self.func_list = tools

    def get_func(self, name):
        for tool in self.func_list:
            if tool.name == name:
                return tool
        return None


class _FakeContext:
    """Context stub that reproduces AstrBot's broken tool state."""

    def __init__(self) -> None:
        self.registered_web_apis: list[tuple] = []
        self.tools = [_FakeTool("pc_generate_photo", active=False)]
        self.activate_calls: list[str] = []

    def register_web_api(self, route, handler, methods, desc):
        self.registered_web_apis.append((route, methods))

    def get_config(self, umo=None):
        return {}

    def get_all_stars(self):
        return []

    def get_registered_star(self, name):
        return None

    def get_llm_tool_manager(self):
        return _FakeToolManager(self.tools)

    async def activate_llm_tool_async(self, name):
        self.activate_calls.append(name)
        for tool in self.tools:
            if tool.name == name:
                tool.active = True
        return True


def _install_astrbot_stubs() -> None:
    """Register the fake ``astrbot`` package surface used by main.py."""
    if "astrbot" in sys.modules and getattr(
        sys.modules["astrbot"], "__is_test_stub__", False
    ):
        return

    std_logger = MagicMock()
    fake_filter = _FakeFilter()

    def mk_module(name: str, **attrs) -> None:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod

    mk_module("astrbot", logger=std_logger)
    sys.modules["astrbot"].__is_test_stub__ = True
    mk_module("astrbot.api", logger=std_logger)
    mk_module(
        "astrbot.api.event",
        AstrMessageEvent=type("AstrMessageEvent", (), {}),
        filter=fake_filter,
    )
    mk_module("astrbot.api.provider", ProviderRequest=type("ProviderRequest", (), {}))
    mk_module("astrbot.api.star", Context=object, Star=_FakeStar)
    mk_module(
        "astrbot.api.message_components",
        Image=types.SimpleNamespace(fromFileSystem=lambda p, **k: ("image", p)),
        Plain=lambda text="": ("plain", text),
    )
    mk_module(
        "astrbot.core.message.message_event_result",
        MessageChain=lambda chain=None: ("chain", chain),
    )


def _load_plugin_module():
    """Import ``main.py`` under the module path AstrBot uses."""
    _install_astrbot_stubs()
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]

    spec = importlib.util.spec_from_file_location(MODULE_NAME, PLUGIN_ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


class TestLLMToolRegistration(unittest.TestCase):
    def test_pc_generate_photo_registered_with_typed_params(self):
        _load_plugin_module()

        tools = {tool["name"]: tool for tool in registered_tools}
        self.assertIn("pc_generate_photo", tools)

        params = {p["arg_name"]: p for p in tools["pc_generate_photo"]["params"]}
        self.assertEqual(set(params), {"prompt", "kind", "size", "caption"})
        for name, param in params.items():
            # AstrBot rejects untyped docstring params at load time.
            self.assertEqual(param["type_name"], "string", f"param {name}")


class TestToolStateRepair(unittest.TestCase):
    def test_initialize_repairs_deactivated_tool(self):
        module = _load_plugin_module()
        ctx = _FakeContext()
        plugin = module.PersonatedPlugin(ctx, {})

        asyncio.run(plugin.initialize())

        tool = ctx.tools[0]
        self.assertTrue(tool.active, "tool must be reactivated")
        self.assertEqual(tool.handler_module_path, MODULE_NAME)
        self.assertEqual(ctx.activate_calls, ["pc_generate_photo"])
        self.assertTrue(plugin._nai_tool_ready)

    def test_subsystem_failure_does_not_break_initialization(self):
        module = _load_plugin_module()
        ctx = _FakeContext()
        plugin = module.PersonatedPlugin(ctx, {})

        async def _boom():
            raise RuntimeError("scheduler exploded")

        plugin.schedule_manager.initialize = _boom
        plugin.prompt_injector_mgr.initialize = _boom

        # initialize() must swallow subsystem errors; otherwise AstrBot unloads
        # the plugin and drops every registered LLM tool.
        asyncio.run(plugin.initialize())
        self.assertTrue(plugin._nai_tool_ready)

    def test_preference_prompt_injected_when_tool_ready(self):
        module = _load_plugin_module()
        ctx = _FakeContext()
        plugin = module.PersonatedPlugin(ctx, {})
        asyncio.run(plugin.initialize())

        req = types.SimpleNamespace(system_prompt="BASE")
        plugin._apply_nai_tool_preference(req)

        self.assertIn("pc_generate_photo", req.system_prompt)
        self.assertTrue(req.system_prompt.startswith("BASE"))

    def test_preference_prompt_skipped_when_tool_missing(self):
        module = _load_plugin_module()
        ctx = _FakeContext()
        ctx.tools = []
        plugin = module.PersonatedPlugin(ctx, {})
        asyncio.run(plugin.initialize())

        req = types.SimpleNamespace(system_prompt="BASE")
        plugin._apply_nai_tool_preference(req)
        self.assertEqual(req.system_prompt, "BASE")


if __name__ == "__main__":
    unittest.main()
