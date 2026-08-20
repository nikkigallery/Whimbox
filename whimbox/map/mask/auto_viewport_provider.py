from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import cv2
import numpy as np

from whimbox.common.utils.img_utils import crop, rgb2luma
from whimbox.common.logger import logger
from whimbox.map.detection.cvars import (
    BIGMAP_POSITION_SCALE_DICT,
    BIGMAP_SEARCH_SCALE,
)
from whimbox.map.detection.map_assets import MAP_ASSETS_DICT

from .bigmap_match_diagnostics import (
    BigMapMatchAnalysis,
    analyze_bigmap_match,
)
from .models import MapMaskViewport
from .viewport_provider import ViewportResult

if TYPE_CHECKING:
    from .viewport_provider import ManualCalibrationViewportProvider


_MIRALAND_ZOOM_SCALE_ANCHORS = {
    "second": 2.784,
    "third": 1.162,
    "max": 0.637,
}
_ZOOM_HINT_UNSUPPORTED = "当前地图缩放过小，请点击左下角“+”放大地图"
_ZOOM_HINT_LOW_CONFIDENCE = "暂时无法定位地图，建议将地图调整到最大缩放档位"


@dataclass(frozen=True, slots=True)
class _ZoomDetection:
    status: str
    level: str
    reference_scale: float | None
    confidence: float
    hint: str = ""


