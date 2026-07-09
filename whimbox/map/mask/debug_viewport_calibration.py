from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import MapMaskViewport
from .service import map_mask_service
from .viewport_provider import default_calibration_path

ADMIN_HINT = "Capture is blank or not elevated. Re-run this command in Administrator PowerShell."


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "validate-calibration":
        return _main_validate_calibration(arguments[1:])
    return _main_capture_debug(arguments)


def _main_capture_debug(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Capture current game client and print map-mask viewport debug info.")
    parser.add_argument(
        "--artifact-dir",
        default="map-mask-viewport-artifacts",
        help="directory for captured screenshots and JSON reports",
    )
    parser.add_argument(
        "--detection-mode",
        choices=("auto", "force-open", "force-closed"),
        default="auto",
        help="bigmap detection mode used before reading viewport state",
    )
    parser.add_argument(
        "--viewport-mode",
        choices=("sample", "manual-calibration", "auto-placeholder"),
        help="viewport mode for this run; defaults to WHIMBOX_MAP_MASK_VIEWPORT_MODE or sample",
    )
    parser.add_argument(
        "--calibration",
        help="existing viewport calibration JSON to read for this run",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="save screenshot, report, visible sample points, and calibration template artifacts",
    )
    parser.add_argument(
        "--write-template",
        help="write a calibration template JSON to this path",
    )
    parser.add_argument(
        "--from-current-screen",
        action="store_true",
        help="build the template using the captured client size as screen/map area",
    )
    args = parser.parse_args(argv)

    if args.viewport_mode:
        os.environ["WHIMBOX_MAP_MASK_VIEWPORT_MODE"] = args.viewport_mode
    if args.calibration:
        os.environ["WHIMBOX_MAP_MASK_VIEWPORT_MODE"] = "manual-calibration"
        os.environ["WHIMBOX_MAP_MASK_VIEWPORT_CALIBRATION"] = args.calibration

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")

    capture_path = artifact_dir / f"game-client-{timestamp}.png"
    capture_info = _capture_game_client(capture_path)
    map_mask_service.set_bigmap_detection_mode(args.detection_mode)
    state = map_mask_service.get_state()
    visible = map_mask_service.get_visible_points()

    template = _build_calibration_template(
        capture_info=capture_info,
        state=state,
        from_current_screen=args.from_current_screen,
    )

    artifacts: dict[str, str] = {}
    if capture_info.get("path"):
        artifacts["capture_png"] = str(capture_info["path"])

    visible_points_path = artifact_dir / f"visible-sample-points-{timestamp}.json"
    if args.save:
        _write_json(visible_points_path, visible.get("points", []))
        artifacts["visible_sample_points_json"] = str(visible_points_path.resolve())

    artifact_template_path = artifact_dir / f"viewport-calibration-template-{timestamp}.json"
    if args.save and not args.write_template:
        _write_json(artifact_template_path, template)
        artifacts["calibration_template_json"] = str(artifact_template_path.resolve())

    explicit_template_path: Path | None = None
    if args.write_template:
        explicit_template_path = _resolve_output_path(args.write_template)
        _write_json(explicit_template_path, template)
        artifacts["calibration_template_json"] = str(explicit_template_path.resolve())

    report_path = artifact_dir / f"viewport-report-{timestamp}.json"
    artifacts["viewport_report_json"] = str(report_path.resolve())

    report = {
        "runtime": {
            "python": sys.executable,
            "is_admin": _is_admin(),
            "cwd": str(Path.cwd()),
        },
        "capture": capture_info,
        "state": state,
        "viewport": state.get("viewport") or {},
        "visible_points": visible.get("points", []),
        "calibration_template": template,
        "artifacts": artifacts,
    }
    if _needs_admin_hint(capture_info):
        report["hint"] = ADMIN_HINT
        capture_info["hint"] = ADMIN_HINT

    _write_json(report_path, report)

    print("Viewport calibration debug:", flush=True)
    print(f"  artifact_dir={artifact_dir.resolve()}", flush=True)
    print(f"  report={report_path.resolve()}", flush=True)
    print(f"  capture_status={capture_info.get('status')}", flush=True)
    print(f"  is_admin={report['runtime']['is_admin']} python={sys.executable}", flush=True)
    if capture_info.get("path"):
        print(f"  capture={capture_info.get('path')}", flush=True)
    if capture_info.get("error"):
        print(f"  capture_error={capture_info.get('error')}", flush=True)
    if report.get("hint"):
        print(f"  hint={report['hint']}", flush=True)
    print(
        "  bigmap="
        f"{state.get('is_bigmap_open')} raw={state.get('raw_is_bigmap_open')} "
        f"stable={state.get('stable_is_bigmap_open')} source={state.get('detection_source')}",
        flush=True,
    )
    print(
        "  viewport="
        f"mode={state.get('viewport_mode')} source={state.get('viewport_source')} "
        f"valid={state.get('has_valid_viewport')} fallback={state.get('viewport_fallback_used')}",
        flush=True,
    )
    if state.get("viewport_calibration_path"):
        print(f"  calibration={state.get('viewport_calibration_path')}", flush=True)
    if state.get("viewport_calibration_error"):
        print(f"  calibration_error={state.get('viewport_calibration_error')}", flush=True)
    print(f"  viewport_json={json.dumps(state.get('viewport') or {}, ensure_ascii=False)}", flush=True)
    print(f"  template_json={json.dumps(template, ensure_ascii=False)}", flush=True)
    if explicit_template_path:
        print(f"  template_written={explicit_template_path.resolve()}", flush=True)
    print(f"  visible_points={len(visible.get('points', []))}", flush=True)
    for point in visible.get("points", []):
        print(
            f"    {point.get('id')} {point.get('name')} "
            f"screen=({float(point.get('screen_x') or 0):.1f}, {float(point.get('screen_y') or 0):.1f})",
            flush=True,
        )
    return 0


def _main_validate_calibration(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the map-mask viewport calibration file without capturing the game window.",
    )
    parser.add_argument(
        "--calibration",
        help="calibration JSON to validate; defaults to WHIMBOX_MAP_MASK_VIEWPORT_CALIBRATION or assets/map_mask/viewport_calibration.json",
    )
    parser.add_argument(
        "--map-name",
        default="miraland",
        help="map_name expected by the calibration and sample points",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable validation output",
    )
    args = parser.parse_args(argv)

    os.environ["WHIMBOX_MAP_MASK_VIEWPORT_MODE"] = "manual-calibration"
    if args.calibration:
        os.environ["WHIMBOX_MAP_MASK_VIEWPORT_CALIBRATION"] = args.calibration

    map_mask_service.set_bigmap_detection_mode("force-open")
    state = map_mask_service.get_state(map_name=args.map_name)
    visible = map_mask_service.get_visible_points(map_name=args.map_name)
    result = _build_validation_result(
        state=state,
        visible_points=visible.get("points", []),
        requested_path=args.calibration,
        map_name=args.map_name,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    else:
        _print_validation_result(result)

    return 0 if result["ok"] else 1


def _build_validation_result(
    state: dict[str, Any],
    visible_points: list[dict[str, Any]],
    requested_path: str | None,
    map_name: str,
) -> dict[str, Any]:
    viewport = state.get("viewport") if isinstance(state.get("viewport"), dict) else {}
    calibration_path = str(state.get("viewport_calibration_path") or "")
    default_path = str(default_calibration_path().resolve())
    errors: list[str] = []

    if state.get("viewport_mode") != "manual-calibration":
        errors.append(f"viewport_mode is {state.get('viewport_mode')!r}, expected 'manual-calibration'")
    if state.get("viewport_source") != "manual-calibration":
        errors.append(f"viewport_source is {state.get('viewport_source')!r}, expected 'manual-calibration'")
    if state.get("viewport_fallback_used"):
        errors.append("manual calibration fell back to sample viewport")
    if not state.get("has_valid_viewport"):
        errors.append("state.has_valid_viewport is false")
    if state.get("viewport_calibration_error"):
        errors.append(f"viewport_calibration_error: {state.get('viewport_calibration_error')}")
    if not calibration_path:
        errors.append("viewport_calibration_path is empty")
    if requested_path and calibration_path:
        expected = str(_resolve_output_path(requested_path).expanduser().resolve())
        if calibration_path.lower() != expected.lower():
            errors.append(f"loaded {calibration_path}, expected {expected}")
    if not _viewport_has_positive_rects(viewport):
        errors.append("viewport has invalid map area or map image dimensions")
    if map_name and viewport.get("map_name") != map_name:
        errors.append(f"viewport map_name is {viewport.get('map_name')!r}, expected {map_name!r}")
    if not visible_points:
        errors.append("visible sample points is empty")
    for point in visible_points:
        if not _point_has_screen_xy(point):
            errors.append(f"point {point.get('id') or '<unknown>'} has invalid screen_x/screen_y")
            break

    return {
        "ok": not errors,
        "errors": errors,
        "default_calibration_path": default_path,
        "requested_calibration_path": requested_path or "",
        "loaded_calibration_path": calibration_path,
        "fallback_used": bool(state.get("viewport_fallback_used")),
        "viewport_mode": state.get("viewport_mode"),
        "viewport_source": state.get("viewport_source"),
        "viewport_calibration_error": state.get("viewport_calibration_error") or "",
        "has_valid_viewport": bool(state.get("has_valid_viewport")),
        "bigmap_mode": state.get("detection_mode"),
        "is_bigmap_open": bool(state.get("is_bigmap_open")),
        "viewport": viewport,
        "visible_point_count": len(visible_points),
        "visible_points": visible_points,
    }


def _viewport_has_positive_rects(viewport: Any) -> bool:
    if not isinstance(viewport, dict):
        return False
    required_positive = [
        "screen_width",
        "screen_height",
        "image_width",
        "image_height",
    ]
    for key in required_positive:
        try:
            if float(viewport.get(key, 0)) <= 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _point_has_screen_xy(point: Any) -> bool:
    if not isinstance(point, dict):
        return False
    try:
        screen_x = float(point.get("screen_x"))
        screen_y = float(point.get("screen_y"))
    except (TypeError, ValueError):
        return False
    return screen_x == screen_x and screen_y == screen_y


def _print_validation_result(result: dict[str, Any]) -> None:
    status = "PASS" if result["ok"] else "FAIL"
    viewport = result.get("viewport") if isinstance(result.get("viewport"), dict) else {}
    print(f"Map mask calibration validation: {status}", flush=True)
    print(f"  default_path={result.get('default_calibration_path')}", flush=True)
    print(f"  loaded_path={result.get('loaded_calibration_path') or 'none'}", flush=True)
    print(f"  fallback_used={result.get('fallback_used')}", flush=True)
    print(
        "  viewport="
        f"mode={result.get('viewport_mode')} source={result.get('viewport_source')} "
        f"valid={result.get('has_valid_viewport')}",
        flush=True,
    )
    print(
        "  map_area="
        f"{viewport.get('screen_width', 'n/a')}x{viewport.get('screen_height', 'n/a')} "
        f"at {viewport.get('screen_left', 'n/a')},{viewport.get('screen_top', 'n/a')}",
        flush=True,
    )
    print(
        "  map_image="
        f"{viewport.get('image_width', 'n/a')}x{viewport.get('image_height', 'n/a')} "
        f"at {viewport.get('image_left', 'n/a')},{viewport.get('image_top', 'n/a')}",
        flush=True,
    )
    print(f"  zoom={viewport.get('scale', 'n/a')} map={viewport.get('map_name', 'n/a')}", flush=True)
    print(f"  visible_points={result.get('visible_point_count')}", flush=True)
    for point in result.get("visible_points", [])[:10]:
        print(
            f"    {point.get('id')} {point.get('name')} "
            f"screen=({float(point.get('screen_x') or 0):.1f}, {float(point.get('screen_y') or 0):.1f})",
            flush=True,
        )
    if result.get("errors"):
        print("  errors:", flush=True)
        for error in result["errors"]:
            print(f"    - {error}", flush=True)


def _capture_game_client(path: Path) -> dict[str, Any]:
    try:
        from whimbox.interaction.interaction_core import itt
    except Exception as exc:  # noqa: BLE001
        return {"status": "itt_init_failed", "error": f"{type(exc).__name__}: {exc}"}

    handler = getattr(itt, "hwnd_handler", None)
    if handler is None:
        return {"status": "itt_init_failed", "error": "itt.hwnd_handler missing"}

    try:
        handler.refresh_handle()
        handle = handler.get_handle()
        pid = getattr(handler, "pid", None)
        if not handle or not handler.is_alive():
            return {"status": "game_window_not_found", "handle": handle, "pid": pid}
        if handler.is_minimized():
            return {"status": "game_window_minimized", "handle": handle, "pid": pid}
        shape_ok, width, height = handler.check_shape()
        rect = handler._mgr.get_window_rect(handle, pid)
    except Exception as exc:  # noqa: BLE001
        return {"status": "game_window_lookup_failed", "error": f"{type(exc).__name__}: {exc}"}

    try:
        image = itt.capture_obj.capture(force=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "capture_failed", "error": f"{type(exc).__name__}: {exc}"}

    if image is None:
        return {"status": "capture_failed", "error": "capture returned None"}

    max_value = int(image.max()) if image.size else 0
    mean_value = float(image.mean()) if image.size else 0.0
    base_info = {
        "handle": handle,
        "pid": pid,
        "shape_ok": shape_ok,
        "client_size": [width, height],
        "rect": rect,
        "shape": list(image.shape),
        "mean": mean_value,
        "max": max_value,
    }

    save_result = _write_capture_png(path, image)
    if max_value == 0:
        return {
            "status": "capture_blank",
            **base_info,
            **save_result,
        }

    return {
        "status": "capture_ok",
        **base_info,
        **save_result,
    }


def _write_capture_png(path: Path, image: Any) -> dict[str, str]:
    try:
        import cv2

        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), image):
            return {"save_error": "cv2.imwrite returned false"}
        return {"path": str(path.resolve())}
    except Exception as exc:  # noqa: BLE001
        return {"save_error": f"{type(exc).__name__}: {exc}"}


