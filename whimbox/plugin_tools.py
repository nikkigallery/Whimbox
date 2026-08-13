from threading import Event
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model
from typing_extensions import Literal

from whimbox.plugins.registry import PluginRegistry


def _json_type_to_py(schema: Dict[str, Any]) -> Type[Any]:
    schema_type = schema.get("type", "string")
    if isinstance(schema_type, list):
        schema_type = next((t for t in schema_type if t != "null"), "string")

    if "enum" in schema:
        return Literal[tuple(schema["enum"])]

    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(schema_type, Any)


def _build_args_schema(input_schema: Dict[str, Any], model_name: str):
    properties = input_schema.get("properties", {}) if input_schema else {}
    required = set(input_schema.get("required", [])) if input_schema else set()

    fields: Dict[str, Tuple[Type[Any], Any]] = {}
    for name, prop in properties.items():
        py_type = _json_type_to_py(prop or {})
        default = ... if name in required else None
        fields[name] = (
            py_type,
            Field(default, description=(prop or {}).get("description", "")),
        )

    return create_model(model_name, **fields)


def build_tools(
    registry: PluginRegistry,
    session_id_getter: Callable[[], str],
    stop_event_getter: Optional[Callable[[], Optional[Event]]] = None,
) -> List[StructuredTool]:
    tools: List[StructuredTool] = []
    for tool_meta in registry.list_tools():
        tool_id = tool_meta.get("tool_id")
        if not tool_id:
            continue

        name = tool_meta.get("name") or tool_id
        description = tool_meta.get("description") or ""
        ui_behavior = tool_meta.get("ui_behavior") or "silent"
        input_schema = tool_meta.get("input_schema") or {}
        model_name = f"Args_{tool_id.replace('.', '_')}"
        args_schema = _build_args_schema(input_schema, model_name)

        def _make_tool_func(target_tool_id: str):
            def _tool_func(**kwargs):
                session_id = session_id_getter() or "default"
                context: Dict[str, Any] = {
                    "session_id": session_id,
                    "invocation_source": "agent",
                    "wait_policy": "wait",
                }
                if stop_event_getter is not None:
                    stop_event = stop_event_getter()
                    if stop_event is not None:
                        context["stop_event"] = stop_event
                return registry.invoke(
                    tool_id=target_tool_id,
                    session_id=session_id,
                    input_data=kwargs,
                    context=context,
                )

            return _tool_func

        tool_func = _make_tool_func(tool_id)
        tools.append(
            StructuredTool.from_function(
                func=tool_func,
                name=name,
                description=description,
                args_schema=args_schema,
                metadata={"tool_id": tool_id, "ui_behavior": ui_behavior},
            )
        )
    return tools

