from __future__ import annotations

import math
import threading
import time
from typing import Any

from whimbox.common.logger import logger
from whimbox.config.config import global_config

from .bigmap_state_provider import BigMapDetectionState, BigMapStateProvider
from .coordinate import point_to_visible
from .local_provider import LocalJsonProvider
from .models import MapMaskLabel, MapMaskState, MapMaskViewport
from .pearpal_provider import OfficialPearPalProvider
from .provider import MapMaskProvider
from .viewport_provider import MapMaskViewportProvider, ViewportResult


_DETECTION_WORKER_INTERVAL_SECONDS = 0.05
_DETECTION_WORKER_IDLE_SECONDS = 2.0


class MapMaskService:
    def __init__(self) -> None:
        self.local_provider = LocalJsonProvider()
        point_provider_name = str(
            global_config.get("MapMask", "point_provider", "pearpal") or "pearpal"
        ).strip().lower()
        use_pearpal = point_provider_name != "local"
        self.official_provider = OfficialPearPalProvider(enabled=use_pearpal)
        self.viewport_provider = MapMaskViewportProvider()
        self.bigmap_state_provider = BigMapStateProvider()
        self.provider: MapMaskProvider = (
            self.official_provider if use_pearpal else self.local_provider
        )
        self.fallback_provider: MapMaskProvider = self.local_provider
        self.enabled = global_config.get_bool("MapMask", "enabled", True)
        self.use_sample_viewport = global_config.get_bool("MapMask", "use_sample_viewport", True)
        self._selected_label_ids: list[str] | None = None
        self._detection_lock = threading.Lock()
        self._detection_provider_lock = threading.Lock()
        self._detection_wake = threading.Event()
        self._detection_thread: threading.Thread | None = None
        self._detection_last_activity = 0.0
        self._detection_map_name: str | None = None
        self._detection_snapshot: tuple[BigMapDetectionState, ViewportResult] | None = None

    def _touch_detection_worker(self, map_name: str | None) -> None:
        with self._detection_lock:
            if not self.enabled:
                return
            map_changed = map_name != self._detection_map_name
            self._detection_last_activity = time.monotonic()
            self._detection_map_name = map_name
            worker_running = bool(
                self._detection_thread is not None
                and self._detection_thread.is_alive()
            )
            if not worker_running:
                self._detection_snapshot = None
                self._detection_wake.clear()
            self._ensure_detection_thread_locked()
            if worker_running and map_changed:
                self._detection_wake.set()

    def _ensure_detection_thread_locked(self) -> None:
        if self._detection_thread is not None and self._detection_thread.is_alive():
            return
        thread = threading.Thread(
            target=self._detection_loop,
            name="map-mask-detection",
            daemon=True,
        )
        self._detection_thread = thread
        thread.start()

    def _detection_loop(self) -> None:
        current_thread = threading.current_thread()
        logger.info("[map-mask-worker] started")
        stop_reason = "inactive"
        try:
            while True:
                with self._detection_lock:
                    inactive_for = time.monotonic() - self._detection_last_activity
                    if not self.enabled:
                        stop_reason = "disabled"
                        if self._detection_thread is current_thread:
                            self._detection_thread = None
                            self._detection_snapshot = None
                        break
                    if inactive_for >= _DETECTION_WORKER_IDLE_SECONDS:
                        stop_reason = "request-idle-timeout"
                        if self._detection_thread is current_thread:
                            # Release ownership before leaving the loop so a request
                            # arriving at the timeout boundary can start a new worker.
                            self._detection_thread = None
                            self._detection_snapshot = None
                        break
                    map_name = self._detection_map_name

                cycle_started = time.perf_counter()
                try:
                    with self._detection_provider_lock:
                        bigmap_state = self.bigmap_state_provider.detect()
                        viewport_result = self._detect_viewport_result(
                            map_name=map_name,
                            is_bigmap_open=bigmap_state.is_bigmap_open,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(f"[map-mask-worker] detection cycle failed: {exc}")
                else:
                    with self._detection_lock:
                        if self.enabled and self._detection_thread is current_thread:
                            self._detection_snapshot = (bigmap_state, viewport_result)

                elapsed = time.perf_counter() - cycle_started
                wait_seconds = max(0.0, _DETECTION_WORKER_INTERVAL_SECONDS - elapsed)
                self._detection_wake.wait(wait_seconds)
                self._detection_wake.clear()
        finally:
            with self._detection_lock:
                if self._detection_thread is current_thread:
                    self._detection_thread = None
                    self._detection_snapshot = None
            logger.info(f"[map-mask-worker] stopped reason={stop_reason}")

    def _detect_viewport_result(
        self,
        *,
        map_name: str | None,
        is_bigmap_open: bool,
    ) -> ViewportResult:
        if not is_bigmap_open:
            return ViewportResult(
                viewport=None,
                mode=self.viewport_provider.get_mode(),
                source="bigmap-closed",
                fallback_reason="big map is closed",
            )
        if not self.use_sample_viewport:
            return ViewportResult(
                viewport=None,
                mode="sample",
                source="none",
                calibration_error="sample viewport disabled",
            )
        return self.viewport_provider.get_viewport(
            map_name=map_name,
            force_refresh=True,
        )

    def _get_detection_snapshot(
        self,
    ) -> tuple[BigMapDetectionState, ViewportResult] | None:
        with self._detection_lock:
            if not self.enabled:
                return None
            return self._detection_snapshot

    def _pending_detection_state(self) -> BigMapDetectionState:
        mode = self.bigmap_state_provider.get_mode()
        return BigMapDetectionState(
            is_bigmap_open=False,
            raw_is_bigmap_open=False,
            stable_is_bigmap_open=False,
            consecutive_open_count=0,
            consecutive_closed_count=0,
            detection_mode=mode,
            detection_source="worker.pending",
            detection_confidence=0.0,
            detection_error="",
            last_detection_time="",
            last_successful_detection_time="",
            detection_duration_ms=0.0,
            detection_interval_ms=int(_DETECTION_WORKER_INTERVAL_SECONDS * 1000),
            stable_open_frames=2,
            stable_closed_frames=2,
            message="map-mask detection worker is pending or inactive",
        )

    def get_state(
        self,
        viewport: MapMaskViewport | None = None,
        map_name: str | None = None,
    ) -> dict[str, Any]:
        state, _, _ = self._build_state(viewport=viewport, map_name=map_name)
        return state.to_dict()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        self.enabled = bool(enabled)
        if not self.enabled:
            with self._detection_lock:
                self._detection_snapshot = None
                self._detection_wake.set()
        return self.get_state()

    def set_bigmap_detection_mode(self, mode: str) -> dict[str, Any]:
        with self._detection_provider_lock:
            self.bigmap_state_provider.set_mode(mode)
        with self._detection_lock:
            self._detection_snapshot = None
            self._detection_wake.set()
        return self.get_state()

    def get_labels(self) -> list[dict[str, Any]]:
        return [label.to_dict() for label in self._list_labels()]

    def get_selected_label_ids(self) -> list[str]:
        if self._selected_label_ids is None:
            self._selected_label_ids = [
                label.id for label in self._list_labels() if label.default_enabled
            ]
        return list(self._selected_label_ids)

    def set_selected_label_ids(self, label_ids: list[str]) -> dict[str, Any]:
        valid_ids = {label.id for label in self._list_labels()}
        self._selected_label_ids = [
            str(label_id) for label_id in label_ids if str(label_id) in valid_ids
        ]
        return {
            "selected_label_ids": self.get_selected_label_ids(),
            "labels": self.get_labels(),
        }

    def get_visible_points(
        self,
        viewport: MapMaskViewport | None = None,
        map_name: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self._touch_detection_worker(map_name)
        state, active_viewport, _ = self._build_state(viewport=viewport, map_name=map_name)
        state_dict = state.to_dict()
        if not self.enabled or not state.is_bigmap_open or active_viewport is None:
            return {"state": state_dict, "viewport": {}, "points": []}

        selected_label_ids = label_ids if label_ids is not None else self.get_selected_label_ids()
        points = self._list_points(label_ids=selected_label_ids, map_name=active_viewport.map_name)
        visible_points = []
        for point in points:
            visible = point_to_visible(point, active_viewport)
            if visible is not None:
                visible_points.append(visible.to_dict())

        return {
            "state": state_dict,
            "viewport": active_viewport.to_dict(),
            "points": visible_points,
        }

    def get_point_detail(self, point_id: str) -> dict[str, Any]:
        return self._provider_with_fallback().get_point_detail(point_id)

    def get_viewport(self, map_name: str | None = None) -> MapMaskViewport | None:
        if not self.use_sample_viewport:
            return None
        return self.viewport_provider.get_viewport(map_name=map_name).viewport

    def _build_state(
        self,
        viewport: MapMaskViewport | None = None,
        map_name: str | None = None,
    ) -> tuple[MapMaskState, MapMaskViewport | None, BigMapDetectionState]:
        selected_label_ids = self.get_selected_label_ids()
        uses_detection_worker = bool(
            viewport is None
            and self.viewport_provider.get_mode() == "hybrid-auto-center"
        )
        if uses_detection_worker:
            snapshot = self._get_detection_snapshot()
            if snapshot is None:
                bigmap_state = self._pending_detection_state()
                viewport_result = ViewportResult(
                    viewport=None,
                    mode="hybrid-auto-center",
                    source="detection-worker-pending",
                    fallback_reason="detection worker has no snapshot yet",
                    stale=True,
                )
            else:
                bigmap_state, viewport_result = snapshot
        else:
            bigmap_state = self.bigmap_state_provider.detect()
            viewport_result = self._get_viewport_result(
                viewport=viewport,
                map_name=map_name,
                is_bigmap_open=bigmap_state.is_bigmap_open,
            )
        data_status = self._get_data_status()
        raw_viewport = viewport_result.viewport
        viewport_source = self._get_viewport_source(viewport_result, bigmap_state.is_bigmap_open)
        active_viewport = raw_viewport if bigmap_state.is_bigmap_open else None
        has_valid_viewport = active_viewport is not None
        nearest_point = self._nearest_loaded_point(
            active_viewport,
            viewport_result,
            selected_label_ids,
        )
        state = MapMaskState(
            enabled=self.enabled,
            is_map_open=self.enabled and bigmap_state.is_bigmap_open and has_valid_viewport,
            is_bigmap_open=bigmap_state.is_bigmap_open,
            has_valid_viewport=has_valid_viewport,
            selected_label_ids=selected_label_ids,
            provider=self.provider.name,
            fallback_provider=self.fallback_provider.name,
            data_source=str(data_status.get("data_source") or "sample"),
            labels_source=str(data_status.get("labels_source") or "sample"),
            points_source=str(data_status.get("points_source") or "sample"),
            local_labels_path=str(data_status.get("labels_path") or ""),
            local_points_path=str(data_status.get("points_path") or ""),
            local_labels_error=str(data_status.get("labels_error") or ""),
            local_points_error=str(data_status.get("points_error") or ""),
            viewport=active_viewport.to_dict() if active_viewport else {},
            viewport_mode=viewport_result.mode,
            viewport_source=viewport_source,
            viewport_fallback_used=viewport_result.fallback_used,
            viewport_fallback_reason=viewport_result.fallback_reason,
            viewport_detection_confidence=viewport_result.detection_confidence,
            viewport_detection_error=viewport_result.detection_error,
            viewport_center_x=viewport_result.center_x,
            viewport_center_y=viewport_result.center_y,
            raw_center_x=viewport_result.raw_center_x,
            raw_center_y=viewport_result.raw_center_y,
            accepted_center_x=viewport_result.accepted_center_x,
            accepted_center_y=viewport_result.accepted_center_y,
            corrected_center_x=viewport_result.corrected_center_x,
            corrected_center_y=viewport_result.corrected_center_y,
            center_correction_enabled=viewport_result.center_correction_enabled,
            center_correction_scale_x=viewport_result.center_correction_scale_x,
            center_correction_scale_y=viewport_result.center_correction_scale_y,
            center_correction_offset_x=viewport_result.center_correction_offset_x,
            center_correction_offset_y=viewport_result.center_correction_offset_y,
            center_correction_source=viewport_result.center_correction_source,
            **nearest_point,
            pending_center_x=viewport_result.pending_center_x,
            pending_center_y=viewport_result.pending_center_y,
            center_jump_distance=viewport_result.center_jump_distance,
            center_accept_reason=viewport_result.center_accept_reason,
            center_rejected_reason=viewport_result.center_rejected_reason,
            pending_confirm_count=viewport_result.pending_confirm_count,
            last_good_center_age_ms=viewport_result.last_good_center_age_ms,
            smoothing_mode=viewport_result.smoothing_mode,
            smoothing_applied=viewport_result.smoothing_applied,
            smoothing_distance=viewport_result.smoothing_distance,
            snap_reason=viewport_result.snap_reason,
            tracking_mode=viewport_result.tracking_mode,
            motion_diff=viewport_result.motion_diff,
            motion_unstable=viewport_result.motion_unstable,
            motion_stable_count=viewport_result.motion_stable_count,
            candidate_distance_to_last_good=viewport_result.candidate_distance_to_last_good,
            local_match_confidence=viewport_result.local_match_confidence,
            global_match_confidence=viewport_result.global_match_confidence,
            selected_match_source=viewport_result.selected_match_source,
            reacquire_pending_count=viewport_result.reacquire_pending_count,
            tracking_center_x=viewport_result.tracking_center_x,
            tracking_center_y=viewport_result.tracking_center_y,
            global_check_center_x=viewport_result.global_check_center_x,
            global_check_center_y=viewport_result.global_check_center_y,
            global_check_delta=viewport_result.global_check_delta,
            global_check_confidence=viewport_result.global_check_confidence,
            tracking_suspect=viewport_result.tracking_suspect,
            tracking_reset_reason=viewport_result.tracking_reset_reason,
            last_global_check_time=viewport_result.last_global_check_time,
            matching_status=viewport_result.matching_status,
            matching_rejection_reason=viewport_result.matching_rejection_reason,
            global_match_top1_confidence=viewport_result.global_match_top1_confidence,
            global_match_top2_confidence=viewport_result.global_match_top2_confidence,
            global_match_margin=viewport_result.global_match_margin,
            global_selected_confidence=viewport_result.global_selected_confidence,
            global_selected_local_score=viewport_result.global_selected_local_score,
            global_selected_to_top1_distance=(
                viewport_result.global_selected_to_top1_distance
            ),
            last_viewport_update_time=viewport_result.last_update_time,
            viewport_stale=viewport_result.stale,
            viewport_calibration_path=viewport_result.calibration_path,
            viewport_calibration_error=viewport_result.calibration_error,
            viewport_screen_width=viewport_result.screen_width,
            viewport_screen_height=viewport_result.screen_height,
            map_scale=viewport_result.map_scale,
            map_scale_source=viewport_result.map_scale_source,
            viewport_span_source=viewport_result.viewport_span_source,
            assumes_max_bigmap_zoom=viewport_result.assumes_max_bigmap_zoom,
            detection_mode=bigmap_state.detection_mode,
            detection_source=bigmap_state.detection_source,
            detection_confidence=bigmap_state.detection_confidence,
            raw_is_bigmap_open=bigmap_state.raw_is_bigmap_open,
            stable_is_bigmap_open=bigmap_state.stable_is_bigmap_open,
            consecutive_open_count=bigmap_state.consecutive_open_count,
            consecutive_closed_count=bigmap_state.consecutive_closed_count,
            detection_error=bigmap_state.detection_error,
            last_detection_time=bigmap_state.last_detection_time,
            last_successful_detection_time=bigmap_state.last_successful_detection_time,
            detection_duration_ms=bigmap_state.detection_duration_ms,
            detection_interval_ms=bigmap_state.detection_interval_ms,
            stable_open_frames=bigmap_state.stable_open_frames,
            stable_closed_frames=bigmap_state.stable_closed_frames,
            debug=self.use_sample_viewport,
            message=bigmap_state.message,
        )
        return state, active_viewport, bigmap_state

    def _get_viewport_result(
        self,
        viewport: MapMaskViewport | None,
        map_name: str | None,
        is_bigmap_open: bool,
    ) -> ViewportResult:
        if not is_bigmap_open:
            return ViewportResult(
                viewport=None,
                mode=self.viewport_provider.get_mode(),
                source="bigmap-closed",
                fallback_reason="big map is closed",
            )
        if viewport is not None:
            return ViewportResult(
                viewport=viewport,
                mode="manual-calibration",
                source="request",
            )
        if not self.use_sample_viewport:
            return ViewportResult(
                viewport=None,
                mode="sample",
                source="none",
                calibration_error="sample viewport disabled",
            )
        return self.viewport_provider.get_viewport(map_name=map_name)

    def _get_viewport_source(
        self,
        viewport_result: ViewportResult,
        is_bigmap_open: bool,
    ) -> str:
        if not is_bigmap_open:
            return "bigmap-closed"
        return viewport_result.source if viewport_result.viewport is not None else "none"

    def _nearest_loaded_point(
        self,
        viewport: MapMaskViewport | None,
        viewport_result: ViewportResult,
        selected_label_ids: list[str],
    ) -> dict[str, Any]:
        empty = {
            "nearest_loaded_point_id": "",
            "nearest_loaded_point_name": "",
            "nearest_loaded_point_image_x": None,
            "nearest_loaded_point_image_y": None,
            "nearest_loaded_point_distance": None,
            "nearest_loaded_point_delta_image_x": None,
            "nearest_loaded_point_delta_image_y": None,
            "nearest_loaded_point_delta_screen_x": None,
            "nearest_loaded_point_delta_screen_y": None,
            "nearest_loaded_point_label_id": "",
            "nearest_loaded_point_label_exists": False,
            "nearest_loaded_point_label_enabled": False,
            "nearest_loaded_point_final_visible": False,
            "nearest_loaded_point_invisible_reason": "no_valid_viewport",
        }
        if viewport is None:
            return empty
        center_x = (
            viewport_result.corrected_center_x
            if viewport_result.corrected_center_x is not None
            else viewport.image_left + viewport.image_width / 2
        )
        center_y = (
            viewport_result.corrected_center_y
            if viewport_result.corrected_center_y is not None
            else viewport.image_top + viewport.image_height / 2
        )
        try:
            points = self._list_points(map_name=viewport.map_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"failed to inspect nearest map-mask point: {exc}")
            return empty
        if not points:
            return empty
        nearest = min(
            points,
            key=lambda point: math.hypot(
                point.image_x - center_x,
                point.image_y - center_y,
            ),
        )
        labels_by_id = {label.id: label for label in self._list_labels()}
        label_exists = nearest.label_id in labels_by_id
        label_enabled = nearest.label_id in set(selected_label_ids)
        projected = point_to_visible(nearest, viewport)
        final_visible = bool(label_exists and label_enabled and projected is not None)
        if not label_exists:
            invisible_reason = "label_not_registered"
        elif not label_enabled:
            invisible_reason = "label_not_enabled"
        elif projected is None:
            invisible_reason = "outside_viewport"
        else:
            invisible_reason = ""
        point_screen_x = (
            viewport.screen_left
            + (nearest.image_x - viewport.image_left)
            / viewport.image_width
            * viewport.screen_width
        )
        point_screen_y = (
            viewport.screen_top
            + (nearest.image_y - viewport.image_top)
            / viewport.image_height
            * viewport.screen_height
        )
        screen_center_x = viewport.screen_left + viewport.screen_width / 2
        screen_center_y = viewport.screen_top + viewport.screen_height / 2
        accepted_x = (
            viewport_result.accepted_center_x
            if viewport_result.accepted_center_x is not None
            else center_x
        )
        accepted_y = (
            viewport_result.accepted_center_y
            if viewport_result.accepted_center_y is not None
            else center_y
        )
        return {
            "nearest_loaded_point_id": nearest.id,
            "nearest_loaded_point_name": nearest.name,
            "nearest_loaded_point_image_x": nearest.image_x,
            "nearest_loaded_point_image_y": nearest.image_y,
            "nearest_loaded_point_distance": math.hypot(
                nearest.image_x - center_x,
                nearest.image_y - center_y,
            ),
            "nearest_loaded_point_delta_image_x": nearest.image_x - accepted_x,
            "nearest_loaded_point_delta_image_y": nearest.image_y - accepted_y,
            "nearest_loaded_point_delta_screen_x": point_screen_x - screen_center_x,
            "nearest_loaded_point_delta_screen_y": point_screen_y - screen_center_y,
            "nearest_loaded_point_label_id": nearest.label_id,
            "nearest_loaded_point_label_exists": label_exists,
            "nearest_loaded_point_label_enabled": label_enabled,
            "nearest_loaded_point_final_visible": final_visible,
            "nearest_loaded_point_invisible_reason": invisible_reason,
        }

    def _get_data_status(self) -> dict[str, Any]:
        if hasattr(self.provider, "get_data_status"):
            return self.provider.get_data_status()
        return {
            "data_source": self.provider.name,
            "labels_source": self.provider.name,
            "points_source": self.provider.name,
        }

    def _list_labels(self) -> list[MapMaskLabel]:
        return self._provider_with_fallback().list_labels()

    def _list_points(
        self,
        label_ids: list[str] | None = None,
        map_name: str | None = None,
    ):
        return self._provider_with_fallback().list_points(
            label_ids=label_ids,
            map_name=map_name,
        )

    def _provider_with_fallback(self) -> MapMaskProvider:
        try:
            if self.provider.name == self.official_provider.name and not self.official_provider.enabled:
                raise RuntimeError("official provider disabled")
            return self.provider
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"map mask provider unavailable, fallback to local: {exc}")
            return self.fallback_provider


map_mask_service = MapMaskService()
