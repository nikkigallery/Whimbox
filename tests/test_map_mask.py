from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from whimbox.map.mask.auto_viewport_provider import (
    HybridAutoCenterViewportProvider,
)
from whimbox.map.mask.bigmap_match_diagnostics import BigMapMatchAnalysis
from whimbox.map.mask.coordinate import point_to_visible
from whimbox.map.mask.local_provider import LocalJsonProvider
from whimbox.map.mask.models import MapMaskPoint, MapMaskViewport
from whimbox.map.mask.resource_paths import package_map_mask_dir
from whimbox.map.mask.service import MapMaskService
from whimbox.map.mask.viewport_provider import ViewportResult, _resolve_viewport_mode


POINT = {
    "id": "pearpal_test",
    "label_id": "pearpal_10",
    "name": "Test warp spire",
    "map_name": "miraland",
    "image_x": 16497.5,
    "image_y": 14517.4,
    "icon": "marker.svg",
    "provider": "pearpal-debug",
    "detail": {},
}


def viewport() -> MapMaskViewport:
    image_width = 1920 * 0.637
    image_height = 1080 * 0.637
    return MapMaskViewport(
        map_name="miraland",
        image_left=16470.7 - image_width / 2,
        image_top=14495.0 - image_height / 2,
        image_width=image_width,
        image_height=image_height,
        screen_left=0,
        screen_top=0,
        screen_width=1920,
        screen_height=1080,
    )


class LocalJsonProviderTests(unittest.TestCase):
    def test_unknown_point_label_is_registered_and_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            points_path = Path(directory) / "points.local.json"
            points_path.write_text(
                json.dumps([POINT], ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"WHIMBOX_MAP_MASK_LOCAL_POINTS": str(points_path)},
                clear=False,
            ):
                provider = LocalJsonProvider()
                labels = {label.id: label for label in provider.list_labels()}
                points = provider.list_points(label_ids=["pearpal_10"])

        self.assertIn("pearpal_10", labels)
        self.assertTrue(labels["pearpal_10"].default_enabled)
        self.assertEqual([point.id for point in points], ["pearpal_test"])

    def test_packaged_sample_resources_exist(self) -> None:
        resource_dir = package_map_mask_dir()
        self.assertTrue((resource_dir / "labels.sample.json").is_file())
        self.assertTrue((resource_dir / "points.sample.json").is_file())
        self.assertTrue((resource_dir / "viewport_samples.sample.json").is_file())


class CoordinateProjectionTests(unittest.TestCase):
    def test_png_point_projects_to_expected_screen_coordinate(self) -> None:
        point = MapMaskPoint.from_dict(POINT)
        visible = point_to_visible(point, viewport())
        self.assertIsNotNone(visible)
        assert visible is not None
        self.assertAlmostEqual(visible.screen_x, 1002.0, delta=0.2)
        self.assertAlmostEqual(visible.screen_y, 575.1, delta=0.2)


class BigMapMatchGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        provider = HybridAutoCenterViewportProvider.__new__(
            HybridAutoCenterViewportProvider
        )
        provider._confidence_threshold = 0.35
        provider._global_match_min_margin = 0.02
        provider._global_selected_top1_max_distance = 800.0
        provider._expected_center = None
        provider._expected_center_max_distance = 3000.0
        provider._reject_far_expected_center = False
        self.provider = provider

    def analysis(
        self,
        *,
        selected_confidence: float = 0.6,
        margin: float = 0.1,
        selected_to_top1_distance: float = 0.0,
    ) -> BigMapMatchAnalysis:
        empty = np.zeros((2, 2), dtype=np.float32)
        return BigMapMatchAnalysis(
            map_name="miraland",
            asset_name="test",
            asset_path="",
            input_shape=(1080, 1920, 4),
            preprocessed_shape=(86, 153),
            asset_shape=(2048, 2048),
            result_shape=(1963, 1896),
            resize_scale=0.079625,
            input_mean=100.0,
            input_std=20.0,
            input_min=0.0,
            input_max=255.0,
            selected_center=(1000.0, 1000.0),
            selected_confidence=selected_confidence,
            selected_local_score=0.05,
            raw_top1_confidence=0.6,
            raw_top2_confidence=0.6 - margin,
            raw_top1_top2_margin=margin,
            selected_to_raw_top1_distance=selected_to_top1_distance,
            raw_candidates=[],
            local_candidates=[],
            preprocessed=empty,
            result=empty,
            local_maximum=empty,
            asset=empty,
        )

    def test_marks_low_selected_confidence_provisional(self) -> None:
        status, _ = self.provider._classify_global_match(
            self.analysis(selected_confidence=0.2)
        )
        self.assertEqual(status, "matching_provisional")

    def test_marks_small_top1_top2_margin_provisional(self) -> None:
        status, _ = self.provider._classify_global_match(
            self.analysis(margin=0.01)
        )
        self.assertEqual(status, "matching_provisional")

    def test_marks_selected_center_far_from_raw_top1_provisional(self) -> None:
        status, _ = self.provider._classify_global_match(
            self.analysis(selected_to_top1_distance=1000.0)
        )
        self.assertEqual(status, "matching_provisional")


