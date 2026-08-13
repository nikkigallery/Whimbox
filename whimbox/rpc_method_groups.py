from __future__ import annotations

import json
import os
from typing import Any, Dict

from whimbox.common.path_lib import ASSETS_PATH
from whimbox.common.scripts_manager import scripts_manager
from whimbox.config.config import global_config
from whimbox.config.default_config import DEFAULT_CONFIG
from whimbox.event_bus import emit_event
from whimbox.task.background_task import BackgroundFeature, background_manager
from whimbox.weixin_service import weixin_service


UNHANDLED = object()

_setting_options_cache: Dict[str, Any] | None = None
_material_options_cache: list[str] | None = None


def handle_script_method(method: str, params: Dict[str, Any]) -> Any:
    if method == "script.query_path":
        name = params.get("name")
        target = params.get("target")
        nav_type = params.get("type")
        count = params.get("count")
        show_default = bool(params.get("show_default", False))
        if isinstance(count, str):
            try:
                count = int(count)
            except ValueError as exc:
                raise ValueError("count must be a number") from exc
        paths = scripts_manager.query_path(
            name=name,
            target=target,
            type=nav_type,
            count=count,
            return_one=False,
            show_default=show_default,
        )
        return [
            {
                "info": _serialize_script_info(record),
                "loops": [loop.model_dump() for loop in record.loops],
            }
            for record in paths
        ]

    if method == "script.query_macro":
        name = params.get("name")
        is_play_music = bool(params.get("is_play_music", False))
        show_default = bool(params.get("show_default", False))
        macros = scripts_manager.query_macro(
            name=name,
            is_play_music=is_play_music,
            return_one=False,
            show_default=show_default,
        )
        return [{"info": _serialize_script_info(record)} for record in macros]

    if method == "script.delete":
        name = params.get("name")
        category = params.get("category")
        if not name:
            raise ValueError("name is required")
        if category not in ("path", "macro", "music"):
            raise ValueError("category must be one of: path, macro, music")
        if category == "path":
            deleted = scripts_manager.delete_path(name)
        else:
            deleted = scripts_manager.delete_macro(name)
        return {"deleted": deleted}

    if method == "script.refresh":
        snapshot = scripts_manager.init_scripts_dict()
        emit_event("event.scripts.changed", {**snapshot, "source": "manual"})
        return {"ok": True, **snapshot}

    return UNHANDLED


def handle_config_method(method: str, params: Dict[str, Any]) -> Any:
    if method == "config.get":
        path = params.get("path", "OneDragon")
        value = _get_config_value(path)
        return {"path": path, "value": value}

    if method == "config.meta":
        section = params.get("section", "OneDragon")
        if section not in DEFAULT_CONFIG:
            raise ValueError(f"config section not found: {section}")
        setting_options = _load_setting_options()
        material_options = _load_material_options()
        items = []
        for key, item in DEFAULT_CONFIG.get(section, {}).items():
            value = item.get("value")
            meta_item = {
                "key": key,
                "description": item.get("description", ""),
                "type": _infer_config_type(value),
            }
            if key in setting_options:
                meta_item["options"] = setting_options.get(key, [])
            if key in ("jihua_cost", "jihua_cost_2", "jihua_cost_3"):
                meta_item["options"] = material_options
            items.append(meta_item)
        return {"section": section, "items": items}

    if method == "config.update":
        updates = params.get("updates")
        if updates is not None:
            if not isinstance(updates, list):
                raise ValueError("updates must be a list")
            for item in updates:
                if not isinstance(item, dict):
                    raise ValueError("update item must be object")
                _apply_config_update(item.get("path"), item.get("value"))
        else:
            _apply_config_update(params.get("path"), params.get("value"))
        if not global_config.save():
            raise ValueError("config save failed")
        return {"ok": True}

    if method == "one_dragon.flow.get":
        pre_custom_steps = _get_one_dragon_pre_custom_steps()
        post_custom_steps = _get_one_dragon_post_custom_steps()
        return {
            "default_steps": _get_one_dragon_default_steps(),
            "pre_custom_steps": pre_custom_steps,
            "post_custom_steps": post_custom_steps,
            "custom_steps": post_custom_steps,
        }

    if method == "one_dragon.flow.update":
        _update_one_dragon_flow(
            default_steps=params.get("default_steps"),
            pre_custom_steps=params.get("pre_custom_steps"),
            post_custom_steps=params.get("post_custom_steps"),
        )
        pre_custom_steps = _get_one_dragon_pre_custom_steps()
        post_custom_steps = _get_one_dragon_post_custom_steps()
        return {
            "ok": True,
            "default_steps": _get_one_dragon_default_steps(),
            "pre_custom_steps": pre_custom_steps,
            "post_custom_steps": post_custom_steps,
            "custom_steps": post_custom_steps,
        }

    return UNHANDLED


