from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_rejects_when_reported_confidence_does_not_belong_to_center(self) -> None:
        status, _ = self.provider._classify_global_match(
            self.analysis(selected_confidence=0.2)
        )
        self.assertEqual(status, "matching_ambiguous")

    def test_rejects_small_top1_top2_margin(self) -> None:
        status, _ = self.provider._classify_global_match(
            self.analysis(margin=0.01)
        )
        self.assertEqual(status, "matching_ambiguous")

    def test_rejects_selected_center_far_from_raw_top1(self) -> None:
        status, _ = self.provider._classify_global_match(
            self.analysis(selected_to_top1_distance=1000.0)
        )
        self.assertEqual(status, "matching_ambiguous")


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
