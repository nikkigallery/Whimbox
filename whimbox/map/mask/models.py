from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class MapMaskLabel:
    id: str
    name: str
    parent_id: str | None = None
    icon: str = ""
    provider: str = "local"
    default_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MapMaskLabel":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            parent_id=data.get("parent_id"),
            icon=str(data.get("icon") or ""),
            provider=str(data.get("provider") or "local"),
            default_enabled=bool(data.get("default_enabled", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MapMaskPoint:
    id: str
    label_id: str
    name: str
    map_name: str
    image_x: float
    image_y: float
    game_x: float | None = None
    game_y: float | None = None
    icon: str = ""
    provider: str = "local"
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MapMaskPoint":
        return cls(
            id=str(data.get("id") or ""),
            label_id=str(data.get("label_id") or ""),
            name=str(data.get("name") or ""),
            map_name=str(data.get("map_name") or "miraland"),
            image_x=float(data.get("image_x") or 0.0),
            image_y=float(data.get("image_y") or 0.0),
            game_x=_optional_float(data.get("game_x")),
            game_y=_optional_float(data.get("game_y")),
            icon=str(data.get("icon") or ""),
            provider=str(data.get("provider") or "local"),
            detail=dict(data.get("detail") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MapMaskViewport:
    map_name: str
    image_left: float
    image_top: float
    image_width: float
    image_height: float
    screen_left: int
    screen_top: int
    screen_width: int
    screen_height: int
    scale: float = 1.0
    rotation: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MapMaskViewport":
        return cls(
            map_name=str(data.get("map_name") or "miraland"),
            image_left=float(data.get("image_left") or 0.0),
            image_top=float(data.get("image_top") or 0.0),
            image_width=float(data.get("image_width") or 0.0),
            image_height=float(data.get("image_height") or 0.0),
            screen_left=int(data.get("screen_left") or 0),
            screen_top=int(data.get("screen_top") or 0),
            screen_width=int(data.get("screen_width") or 0),
            screen_height=int(data.get("screen_height") or 0),
            scale=float(data.get("scale") or 1.0),
            rotation=float(data.get("rotation") or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VisibleMapMaskPoint:
    id: str
    label_id: str
    name: str
    map_name: str
    screen_x: float
    screen_y: float
    icon: str = ""
    provider: str = "local"
    is_visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MapMaskState:
    enabled: bool
    is_map_open: bool
    is_bigmap_open: bool
    has_valid_viewport: bool
    selected_label_ids: list[str]
    provider: str = "local"
    fallback_provider: str = "local"
    data_source: str = "sample"
    labels_source: str = "sample"
    points_source: str = "sample"
    local_labels_path: str = ""
    local_points_path: str = ""
    local_labels_error: str = ""
    local_points_error: str = ""
    viewport: dict[str, Any] = field(default_factory=dict)
    viewport_mode: str = "sample"
    viewport_source: str = "none"
    viewport_fallback_used: bool = False
    viewport_fallback_reason: str = ""
    viewport_detection_confidence: float = 0.0
    viewport_detection_error: str = ""
    viewport_center_x: float | None = None
    viewport_center_y: float | None = None
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
    last_viewport_update_time: str = ""
    viewport_stale: bool = False
    viewport_calibration_path: str = ""
    viewport_calibration_error: str = ""
    viewport_screen_width: int | None = None
    viewport_screen_height: int | None = None
    map_scale: float | None = None
    map_scale_source: str = ""
    viewport_span_source: str = "manual-calibration"
    assumes_max_bigmap_zoom: bool = False
    detection_mode: str = "auto"
    detection_source: str = "unknown"
    detection_confidence: float = 0.0
    raw_is_bigmap_open: bool = False
    detection_error: str = ""
    last_detection_time: str = ""
    last_successful_detection_time: str = ""
    detection_duration_ms: float = 0.0
    debug: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
