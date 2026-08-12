from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from whimbox.common.logger import logger
from whimbox.map.detection.cvars import BIGMAP_POSITION_SCALE_DICT

from .local_provider import _default_sample_data_dir
from .models import MapMaskViewport
from .resource_paths import development_map_mask_dir, package_map_mask_dir


ViewportMode = Literal["sample", "manual-calibration", "auto-placeholder", "hybrid-auto-center"]


@dataclass(slots=True)
class ViewportResult:
    viewport: MapMaskViewport | None
    mode: ViewportMode
    source: str
    fallback_used: bool = False
    fallback_reason: str = ""
    detection_confidence: float = 0.0
    detection_error: str = ""
    center_x: float | None = None
    center_y: float | None = None
    raw_center_x: float | None = None
    raw_center_y: float | None = None
    accepted_center_x: float | None = None
    accepted_center_y: float | None = None
    corrected_center_x: float | None = None
    corrected_center_y: float | None = None
    center_correction_enabled: bool = False
    center_correction_scale_x: float = 1.0
    center_correction_scale_y: float = 1.0
    center_correction_offset_x: float = 0.0
    center_correction_offset_y: float = 0.0
    center_correction_source: str = "disabled"
    pending_center_x: float | None = None
    pending_center_y: float | None = None
    center_jump_distance: float | None = None
    center_accept_reason: str = ""
    center_rejected_reason: str = ""
    pending_confirm_count: int = 0
    last_good_center_age_ms: float | None = None
    smoothing_mode: str = "off"
    smoothing_applied: bool = False
    smoothing_distance: float | None = None
    snap_reason: str = ""
    tracking_mode: str = "idle"
    motion_diff: float | None = None
    motion_unstable: bool = False
    candidate_distance_to_last_good: float | None = None
    local_match_confidence: float | None = None
    global_match_confidence: float | None = None
    selected_match_source: str = "none"
    reacquire_pending_count: int = 0
    tracking_center_x: float | None = None
    tracking_center_y: float | None = None
    global_check_center_x: float | None = None
    global_check_center_y: float | None = None
    global_check_delta: float | None = None
    global_check_confidence: float | None = None
    tracking_suspect: bool = False
    tracking_reset_reason: str = ""
    last_global_check_time: str = ""
    matching_status: str = "matching_failed"
    matching_rejection_reason: str = ""
    global_match_top1_confidence: float | None = None
    global_match_top2_confidence: float | None = None
    global_match_margin: float | None = None
    global_selected_confidence: float | None = None
    global_selected_local_score: float | None = None
    global_selected_to_top1_distance: float | None = None
    last_update_time: str = ""
    stale: bool = False
    calibration_path: str = ""
    calibration_error: str = ""
    screen_width: int | None = None
    screen_height: int | None = None
    map_scale: float | None = None
    map_scale_source: str = ""
    viewport_span_source: str = "manual-calibration"
    assumes_max_bigmap_zoom: bool = False