class HybridAutoCenterViewportProvider:
    """Update the map-image center and zoom from a big-map screenshot match.

    Screen bounds still come from calibration or the current capture. Matching
    remains side-effect free and never clicks the game's zoom controls.
    """

    def __init__(self, manual_provider: ManualCalibrationViewportProvider) -> None:
        self.manual_provider = manual_provider
        self._confidence_threshold = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_CONFIDENCE_THRESHOLD",
            default=0.35,
            minimum=0.0,
        )
        self._max_center_jump = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_MAX_CENTER_JUMP",
            default=1200.0,
            minimum=0.0,
        )
        self._confirm_frames = _env_int(
            "WHIMBOX_MAP_MASK_VIEWPORT_CONFIRM_FRAMES",
            default=2,
            minimum=1,
        )
        self._pending_radius = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_PENDING_RADIUS",
            default=300.0,
            minimum=0.0,
        )
        self._tracking_radius = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_TRACKING_RADIUS",
            default=1800.0,
            minimum=1.0,
        )
        self._reacquire_confirm_frames = _env_int(
            "WHIMBOX_MAP_MASK_VIEWPORT_REACQUIRE_CONFIRM_FRAMES",
            default=2,
            minimum=1,
        )
        self._reacquire_pending_radius = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_REACQUIRE_PENDING_RADIUS",
            default=250.0,
            minimum=0.0,
        )
        self._motion_diff_threshold = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_MOTION_DIFF_THRESHOLD",
            default=8.0,
            minimum=0.0,
        )
        self._smoothing_mode = _resolve_smoothing_mode()
        self._smoothing_max_distance = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_MAX_DISTANCE",
            default=300.0,
            minimum=0.0,
        )
        self._smoothing_alpha = min(
            1.0,
            _env_float(
                "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_ALPHA",
                default=0.3,
                minimum=0.0,
            ),
        )
        self._global_check_interval_ms = _env_int(
            "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_CHECK_INTERVAL_MS",
            default=3000,
            minimum=500,
        )
        self._global_check_delta_threshold = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_CHECK_DELTA_THRESHOLD",
            default=800.0,
            minimum=0.0,
        )
        self._global_match_min_margin = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_MATCH_MIN_MARGIN",
            default=0.02,
            minimum=0.0,
        )
        self._global_selected_top1_max_distance = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_GLOBAL_SELECTED_TOP1_MAX_DISTANCE",
            default=800.0,
            minimum=0.0,
        )
        self._expected_center = _expected_center_from_environment()
        self._expected_center_max_distance = _env_float(
            "WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_MAX_DISTANCE",
            default=3000.0,
            minimum=0.0,
        )
        self._reject_far_expected_center = _env_bool(
            "WHIMBOX_MAP_MASK_VIEWPORT_REJECT_FAR_EXPECTED_CENTER",
            default=False,
        )
        self._base_signature: tuple[object, ...] | None = None
        self._last_good_result: ViewportResult | None = None
        self._last_good_center: tuple[float, float] | None = None
        self._smoothed_center: tuple[float, float] | None = None
        self._last_good_center_monotonic: float | None = None
        self._pending_center: tuple[float, float] | None = None
        self._pending_confirm_count = 0
        self._previous_motion_frame: np.ndarray | None = None
        self._last_global_check_monotonic = 0.0
        self._tracking_center: tuple[float, float] | None = None
        self._global_check_center: tuple[float, float] | None = None
        self._global_check_delta: float | None = None
        self._global_check_confidence: float | None = None
        self._tracking_suspect = False
        self._tracking_reset_reason = ""
        self._last_global_check_time = ""
        self._last_global_analysis: BigMapMatchAnalysis | None = None
        self._matching_status = "matching_failed"
        self._matching_rejection_reason = ""
        self._zoom_detection = _ZoomDetection(
            status="unknown",
            level="",
            reference_scale=None,
            confidence=0.0,
        )

    def get_viewport(
        self,
        map_name: str | None = None,
        captured_image: np.ndarray | None = None,
    ) -> ViewportResult:
        resolved_map_name = map_name or "miraland"
        try:
            image = captured_image if captured_image is not None else self._capture_game()
            self._zoom_detection = self._detect_zoom_level(
                image,
                resolved_map_name,
            )
        except Exception as exc:  # noqa: BLE001
            reason = f"zoom detection failed: {type(exc).__name__}: {exc}"
            logger.warning(reason)
            self._reset_center_tracking()
            return ViewportResult(
                viewport=None,
                mode="hybrid-auto-center",
                source="zoom-detection-failed",
                fallback_used=True,
                fallback_reason=reason,
                detection_error=reason,
                stale=True,
                zoom_status="error",
                overlay_hint=_ZOOM_HINT_LOW_CONFIDENCE,
            )

        if self._zoom_detection.status != "supported":
            self._reset_center_tracking()
            return ViewportResult(
                viewport=None,
                mode="hybrid-auto-center",
                source="unsupported-bigmap-zoom",
                fallback_used=True,
                fallback_reason="supported big-map zoom level was not detected",
                stale=True,
                **self._zoom_result_fields(),
            )

        base = self.manual_provider.get_viewport(map_name=map_name)
        if base.viewport is None:
            try:
                base = _automatic_base_viewport(
                    image,
                    map_name=resolved_map_name,
                    map_scale=self._zoom_detection.reference_scale,
                )
            except Exception as exc:  # noqa: BLE001
                reason = f"automatic viewport base unavailable: {type(exc).__name__}: {exc}"
                logger.warning(reason)
                return ViewportResult(
                    viewport=None,
                    mode="hybrid-auto-center",
                    source="capture-derived-base-unavailable",
                    fallback_used=True,
                    fallback_reason=reason,
                    detection_error=reason,
                    smoothing_mode=self._smoothing_mode,
                    stale=True,
                )

        base_signature = _viewport_result_signature(base)
        if (
            self._base_signature is not None
            and self._base_signature != base_signature
        ):
            self._reset_tracking()
        self._base_signature = base_signature

        now = time.monotonic()
        try:
            motion_diff, motion_unstable = self._detect_motion(image)
            match = self._detect_tracking_first(
                image,
                base.viewport.map_name,
            )
            match = self._cross_check_tracking(
                image,
                base.viewport.map_name,
                match,
                now=now,
            )
            raw_center_x = float(match["center_x"])
            raw_center_y = float(match["center_y"])
            confidence = float(match["confidence"])
            matched_scale = float(
                match.get("map_scale")
                or self._zoom_detection.reference_scale
                or BIGMAP_POSITION_SCALE_DICT[base.viewport.map_name]
            )
            local_confidence = _optional_number(match.get("local_confidence"))
            global_confidence = _optional_number(match.get("global_confidence"))
            selected_match_source = str(match["source"])
            self._matching_status = str(
                match.get("matching_status") or "matching_accepted"
            )
            self._matching_rejection_reason = str(
                match.get("matching_rejection_reason") or ""
            )
            if self._matching_status in {"matching_failed", "matching_ambiguous"}:
                reason = (
                    f"{self._matching_status}: "
                    f"{self._matching_rejection_reason or 'global match rejected'}"
                )
                self._reset_pending()
                return self._fallback(
                    base=base,
                    reason=reason,
                    detection_error=reason,
                    confidence=confidence,
                    raw_center_x=raw_center_x,
                    raw_center_y=raw_center_y,
                    tracking_mode="tracking" if self._last_good_center else "reacquire",
                    motion_diff=motion_diff,
                    motion_unstable=motion_unstable,
                    local_confidence=local_confidence,
                    global_confidence=global_confidence,
                    selected_match_source=selected_match_source,
                    suppress_manual_viewport=True,
                    hide_last_good=True,
                )

            if confidence < self._confidence_threshold:
                reason = (
                    f"map match confidence {confidence:.3f} below threshold "
                    f"{self._confidence_threshold:.3f}"
                )
                self._matching_status = "matching_failed"
                self._matching_rejection_reason = reason
                self._reset_pending()
                return self._fallback(
                    base=base,
                    reason=reason,
                    detection_error=reason,
                    confidence=confidence,
                    raw_center_x=raw_center_x,
                    raw_center_y=raw_center_y,
                    tracking_mode=(
                        "tracking" if self._last_good_center else "reacquire"
                    ),
                    motion_diff=motion_diff,
                    motion_unstable=motion_unstable,
                    local_confidence=local_confidence,
                    global_confidence=global_confidence,
                    selected_match_source=selected_match_source,
                    suppress_manual_viewport=True,
                    hide_last_good=True,
                )

            if bool(match.get("force_global_reset")):
                smoothing = self._accept_center(
                    (raw_center_x, raw_center_y),
                    now=now,
                    confirmed_jump=True,
                )
                decision = {
                    "accepted_center": smoothing["accepted_center"],
                    "jump_distance": self._global_check_delta,
                    "candidate_distance": self._global_check_delta,
                    "accept_reason": "global-cross-check-reset",
                    "rejected_reason": "",
                    "tracking_mode": "reacquire",
                    **smoothing,
                }
            else:
                decision = self._stabilize_center(
                    raw_center=(raw_center_x, raw_center_y),
                    now=now,
                    selected_match_source=selected_match_source,
                    motion_unstable=motion_unstable,
                )
            if decision["accepted_center"] is None:
                return self._pending_fallback(
                    base=base,
                    raw_center=(raw_center_x, raw_center_y),
                    confidence=confidence,
                    jump_distance=decision["jump_distance"],
                    rejected_reason=str(decision["rejected_reason"]),
                    now=now,
                    tracking_mode=str(decision["tracking_mode"]),
                    motion_diff=motion_diff,
                    motion_unstable=motion_unstable,
                    local_confidence=local_confidence,
                    global_confidence=global_confidence,
                    selected_match_source=selected_match_source,
                )

            accepted_center = decision["accepted_center"]
            assert isinstance(accepted_center, tuple)
            accepted_center_x, accepted_center_y = accepted_center
            base = _base_with_map_scale(base, matched_scale)
            corrected_center_x, corrected_center_y = _apply_center_correction(
                accepted_center,
                base,
            )
            viewport = _viewport_from_center(
                base.viewport,
                center_x=corrected_center_x,
                center_y=corrected_center_y,
            )
            result = ViewportResult(
                viewport=viewport,
                mode="hybrid-auto-center",
                source="hybrid-auto-center",
                detection_confidence=confidence,
                center_x=corrected_center_x,
                center_y=corrected_center_y,
                raw_center_x=raw_center_x,
                raw_center_y=raw_center_y,
                accepted_center_x=accepted_center_x,
                accepted_center_y=accepted_center_y,
                corrected_center_x=corrected_center_x,
                corrected_center_y=corrected_center_y,
                center_jump_distance=decision["jump_distance"],
                center_accept_reason=str(decision["accept_reason"]),
                pending_confirm_count=0,
                last_good_center_age_ms=0.0,
                smoothing_mode=self._smoothing_mode,
                smoothing_applied=bool(decision["smoothing_applied"]),
                smoothing_distance=float(decision["smoothing_distance"]),
                snap_reason=str(decision["snap_reason"]),
                tracking_mode=str(decision["tracking_mode"]),
                motion_diff=motion_diff,
                motion_unstable=motion_unstable,
                candidate_distance_to_last_good=_optional_number(
                    decision["candidate_distance"]
                ),
                local_match_confidence=local_confidence,
                global_match_confidence=global_confidence,
                selected_match_source=selected_match_source,
                reacquire_pending_count=0,
                **self._cross_check_result_fields(),
                **self._matching_result_fields(),
                last_update_time=_now(),
                calibration_path=base.calibration_path,
                calibration_error=base.calibration_error,
                screen_width=base.screen_width,
                screen_height=base.screen_height,
                **_span_result_fields(base),
                **_correction_result_fields(base),
                **self._zoom_result_fields(),
            )
            self._last_good_result = result
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"hybrid auto viewport detection failed: {exc}")
            self._reset_pending()
            self._matching_status = "matching_failed"
            self._matching_rejection_reason = f"{type(exc).__name__}: {exc}"
            return self._fallback(
                base=base,
                reason="hybrid auto center detection failed",
                detection_error=f"{type(exc).__name__}: {exc}",
                confidence=0.0,
                raw_center_x=None,
                raw_center_y=None,
                tracking_mode="tracking" if self._last_good_center else "reacquire",
                motion_diff=None,
                motion_unstable=False,
                local_confidence=None,
                global_confidence=None,
                selected_match_source="none",
                suppress_manual_viewport=True,
                hide_last_good=True,
            )

    def _capture_game(self):
        from whimbox.interaction.interaction_core import itt

        image = itt.capture()
        if image is None or not hasattr(image, "shape"):
            raise RuntimeError("capture returned no image")
        shape = getattr(image, "shape", ())
        if len(shape) < 2 or int(shape[0]) <= 0 or int(shape[1]) <= 0:
            raise RuntimeError(f"capture has invalid shape: {shape!r}")
        return image

    def _detect_zoom_level(self, image, map_name: str) -> _ZoomDetection:
        from whimbox.common.cvars import IMG_RATE
        from whimbox.interaction.interaction_core import itt
        from whimbox.ui.ui_assets import (
            IconBigMapMaxScale,
            IconBigMapSecondScale,
            IconBigMapThirdScale,
        )

        icons = (
            ("max", IconBigMapMaxScale),
            ("third", IconBigMapThirdScale),
            ("second", IconBigMapSecondScale),
        )
        best_level = ""
        best_score = float("-inf")
        for level, icon in icons:
            icon_cap = crop(image, icon.cap_posi)
            score = float(
                itt.get_img_existence(
                    icon,
                    ret_mode=IMG_RATE,
                    cap=icon_cap,
                )
            )
            if score >= float(icon.threshold) and score > best_score:
                best_level = level
                best_score = score

        if not best_level:
            return _ZoomDetection(
                status="unsupported",
                level="",
                reference_scale=None,
                confidence=max(0.0, best_score),
                hint=_ZOOM_HINT_UNSUPPORTED,
            )

        reference = _zoom_scale_for_level(
            map_name,
            best_level,
        )
        return _ZoomDetection(
            status="supported",
            level=best_level,
            reference_scale=reference,
            confidence=best_score,
        )

    def _detect_tracking_first(self, image, map_name: str) -> dict[str, object]:
        local_confidence: float | None = None
        reference_scale = self._zoom_detection.reference_scale
        if reference_scale is None:
            raise RuntimeError("supported zoom has no reference scale")

        tracking_center = self._last_good_center or self._pending_center
        if tracking_center is not None:
            try:
                center_x, center_y, local_confidence = self._detect_center_local(
                    image,
                    map_name,
                    center=tracking_center,
                    map_scale=reference_scale,
                )
                if local_confidence >= self._confidence_threshold:
                    return {
                        "center_x": center_x,
                        "center_y": center_y,
                        "confidence": local_confidence,
                        "map_scale": reference_scale,
                        "local_confidence": local_confidence,
                        "global_confidence": None,
                        "source": "local",
                        "tracking_center_x": center_x,
                        "tracking_center_y": center_y,
                        "matching_status": "matching_accepted",
                        "matching_rejection_reason": "",
                    }
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"hybrid local viewport match failed: {exc}")

        center_x, center_y, global_confidence, global_scale = self._detect_center_global(
            image,
            map_name,
            map_scale=reference_scale,
        )
        return {
            "center_x": center_x,
            "center_y": center_y,
            "confidence": global_confidence,
            "map_scale": global_scale,
            "local_confidence": local_confidence,
            "global_confidence": global_confidence,
            "source": (
                "local-match-failed-global-used"
                if self._last_good_center is not None
                else "global-top1"
            ),
            "tracking_center_x": None,
            "tracking_center_y": None,
            "matching_status": self._matching_status,
            "matching_rejection_reason": self._matching_rejection_reason,
        }

    def _cross_check_tracking(
        self,
        image,
        map_name: str,
        match: dict[str, object],
        *,
        now: float,
    ) -> dict[str, object]:
        tracking_x = _optional_number(match.get("tracking_center_x"))
        tracking_y = _optional_number(match.get("tracking_center_y"))
        if tracking_x is not None and tracking_y is not None:
            self._tracking_center = (tracking_x, tracking_y)
        elif str(match.get("source")) == "local":
            self._tracking_center = (
                float(match["center_x"]),
                float(match["center_y"]),
            )

        if (
            self._last_good_center is None
            or str(match.get("source")) != "local"
            or (
                (now - self._last_global_check_monotonic) * 1000
                < self._global_check_interval_ms
            )
        ):
            return match

        self._last_global_check_monotonic = now
        self._last_global_check_time = _now()
        try:
            global_x, global_y, confidence, global_scale = self._detect_center_global(
                image,
                map_name,
                map_scale=self._zoom_detection.reference_scale,
            )
        except Exception as exc:  # noqa: BLE001
            self._global_check_center = None
            self._global_check_delta = None
            self._global_check_confidence = None
            self._tracking_suspect = False
            self._tracking_reset_reason = (
                f"global-cross-check-failed: {type(exc).__name__}: {exc}"
            )
            return match

        if self._matching_status in {"matching_failed", "matching_ambiguous"}:
            self._tracking_suspect = False
            self._tracking_reset_reason = (
                f"global-cross-check-{self._matching_status}: "
                f"{self._matching_rejection_reason}"
            )
            return match

        self._global_check_center = (global_x, global_y)
        self._global_check_confidence = confidence
        selected_center = (
            float(match["center_x"]),
            float(match["center_y"]),
        )
        self._global_check_delta = _distance(selected_center, self._global_check_center)
        if confidence < self._confidence_threshold:
            self._tracking_suspect = False
            self._tracking_reset_reason = "global-cross-check-confidence-low"
            return match
        if self._global_check_delta <= self._global_check_delta_threshold:
            self._tracking_suspect = False
            self._tracking_reset_reason = ""
            return match

        self._tracking_suspect = True
        self._tracking_reset_reason = "global-cross-check-delta-exceeded"
        self._reset_center_tracking()
        return {
            **match,
            "center_x": global_x,
            "center_y": global_y,
            "confidence": confidence,
            "map_scale": global_scale,
            "global_confidence": confidence,
            "source": "global-cross-check-reset",
            "force_global_reset": True,
        }

    def _detect_center_global(
        self,
        image,
        map_name: str,
        *,
        map_scale: float | None,
    ) -> tuple[float, float, float, float]:
        if map_scale is None:
            raise RuntimeError("global map match requires a map scale")
        analysis = analyze_bigmap_match(
            image,
            map_name,
            map_scale=map_scale,
        )
        self._last_global_analysis = analysis
        self._matching_status, self._matching_rejection_reason = (
            self._classify_global_match(analysis)
        )
        return (
            analysis.selected_center[0],
            analysis.selected_center[1],
            analysis.selected_confidence,
            float(map_scale),
        )

    def _classify_global_match(
        self,
        analysis: BigMapMatchAnalysis,
    ) -> tuple[str, str]:
        if analysis.input_std < 1.0:
            return (
                "matching_failed",
                "capture is blank or near-uniform "
                f"(mean={analysis.input_mean:.2f}, std={analysis.input_std:.2f}, "
                f"range={analysis.input_min:.0f}-{analysis.input_max:.0f})",
            )
        if not math.isfinite(analysis.selected_confidence):
            return "matching_failed", "selected center confidence is not finite"
        if not all(math.isfinite(value) for value in analysis.selected_center):
            return (
                "matching_failed",
                "selected center contains a non-finite coordinate",
            )

        warnings = []
        if analysis.selected_confidence < self._confidence_threshold:
            warnings.append(
                "selected-center confidence "
                f"{analysis.selected_confidence:.3f} below threshold "
                f"{self._confidence_threshold:.3f}; reported global top1 was "
                f"{analysis.raw_top1_confidence:.3f}"
            )
        margin = analysis.raw_top1_top2_margin
        if margin is None or margin < self._global_match_min_margin:
            warnings.append(
                f"top1/top2 margin {_format_optional(margin)} below "
                f"{self._global_match_min_margin:.3f}"
            )
        selected_delta = analysis.selected_to_raw_top1_distance
        if (
            selected_delta is None
            or selected_delta > self._global_selected_top1_max_distance
        ):
            warnings.append(
                "selected local-maximum center differs from raw top1 by "
                f"{_format_optional(selected_delta)} PNG px"
            )
        if self._expected_center is not None:
            expected_distance = _distance(
                analysis.selected_center,
                self._expected_center,
            )
            if expected_distance > self._expected_center_max_distance:
                warning = (
                    "BigMap center is far from known point; likely wrong area "
                    f"or user is not near this point ({expected_distance:.1f}px)"
                )
                if self._reject_far_expected_center:
                    return "matching_ambiguous", warning
                warnings.append(warning)

        if warnings:
            return "matching_provisional", "; ".join(warnings)
        return "matching_accepted", ""

    def _detect_center_local(
        self,
        image,
        map_name: str,
        *,
        center: tuple[float, float],
        map_scale: float,
    ) -> tuple[float, float, float]:
        if map_name not in MAP_ASSETS_DICT or map_name not in BIGMAP_POSITION_SCALE_DICT:
            raise RuntimeError(f"local map asset unavailable for {map_name!r}")

        template_scale = map_scale * BIGMAP_SEARCH_SCALE
        template = rgb2luma(image)
        template = cv2.resize(
            template,
            None,
            fx=template_scale,
            fy=template_scale,
            interpolation=cv2.INTER_NEAREST,
        )
        template_height, template_width = template.shape[:2]
        map_image = MAP_ASSETS_DICT[map_name]["luma_0125x"].img
        map_height, map_width = map_image.shape[:2]

        center_asset_x = center[0] * BIGMAP_SEARCH_SCALE
        center_asset_y = center[1] * BIGMAP_SEARCH_SCALE
        radius_asset = self._tracking_radius * BIGMAP_SEARCH_SCALE
        x1 = max(
            0,
            int(math.floor(center_asset_x - radius_asset - template_width / 2)),
        )
        y1 = max(
            0,
            int(math.floor(center_asset_y - radius_asset - template_height / 2)),
        )
        x2 = min(
            map_width,
            int(math.ceil(center_asset_x + radius_asset + template_width / 2)) + 1,
        )
        y2 = min(
            map_height,
            int(math.ceil(center_asset_y + radius_asset + template_height / 2)) + 1,
        )
        search_image = map_image[y1:y2, x1:x2]
        if (
            search_image.shape[0] < template_height
            or search_image.shape[1] < template_width
        ):
            raise RuntimeError("local search area is smaller than the screenshot template")

        result = cv2.matchTemplate(search_image, template, cv2.TM_CCOEFF_NORMED)
        result = self._mask_local_match_result(
            result,
            map_name=map_name,
            roi_left=x1,
            roi_top=y1,
            template_width=template_width,
            template_height=template_height,
            expected_center=center,
        )
        _, confidence, _, location = cv2.minMaxLoc(result)
        subpixel_x, subpixel_y = _subpixel_peak(result, location)
        candidate_x = (
            x1 + location[0] + subpixel_x + template_width / 2
        ) / BIGMAP_SEARCH_SCALE
        candidate_y = (
            y1 + location[1] + subpixel_y + template_height / 2
        ) / BIGMAP_SEARCH_SCALE
        return float(candidate_x), float(candidate_y), float(confidence)

    def _mask_local_match_result(
        self,
        result: np.ndarray,
        *,
        map_name: str,
        roi_left: int,
        roi_top: int,
        template_width: int,
        template_height: int,
        expected_center: tuple[float, float],
    ) -> np.ndarray:
        result_height, result_width = result.shape[:2]
        candidate_x = (
            roi_left
            + np.arange(result_width, dtype=np.float32)
            + template_width / 2
        )
        candidate_y = (
            roi_top
            + np.arange(result_height, dtype=np.float32)
            + template_height / 2
        )
        expected_x = expected_center[0] * BIGMAP_SEARCH_SCALE
        expected_y = expected_center[1] * BIGMAP_SEARCH_SCALE
        radius_asset = self._tracking_radius * BIGMAP_SEARCH_SCALE
        tracking_mask = (
            (candidate_x[np.newaxis, :] - expected_x) ** 2
            + (candidate_y[:, np.newaxis] - expected_y) ** 2
            <= radius_asset**2
        )

        mask_asset = MAP_ASSETS_DICT[map_name].get("mask_0125x")
        if mask_asset is None:
            return np.where(tracking_mask, result, -1.0).astype(np.float32)
        mask = mask_asset.img
        center_left = roi_left + template_width // 2
        center_top = roi_top + template_height // 2
        valid = mask[
            center_top:center_top + result_height,
            center_left:center_left + result_width,
        ]
        if valid.shape != result.shape:
            return np.where(tracking_mask, result, -1.0).astype(np.float32)
        return np.where(tracking_mask & (valid > 0), result, -1.0).astype(np.float32)

    def _detect_motion(self, image) -> tuple[float | None, bool]:
        current = _motion_frame(image)
        if self._previous_motion_frame is None:
            self._previous_motion_frame = current
            return None, False

        motion_diff = float(
            np.mean(
                cv2.absdiff(
                    current,
                    self._previous_motion_frame,
                )
            )
        )
        self._previous_motion_frame = current
        return motion_diff, motion_diff > self._motion_diff_threshold

    def _fallback(
        self,
        *,
        base: ViewportResult,
        reason: str,
        detection_error: str,
        confidence: float,
        raw_center_x: float | None,
        raw_center_y: float | None,
        tracking_mode: str,
        motion_diff: float | None,
        motion_unstable: bool,
        local_confidence: float | None,
        global_confidence: float | None,
        selected_match_source: str,
        suppress_manual_viewport: bool = False,
        hide_last_good: bool = False,
    ) -> ViewportResult:
        now = time.monotonic()
        jump_distance = _distance_optional(
            (raw_center_x, raw_center_y),
            self._last_good_center,
        )
        if (
            not hide_last_good
            and self._last_good_result is not None
            and self._last_good_result.viewport is not None
            and self._last_good_result.viewport.map_name == base.viewport.map_name
        ):
            accepted_center = self._applied_center()
            corrected_center = (
                self._last_good_result.corrected_center_x,
                self._last_good_result.corrected_center_y,
            )
            if corrected_center[0] is None or corrected_center[1] is None:
                corrected_center = (
                    _viewport_center_x(self._last_good_result.viewport),
                    _viewport_center_y(self._last_good_result.viewport),
                )
            result = replace(
                self._last_good_result,
                source="last-good-fallback",
                fallback_used=True,
                fallback_reason=reason,
                detection_confidence=confidence,
                detection_error=detection_error,
                center_x=corrected_center[0],
                center_y=corrected_center[1],
                raw_center_x=raw_center_x,
                raw_center_y=raw_center_y,
                accepted_center_x=accepted_center[0],
                accepted_center_y=accepted_center[1],
                corrected_center_x=corrected_center[0],
                corrected_center_y=corrected_center[1],
                pending_center_x=None,
                pending_center_y=None,
                center_jump_distance=jump_distance,
                center_accept_reason="",
                center_rejected_reason=reason,
                pending_confirm_count=0,
                last_good_center_age_ms=self._last_good_age_ms(now),
                smoothing_mode=self._smoothing_mode,
                smoothing_applied=False,
                smoothing_distance=_distance_optional(
                    (raw_center_x, raw_center_y),
                    accepted_center,
                ),
                snap_reason="",
                tracking_mode=tracking_mode,
                motion_diff=motion_diff,
                motion_unstable=motion_unstable,
                candidate_distance_to_last_good=jump_distance,
                local_match_confidence=local_confidence,
                global_match_confidence=global_confidence,
                selected_match_source=selected_match_source,
                reacquire_pending_count=0,
                **self._cross_check_result_fields(),
                **self._matching_result_fields(),
                **self._zoom_result_fields(
                    hint_override=_ZOOM_HINT_LOW_CONFIDENCE,
                ),
                stale=True,
            )
        else:
            accepted_center = (
                (None, None)
                if suppress_manual_viewport
                else (
                    _viewport_center_x(base.viewport),
                    _viewport_center_y(base.viewport),
                )
            )
            result = ViewportResult(
                viewport=None if suppress_manual_viewport else base.viewport,
                mode="hybrid-auto-center",
                source=(
                    "matching-rejected"
                    if suppress_manual_viewport
                    else "manual-calibration-fallback"
                ),
                fallback_used=True,
                fallback_reason=reason,
                detection_confidence=confidence,
                detection_error=detection_error,
                center_x=accepted_center[0],
                center_y=accepted_center[1],
                raw_center_x=raw_center_x,
                raw_center_y=raw_center_y,
                accepted_center_x=accepted_center[0],
                accepted_center_y=accepted_center[1],
                corrected_center_x=accepted_center[0],
                corrected_center_y=accepted_center[1],
                center_jump_distance=jump_distance,
                center_rejected_reason=reason,
                smoothing_mode=self._smoothing_mode,
                smoothing_applied=False,
                smoothing_distance=_distance_optional(
                    (raw_center_x, raw_center_y),
                    (
                        accepted_center
                        if accepted_center[0] is not None
                        and accepted_center[1] is not None
                        else None
                    ),
                ),
                tracking_mode=tracking_mode,
                motion_diff=motion_diff,
                motion_unstable=motion_unstable,
                candidate_distance_to_last_good=jump_distance,
                local_match_confidence=local_confidence,
                global_match_confidence=global_confidence,
                selected_match_source=selected_match_source,
                reacquire_pending_count=0,
                **self._cross_check_result_fields(),
                **self._matching_result_fields(),
                calibration_path=base.calibration_path,
                calibration_error=base.calibration_error,
                screen_width=base.screen_width,
                screen_height=base.screen_height,
                stale=True,
                **_span_result_fields(base),
                **_correction_result_fields(
                    base,
                    source_override="manual-calibration-fallback",
                ),
                **self._zoom_result_fields(
                    hint_override=_ZOOM_HINT_LOW_CONFIDENCE,
                ),
            )

        return result

    def _stabilize_center(
        self,
        *,
        raw_center: tuple[float, float],
        now: float,
        selected_match_source: str,
        motion_unstable: bool,
    ) -> dict[str, object]:
        candidate_distance = (
            _distance(raw_center, self._last_good_center)
            if self._last_good_center is not None
            else None
        )
        tracking_mode = "tracking" if self._last_good_center is not None else "reacquire"
        jump_distance = candidate_distance
        if (
            self._last_good_center is not None
            and candidate_distance is not None
            and candidate_distance <= self._tracking_radius
        ):
            self._reset_pending()
            smoothing = self._accept_center(
                raw_center,
                now=now,
                confirmed_jump=motion_unstable,
            )
            reason = (
                "tracking-motion-active"
                if motion_unstable
                else "tracking-local-match"
            )
            if selected_match_source != "local":
                reason = "tracking-near-last-good;local-match-failed-global-used"
            return {
                "accepted_center": smoothing["accepted_center"],
                "jump_distance": candidate_distance,
                "candidate_distance": candidate_distance,
                "accept_reason": reason,
                "rejected_reason": "",
                "tracking_mode": "tracking",
                **smoothing,
            }

        pending_started = bool(
            self._pending_center is None
            or _distance(raw_center, self._pending_center)
            > self._reacquire_pending_radius
        )
        if pending_started:
            self._pending_center = raw_center
            self._pending_confirm_count = 1
        else:
            old_count = self._pending_confirm_count
            new_count = old_count + 1
            assert self._pending_center is not None
            self._pending_center = (
                (self._pending_center[0] * old_count + raw_center[0]) / new_count,
                (self._pending_center[1] * old_count + raw_center[1]) / new_count,
            )
            self._pending_confirm_count = new_count

        if self._pending_confirm_count >= self._reacquire_confirm_frames:
            smoothing = self._accept_center(
                raw_center,
                now=now,
                confirmed_jump=True,
            )
            self._reset_pending()
            return {
                "accepted_center": smoothing["accepted_center"],
                "jump_distance": jump_distance,
                "candidate_distance": candidate_distance,
                "accept_reason": "reacquire-pending-confirmed",
                "rejected_reason": "",
                "tracking_mode": tracking_mode,
                **smoothing,
            }

        reasons = []
        if self._last_good_center is not None:
            reasons.append("rejected-far-candidate-in-tracking")
            if selected_match_source != "local":
                reasons.append("rejected-top1-far-jump")
        reasons.append(
            "reacquire-pending-started"
            if pending_started
            else "reacquire-pending-confirmation"
        )
        return {
            "accepted_center": None,
            "jump_distance": jump_distance,
            "candidate_distance": candidate_distance,
            "accept_reason": "",
            "rejected_reason": ";".join(reasons),
            "tracking_mode": tracking_mode,
            "smoothing_applied": False,
            "smoothing_distance": _distance_optional(
                raw_center,
                self._smoothed_center,
            ),
            "snap_reason": "",
        }

    def _accept_center(
        self,
        center: tuple[float, float],
        *,
        now: float,
        confirmed_jump: bool = False,
    ) -> dict[str, object]:
        previous_applied = self._smoothed_center
        smoothing_distance = (
            _distance(center, previous_applied)
            if previous_applied is not None
            else 0.0
        )
        self._last_good_center = center
        self._last_good_center_monotonic = now
        smoothing_applied = bool(
            previous_applied is not None
            and (
                self._smoothing_mode == "all"
                or (
                    self._smoothing_mode == "jitter-only"
                    and not confirmed_jump
                    and smoothing_distance <= self._smoothing_max_distance
                )
            )
        )
        snap_reason = ""
        if smoothing_applied:
            alpha = self._smoothing_alpha
            assert previous_applied is not None
            self._smoothed_center = (
                previous_applied[0] * (1.0 - alpha) + center[0] * alpha,
                previous_applied[1] * (1.0 - alpha) + center[1] * alpha,
            )
        else:
            self._smoothed_center = center
            if previous_applied is None:
                snap_reason = "initial-center"
            elif confirmed_jump:
                snap_reason = "confirmed-center-jump"
            elif self._smoothing_mode == "off":
                snap_reason = "smoothing-off"
            elif (
                self._smoothing_mode == "jitter-only"
                and smoothing_distance > self._smoothing_max_distance
            ):
                snap_reason = "smoothing-distance-exceeded"

        return {
            "accepted_center": self._smoothed_center,
            "smoothing_applied": smoothing_applied,
            "smoothing_distance": smoothing_distance,
            "snap_reason": snap_reason,
        }

    def _pending_fallback(
        self,
        *,
        base: ViewportResult,
        raw_center: tuple[float, float],
        confidence: float,
        jump_distance: object,
        rejected_reason: str,
        now: float,
        tracking_mode: str,
        motion_diff: float | None,
        motion_unstable: bool,
        local_confidence: float | None,
        global_confidence: float | None,
        selected_match_source: str,
    ) -> ViewportResult:
        pending_center = self._pending_center
        reason = rejected_reason
        if self._pending_confirm_count:
            reason += (
                f": {self._pending_confirm_count}/"
                f"{self._reacquire_confirm_frames} frames"
            )
        has_last_good = bool(
            self._last_good_result is not None
            and self._last_good_result.viewport is not None
        )
        accepted_center = self._applied_center() if has_last_good else (None, None)
        if has_last_good:
            assert self._last_good_result is not None
            corrected_center = (
                self._last_good_result.corrected_center_x,
                self._last_good_result.corrected_center_y,
            )
            if corrected_center[0] is None or corrected_center[1] is None:
                assert self._last_good_result.viewport is not None
                corrected_center = (
                    _viewport_center_x(self._last_good_result.viewport),
                    _viewport_center_y(self._last_good_result.viewport),
                )
        else:
            corrected_center = accepted_center
        common = {
            "fallback_used": True,
            "fallback_reason": reason,
            "detection_confidence": confidence,
            "detection_error": "",
            "center_x": corrected_center[0],
            "center_y": corrected_center[1],
            "raw_center_x": raw_center[0],
            "raw_center_y": raw_center[1],
            "accepted_center_x": accepted_center[0],
            "accepted_center_y": accepted_center[1],
            "corrected_center_x": corrected_center[0],
            "corrected_center_y": corrected_center[1],
            "pending_center_x": pending_center[0] if pending_center else None,
            "pending_center_y": pending_center[1] if pending_center else None,
            "center_jump_distance": _optional_number(jump_distance),
            "center_accept_reason": "",
            "center_rejected_reason": rejected_reason,
            "pending_confirm_count": self._pending_confirm_count,
            "last_good_center_age_ms": self._last_good_age_ms(now),
            "smoothing_mode": self._smoothing_mode,
            "smoothing_applied": False,
            "smoothing_distance": (
                _distance(raw_center, accepted_center) if has_last_good else None
            ),
            "snap_reason": "",
            "tracking_mode": tracking_mode,
            "motion_diff": motion_diff,
            "motion_unstable": motion_unstable,
            "candidate_distance_to_last_good": _optional_number(jump_distance),
            "local_match_confidence": local_confidence,
            "global_match_confidence": global_confidence,
            "selected_match_source": selected_match_source,
            "reacquire_pending_count": self._pending_confirm_count,
            **self._cross_check_result_fields(),
            **self._matching_result_fields(),
            **self._zoom_result_fields(),
            "stale": True,
        }
        if has_last_good:
            assert self._last_good_result is not None
            result = replace(
                self._last_good_result,
                source="last-good-fallback",
                **common,
            )
        else:
            result = ViewportResult(
                viewport=None,
                mode="hybrid-auto-center",
                source="reacquire-pending",
                calibration_path=base.calibration_path,
                calibration_error=base.calibration_error,
                screen_width=base.screen_width,
                screen_height=base.screen_height,
                **_span_result_fields(base),
                **_correction_result_fields(
                    base,
                    source_override="manual-calibration-fallback",
                ),
                **common,
            )
        return result

    def _applied_center(self) -> tuple[float, float]:
        if self._smoothed_center is not None:
            return self._smoothed_center
        if self._last_good_center is not None:
            return self._last_good_center
        if self._last_good_result is not None:
            if (
                self._last_good_result.accepted_center_x is not None
                and self._last_good_result.accepted_center_y is not None
            ):
                return (
                    self._last_good_result.accepted_center_x,
                    self._last_good_result.accepted_center_y,
                )
        if self._last_good_result is not None and self._last_good_result.viewport is not None:
            return (
                _viewport_center_x(self._last_good_result.viewport),
                _viewport_center_y(self._last_good_result.viewport),
            )
        raise RuntimeError("last-good viewport has no center")

    def _last_good_age_ms(self, now: float | None = None) -> float | None:
        if self._last_good_center_monotonic is None:
            return None
        current = time.monotonic() if now is None else now
        return max(0.0, (current - self._last_good_center_monotonic) * 1000)

    def _reset_pending(self) -> None:
        self._pending_center = None
        self._pending_confirm_count = 0

    def _reset_tracking(self) -> None:
        self._base_signature = None
        self._last_good_result = None
        self._last_good_center = None
        self._smoothed_center = None
        self._last_good_center_monotonic = None
        self._previous_motion_frame = None
        self._last_global_check_monotonic = 0.0
        self._tracking_center = None
        self._global_check_center = None
        self._global_check_delta = None
        self._global_check_confidence = None
        self._tracking_suspect = False
        self._tracking_reset_reason = ""
        self._last_global_check_time = ""
        self._last_global_analysis = None
        self._matching_status = "matching_failed"
        self._matching_rejection_reason = ""
        self._reset_pending()

    def _reset_center_tracking(self) -> None:
        self._last_good_result = None
        self._last_good_center = None
        self._smoothed_center = None
        self._last_good_center_monotonic = None
        self._reset_pending()

    def _cross_check_result_fields(self) -> dict[str, object]:
        return {
            "tracking_center_x": (
                self._tracking_center[0] if self._tracking_center else None
            ),
            "tracking_center_y": (
                self._tracking_center[1] if self._tracking_center else None
            ),
            "global_check_center_x": (
                self._global_check_center[0] if self._global_check_center else None
            ),
            "global_check_center_y": (
                self._global_check_center[1] if self._global_check_center else None
            ),
            "global_check_delta": self._global_check_delta,
            "global_check_confidence": self._global_check_confidence,
            "tracking_suspect": self._tracking_suspect,
            "tracking_reset_reason": self._tracking_reset_reason,
            "last_global_check_time": self._last_global_check_time,
        }

    def _matching_result_fields(self) -> dict[str, object]:
        analysis = self._last_global_analysis
        return {
            "matching_status": self._matching_status,
            "matching_rejection_reason": self._matching_rejection_reason,
            "global_match_top1_confidence": (
                analysis.raw_top1_confidence if analysis else None
            ),
            "global_match_top2_confidence": (
                analysis.raw_top2_confidence if analysis else None
            ),
            "global_match_margin": (
                analysis.raw_top1_top2_margin if analysis else None
            ),
            "global_selected_confidence": (
                analysis.selected_confidence if analysis else None
            ),
            "global_selected_local_score": (
                analysis.selected_local_score if analysis else None
            ),
            "global_selected_to_top1_distance": (
                analysis.selected_to_raw_top1_distance if analysis else None
            ),
        }

    def _zoom_result_fields(
        self,
        *,
        hint_override: str | None = None,
    ) -> dict[str, object]:
        zoom = self._zoom_detection
        return {
            "zoom_status": zoom.status,
            "zoom_level": zoom.level,
            "zoom_confidence": zoom.confidence,
            "overlay_hint": zoom.hint if hint_override is None else hint_override,
        }


