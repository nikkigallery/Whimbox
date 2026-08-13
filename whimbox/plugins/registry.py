from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Dict, List, Optional

from whimbox.tool_invocation_coordinator import tool_invocation_coordinator


class ToolRegistryError(Exception):
    pass


@dataclass
class ToolSpec:
    tool_id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    func: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
    plugin_id: str
    permissions: List[str]
    ui_behavior: str


class PluginRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._plugins: Dict[str, Dict[str, Any]] = {}

    def clear(self) -> None:
        self._tools.clear()
        self._plugins.clear()

    def register_plugin(self, plugin_meta: Dict[str, Any]) -> None:
        plugin_id = plugin_meta.get("id")
        if not plugin_id:
            raise ToolRegistryError("plugin_meta.id is required")
        if plugin_id in self._plugins:
            raise ToolRegistryError(f"plugin already registered: {plugin_id}")
        self._plugins[plugin_id] = plugin_meta

    def register(
        self,
        tool_id: str,
        func: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        input_schema: Dict[str, Any],
        output_schema: Dict[str, Any],
        name: Optional[str] = None,
        description: str = "",
        plugin_id: str = "",
        permissions: Optional[List[str]] = None,
        ui_behavior: str = "",
    ) -> None:
        if tool_id in self._tools:
            raise ToolRegistryError(f"tool already registered: {tool_id}")
        if not plugin_id:
            raise ToolRegistryError("plugin_id is required")
        resolved_permissions = permissions or []
        resolved_ui_behavior = ui_behavior or _resolve_ui_behavior(resolved_permissions)
        if resolved_ui_behavior not in {"silent", "game_overlay"}:
            raise ToolRegistryError(f"invalid ui_behavior: {resolved_ui_behavior}")
        tool_spec = ToolSpec(
            tool_id=tool_id,
            name=name or tool_id,
            description=description or "",
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            func=func,
            plugin_id=plugin_id,
            permissions=resolved_permissions,
            ui_behavior=resolved_ui_behavior,
        )
        self._tools[tool_id] = tool_spec

    def list_tools(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for spec in self._tools.values():
            items.append(
                {
                    "tool_id": spec.tool_id,
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "output_schema": spec.output_schema,
                    "plugin_id": spec.plugin_id,
                    "permissions": spec.permissions,
                    "ui_behavior": spec.ui_behavior,
                }
            )
        return items

    def get_tool_metadata(self, tool_id: str) -> Dict[str, Any]:
        spec = self._tools.get(tool_id)
        if spec is None:
            return {}
        return {
            "tool_id": spec.tool_id,
            "permissions": list(spec.permissions),
            "ui_behavior": spec.ui_behavior,
        }

    def invoke(
        self,
        tool_id: str,
        session_id: str,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if tool_id not in self._tools:
            raise ToolRegistryError(f"tool not found: {tool_id}")
        spec = self._tools[tool_id]
        resolved_context = context or {}
        stop_event = resolved_context.get("stop_event")
        if not isinstance(stop_event, Event):
            stop_event = None
        invocation_source = str(resolved_context.get("invocation_source") or "agent")
        wait_policy = str(resolved_context.get("wait_policy") or "wait")
        on_wait = resolved_context.get("on_wait")
        if not callable(on_wait):
            on_wait = None
        resource_group = _resolve_resource_group(spec.permissions)
        owner = str(
            resolved_context.get("run_id")
            or resolved_context.get("tool_call_id")
            or f"{invocation_source}:{session_id}:{tool_id}"
        )
        with tool_invocation_coordinator.hold_sync(
            resource_group=resource_group,
            owner=owner,
            wait_policy=wait_policy,
            stop_event=stop_event,
            on_wait=on_wait,
        ) as acquire_result:
            if not acquire_result.acquired:
                if acquire_result.reason == "stopped":
                    return {"status": "stop", "message": "任务已停止"}
                return {
                    "status": "busy",
                    "message": f"resource group is occupied: {resource_group}",
                }
            resolved_context = {**resolved_context, "resource_group": resource_group}
            return spec.func(session_id=session_id, input=input_data, context=resolved_context)


def _resolve_resource_group(permissions: List[str]) -> str:
    values = set(permissions or [])
    if "screen" in values or "input" in values:
        return "game_runtime"
    return "default"


def _resolve_ui_behavior(permissions: List[str]) -> str:
    return "game_overlay" if _resolve_resource_group(permissions) == "game_runtime" else "silent"

