from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import websockets

from .models import MapMaskViewport
from .service import map_mask_service


HOST = "127.0.0.1"
PORT = 8350


def _result_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        response["error"]["data"] = data
    return response


def _parse_viewport(value: Any) -> MapMaskViewport | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("viewport must be an object")
    return MapMaskViewport.from_dict(value)


def _dispatch(method: str, params: dict[str, Any]) -> Any:
    if method == "health":
        return {"status": "ok", "mode": "map-mask-debug"}

    if method == "agent.status":
        return {
            "ready": True,
            "status": "debug",
            "message": "Map mask debug backend is running.",
        }

    if method == "session.create":
        return {"session_id": "map-mask-debug"}

    if method == "session.list":
        return [
            {
                "session_id": "map-mask-debug",
                "name": "map-mask-debug",
                "profile": "debug",
                "state": "OPEN",
            }
        ]

    if method == "map_mask.get_state":
        return map_mask_service.get_state(viewport=_parse_viewport(params.get("viewport")))

    if method == "map_mask.get_labels":
        return {
            "labels": map_mask_service.get_labels(),
            "selected_label_ids": map_mask_service.get_selected_label_ids(),
        }

    if method == "map_mask.set_selected_labels":
        label_ids = params.get("label_ids")
        if not isinstance(label_ids, list):
            raise ValueError("label_ids must be a list")
        return map_mask_service.set_selected_label_ids([str(item) for item in label_ids])

    if method == "map_mask.get_visible_points":
        return map_mask_service.get_visible_points(
            viewport=_parse_viewport(params.get("viewport")),
            map_name=params.get("map_name") if isinstance(params.get("map_name"), str) else None,
        )

    if method == "map_mask.get_point_detail":
        point_id = params.get("point_id")
        if not isinstance(point_id, str) or not point_id:
            raise ValueError("point_id is required")
        return map_mask_service.get_point_detail(point_id)

    if method == "map_mask.set_enabled":
        return map_mask_service.set_enabled(bool(params.get("enabled", True)))

    if method == "map_mask.set_bigmap_detection_mode":
        mode = params.get("mode")
        if not isinstance(mode, str) or not mode:
            raise ValueError("mode is required")
        return map_mask_service.set_bigmap_detection_mode(mode)

    raise NotImplementedError(f"method not found: {method}")


async def _handle_message(message: str) -> dict[str, Any] | None:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return _error_response(None, -32700, "Parse error")

    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
        return _error_response(None, -32600, "Invalid Request")

    request_id = data.get("id")
    method = data.get("method")
    params = data.get("params") or {}

    if request_id is None:
        return None
    if not isinstance(method, str) or not method:
        return _error_response(request_id, -32600, "Invalid Request")
    if not isinstance(params, dict):
        return _error_response(request_id, -32602, "Invalid params")

    try:
        return _result_response(request_id, _dispatch(method, params))
    except ValueError as exc:
        return _error_response(request_id, -32602, "Invalid params", {"detail": str(exc)})
    except NotImplementedError as exc:
        return _error_response(request_id, -32601, "Method not found", {"detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return _error_response(request_id, -32603, "Internal error", {"detail": str(exc)})


async def _ws_handler(websocket: Any) -> None:
    async for message in websocket:
        response = await _handle_message(message)
        if response is not None:
            await websocket.send(json.dumps(response, ensure_ascii=False))


async def run_server() -> None:
    print(f"Map mask debug RPC server listening on ws://{HOST}:{PORT}", flush=True)
    async with websockets.serve(_ws_handler, HOST, PORT, max_size=10 * 1024 * 1024):
        await asyncio.Future()


def main() -> None:
    if not any(
        os.environ.get(name)
        for name in (
            "WHIMBOX_MAP_MASK_FORCE_BIGMAP_OPEN",
            "WHIMBOX_MAP_MASK_FORCE_BIGMAP_CLOSED",
            "WHIMBOX_MAP_MASK_BIGMAP_DETECTION_MODE",
            "WHIMBOX_MAP_MASK_SMOKE",
        )
    ):
        map_mask_service.set_bigmap_detection_mode("force-open")
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