def _automatic_base_viewport(
    image,
    *,
    map_name: str | None,
    map_scale: float | None = None,
) -> ViewportResult:
    resolved_map_name = map_name or "miraland"
    resolved_map_scale = (
        BIGMAP_POSITION_SCALE_DICT.get(resolved_map_name)
        if map_scale is None
        else float(map_scale)
    )
    if (
        resolved_map_scale is None
        or not math.isfinite(resolved_map_scale)
        or resolved_map_scale <= 0
    ):
        raise RuntimeError(
            f"map scale unavailable for automatic viewport: {resolved_map_name!r}"
        )

    shape = getattr(image, "shape", ())
    if len(shape) < 2:
        raise RuntimeError(
            f"capture has invalid shape for automatic viewport: {shape!r}"
        )
    screen_height = int(shape[0])
    screen_width = int(shape[1])
    if screen_width <= 0 or screen_height <= 0:
        raise RuntimeError(
            f"capture has invalid size: {screen_width}x{screen_height}"
        )

    image_width = screen_width * resolved_map_scale
    image_height = screen_height * resolved_map_scale
    viewport = MapMaskViewport(
        map_name=resolved_map_name,
        image_left=-image_width / 2,
        image_top=-image_height / 2,
        image_width=image_width,
        image_height=image_height,
        screen_left=0,
        screen_top=0,
        screen_width=screen_width,
        screen_height=screen_height,
        scale=1.0,
        rotation=0.0,
    )
    return ViewportResult(
        viewport=viewport,
        mode="hybrid-auto-center",
        source="capture-derived-base",
        screen_width=screen_width,
        screen_height=screen_height,
        map_scale=resolved_map_scale,
        map_scale_source=(
            "BIGMAP_POSITION_SCALE_DICT"
            if map_scale is None
            else "bigmap-zoom-ui-anchor"
        ),
        viewport_span_source="map-scale",
        assumes_max_bigmap_zoom=False,
    )


