import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Tuple

from .registry import PluginRegistry, ToolRegistryError


class PluginLoadError(Exception):
    pass


def _load_module_from_path(module_path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"failed to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_entry(entry: str) -> Tuple[str, str]:
    if ":" in entry:
        file_name, func_name = entry.split(":", 1)
        return file_name, func_name
    return entry, ""


def _read_plugin_meta(plugin_dir: Path) -> Dict[str, Any]:
    meta_path = plugin_dir / "plugin.json"
    if not meta_path.exists():
        raise PluginLoadError(f"plugin.json not found: {plugin_dir}")
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_plugins(
    plugins_dir: Path, registry: PluginRegistry
) -> List[Dict[str, Any]]:
    if not plugins_dir.exists():
        return []

    loaded: List[Dict[str, Any]] = []
    for plugin_dir in plugins_dir.iterdir():
        if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
            continue
        try:
            meta = _read_plugin_meta(plugin_dir)
            registry.register_plugin(meta)

            entry = meta.get("entry")
            if not entry:
                raise PluginLoadError(f"entry missing in {plugin_dir}")
            file_name, func_name = _parse_entry(entry)
            entry_path = plugin_dir / file_name
            module_name = f"whimbox_plugin_{meta.get('id', plugin_dir.name)}"
            module = _load_module_from_path(entry_path, module_name)

            if func_name:
                # 手动注册
                register_func = getattr(module, func_name, None)
                if register_func is None:
                    raise PluginLoadError(
                        f"register function not found: {entry_path}:{func_name}"
                    )
                register_func(registry, meta)
            else:
                # 自动注册
                tool_funcs = getattr(module, "TOOL_FUNCS", None)
                if not isinstance(tool_funcs, dict):
                    raise PluginLoadError(
                        f"TOOL_FUNCS not found in: {entry_path}"
                    )
                for tool_meta in meta.get("tools", []):
                    tool_id = tool_meta.get("id")
                    if not tool_id:
                        raise PluginLoadError("tool.id missing in plugin.json")
                    func = tool_funcs.get(tool_id)
                    if func is None:
                        raise PluginLoadError(
                            f"tool handler not found for: {tool_id}"
                        )
                    registry.register(
                        tool_id=tool_id,
                        func=func,
                        input_schema=tool_meta.get("input_schema", {}),
                        output_schema=tool_meta.get("output_schema", {}),
                        name=tool_meta.get("name"),
                        description=tool_meta.get("description", ""),
                        plugin_id=meta.get("id", ""),
                        permissions=tool_meta.get("permissions", meta.get("permissions", [])),
                        ui_behavior=tool_meta.get("ui_behavior", meta.get("ui_behavior", "")),
                    )
            loaded.append(meta)
        except (PluginLoadError, ToolRegistryError) as exc:
            meta_id = plugin_dir.name
            loaded.append({"id": meta_id, "error": str(exc)})
    return loaded

