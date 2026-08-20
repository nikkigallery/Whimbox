import hashlib
import re
from threading import Event
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model
from typing_extensions import Literal

from whimbox.plugins.registry import PluginRegistry


_LLM_TOOL_NAME_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9_-]+")
_LLM_TOOL_NAME_MAX_LENGTH = 64


def _build_llm_tool_name(tool_id: str, used_names: set[str]) -> str:
    """Build a provider-compatible, unique name without changing the tool id."""
    base_name = _LLM_TOOL_NAME_INVALID_CHARS.sub("_", tool_id).strip("_-") or "tool"
    candidate = base_name[:_LLM_TOOL_NAME_MAX_LENGTH]

    if candidate in used_names:
        digest = hashlib.sha1(tool_id.encode("utf-8")).hexdigest()[:8]
        suffix = f"_{digest}"
        candidate = f"{base_name[: _LLM_TOOL_NAME_MAX_LENGTH - len(suffix)]}{suffix}"
        collision_index = 2
        while candidate in used_names:
            suffix = f"_{digest}_{collision_index}"
            candidate = f"{base_name[: _LLM_TOOL_NAME_MAX_LENGTH - len(suffix)]}{suffix}"
            collision_index += 1

    used_names.add(candidate)
    return candidate


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
    used_llm_names: set[str] = set()
    for tool_meta in registry.list_tools():
        tool_id = tool_meta.get("tool_id")
        if not tool_id:
            continue

        display_name = str(tool_meta.get("name") or tool_id).strip()
        llm_name = _build_llm_tool_name(str(tool_id), used_llm_names)
        description = str(tool_meta.get("description") or "").strip()
        if display_name and display_name != str(tool_id):
            description = f"{display_name}。{description}" if description else display_name
        ui_behavior = tool_meta.get("ui_behavior") or "silent"
        input_schema = tool_meta.get("input_schema") or {}
        model_name = f"Args_{llm_name.replace('-', '_')}"
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
                name=llm_name,
                description=description,
                args_schema=args_schema,
                metadata={
                    "tool_id": tool_id,
                    "display_name": display_name,
                    "ui_behavior": ui_behavior,
                },
            )
        )
    return tools