def _base_with_map_scale(
    base: ViewportResult,
    map_scale: float,
) -> ViewportResult:
    viewport = base.viewport
    if viewport is None:
        raise RuntimeError("cannot apply map scale without a base viewport")
    if not math.isfinite(map_scale) or map_scale <= 0:
        raise RuntimeError(f"invalid matched map scale: {map_scale!r}")
    image_width = viewport.screen_width * map_scale
    image_height = viewport.screen_height * map_scale
    center_x = _viewport_center_x(viewport)
    center_y = _viewport_center_y(viewport)
    scaled_viewport = replace(
        viewport,
        image_left=center_x - image_width / 2,
        image_top=center_y - image_height / 2,
        image_width=image_width,
        image_height=image_height,
    )
    return replace(
        base,
        viewport=scaled_viewport,
        map_scale=map_scale,
        map_scale_source="bigmap-zoom-ui-anchor",
        viewport_span_source="fixed-map-scale",
        assumes_max_bigmap_zoom=False,
    )


def _viewport_from_center(
    base: MapMaskViewport,
    *,
    center_x: float,
    center_y: float,
) -> MapMaskViewport:
    return MapMaskViewport(
        map_name=base.map_name,
        image_left=center_x - base.image_width / 2,
        image_top=center_y - base.image_height / 2,
        image_width=base.image_width,
        image_height=base.image_height,
        screen_left=base.screen_left,
        screen_top=base.screen_top,
        screen_width=base.screen_width,
        screen_height=base.screen_height,
        scale=base.scale,
        rotation=base.rotation,
    )