class AutomaticViewportTrackingTests(unittest.TestCase):
    def test_hybrid_auto_center_is_the_default_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"WHIMBOX_MAP_MASK_VIEWPORT_MODE": ""},
            clear=False,
        ):
            self.assertEqual(_resolve_viewport_mode(), "hybrid-auto-center")

    def test_motion_state_reports_single_settled_transition(self) -> None:
        manual_provider = Mock()
        provider = HybridAutoCenterViewportProvider(manual_provider)
        provider._motion_stable_frames = 2
        still = np.zeros((180, 320), dtype=np.uint8)
        moved = np.full((180, 320), 255, dtype=np.uint8)

        initial = provider._update_motion_state(still)
        moving = provider._update_motion_state(moved)
        settling = provider._update_motion_state(moved)
        settled = provider._update_motion_state(moved)
        stable = provider._update_motion_state(moved)

        self.assertEqual(initial, (None, False, False))
        self.assertTrue(moving[1])
        self.assertFalse(moving[2])
        self.assertTrue(settling[1])
        self.assertFalse(settling[2])
        self.assertFalse(settled[1])
        self.assertTrue(settled[2])
        self.assertFalse(stable[1])
        self.assertFalse(stable[2])

    def test_dragged_map_center_moves_projected_point(self) -> None:
        manual_provider = Mock()
        manual_provider.get_viewport.return_value = ViewportResult(
            viewport=None,
            mode="manual-calibration",
            source="manual-calibration",
            calibration_error="calibration file not found",
        )
        provider = HybridAutoCenterViewportProvider(manual_provider)
        provider._smoothing_mode = "jitter-only"
        provider._capture_game = Mock(
            return_value=np.zeros((1080, 1920, 4), dtype=np.uint8)
        )
        provider._update_motion_state = Mock(
            side_effect=[
                (0.0, False, False),
                (0.0, False, False),
                (20.0, True, False),
                (0.0, False, True),
            ]
        )
        provider._detect_tracking_first = Mock(
            side_effect=[
                {
                    "center_x": 16000.0,
                    "center_y": 14000.0,
                    "confidence": 0.32,
                    "local_confidence": None,
                    "global_confidence": 0.32,
                    "source": "global-top1",
                    "matching_status": "matching_provisional",
                    "matching_rejection_reason": "weak global match",
                },
                {
                    "center_x": 16000.0,
                    "center_y": 14000.0,
                    "confidence": 0.32,
                    "local_confidence": None,
                    "global_confidence": 0.32,
                    "source": "global-top1",
                    "matching_status": "matching_provisional",
                    "matching_rejection_reason": "weak global match",
                },
                {
                    "center_x": 16100.0,
                    "center_y": 14000.0,
                    "confidence": 0.8,
                    "local_confidence": 0.8,
                    "global_confidence": None,
                    "source": "local",
                    "matching_status": "matching_accepted",
                    "matching_rejection_reason": "",
                },
                {
                    "center_x": 16100.0,
                    "center_y": 14000.0,
                    "confidence": 0.8,
                    "local_confidence": 0.8,
                    "global_confidence": None,
                    "source": "local",
                    "matching_status": "matching_accepted",
                    "matching_rejection_reason": "",
                },
            ]
        )
        provider._cross_check_tracking = Mock(
            side_effect=lambda _image, _map_name, match, **_kwargs: match
        )

        pending = provider.get_viewport(force_refresh=True)
        first = provider.get_viewport(force_refresh=True)
        during_drag = provider.get_viewport(force_refresh=True)
        second = provider.get_viewport(force_refresh=True)
        self.assertIsNone(pending.viewport)
        self.assertIsNotNone(first.viewport)
        self.assertIsNotNone(during_drag.viewport)
        self.assertIsNotNone(second.viewport)
        assert first.viewport is not None
        assert during_drag.viewport is not None
        assert second.viewport is not None
        self.assertEqual(during_drag.viewport, first.viewport)
        self.assertEqual(second.center_x, 16100.0)
        self.assertEqual(second.center_y, 14000.0)
        self.assertFalse(second.smoothing_applied)

        point = MapMaskPoint.from_dict(
            {
                **POINT,
                "image_x": 16100.0,
                "image_y": 14000.0,
            }
        )
        first_visible = point_to_visible(point, first.viewport)
        second_visible = point_to_visible(point, second.viewport)
        self.assertIsNotNone(first_visible)
        self.assertIsNotNone(second_visible)
        assert first_visible is not None
        assert second_visible is not None
        self.assertLess(second_visible.screen_x, first_visible.screen_x)
        self.assertAlmostEqual(second_visible.screen_y, first_visible.screen_y)


