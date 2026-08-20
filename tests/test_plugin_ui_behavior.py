import json
import unittest
from pathlib import Path

from whimbox.plugin_tools import build_tools
from whimbox.plugins.registry import PluginRegistry, ToolRegistryError


def _success_tool(session_id, input, context):
    return {"status": "success"}


class PluginUiBehaviorTests(unittest.TestCase):
    def test_ui_behavior_defaults_from_permissions(self):
        registry = PluginRegistry()
        registry.register(
            tool_id="test.game",
            func=_success_tool,
            input_schema={},
            output_schema={},
            plugin_id="test",
            permissions=["screen"],
        )
        registry.register(
            tool_id="test.silent",
            func=_success_tool,
            input_schema={},
            output_schema={},
            plugin_id="test",
            permissions=[],
        )

        self.assertEqual("game_overlay", registry.get_tool_metadata("test.game")["ui_behavior"])
        self.assertEqual("silent", registry.get_tool_metadata("test.silent")["ui_behavior"])

    def test_explicit_ui_behavior_is_exposed_to_langchain_events(self):
        registry = PluginRegistry()
        registry.register(
            tool_id="test.lookup",
            func=_success_tool,
            input_schema={"type": "object", "properties": {}},
            output_schema={},
            plugin_id="test",
            permissions=[],
            ui_behavior="silent",
        )

        tools = build_tools(registry, lambda: "test-session")

        self.assertEqual(
            {
                "tool_id": "test.lookup",
                "display_name": "test.lookup",
                "ui_behavior": "silent",
            },
            tools[0].metadata,
        )

    def test_langchain_tool_name_is_provider_compatible(self):
        registry = PluginRegistry()
        registry.register(
            tool_id="test.lookup-item",
            name="查询物品",
            description="按名称查询物品。",
            func=_success_tool,
            input_schema={"type": "object", "properties": {}},
            output_schema={},
            plugin_id="test",
            permissions=[],
        )

        tool = build_tools(registry, lambda: "test-session")[0]

        self.assertEqual("test_lookup-item", tool.name)
        self.assertEqual("查询物品。按名称查询物品。", tool.description)
        self.assertEqual("test.lookup-item", tool.metadata["tool_id"])
        self.assertEqual("查询物品", tool.metadata["display_name"])

    def test_invalid_ui_behavior_is_rejected(self):
        registry = PluginRegistry()
        with self.assertRaises(ToolRegistryError):
            registry.register(
                tool_id="test.invalid",
                func=_success_tool,
                input_schema={},
                output_schema={},
                plugin_id="test",
                ui_behavior="popup",
            )

    def test_non_game_nikki_tools_are_silent(self):
        manifest_path = (
            Path(__file__).parents[1]
            / "whimbox"
            / "plugins"
            / "game_nikki"
            / "plugin.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tools = {item["id"]: item for item in manifest["tools"]}

        for tool_id in ("nikki.search_path", "nikki.open_path_folder"):
            self.assertEqual([], tools[tool_id]["permissions"])
            self.assertEqual("silent", tools[tool_id]["ui_behavior"])


if __name__ == "__main__":
    unittest.main()