class MapMaskViewportProvider:
    def __init__(self) -> None:
        self.sample_provider = SampleViewportProvider()
        self.manual_provider = ManualCalibrationViewportProvider()
        self.hybrid_provider = None

    def get_viewport(
        self,
        map_name: str | None = None,
        mode: str | None = None,
        captured_image: Any | None = None,
    ) -> ViewportResult:
        viewport_mode = _resolve_viewport_mode(mode)
        if viewport_mode == "sample":
            return self._sample(map_name=map_name)
        if viewport_mode == "manual-calibration":
            return self._manual_with_fallback(map_name=map_name)
        if viewport_mode == "hybrid-auto-center":
            return self._hybrid_with_fallback(
                map_name=map_name,
                captured_image=captured_image,
            )
        return self._auto_placeholder_with_fallback(map_name=map_name)

    def get_mode(self, mode: str | None = None) -> ViewportMode:
        return _resolve_viewport_mode(mode)

    def _sample(self, map_name: str | None = None) -> ViewportResult:
        viewport = self.sample_provider.get_viewport(map_name=map_name)
        return ViewportResult(
            viewport=viewport,
            mode="sample",
            source="sample" if viewport else "none",
        )

    def _manual_with_fallback(self, map_name: str | None = None) -> ViewportResult:
        manual = self.manual_provider.get_viewport(map_name=map_name)
        if manual.viewport is not None:
            return manual

        fallback = self._sample(map_name=map_name)
        fallback.mode = "manual-calibration"
        fallback.source = "sample-fallback" if fallback.viewport else "none"
        fallback.fallback_used = True
        fallback.calibration_path = manual.calibration_path
        fallback.calibration_error = manual.calibration_error or "manual calibration unavailable"
        return fallback

    def _auto_placeholder_with_fallback(self, map_name: str | None = None) -> ViewportResult:
        fallback = self._sample(map_name=map_name)
        fallback.mode = "auto-placeholder"
        fallback.source = "sample-fallback" if fallback.viewport else "none"
        fallback.fallback_used = True
        fallback.calibration_error = "auto viewport calibration is not implemented yet"
        return fallback

    def _hybrid_with_fallback(
        self,
        map_name: str | None = None,
        captured_image: Any | None = None,
    ) -> ViewportResult:
        if self.hybrid_provider is None:
            from .auto_viewport_provider import HybridAutoCenterViewportProvider

            self.hybrid_provider = HybridAutoCenterViewportProvider(self.manual_provider)
        hybrid = self.hybrid_provider.get_viewport(
            map_name=map_name,
            captured_image=captured_image,
        )
        if hybrid.viewport is not None:
            return hybrid
        if hybrid.source == "matching-rejected":
            return hybrid

        fallback = self._manual_with_fallback(map_name=map_name)
        fallback.mode = "hybrid-auto-center"
        fallback.fallback_used = True
        fallback.fallback_reason = hybrid.fallback_reason or "hybrid viewport unavailable"
        fallback.detection_confidence = hybrid.detection_confidence
        fallback.detection_error = hybrid.detection_error
        fallback.center_x = hybrid.center_x
        fallback.center_y = hybrid.center_y
        fallback.raw_center_x = hybrid.raw_center_x
        fallback.raw_center_y = hybrid.raw_center_y
        fallback.accepted_center_x = hybrid.accepted_center_x
        fallback.accepted_center_y = hybrid.accepted_center_y
        fallback.corrected_center_x = hybrid.corrected_center_x
        fallback.corrected_center_y = hybrid.corrected_center_y
        fallback.center_correction_enabled = hybrid.center_correction_enabled
        fallback.center_correction_scale_x = hybrid.center_correction_scale_x
        fallback.center_correction_scale_y = hybrid.center_correction_scale_y
        fallback.center_correction_offset_x = hybrid.center_correction_offset_x
        fallback.center_correction_offset_y = hybrid.center_correction_offset_y
        fallback.center_correction_source = hybrid.center_correction_source
        fallback.pending_center_x = hybrid.pending_center_x
        fallback.pending_center_y = hybrid.pending_center_y
        fallback.center_jump_distance = hybrid.center_jump_distance
        fallback.center_accept_reason = hybrid.center_accept_reason
        fallback.center_rejected_reason = hybrid.center_rejected_reason
        fallback.pending_confirm_count = hybrid.pending_confirm_count
        fallback.last_good_center_age_ms = hybrid.last_good_center_age_ms
        fallback.smoothing_mode = hybrid.smoothing_mode
        fallback.smoothing_applied = hybrid.smoothing_applied
        fallback.smoothing_distance = hybrid.smoothing_distance
        fallback.snap_reason = hybrid.snap_reason
        fallback.tracking_mode = hybrid.tracking_mode
        fallback.motion_diff = hybrid.motion_diff
        fallback.motion_unstable = hybrid.motion_unstable
        fallback.candidate_distance_to_last_good = hybrid.candidate_distance_to_last_good
        fallback.local_match_confidence = hybrid.local_match_confidence
        fallback.global_match_confidence = hybrid.global_match_confidence
        fallback.selected_match_source = hybrid.selected_match_source
        fallback.reacquire_pending_count = hybrid.reacquire_pending_count
        fallback.tracking_center_x = hybrid.tracking_center_x
        fallback.tracking_center_y = hybrid.tracking_center_y
        fallback.global_check_center_x = hybrid.global_check_center_x
        fallback.global_check_center_y = hybrid.global_check_center_y
        fallback.global_check_delta = hybrid.global_check_delta
        fallback.global_check_confidence = hybrid.global_check_confidence
        fallback.tracking_suspect = hybrid.tracking_suspect
        fallback.tracking_reset_reason = hybrid.tracking_reset_reason
        fallback.last_global_check_time = hybrid.last_global_check_time
        fallback.matching_status = hybrid.matching_status
        fallback.matching_rejection_reason = hybrid.matching_rejection_reason
        fallback.global_match_top1_confidence = hybrid.global_match_top1_confidence
        fallback.global_match_top2_confidence = hybrid.global_match_top2_confidence
        fallback.global_match_margin = hybrid.global_match_margin
        fallback.global_selected_confidence = hybrid.global_selected_confidence
        fallback.global_selected_local_score = hybrid.global_selected_local_score
        fallback.global_selected_to_top1_distance = (
            hybrid.global_selected_to_top1_distance
        )
        fallback.last_update_time = hybrid.last_update_time
        fallback.stale = True
        fallback.map_scale = hybrid.map_scale
        fallback.map_scale_source = hybrid.map_scale_source
        fallback.viewport_span_source = hybrid.viewport_span_source
        fallback.assumes_max_bigmap_zoom = hybrid.assumes_max_bigmap_zoom
        return fallback