class DetectionWorkerLifecycleTests(unittest.TestCase):
    def test_visible_points_request_starts_worker_and_disable_stops_it(self) -> None:
        service = MapMaskService()
        service.enabled = True
        service.bigmap_state_provider.set_mode("force-open")
        service.viewport_provider.get_mode = Mock(return_value="hybrid-auto-center")
        service.viewport_provider.get_viewport = Mock(
            return_value=ViewportResult(
                viewport=viewport(),
                mode="hybrid-auto-center",
                source="test-worker",
                center_x=1500.0,
                center_y=2500.0,
            )
        )

        self.assertIsNone(service._detection_thread)
        self.assertIsNone(service._get_detection_snapshot())

        service.get_visible_points()
        deadline = time.monotonic() + 1.0
        while service._get_detection_snapshot() is None and time.monotonic() < deadline:
            time.sleep(0.01)

        snapshot = service._get_detection_snapshot()
        self.assertIsNotNone(snapshot)
        worker = service._detection_thread
        self.assertIsNotNone(worker)
        assert worker is not None
        self.assertTrue(worker.is_alive())

        service.set_enabled(False)
        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(service._get_detection_snapshot())

    def test_worker_exits_after_request_timeout_and_restarts_on_next_request(self) -> None:
        service = MapMaskService()
        service.enabled = True
        service.bigmap_state_provider.set_mode("force-closed")

        with patch(
            "whimbox.map.mask.service._DETECTION_WORKER_IDLE_SECONDS",
            0.05,
        ):
            service.get_visible_points()
            worker = service._detection_thread
            self.assertIsNotNone(worker)
            assert worker is not None
            worker.join(timeout=1.0)
            self.assertFalse(worker.is_alive())
            self.assertIsNone(service._detection_thread)
            self.assertIsNone(service._get_detection_snapshot())

            service.get_visible_points()
            restarted_worker = service._detection_thread
            self.assertIsNotNone(restarted_worker)
            assert restarted_worker is not None
            self.assertIsNot(restarted_worker, worker)
            self.assertTrue(restarted_worker.is_alive())

            service.set_enabled(False)
            restarted_worker.join(timeout=1.0)
            self.assertFalse(restarted_worker.is_alive())


class VisiblePointsTests(unittest.TestCase):
    def test_enabled_label_is_visible_and_disabled_label_is_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            points_path = Path(directory) / "points.local.json"
            points_path.write_text(
                json.dumps([POINT], ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "WHIMBOX_MAP_MASK_LOCAL_POINTS": str(points_path),
                    "WHIMBOX_MAP_MASK_FORCE_BIGMAP_OPEN": "1",
                },
                clear=False,
            ):
                provider = LocalJsonProvider()
                service = MapMaskService()
                service.provider = provider
                service.fallback_provider = provider
                enabled = service.get_visible_points(
                    viewport=viewport(),
                    label_ids=["pearpal_10"],
                )
                disabled = service.get_visible_points(
                    viewport=viewport(),
                    label_ids=[],
                )

        self.assertEqual(
            [point["id"] for point in enabled["points"]],
            ["pearpal_test"],
        )
        self.assertEqual(disabled["points"], [])


if __name__ == "__main__":
    unittest.main()
