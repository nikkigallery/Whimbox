from typing import Any, Dict

from whimbox.config.config import global_config


DEFAULT_FLOW_ID = "default"
DEFAULT_FLOW_NAME = "默认流程"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def normalize_custom_flow_step(step: Any) -> Dict[str, Any]:
    if not isinstance(step, dict):
        raise ValueError("custom flow step must be an object")
    step_id = str(step.get("id") or "").strip()
    if not step_id:
        raise ValueError("custom flow step id is required")
    step_type = str(step.get("type") or "").strip()
    if step_type not in ("path", "macro"):
        raise ValueError("custom flow step type must be one of: path, macro")
    return {
        "id": step_id,
        "enabled": _coerce_bool(step.get("enabled", True)),
        "type": step_type,
        "script_name": str(step.get("script_name") or "").strip(),
    }


def normalize_custom_flow(flow: Any) -> Dict[str, Any]:
    if not isinstance(flow, dict):
        raise ValueError("custom flow must be an object")
    flow_id = str(flow.get("id") or "").strip()
    if not flow_id:
        raise ValueError("custom flow id is required")
    name = str(flow.get("name") or "").strip()
    if not name:
        raise ValueError("custom flow name is required")
    raw_items = flow.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("custom flow items must be a list")
    return {
        "id": flow_id,
        "name": name,
        "items": [normalize_custom_flow_step(item) for item in raw_items],
    }


def _get_legacy_items() -> list[Dict[str, Any]]:
    raw_items = global_config.get("CustomFlow", "items", [])
    if not isinstance(raw_items, list):
        return []
    items = []
    for item in raw_items:
        try:
            items.append(normalize_custom_flow_step(item))
        except ValueError:
            continue
    return items


def get_custom_flow_state() -> Dict[str, Any]:
    raw_flows = global_config.get("CustomFlow", "flows", [])
    flows = []
    seen_ids = set()
    if isinstance(raw_flows, list):
        for raw_flow in raw_flows:
            try:
                flow = normalize_custom_flow(raw_flow)
            except ValueError:
                continue
            if flow["id"] in seen_ids:
                continue
            seen_ids.add(flow["id"])
            flows.append(flow)

    if not flows:
        flows = [
            {
                "id": DEFAULT_FLOW_ID,
                "name": DEFAULT_FLOW_NAME,
                "items": _get_legacy_items(),
            }
        ]

    active_flow_id = str(
        global_config.get("CustomFlow", "active_flow_id", "") or ""
    ).strip()
    if active_flow_id not in {flow["id"] for flow in flows}:
        active_flow_id = flows[0]["id"]

    return {"flows": flows, "active_flow_id": active_flow_id}


def save_custom_flow_state(flows: Any, active_flow_id: Any) -> Dict[str, Any]:
    if not isinstance(flows, list) or not flows:
        raise ValueError("flows must be a non-empty list")

    normalized_flows = []
    seen_ids = set()
    for raw_flow in flows:
        flow = normalize_custom_flow(raw_flow)
        if flow["id"] in seen_ids:
            raise ValueError(f'duplicate custom flow id: {flow["id"]}')
        seen_ids.add(flow["id"])
        normalized_flows.append(flow)

    normalized_active_flow_id = str(active_flow_id or "").strip()
    if normalized_active_flow_id not in seen_ids:
        normalized_active_flow_id = normalized_flows[0]["id"]

    global_config.set("CustomFlow", "flows", normalized_flows)
    global_config.set("CustomFlow", "active_flow_id", normalized_active_flow_id)
    global_config.set("CustomFlow", "items", [])
    if not global_config.save():
        raise ValueError("config save failed")

    return {
        "flows": normalized_flows,
        "active_flow_id": normalized_active_flow_id,
    }


def get_custom_flow_items(flow_id: str | None = None) -> list[Dict[str, Any]]:
    state = get_custom_flow_state()
    target_flow_id = str(flow_id or state["active_flow_id"]).strip()
    for flow in state["flows"]:
        if flow["id"] == target_flow_id:
            return flow["items"]
    return []
