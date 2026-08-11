from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from .service import map_mask_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously print map-mask bigmap detection state.")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to run")
    parser.add_argument("--interval", type=float, default=0.5, help="poll interval in seconds")
    parser.add_argument(
        "--mode",
        choices=("auto", "force-open", "force-closed"),
        default="auto",
        help="detection mode to set before polling",
    )
    parser.add_argument("--verbose", action="store_true", help="print every poll instead of changes only")
    parser.add_argument(
        "--probe-capture",
        action="store_true",
        help="probe the real game window handle and PrintWindow capture path before polling",
    )
    parser.add_argument(
        "--save-capture",
        default="",
        help="optional PNG path for the latest captured client image",
    )
    args = parser.parse_args()

    if args.probe_capture:
        print_capture_probe(args.save_capture)

    map_mask_service.set_bigmap_detection_mode(args.mode)
    deadline = time.monotonic() + max(0.0, args.duration)
    previous_signature: tuple[Any, ...] | None = None

    print(
        "Running map mask bigmap detection "
        f"for {args.duration:.1f}s, poll={args.interval:.2f}s, mode={args.mode}",
        flush=True,
    )
    while time.monotonic() <= deadline:
        state = map_mask_service.get_state()
        signature = (
            state.get("is_bigmap_open"),
            state.get("raw_is_bigmap_open"),
            state.get("detection_source"),
            state.get("detection_error"),
        )
        if args.verbose or signature != previous_signature:
            print(_format_state(state), flush=True)
            previous_signature = signature
        time.sleep(max(0.05, args.interval))


def print_capture_probe(save_capture: str = "") -> None:
    print("Capture probe:", flush=True)
    try:
        from whimbox.interaction.interaction_core import itt
        from whimbox.ui.page_assets import page_bigmap
    except Exception as exc:  # noqa: BLE001
        print(f"  status=itt_init_failed error={type(exc).__name__}: {exc}", flush=True)
        return

    handler = getattr(itt, "hwnd_handler", None)
    if handler is None:
        print("  status=itt_init_failed error=itt.hwnd_handler missing", flush=True)
        return

    try:
        handler.refresh_handle()
        handle = handler.get_handle()
        pid = getattr(handler, "pid", None)
        is_alive = bool(handler.is_alive())
        is_minimized = bool(handler.is_minimized())
    except Exception as exc:  # noqa: BLE001
        print(f"  status=game_window_lookup_failed error={type(exc).__name__}: {exc}", flush=True)
        return

    print(f"  handle={handle} pid={pid} alive={is_alive} minimized={is_minimized}", flush=True)
    if not handle or not is_alive:
        print("  status=game_window_not_found", flush=True)
        return
    if is_minimized:
        print("  status=game_window_minimized", flush=True)
        return

    try:
        shape_ok, width, height = handler.check_shape()
        rect = handler._mgr.get_window_rect(handle, pid)
        print(f"  client_shape_ok={shape_ok} client_size={width}x{height} rect={rect}", flush=True)
        if not shape_ok:
            print("  status=dpi_client_area_invalid", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  status=dpi_client_area_failed error={type(exc).__name__}: {exc}", flush=True)

    raw = None
    try:
        raw = itt.capture_obj._cap_mgr.capture_window(handle, pid)
    except Exception as exc:  # noqa: BLE001
        print(f"  status=capture_failed error={type(exc).__name__}: {exc}", flush=True)

    if raw is None:
        print("  status=capture_failed raw=None", flush=True)
        return

    raw_mean = float(raw.mean()) if raw.size else 0.0
    raw_max = int(raw.max()) if raw.size else 0
    print(f"  raw_capture shape={raw.shape} dtype={raw.dtype} mean={raw_mean:.2f} max={raw_max}", flush=True)
    if raw_max == 0:
        print("  status=capture_blank", flush=True)
        return

    try:
        normalized = itt.capture_obj.capture(force=True)
        norm_mean = float(normalized.mean()) if normalized.size else 0.0
        norm_max = int(normalized.max()) if normalized.size else 0
        print(
            f"  normalized_capture shape={normalized.shape} dtype={normalized.dtype} "
            f"mean={norm_mean:.2f} max={norm_max}",
            flush=True,
        )
        if save_capture:
            _save_capture(save_capture, normalized)
    except Exception as exc:  # noqa: BLE001
        print(f"  status=capture_normalize_failed error={type(exc).__name__}: {exc}", flush=True)
        return

    try:
        is_bigmap = bool(page_bigmap.is_current_page(itt))
        print(f"  page_bigmap={is_bigmap}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  status=page_bigmap_detection_failed error={type(exc).__name__}: {exc}", flush=True)
        return

    print("  status=capture_ok", flush=True)


def _save_capture(path: str, image: Any) -> None:
    import cv2

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), image)
    print(f"  saved_capture={output}", flush=True)


def _format_state(state: dict[str, Any]) -> str:
    error = state.get("detection_error") or ""
    error_text = f" error={error}" if error else ""
    return (
        f"{state.get('last_detection_time') or 'pending'} "
        f"mode={state.get('detection_mode')} "
        f"raw={state.get('raw_is_bigmap_open')} "
        f"open={state.get('is_bigmap_open')} "
        f"confidence={float(state.get('detection_confidence') or 0):.2f} "
        f"duration_ms={float(state.get('detection_duration_ms') or 0):.2f} "
        f"source={state.get('detection_source')}"
        f"{error_text}"
    )


if __name__ == "__main__":
    main()
