from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .coordinate import point_to_visible
from .local_provider import LocalJsonProvider, default_local_labels_path, default_local_points_path
from .models import MapMaskPoint
from .viewport_provider import MapMaskViewportProvider


REQUIRED_POINT_FIELDS = ("id", "label_id", "name", "map_name", "image_x", "image_y")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["validate"]
    if arguments[0] == "validate":
        return _validate(arguments[1:])
    print("Usage: python -m whimbox.map.mask.debug_local_points validate", file=sys.stderr)
    return 2


def _validate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate local map-mask points and their current screen positions.")
    parser.add_argument(
        "--points",
        help="points.local.json path; defaults to WHIMBOX_MAP_MASK_LOCAL_POINTS or assets/map_mask/points.local.json",
    )
    parser.add_argument(
        "--map-name",
        default="miraland",
        help="map_name used for viewport and point filtering",
    )
    parser.add_argument(
        "--viewport-mode",
        choices=("sample", "manual-calibration", "auto-placeholder"),
        default=os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_MODE") or "manual-calibration",
        help="viewport mode used for screen coordinate validation",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable validation output")
    args = parser.parse_args(argv)

    if args.points:
        os.environ["WHIMBOX_MAP_MASK_LOCAL_POINTS"] = args.points

    local_points_path = _resolve_points_path(args.points)
    raw_points, raw_error = _load_raw_points(local_points_path)
    raw_results = [_validate_raw_point(item, index) for index, item in enumerate(raw_points)]

    provider = LocalJsonProvider()
    labels = provider.list_labels()
    points = provider.list_points(map_name=args.map_name)
    status = provider.get_data_status()
    viewport_result = MapMaskViewportProvider().get_viewport(
        map_name=args.map_name,
        mode=args.viewport_mode,
    )
    viewport = viewport_result.viewport

    screen_results: list[dict[str, Any]] = []
    for point in points:
        visible = point_to_visible(point, viewport) if viewport else None
        screen_results.append(
            {
                "id": point.id,
                "label_id": point.label_id,
                "name": point.name,
                "map_name": point.map_name,
                "image_x": point.image_x,
                "image_y": point.image_y,
                "screen_x": visible.screen_x if visible else None,
                "screen_y": visible.screen_y if visible else None,
                "inside_map_area": visible is not None,
            }
        )

    errors: list[str] = []
    warnings: list[str] = []
    if raw_error:
        errors.append(raw_error)
    for item in raw_results:
        errors.extend(item["errors"])
    if not raw_points:
        warnings.append(f"local points file is empty: {local_points_path}")
    if status.get("points_source") == "fallback":
        errors.append(str(status.get("points_error") or "local points fell back to sample data"))
    if viewport is None:
        errors.append("viewport unavailable")
    for item in screen_results:
        if item["inside_map_area"]:
            continue
        message = f"point {item['id']} is outside current map_area"
        if status.get("points_source") == "local":
            errors.append(message)
        else:
            warnings.append(message)

    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "labels_count": len(labels),
        "points_count": len(points),
        "raw_local_points_count": len(raw_points),
        "labels_path": str(default_local_labels_path().resolve()),
        "points_path": str(local_points_path),
        "provider_status": status,
        "viewport_mode": viewport_result.mode,
        "viewport_source": viewport_result.source,
        "viewport_fallback_used": viewport_result.fallback_used,
        "viewport": viewport.to_dict() if viewport else {},
        "raw_point_validation": raw_results,
        "screen_points": screen_results,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    else:
        _print_result(result)
    return 0 if result["ok"] else 1


def _resolve_points_path(value: str | None) -> Path:
    raw = value or os.environ.get("WHIMBOX_MAP_MASK_LOCAL_POINTS")
    if raw:
        return _safe_resolve(Path(raw))
    return default_local_points_path().resolve()


def _load_raw_points(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    if not isinstance(data, list):
        return [], f"local points root must be a list: {path}"
    points: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            return [], f"point {index} must be an object"
        points.append(item)
    return points, ""


def _validate_raw_point(item: dict[str, Any], index: int) -> dict[str, Any]:
    errors: list[str] = []
    for field in REQUIRED_POINT_FIELDS:
        if item.get(field) in (None, ""):
            errors.append(f"point {index} missing {field}")
    for field in ("image_x", "image_y"):
        try:
            float(item.get(field))
        except (TypeError, ValueError):
            errors.append(f"point {index} {field} must be a number")
    try:
        point = MapMaskPoint.from_dict(item)
        normalized = point.to_dict()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"point {index} cannot be normalized: {type(exc).__name__}: {exc}")
        normalized = {}
    return {
        "index": index,
        "id": str(item.get("id") or ""),
        "ok": not errors,
        "errors": errors,
        "point": normalized,
    }


def _print_result(result: dict[str, Any]) -> None:
    status = "PASS" if result["ok"] else "FAIL"
    provider_status = result.get("provider_status") if isinstance(result.get("provider_status"), dict) else {}
    print(f"Map mask local points validation: {status}", flush=True)
    print(f"  labels={result['labels_count']} points={result['points_count']}", flush=True)
    print(f"  raw_local_points={result['raw_local_points_count']}", flush=True)
    print(f"  labels_path={result['labels_path']}", flush=True)
    print(f"  points_path={result['points_path']}", flush=True)
    print(
        "  provider="
        f"data_source={provider_status.get('data_source')} "
        f"labels={provider_status.get('labels_source')} "
        f"points={provider_status.get('points_source')}",
        flush=True,
    )
    print(
        "  viewport="
        f"mode={result['viewport_mode']} source={result['viewport_source']} "
        f"fallback={result['viewport_fallback_used']}",
        flush=True,
    )
    for point in result.get("screen_points", []):
        print(
            f"    {point['id']} {point['name']} "
            f"image=({float(point['image_x']):.1f}, {float(point['image_y']):.1f}) "
            f"screen=({ _format_optional_number(point['screen_x'])}, {_format_optional_number(point['screen_y'])}) "
            f"inside={point['inside_map_area']}",
            flush=True,
        )
    for warning in result.get("warnings", []):
        print(f"  warning: {warning}", flush=True)
    if result.get("errors"):
        print("  errors:", flush=True)
        for error in result["errors"]:
            print(f"    - {error}", flush=True)


def _format_optional_number(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "n/a"


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except Exception:
        return path


if __name__ == "__main__":
    raise SystemExit(main())