def _build_calibration_template(
    capture_info: dict[str, Any],
    state: dict[str, Any],
    from_current_screen: bool,
) -> dict[str, Any]:
    viewport = _viewport_from_state(state)
    capture_width, capture_height = _capture_size(capture_info)

    if from_current_screen and capture_width and capture_height:
        screen_width = capture_width
        screen_height = capture_height
        map_area_left = 0
        map_area_top = 0
        map_area_width = capture_width
        map_area_height = capture_height
    else:
        screen_width = int(state.get("viewport_screen_width") or viewport.screen_width)
        screen_height = int(state.get("viewport_screen_height") or viewport.screen_height)
        map_area_left = viewport.screen_left
        map_area_top = viewport.screen_top
        map_area_width = viewport.screen_width
        map_area_height = viewport.screen_height

    return {
        "screen_width": screen_width,
        "screen_height": screen_height,
        "map_area_left": map_area_left,
        "map_area_top": map_area_top,
        "map_area_width": map_area_width,
        "map_area_height": map_area_height,
        "map_image_left": viewport.image_left,
        "map_image_top": viewport.image_top,
        "map_image_width": viewport.image_width,
        "map_image_height": viewport.image_height,
        "zoom": viewport.scale,
        "map_name": viewport.map_name,
    }


def _viewport_from_state(state: dict[str, Any]) -> MapMaskViewport:
    viewport = state.get("viewport")
    if isinstance(viewport, dict) and viewport:
        try:
            return MapMaskViewport.from_dict(viewport)
        except Exception:
            pass
    return MapMaskViewport(
        map_name="miraland",
        image_left=1000.0,
        image_top=6500.0,
        image_width=1920.0,
        image_height=1080.0,
        screen_left=0,
        screen_top=0,
        screen_width=1920,
        screen_height=1080,
        scale=1.0,
        rotation=0.0,
    )


def _capture_size(capture_info: dict[str, Any]) -> tuple[int | None, int | None]:
    size = capture_info.get("client_size")
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        return None, None
    try:
        width = int(size[0])
        height = int(size[1])
    except (TypeError, ValueError):
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def _resolve_output_path(value: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        parts = raw.parts
        if parts and parts[0].lower() == "whimbox" and Path.cwd().name.lower() == "whimbox":
            raw = Path(*parts[1:])
    return raw


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _needs_admin_hint(capture_info: dict[str, Any]) -> bool:
    return not _is_admin() or capture_info.get("status") == "capture_blank"


if __name__ == "__main__":
    raise SystemExit(main())