class SampleViewportProvider:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else _default_sample_data_dir()
        self._viewports: list[MapMaskViewport] | None = None

    def get_viewport(
        self,
        map_name: str | None = None,
        index: int = 0,
    ) -> MapMaskViewport | None:
        viewports = self._load_viewports()
        if map_name:
            viewports = [item for item in viewports if item.map_name == map_name]
        if not viewports:
            return None
        safe_index = min(max(index, 0), len(viewports) - 1)
        return viewports[safe_index]

    def _load_viewports(self) -> list[MapMaskViewport]:
        if self._viewports is not None:
            return list(self._viewports)

        path = self.data_dir / "viewport_samples.sample.json"
        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
            if isinstance(data, list):
                self._viewports = [MapMaskViewport.from_dict(item) for item in data]
                return list(self._viewports)
            logger.warning(f"map mask viewport sample is not a list: {path}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"failed to load map mask viewport sample {path}: {exc}")

        self._viewports = [_fallback_viewport()]
        return list(self._viewports)


class ManualCalibrationViewportProvider:
    def get_viewport(self, map_name: str | None = None) -> ViewportResult:
        path = _resolve_calibration_path()
        if path is None:
            configured_path = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_CALIBRATION") or ""
            return ViewportResult(
                viewport=None,
                mode="manual-calibration",
                source="manual-calibration",
                calibration_path=str(_safe_resolve(Path(configured_path))) if configured_path else "",
                calibration_error="calibration file not found",
            )

        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
            viewport, screen_width, screen_height, span = _viewport_from_calibration(
                data,
                map_name=map_name,
            )
            correction = _center_correction_from_calibration(data)
            return ViewportResult(
                viewport=viewport,
                mode="manual-calibration",
                source="manual-calibration",
                calibration_path=str(path),
                screen_width=screen_width,
                screen_height=screen_height,
                **span,
                **correction,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"failed to load map mask viewport calibration {path}: {exc}")
            return ViewportResult(
                viewport=None,
                mode="manual-calibration",
                source="manual-calibration",
                calibration_path=str(path),
                calibration_error=str(exc),
            )


def _resolve_viewport_mode(value: str | None = None) -> ViewportMode:
    raw = (
        value
        or os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_MODE")
        or "hybrid-auto-center"
    ).strip().lower()
    raw = raw.replace("_", "-")
    if raw in {"manual", "manual-calibration", "calibration"}:
        return "manual-calibration"
    if raw in {"hybrid", "hybrid-auto", "hybrid-auto-center", "auto-center"}:
        return "hybrid-auto-center"
    if raw in {"auto", "auto-placeholder", "placeholder"}:
        return "auto-placeholder"
    return "sample"


def _resolve_calibration_path() -> Path | None:
    env_path = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_CALIBRATION")
    if env_path:
        path = _safe_resolve(Path(env_path))
        return path if path.exists() and path.is_file() else None

    candidates = [
        package_map_mask_dir() / "viewport_calibration.json",
        development_map_mask_dir() / "viewport_calibration.json",
        Path.cwd() / "map-mask-viewport-calibration.json",
    ]

    for candidate in candidates:
        path = _safe_resolve(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def default_calibration_path() -> Path:
    configured = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_CALIBRATION")
    if configured:
        return _safe_resolve(Path(configured))
    return development_map_mask_dir() / "viewport_calibration.json"


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except Exception:
        return path


def _viewport_from_calibration(
    data: object,
    map_name: str | None = None,
) -> tuple[MapMaskViewport, int, int, dict[str, object]]:
    if not isinstance(data, dict):
        raise ValueError("calibration must be a JSON object")

    config_map_name = str(data.get("map_name") or map_name or "miraland")
    if map_name and config_map_name != map_name:
        raise ValueError(f"calibration map_name={config_map_name!r} does not match requested {map_name!r}")

    screen_width = _required_int(data, "screen_width")
    screen_height = _required_int(data, "screen_height")
    map_area_left = _required_int(data, "map_area_left")
    map_area_top = _required_int(data, "map_area_top")
    map_area_width = _required_int(data, "map_area_width")
    map_area_height = _required_int(data, "map_area_height")
    configured_image_left = _required_float(data, "map_image_left")
    configured_image_top = _required_float(data, "map_image_top")
    configured_image_width = _required_float(data, "map_image_width")
    configured_image_height = _required_float(data, "map_image_height")
    zoom = _optional_float(data, "zoom", default=1.0)

    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("screen_width and screen_height must be positive")
    if map_area_width <= 0 or map_area_height <= 0:
        raise ValueError("map_area_width and map_area_height must be positive")
    if configured_image_width <= 0 or configured_image_height <= 0:
        raise ValueError("map_image_width and map_image_height must be positive")

    span_mode = str(data.get("viewport_span_mode") or "").strip().lower()
    if not span_mode:
        span_mode = "map-scale" if data.get("map_scale") is not None else "manual"
    if span_mode not in {"manual", "map-scale"}:
        raise ValueError("viewport_span_mode must be manual or map-scale")
    map_scale, map_scale_source = _resolve_map_scale(
        data,
        config_map_name,
        required=span_mode == "map-scale",
    )
    map_image_left = configured_image_left
    map_image_top = configured_image_top
    map_image_width = configured_image_width
    map_image_height = configured_image_height
    assumes_max_bigmap_zoom = False
    if span_mode == "map-scale":
        assert map_scale is not None
        center_x = configured_image_left + configured_image_width / 2
        center_y = configured_image_top + configured_image_height / 2
        map_image_width = screen_width * map_scale
        map_image_height = screen_height * map_scale
        map_image_left = center_x - map_image_width / 2
        map_image_top = center_y - map_image_height / 2
        assumes_max_bigmap_zoom = True

    viewport = MapMaskViewport(
        map_name=config_map_name,
        image_left=map_image_left,
        image_top=map_image_top,
        image_width=map_image_width,
        image_height=map_image_height,
        screen_left=map_area_left,
        screen_top=map_area_top,
        screen_width=map_area_width,
        screen_height=map_area_height,
        scale=zoom,
        rotation=_optional_float(data, "rotation", default=0.0),
    )
    return (
        viewport,
        screen_width,
        screen_height,
        {
            "map_scale": map_scale,
            "map_scale_source": map_scale_source,
            "viewport_span_source": span_mode,
            "assumes_max_bigmap_zoom": assumes_max_bigmap_zoom,
        },
    )


def _resolve_map_scale(
    data: dict[str, object],
    map_name: str,
    *,
    required: bool,
) -> tuple[float | None, str]:
    if data.get("map_scale") is not None:
        map_scale = _required_float(data, "map_scale")
        source = "calibration"
    else:
        map_scale = BIGMAP_POSITION_SCALE_DICT.get(map_name)
        source = "BIGMAP_POSITION_SCALE_DICT" if map_scale is not None else ""
    if map_scale is not None and (not math.isfinite(map_scale) or map_scale <= 0):
        raise ValueError("map_scale must be a positive finite number")
    if required and map_scale is None:
        raise ValueError(f"map_scale is unavailable for map_name={map_name!r}")
    return map_scale, source


def _center_correction_from_calibration(
    data: object,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("calibration must be a JSON object")
    raw = data.get("center_correction")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("center_correction must be a JSON object")
    enabled = _optional_bool(raw, "enabled", default=False)
    scale_x = _optional_float(raw, "scale_x", default=1.0)
    scale_y = _optional_float(raw, "scale_y", default=1.0)
    offset_x = _optional_float(raw, "offset_x", default=0.0)
    offset_y = _optional_float(raw, "offset_y", default=0.0)
    values = (scale_x, scale_y, offset_x, offset_y)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("center_correction values must be finite")
    return {
        "center_correction_enabled": enabled,
        "center_correction_scale_x": scale_x,
        "center_correction_scale_y": scale_y,
        "center_correction_offset_x": offset_x,
        "center_correction_offset_y": offset_y,
        "center_correction_source": str(
            raw.get("source") or ("calibration" if enabled else "disabled")
        ),
    }


def _required_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _required_float(data: dict[str, object], key: str) -> float:
    value = data.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _optional_float(data: dict[str, object], key: str, default: float) -> float:
    value = data.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _optional_bool(data: dict[str, object], key: str, default: bool) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{key} must be a boolean")


def _fallback_viewport() -> MapMaskViewport:
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