def handle_background_method(method: str, params: Dict[str, Any]) -> Any:
    if method == "background.get":
        return _get_background_state()

    if method == "background.set":
        updates = params.get("updates")
        if updates is not None:
            if not isinstance(updates, list):
                raise ValueError("updates must be a list")
            for item in updates:
                if not isinstance(item, dict):
                    raise ValueError("update item must be object")
                _set_background_feature(
                    item.get("feature"), bool(item.get("enabled"))
                )
        else:
            _set_background_feature(
                params.get("feature"), bool(params.get("enabled"))
            )
        return _get_background_state()

    return UNHANDLED


def handle_map_mask_method(method: str, params: Dict[str, Any]) -> Any:
    if not method.startswith("map_mask."):
        return UNHANDLED

    if method == "map_mask.get_game_window_state":
        from whimbox.common.handle_lib import HANDLE_OBJ

        if not HANDLE_OBJ.is_alive():
            HANDLE_OBJ.refresh_handle()

        found = bool(HANDLE_OBJ.is_alive())
        physical_x, physical_y, physical_width, physical_height = (
            HANDLE_OBJ.get_window_rect() if found else (0, 0, 0, 0)
        )
        scale_factor = HANDLE_OBJ.get_window_scale_factor() if found else 1.0
        if scale_factor <= 0:
            scale_factor = 1.0
        x = round(physical_x / scale_factor)
        y = round(physical_y / scale_factor)
        width = round(physical_width / scale_factor)
        height = round(physical_height / scale_factor)
        return {
            "found": found,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "isForeground": HANDLE_OBJ.is_foreground() if found else False,
            "isMinimized": bool(HANDLE_OBJ.is_minimized()) if found else False,
        }

    from whimbox.map.mask.service import map_mask_service

    if method == "map_mask.get_labels":
        return {
            "labels": map_mask_service.get_labels(),
            "selected_label_ids": map_mask_service.get_selected_label_ids(),
        }

    if method == "map_mask.set_selected_labels":
        label_ids = params.get("selected_label_ids", params.get("label_ids", []))
        if not isinstance(label_ids, list):
            raise ValueError("selected_label_ids must be a list")
        return map_mask_service.set_selected_label_ids([str(item) for item in label_ids])

    if method == "map_mask.get_visible_points":
        return map_mask_service.get_visible_points(
            viewport=_parse_map_mask_viewport(params.get("viewport")),
            map_name=_parse_optional_string(params.get("map_name")),
            label_ids=_parse_optional_string_list(params.get("label_ids")),
        )

    if method == "map_mask.get_user_status":
        return map_mask_service.get_user_status()

    if method == "map_mask.start_pearpal_login":
        return map_mask_service.start_pearpal_login()

    if method == "map_mask.refresh_pearpal_user_state":
        return map_mask_service.refresh_pearpal_user_state()

    if method == "map_mask.disconnect_pearpal_user":
        return map_mask_service.disconnect_pearpal_user()

    if method == "map_mask.clear_pearpal_login":
        return map_mask_service.clear_pearpal_login_information()

    if method == "map_mask.set_hide_awarded":
        return map_mask_service.set_hide_awarded(
            _coerce_bool(params.get("hide_awarded", True))
        )

    return UNHANDLED


