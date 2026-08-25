from __future__ import annotations

import threading
import time
from typing import Any

from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.common.logger import logger
from whimbox.config.config import global_config

from .bigmap_state_provider import BigMapDetectionState, BigMapStateProvider
from .coordinate import point_to_visible
from .local_provider import LocalJsonProvider
from .models import MapMaskLabel, MapMaskState, MapMaskViewport
from .mouse_wheel_guard import MouseWheelGuard
from .pearpal_auth import parse_login_storage
from .pearpal_provider import OfficialPearPalProvider
from .provider import MapMaskProvider
from .viewport_provider import MapMaskViewportProvider, ViewportResult


_DETECTION_WORKER_DELAY_SECONDS = 0.02
_DETECTION_WORKER_IDLE_SECONDS = 2.0
_WHEEL_BIGMAP_STATE_MAX_AGE_SECONDS = 0.5
_WHEEL_HINT_SECONDS = 2.0
_WHEEL_HINT = "地图遮罩暂不支持滚轮缩放，请使用左下角缩放按钮"


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
        self._wheel_bigmap_open = False
        self._wheel_bigmap_detection_monotonic = 0.0
        self._last_blocked_wheel_monotonic = 0.0
        self._mouse_wheel_guard = MouseWheelGuard(
            should_block=self._should_block_mouse_wheel,
            on_blocked=self._note_mouse_wheel_blocked,
        )

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
        self._mouse_wheel_guard.start()
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

                try:
                    with self._detection_provider_lock:
                        from whimbox.interaction.interaction_core import itt

                        captured_image = itt.capture()
                        bigmap_state = self.bigmap_state_provider.detect(
                            captured_image=captured_image,
                        )
                        self._wheel_bigmap_open = bool(bigmap_state.is_bigmap_open)
                        self._wheel_bigmap_detection_monotonic = time.monotonic()
                        viewport_result = self._detect_viewport_result(
                            map_name=map_name,
                            is_bigmap_open=bigmap_state.is_bigmap_open,
                            captured_image=captured_image,
                        )
                    self.official_provider.note_overlay_activity(
                        is_bigmap_open=bigmap_state.is_bigmap_open,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._wheel_bigmap_open = False
                    logger.exception(f"[map-mask-worker] detection cycle failed: {exc}")
                else:
                    with self._detection_lock:
                        if self.enabled and self._detection_thread is current_thread:
                            self._detection_snapshot = (bigmap_state, viewport_result)

                self._detection_wake.wait(_DETECTION_WORKER_DELAY_SECONDS)
                self._detection_wake.clear()
        finally:
            should_stop_wheel_guard = True
            with self._detection_lock:
                if self._detection_thread is current_thread:
                    self._detection_thread = None
                    self._detection_snapshot = None
                elif (
                    self.enabled
                    and self._detection_thread is not None
                    and self._detection_thread.is_alive()
                ):
                    should_stop_wheel_guard = False
            if should_stop_wheel_guard:
                self._wheel_bigmap_open = False
                self._wheel_bigmap_detection_monotonic = 0.0
                self._last_blocked_wheel_monotonic = 0.0
                self._mouse_wheel_guard.stop()
            self.official_provider.note_overlay_inactive()
            logger.info(f"[map-mask-worker] stopped reason={stop_reason}")

    def _should_block_mouse_wheel(self) -> bool:
        if not self.enabled or not self._wheel_bigmap_open:
            return False
        if (
            time.monotonic() - self._wheel_bigmap_detection_monotonic
            > _WHEEL_BIGMAP_STATE_MAX_AGE_SECONDS
        ):
            return False
        return HANDLE_OBJ.is_foreground()

    def _note_mouse_wheel_blocked(self) -> None:
        self._last_blocked_wheel_monotonic = time.monotonic()

    def _wheel_overlay_hint(self) -> str:
        if self._last_blocked_wheel_monotonic <= 0:
            return ""
        if (
            time.monotonic() - self._last_blocked_wheel_monotonic
            <= _WHEEL_HINT_SECONDS
        ):
            return _WHEEL_HINT
        return ""

    def _detect_viewport_result(
        self,
        *,
        map_name: str | None,
        is_bigmap_open: bool,
        captured_image: Any | None = None,
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
            captured_image=captured_image,
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
            detection_mode=mode,
            detection_source="worker.pending",
            detection_confidence=0.0,
            detection_error="",
            last_detection_time="",
            last_successful_detection_time="",
            detection_duration_ms=0.0,
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
            self._wheel_bigmap_open = False
            self._last_blocked_wheel_monotonic = 0.0
            with self._detection_lock:
                self._detection_snapshot = None
                self._detection_wake.set()
        return self.get_state()

    def get_labels(self) -> list[dict[str, Any]]:
        return [label.to_dict() for label in self._list_labels()]

    def prepare_points(self) -> dict[str, Any]:
        # An empty selection starts lazy provider loading without building a
        # response containing every point. Official data loads in its daemon
        # thread; local data loads synchronously only after explicit use.
        self._list_points(label_ids=[])
        return self._get_data_status()

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

    def get_user_status(self) -> dict[str, Any]:
        return self.official_provider.get_user_status()

    def submit_pearpal_login(
        self,
        momo_token: Any,
        momo_nid: Any,
    ) -> dict[str, Any]:
        credentials = parse_login_storage(momo_token, momo_nid)
        return self.official_provider.authenticate(credentials)

    def refresh_pearpal_user_state(self) -> dict[str, Any]:
        return self.official_provider.refresh_user_state()

    def disconnect_pearpal_user(self) -> dict[str, Any]:
        return self.official_provider.disconnect_user()

    def clear_pearpal_login_information(self) -> dict[str, Any]:
        return self.official_provider.clear_login_information()

    def set_hide_awarded(self, hide_awarded: bool) -> dict[str, Any]:
        return self.official_provider.set_hide_awarded(hide_awarded)


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
            zoom_status=viewport_result.zoom_status,
            zoom_level=viewport_result.zoom_level,
            zoom_confidence=viewport_result.zoom_confidence,
            overlay_hint=self._wheel_overlay_hint() or viewport_result.overlay_hint,
            detection_mode=bigmap_state.detection_mode,
            detection_source=bigmap_state.detection_source,
            detection_confidence=bigmap_state.detection_confidence,
            raw_is_bigmap_open=bigmap_state.raw_is_bigmap_open,
            detection_error=bigmap_state.detection_error,
            last_detection_time=bigmap_state.last_detection_time,
            last_successful_detection_time=bigmap_state.last_successful_detection_time,
            detection_duration_ms=bigmap_state.detection_duration_ms,
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