def _coerce_center(value: object) -> tuple[float, float]:
    try:
        center_x = float(value[0])  # type: ignore[index]
        center_y = float(value[1])  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"invalid bigmap center: {value!r}") from exc
    if not math.isfinite(center_x) or not math.isfinite(center_y):
        raise RuntimeError(f"invalid bigmap center: {value!r}")
    return center_x, center_y


def _viewport_center_x(viewport: MapMaskViewport) -> float:
    return viewport.image_left + viewport.image_width / 2


def _viewport_center_y(viewport: MapMaskViewport) -> float:
    return viewport.image_top + viewport.image_height / 2


def _viewport_signature(viewport: MapMaskViewport) -> tuple[object, ...]:
    return (
        viewport.map_name,
        viewport.screen_left,
        viewport.screen_top,
        viewport.screen_width,
        viewport.screen_height,
        round(viewport.image_left, 6),
        round(viewport.image_top, 6),
        round(viewport.image_width, 6),
        round(viewport.image_height, 6),
        round(viewport.scale, 6),
        round(viewport.rotation, 6),
    )


def _viewport_result_signature(result: ViewportResult) -> tuple[object, ...]:
    assert result.viewport is not None
    return (
        *_viewport_signature(result.viewport),
        result.center_correction_enabled,
        round(result.center_correction_scale_x, 9),
        round(result.center_correction_scale_y, 9),
        round(result.center_correction_offset_x, 6),
        round(result.center_correction_offset_y, 6),
        result.center_correction_source,
        result.map_scale,
        result.map_scale_source,
        result.viewport_span_source,
        result.assumes_max_bigmap_zoom,
    )