async def handle_weixin_method(method: str, params: Dict[str, Any]) -> Any:
    if method == "weixin.login.start":
        return await weixin_service.start_login()

    if method == "weixin.login.poll":
        return await weixin_service.poll_login()

    if method == "weixin.status.get":
        return weixin_service.get_status()

    if method == "weixin.monitor.start":
        return await weixin_service.start_monitor()

    if method == "weixin.monitor.stop":
        return await weixin_service.stop_monitor()

    if method == "weixin.disconnect":
        return await weixin_service.disconnect()

    return UNHANDLED


def _parse_map_mask_viewport(value: Any):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("viewport must be an object")
    from whimbox.map.mask.models import MapMaskViewport

    return MapMaskViewport.from_dict(value)


def _parse_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_optional_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("label_ids must be a list")
    return [str(item) for item in value]


def _load_setting_options() -> Dict[str, Any]:
    global _setting_options_cache
    if _setting_options_cache is not None:
        return _setting_options_cache
    try:
        path = os.path.join(ASSETS_PATH, "setting_options.json")
        with open(path, "r", encoding="utf-8") as f:
            _setting_options_cache = json.load(f)
    except Exception:
        _setting_options_cache = {}
    return _setting_options_cache


def _load_material_options() -> list[str]:
    global _material_options_cache
    if _material_options_cache is not None:
        return _material_options_cache
    try:
        path = os.path.join(ASSETS_PATH, "material.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _material_options_cache = list(data.keys())
    except Exception:
        _material_options_cache = []
    return _material_options_cache


def _infer_config_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("true", "false"):
            return "boolean"
        numeric = value.replace(".", "", 1).replace("-", "", 1)
        if numeric.isdigit():
            return "number"
    return "string"


def _serialize_script_info(record: Any) -> Dict[str, Any]:
    info = getattr(record, "info", None)
    if info is None:
        return {}
    try:
        return info.model_dump()
    except Exception:
        return {}


def _get_background_state() -> Dict[str, Any]:
    feature_keys = {feature.value for feature in BackgroundFeature}
    feature_items = [
        {
            "key": key,
            "label": item.get("description", key),
            "description": item.get("description", ""),
            "type": _infer_config_type(item.get("value")),
        }
        for key, item in (DEFAULT_CONFIG.get("BackgroundTask") or {}).items()
        if key in feature_keys
    ]
    return {
        "running": background_manager.is_running(),
        "features": {
            feature.value: background_manager.is_feature_enabled(feature)
            for feature in BackgroundFeature
        },
        "feature_items": feature_items,
    }


def _set_background_feature(feature_key: str, enabled: bool) -> None:
    try:
        feature = BackgroundFeature(feature_key)
    except ValueError as exc:
        raise ValueError(f"invalid feature: {feature_key}") from exc
    background_manager.set_feature_enabled(feature, enabled)
    any_enabled = any(
        background_manager.is_feature_enabled(item) for item in BackgroundFeature
    )
    if any_enabled and not background_manager.is_running():
        background_manager.start_background_task()
    elif not any_enabled and background_manager.is_running():
        background_manager.stop_background_task()


def _split_config_path(path: str) -> list[str]:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path is required")
    return [part for part in path.split(".") if part]


def _get_config_value(path: str) -> Any:
    parts = _split_config_path(path)
    if len(parts) == 1:
        section = global_config.config.get(parts[0])
        if section is None:
            raise ValueError(f"config section not found: {parts[0]}")
        return section
    if len(parts) == 2:
        section = global_config.config.get(parts[0]) or {}
        if parts[1] not in section:
            raise ValueError(f"config key not found: {path}")
        return section.get(parts[1])
    raise ValueError("path must be in 'Section' or 'Section.key' format")


def _apply_config_update(path: str, value: Any) -> None:
    parts = _split_config_path(path)
    if len(parts) != 2:
        raise ValueError("update path must be in 'Section.key' format")
    section, key = parts
    global_config.set(section, key, value)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _get_one_dragon_default_steps() -> list[Dict[str, Any]]:
    section = global_config.config.get("OneDragonDefaultSteps") or {}
    defaults = DEFAULT_CONFIG.get("OneDragonDefaultSteps") or {}
    items = []
    for key, default_item in defaults.items():
        item = section.get(key) or {}
        items.append(
            {
                "key": key,
                "label": str(
                    item.get("description")
                    or default_item.get("description")
                    or key
                ),
                "enabled": _coerce_bool(item.get("value", default_item.get("value"))),
            }
        )
    return items


def _normalize_one_dragon_custom_step(step: Any) -> Dict[str, Any]:
    if not isinstance(step, dict):
        raise ValueError("custom step must be an object")
    step_id = str(step.get("id") or "").strip()
    if not step_id:
        raise ValueError("custom step id is required")
    step_type = str(step.get("type") or "").strip()
    if step_type not in ("path", "macro"):
        raise ValueError("custom step type must be one of: path, macro")
    script_name = str(step.get("script_name") or "").strip()
    return {
        "id": step_id,
        "enabled": _coerce_bool(step.get("enabled", True)),
        "type": step_type,
        "script_name": script_name,
    }


def _get_one_dragon_custom_steps_from_section(section_name: str) -> list[Dict[str, Any]]:
    raw_items = []
    try:
        raw_items = global_config.get(section_name, "items", [])
    except Exception:
        raw_items = []
    if not isinstance(raw_items, list):
        return []
    items = []
    for item in raw_items:
        try:
            items.append(_normalize_one_dragon_custom_step(item))
        except ValueError:
            continue
    return items


def _get_one_dragon_pre_custom_steps() -> list[Dict[str, Any]]:
    return _get_one_dragon_custom_steps_from_section("OneDragonPreCustomSteps")


def _get_one_dragon_post_custom_steps() -> list[Dict[str, Any]]:
    post_items = _get_one_dragon_custom_steps_from_section("OneDragonPostCustomSteps")
    if post_items:
        return post_items
    legacy_items = _get_one_dragon_custom_steps_from_section("OneDragonCustomSteps")
    if _get_one_dragon_pre_custom_steps():
        return post_items
    return legacy_items


def _update_one_dragon_flow(
    default_steps: Any = None,
    pre_custom_steps: Any = None,
    post_custom_steps: Any = None,
) -> None:
    valid_default_keys = set((DEFAULT_CONFIG.get("OneDragonDefaultSteps") or {}).keys())

    if default_steps is not None:
        if not isinstance(default_steps, dict):
            raise ValueError("default_steps must be an object")
        for key, enabled in default_steps.items():
            if key not in valid_default_keys:
                raise ValueError(f"invalid default step: {key}")
            global_config.set("OneDragonDefaultSteps", key, "true" if _coerce_bool(enabled) else "false")

    if pre_custom_steps is not None:
        if not isinstance(pre_custom_steps, list):
            raise ValueError("pre_custom_steps must be a list")
        normalized_pre_steps = [_normalize_one_dragon_custom_step(item) for item in pre_custom_steps]
        global_config.set("OneDragonPreCustomSteps", "items", normalized_pre_steps)

    if post_custom_steps is not None:
        if not isinstance(post_custom_steps, list):
            raise ValueError("post_custom_steps must be a list")
        normalized_post_steps = [_normalize_one_dragon_custom_step(item) for item in post_custom_steps]
        global_config.set("OneDragonPostCustomSteps", "items", normalized_post_steps)

    if pre_custom_steps is not None or post_custom_steps is not None:
        global_config.set("OneDragonCustomSteps", "items", [])

    if not global_config.save():
        raise ValueError("config save failed")
