from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "usage_meter_plugin",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
plugin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


class _Connection:
    def close(self):
        pass


class _Context:
    def __init__(self):
        self.tools = []
        self.hooks = []
        self.sections = []
        self.skills = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_system_prompt_section(self, section_id, content, **kwargs):
        self.sections.append((section_id, content, kwargs))

    def register_skill(self, name, path, **kwargs):
        self.skills.append((name, path, kwargs))


class PluginRegistrationTests(unittest.TestCase):
    def test_registers_deferred_tool_and_cache_safe_discovery_instruction(self):
        ctx = _Context()
        with mock.patch.object(plugin.meter, "connect_meter", return_value=_Connection()):
            plugin.register(ctx)

        self.assertEqual([entry["name"] for entry in ctx.tools], ["usage_meter"])
        self.assertEqual([entry[0] for entry in ctx.hooks], ["post_llm_call"])
        self.assertEqual([entry[0] for entry in ctx.skills], ["usage-meter"])
        self.assertEqual(len(ctx.sections), 1)
        section_id, content, options = ctx.sections[0]
        self.assertEqual(section_id, "usage-meter.discovery")
        self.assertIn("tool_search", content)
        self.assertIn("tool_describe", content)
        self.assertIn("tool_call", content)
        self.assertIn("usage_meter", content)
        self.assertLessEqual(len(content), options["max_chars"])


if __name__ == "__main__":
    unittest.main()