def _apply_center_correction(
    center: tuple[float, float],
    base: ViewportResult,
) -> tuple[float, float]:
    if not base.center_correction_enabled:
        return center
    return (
        center[0] * base.center_correction_scale_x
        + base.center_correction_offset_x,
        center[1] * base.center_correction_scale_y
        + base.center_correction_offset_y,
    )


def _correction_result_fields(
    base: ViewportResult,
    *,
    source_override: str | None = None,
) -> dict[str, object]:
    return {
        "center_correction_enabled": base.center_correction_enabled,
        "center_correction_scale_x": base.center_correction_scale_x,
        "center_correction_scale_y": base.center_correction_scale_y,
        "center_correction_offset_x": base.center_correction_offset_x,
        "center_correction_offset_y": base.center_correction_offset_y,
        "center_correction_source": (
            source_override or base.center_correction_source
        ),
    }


def _span_result_fields(base: ViewportResult) -> dict[str, object]:
    return {
        "map_scale": base.map_scale,
        "map_scale_source": base.map_scale_source,
        "viewport_span_source": base.viewport_span_source,
        "assumes_max_bigmap_zoom": base.assumes_max_bigmap_zoom,
    }


def _zoom_scale_for_level(
    map_name: str,
    level: str,
) -> float:
    base_scale = BIGMAP_POSITION_SCALE_DICT.get(map_name)
    if base_scale is None or not math.isfinite(base_scale) or base_scale <= 0:
        raise RuntimeError(f"bigmap scale unavailable for {map_name!r}")
    normalization = base_scale / _MIRALAND_ZOOM_SCALE_ANCHORS["max"]
    anchors = {
        name: scale * normalization
        for name, scale in _MIRALAND_ZOOM_SCALE_ANCHORS.items()
    }
    try:
        return anchors[level]
    except KeyError as exc:
        raise RuntimeError(f"unsupported bigmap zoom level: {level!r}") from exc


