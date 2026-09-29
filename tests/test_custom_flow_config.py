import unittest
from unittest.mock import patch

from whimbox.common.custom_flow import (
    DEFAULT_FLOW_ID,
    get_custom_flow_state,
    save_custom_flow_state,
)


class CustomFlowConfigTests(unittest.TestCase):
    @patch("whimbox.common.custom_flow.global_config")
    def test_legacy_items_are_exposed_as_default_flow(self, global_config):
        values = {
            "flows": [],
            "active_flow_id": "",
            "items": [
                {
                    "id": "step-1",
                    "enabled": True,
                    "type": "path",
                    "script_name": "路线A",
                }
            ],
        }
        global_config.get.side_effect = (
            lambda section, key, default: values.get(key, default)
        )

        state = get_custom_flow_state()

        self.assertEqual(DEFAULT_FLOW_ID, state["active_flow_id"])
        self.assertEqual("默认流程", state["flows"][0]["name"])
        self.assertEqual(values["items"], state["flows"][0]["items"])

    @patch("whimbox.common.custom_flow.global_config")
    def test_saved_active_flow_is_restored(self, global_config):
        flows = [
            {"id": "flow-1", "name": "采集", "items": []},
            {"id": "flow-2", "name": "钓鱼", "items": []},
        ]
        values = {"flows": flows, "active_flow_id": "flow-2", "items": []}
        global_config.get.side_effect = (
            lambda section, key, default: values.get(key, default)
        )

        state = get_custom_flow_state()

        self.assertEqual(flows, state["flows"])
        self.assertEqual("flow-2", state["active_flow_id"])

    @patch("whimbox.common.custom_flow.global_config")
    def test_save_falls_back_to_first_flow_and_clears_legacy_items(
        self, global_config
    ):
        global_config.save.return_value = True
        flows = [{"id": "flow-1", "name": "采集", "items": []}]

        state = save_custom_flow_state(flows, "missing")

        self.assertEqual("flow-1", state["active_flow_id"])
        global_config.set.assert_any_call("CustomFlow", "flows", flows)
        global_config.set.assert_any_call(
            "CustomFlow", "active_flow_id", "flow-1"
        )
        global_config.set.assert_any_call("CustomFlow", "items", [])
        global_config.save.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