def _distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _distance_optional(
    first: tuple[float | None, float | None],
    second: tuple[float, float] | None,
) -> float | None:
    if first[0] is None or first[1] is None or second is None:
        return None
    return _distance((first[0], first[1]), second)


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _subpixel_peak(
    result: np.ndarray,
    location: tuple[int, int],
) -> tuple[float, float]:
    x, y = location
    height, width = result.shape[:2]
    offset_x = 0.0
    offset_y = 0.0
    if 0 < x < width - 1:
        offset_x = _parabolic_peak_offset(
            float(result[y, x - 1]),
            float(result[y, x]),
            float(result[y, x + 1]),
        )
    if 0 < y < height - 1:
        offset_y = _parabolic_peak_offset(
            float(result[y - 1, x]),
            float(result[y, x]),
            float(result[y + 1, x]),
        )
    return offset_x, offset_y


def _parabolic_peak_offset(
    before: float,
    center: float,
    after: float,
) -> float:
    denominator = before - 2.0 * center + after
    if not math.isfinite(denominator) or abs(denominator) < 1e-8:
        return 0.0
    offset = 0.5 * (before - after) / denominator
    return max(-1.0, min(1.0, offset)) if math.isfinite(offset) else 0.0


def _motion_frame(image) -> np.ndarray:
    frame = np.asarray(image)
    if frame.ndim == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    elif frame.ndim == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    elif frame.ndim != 2:
        raise RuntimeError(f"unsupported motion frame shape: {frame.shape!r}")
    return cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, value)


def _resolve_smoothing_mode() -> str:
    configured = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_MODE")
    if configured:
        normalized = configured.strip().lower().replace("_", "-")
        if normalized in {"off", "jitter-only", "all"}:
            return normalized
        logger.warning(
            "invalid WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING_MODE="
            f"{configured!r}; using jitter-only"
        )
        return "jitter-only"

    legacy = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING")
    if legacy is not None and not _env_bool(
        "WHIMBOX_MAP_MASK_VIEWPORT_SMOOTHING",
        default=True,
    ):
        return "off"
    return "jitter-only"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _expected_center_from_environment() -> tuple[float, float] | None:
    raw_x = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_X")
    raw_y = os.environ.get("WHIMBOX_MAP_MASK_VIEWPORT_EXPECTED_CENTER_Y")
    if raw_x is None or raw_y is None:
        return None
    try:
        center = (float(raw_x), float(raw_y))
    except ValueError:
        logger.warning("invalid expected BigMap center; debug distance gate disabled")
        return None
    if not all(math.isfinite(value) for value in center):
        logger.warning("non-finite expected BigMap center; debug distance gate disabled")
        return None
    return center


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()
