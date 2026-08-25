from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.map.mask.auto_viewport_provider import (
    HybridAutoCenterViewportProvider,
    _ZoomDetection,
    _zoom_scale_for_level,
)
from whimbox.map.mask.bigmap_match_diagnostics import BigMapMatchAnalysis
from whimbox.map.mask.bigmap_state_provider import (
    BigMapDetectionState,
    BigMapStateProvider,
)
from whimbox.map.mask.coordinate import point_to_visible
from whimbox.map.mask.local_provider import LocalJsonProvider
from whimbox.map.mask.models import MapMaskPoint, MapMaskViewport
from whimbox.map.mask.pearpal_provider import OfficialPearPalProvider
from whimbox.map.mask.pearpal_auth import (
    PearPalAwardedState,
    PearPalCredentials,
    PearPalUserClient,
    decode_user_info,
    parse_login_storage,
)
from whimbox.map.mask.resource_paths import package_map_mask_dir
from whimbox.map.mask.service import MapMaskService
from whimbox.map.mask.viewport_provider import (
    MapMaskViewportProvider,
    ViewportResult,
    _resolve_viewport_mode,
)
from whimbox.rpc_method_groups import handle_map_mask_method


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


class FakePearPalClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def fetch_catalog(self, world_id: str):
        if self.fail:
            raise RuntimeError("public API unavailable")
        return {
            "data": {
                "list": [
                    {
                        "id": 2,
                        "name": "收集物",
                        "catalogs": [
                            {"id": 11, "name": "奇想星", "icon": "star.png"},
                            {"id": 12, "name": "\u7075\u611f\u9732\u73e0", "icon": "dewdrop.png"},
                            {"id": 999, "name": "阶段入口"},
                        ],
                    },
                    {
                        "id": 14,
                        "name": "宝箱",
                        "catalogs": [
                            {"id": 13, "name": "普通宝箱", "icon": "box.png"},
                        ],
                    },
                    {
                        "id": 15,
                        "name": "任务活动",
                        "catalogs": [
                            {"id": 20, "name": "阅读物", "icon": "read.png"},
                        ],
                    },
                ]
            }
        }, None

    def fetch_spawners(self, world_id: str):
        return [
            {"id": 100, "world_id": 1, "catalog": 11, "x": 100, "y": 200},
            {"id": 101, "world_id": 1, "catalog": 12, "x": 150, "y": 250},
            {"id": 102, "world_id": 1, "catalog": 20, "x": 200, "y": 300},
            {
                "id": 200,
                "world_id": 1,
                "catalog": 999,
                "x": 300,
                "y": 400,
                "stage_id": "stage-1",
            },
            {"id": 300, "world_id": 1, "catalog": 999, "x": 500, "y": 600},
        ], None

    def fetch_stage_spawners(self):
        return {
            "stage-1": [
                {"id": 201, "catalog": 13, "description": "阶段宝箱"},
            ]
        }, None


class FakePearPalUserClient:
    def fetch_awarded_state(self, credentials: PearPalCredentials):
        if credentials.openid != "12405094":
            raise RuntimeError("unexpected user")
        return PearPalAwardedState(
            star_ids=frozenset({"100"}),
            box_ids=frozenset(),
            dewdrop_ids=frozenset({"101"}),
            read_ids=frozenset({"102"}),
        )


class MutablePearPalUserClient:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None
        self.awarded_state = PearPalAwardedState(
            star_ids=frozenset({"100"}),
            box_ids=frozenset(),
            dewdrop_ids=frozenset({"101"}),
        )

    def fetch_awarded_state(self, credentials: PearPalCredentials):
        if credentials.openid != "12405094":
            raise RuntimeError("unexpected user")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.awarded_state


class OfficialPearPalProviderTests(unittest.TestCase):
    def test_listing_labels_does_not_start_point_loading(self) -> None:
        client = FakePearPalClient()
        client.fetch_catalog = Mock(wraps=client.fetch_catalog)
        provider = OfficialPearPalProvider(
            enabled=True,
            client=client,
            background=False,
        )

        labels = provider.list_labels()

        self.assertEqual(len(labels), 4)
        self.assertEqual(
            provider.get_data_status()["points_source"],
            "pearpal-public-idle",
        )
        client.fetch_catalog.assert_not_called()

        provider.list_points(label_ids=[])

        client.fetch_catalog.assert_called_once_with("1")
        self.assertEqual(
            provider.get_data_status()["points_source"],
            "pearpal-public-ready",
        )

    def test_loads_supported_collectibles_and_expands_stage_child(self) -> None:
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
        )

        labels = provider.list_labels()
        points = provider.list_points()
        point_by_id = {point.id: point for point in points}

        self.assertEqual(
            [label.id for label in labels],
            [
                "pearpal_star",
                "pearpal_dewdrop",
                "pearpal_box",
                "pearpal_read",
            ],
        )
        self.assertEqual(
            set(point_by_id),
            {
                "pearpal:100",
                "pearpal:101",
                "pearpal:102",
                "pearpal:201",
            },
        )
        self.assertEqual(point_by_id["pearpal:100"].label_id, "pearpal_star")
        self.assertAlmostEqual(
            point_by_id["pearpal:100"].image_x,
            2.2222222222222223,
        )
        self.assertAlmostEqual(
            point_by_id["pearpal:100"].image_y,
            4.444444444444445,
        )
        dewdrop = point_by_id["pearpal:101"]
        self.assertEqual(dewdrop.label_id, "pearpal_dewdrop")
        self.assertAlmostEqual(dewdrop.image_x, 3.3333333333333335)
        self.assertAlmostEqual(dewdrop.image_y, 5.555555555555555)
        self.assertEqual(point_by_id["pearpal:102"].label_id, "pearpal_read")
        stage_box = point_by_id["pearpal:201"]
        self.assertEqual(stage_box.label_id, "pearpal_box")
        self.assertAlmostEqual(stage_box.image_x, 6.666666666666667)
        self.assertAlmostEqual(stage_box.image_y, 8.88888888888889)
        self.assertEqual(stage_box.detail["parent_stage_id"], "stage-1")
        self.assertTrue(stage_box.detail["is_stage_expanded"])
        self.assertEqual(provider.get_data_status()["points_source"], "pearpal-public-ready")

    def test_current_api_anchor_maps_near_checkpoint_png_position(self) -> None:
        client = FakePearPalClient()
        client.fetch_spawners = Mock(
            return_value=(
                [
                    {
                        "id": 1399,
                        "world_id": 1,
                        "catalog": 11,
                        "x": 923326.871094,
                        "y": 895070.148438,
                    }
                ],
                None,
            )
        )
        client.fetch_stage_spawners = Mock(return_value=({}, None))
        provider = OfficialPearPalProvider(
            enabled=True,
            client=client,
            background=False,
        )

        point = provider.list_points()[0]

        self.assertEqual(point.id, "pearpal:1399")
        self.assertAlmostEqual(point.image_x, 20526.281163, delta=15.0)
        self.assertAlmostEqual(point.image_y, 19892.919618, delta=15.0)

    def test_filters_by_label_and_map(self) -> None:
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
        )

        stars = provider.list_points(label_ids=["pearpal_star"], map_name="miraland")

        self.assertEqual([point.id for point in stars], ["pearpal:100"])
        self.assertEqual(provider.list_points(map_name="unsupported"), [])
        self.assertEqual(provider.list_points(label_ids=[]), [])

    def test_public_api_error_is_reported_without_sample_fallback(self) -> None:
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(fail=True),
            background=False,
        )

        self.assertEqual(provider.list_points(), [])
        status = provider.get_data_status()
        self.assertEqual(status["points_source"], "pearpal-public-error")
        self.assertIn("public API unavailable", status["points_error"])


class PearPalUserStateTests(unittest.TestCase):
    def test_user_client_uses_region_specific_api_and_client_id(self) -> None:
        cn_client = PearPalUserClient(region="cn")
        oversea_client = PearPalUserClient(region="oversea")

        self.assertEqual(cn_client.client_id, 1106)
        self.assertEqual(
            cn_client.user_info_url,
            "https://myl-api.nuanpaper.com/v1/strategy/map/user/info",
        )
        self.assertEqual(oversea_client.client_id, 1116)
        self.assertEqual(
            oversea_client.user_info_url,
            "https://pearpal-api.infoldgames.com/v1/strategy/map/user/info",
        )

    def test_parses_login_storage_and_user_info_ids(self) -> None:
        credentials = parse_login_storage(
            '{"token":"abcDEF0123456789","time":1786062221854}',
            '"12405094"',
        )
        awarded = decode_user_info(
            {
                "code": 0,
                "data": {
                    "star": [100, "101", None],
                    "box": [201, 202],
                    "dewdrop": [301, 302],
                    "read": [401, 402],
                },
            }
        )

        self.assertEqual(credentials.openid, "12405094")
        self.assertEqual(credentials.masked_openid, "12****94")
        self.assertEqual(awarded.star_ids, frozenset({"100", "101"}))
        self.assertEqual(awarded.box_ids, frozenset({"201", "202"}))
        self.assertEqual(awarded.dewdrop_ids, frozenset({"301", "302"}))
        self.assertEqual(awarded.read_ids, frozenset({"401", "402"}))

    def test_login_filters_awarded_points_and_can_show_them(self) -> None:
        credentials = PearPalCredentials(
            token="abcDEF0123456789",
            openid="12405094",
        )
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
            user_client=FakePearPalUserClient(),
            auth_background=False,
        )
        self.assertEqual(
            {point.id for point in provider.list_points()},
            {
                "pearpal:100",
                "pearpal:101",
                "pearpal:102",
                "pearpal:201",
            },
        )

        status = provider.authenticate(credentials)

        self.assertTrue(status["authenticated"])
        self.assertEqual(status["matched_awarded_star_count"], 1)
        self.assertEqual(status["matched_awarded_dewdrop_count"], 1)
        self.assertEqual(status["matched_awarded_read_count"], 1)
        self.assertEqual(
            [point.id for point in provider.list_points()],
            ["pearpal:201"],
        )
        provider.set_hide_awarded(False)
        star = provider.get_point_detail("pearpal:100")
        self.assertTrue(star["detail"]["awarded"])
        self.assertFalse(star["detail"]["anonymous"])
        provider.disconnect_user()
        self.assertEqual(len(provider.list_points()), 4)

    def test_switching_region_resets_login_and_reloads_public_points(self) -> None:
        credentials = PearPalCredentials(
            token="abcDEF0123456789",
            openid="12405094",
        )
        client = FakePearPalClient()
        client.fetch_catalog = Mock(wraps=client.fetch_catalog)
        provider = OfficialPearPalProvider(
            enabled=True,
            client=client,
            background=False,
            user_client=FakePearPalUserClient(),
            auth_background=False,
        )
        provider.list_points()
        provider.authenticate(credentials)

        status = provider.set_region("oversea")

        self.assertEqual(status["region"], "oversea")
        self.assertFalse(status["authenticated"])
        self.assertEqual(
            provider.get_data_status()["points_source"],
            "pearpal-public-idle",
        )
        self.assertEqual(len(provider.list_points()), 4)
        self.assertEqual(client.fetch_catalog.call_count, 2)

    def test_clear_login_information_removes_backend_session(self) -> None:
        credentials = PearPalCredentials(
            token="abcDEF0123456789",
            openid="12405094",
        )
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
            user_client=FakePearPalUserClient(),
            auth_background=False,
        )
        provider.list_points()
        self.assertTrue(provider.authenticate(credentials)["authenticated"])

        status = provider.clear_login_information()
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["auth_state"], "anonymous")
        self.assertEqual(len(provider.list_points()), 4)

    def test_clear_login_information_invalidates_in_flight_login(self) -> None:
        credentials = PearPalCredentials(
            token="abcDEF0123456789",
            openid="12405094",
        )
        auth_started = threading.Event()
        release_auth = threading.Event()

        class DelayedPearPalUserClient:
            def fetch_awarded_state(self, received: PearPalCredentials):
                auth_started.set()
                release_auth.wait(timeout=2.0)
                return FakePearPalUserClient().fetch_awarded_state(received)

        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
            user_client=DelayedPearPalUserClient(),
            auth_background=True,
        )

        provider.authenticate(credentials)
        self.assertTrue(auth_started.wait(timeout=1.0))
        provider.clear_login_information()
        release_auth.set()
        auth_thread = provider._auth_thread
        if auth_thread is not None:
            auth_thread.join(timeout=2.0)

        status = provider.get_user_status()
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["auth_state"], "anonymous")

    def test_user_state_refresh_does_not_rebuild_all_points(self) -> None:
        credentials = PearPalCredentials(
            token="abcDEF0123456789",
            openid="12405094",
        )
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
            user_client=FakePearPalUserClient(),
            auth_background=False,
        )
        provider.list_points()
        original_points = provider._points
        original_point_by_id = provider._point_by_id

        provider.authenticate(credentials)
        provider.list_points()
        provider.get_user_status()
        self.assertIs(provider._points, original_points)
        self.assertIs(provider._point_by_id, original_point_by_id)
        self.assertFalse(
            hasattr(provider, "_decorated_points_cache")
        )

        provider.disconnect_user()
        self.assertIs(provider._points, original_points)
        self.assertIs(provider._point_by_id, original_point_by_id)

    def test_auto_refresh_manual_refresh_and_failure_backoff(self) -> None:
        credentials = PearPalCredentials(
            token="abcDEF0123456789",
            openid="12405094",
        )
        user_client = MutablePearPalUserClient()
        clock = [100.0]
        provider = OfficialPearPalProvider(
            enabled=True,
            client=FakePearPalClient(),
            background=False,
            user_client=user_client,
            auth_background=False,
            refresh_background=False,
        )

        with patch(
            "whimbox.map.mask.pearpal_provider.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            provider.list_points()
            login_status = provider.authenticate(credentials)
            self.assertEqual(user_client.calls, 1)
            self.assertEqual(login_status["last_refresh_reason"], "login")

            user_client.awarded_state = PearPalAwardedState(
                star_ids=frozenset(),
                box_ids=frozenset({"201"}),
                dewdrop_ids=frozenset(),
            )
            clock[0] = 106.0
            provider.note_overlay_activity(is_bigmap_open=False)
            provider.note_overlay_activity(is_bigmap_open=True)
            self.assertEqual(user_client.calls, 2)
            self.assertEqual(
                provider.get_user_status()["last_refresh_reason"],
                "map-open",
            )
            self.assertEqual(
                {point.id for point in provider.list_points()},
                {
                    "pearpal:100",
                    "pearpal:101",
                    "pearpal:102",
                },
            )

            clock[0] = 137.0
            provider.note_overlay_activity(is_bigmap_open=True)
            self.assertEqual(user_client.calls, 3)
            self.assertEqual(
                provider.get_user_status()["last_refresh_reason"],
                "periodic",
            )

            user_client.error = RuntimeError("temporary API error")
            failed_status = provider.refresh_user_state()
            self.assertEqual(user_client.calls, 4)
            self.assertEqual(failed_status["refresh_failure_count"], 1)
            self.assertIn("temporary API error", failed_status["refresh_error"])
            self.assertAlmostEqual(
                failed_status["next_refresh_in_seconds"],
                5.0,
            )
            self.assertTrue(
                provider.get_point_detail("pearpal:201")["detail"]["awarded"]
            )

            clock[0] = 138.0
            provider.note_overlay_activity(is_bigmap_open=True)
            self.assertEqual(user_client.calls, 4)

            user_client.error = None
            clock[0] = 142.0
            provider.note_overlay_activity(is_bigmap_open=True)
            retry_status = provider.get_user_status()
            self.assertEqual(user_client.calls, 5)
            self.assertEqual(retry_status["last_refresh_reason"], "retry")
            self.assertEqual(retry_status["refresh_error"], "")


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


class BigMapStateProviderTests(unittest.TestCase):
    def test_each_detection_uses_the_current_single_frame_result(self) -> None:
        provider = BigMapStateProvider()
        provider._detect_with_whimbox_page = Mock(side_effect=[True, False])

        opened = provider.detect()
        closed = provider.detect()

        self.assertTrue(opened.is_bigmap_open)
        self.assertFalse(closed.is_bigmap_open)
        self.assertEqual(provider._detect_with_whimbox_page.call_count, 2)


class GameWindowStateRpcTests(unittest.TestCase):
    def test_returns_physical_client_bounds_for_electron_dip_conversion(self) -> None:
        with (
            patch.object(HANDLE_OBJ, "is_alive", return_value=True),
            patch.object(
                HANDLE_OBJ,
                "get_window_rect",
                return_value=(2400, 180, 1920, 1080),
            ),
            patch.object(HANDLE_OBJ, "get_window_scale_factor", return_value=1.5),
            patch.object(HANDLE_OBJ, "is_foreground", return_value=True),
            patch.object(HANDLE_OBJ, "is_minimized", return_value=False),
        ):
            result = handle_map_mask_method("map_mask.get_game_window_state", {})

        self.assertEqual(result["coordinateSpace"], "physical")
        self.assertEqual(
            (result["x"], result["y"], result["width"], result["height"]),
            (2400, 180, 1920, 1080),
        )
        self.assertEqual(result["dpi"], 144)
        self.assertEqual(result["dpiScale"], 1.5)


class AutomaticViewportTrackingTests(unittest.TestCase):
    def test_low_confidence_log_is_emitted_once_until_recovery(self) -> None:
        provider = HybridAutoCenterViewportProvider(Mock())
        with patch(
            "whimbox.map.mask.auto_viewport_provider.logger.warning"
        ) as warning:
            provider._log_low_confidence_if_needed(
                0.2,
                selected_match_source="global-top1",
                local_confidence=None,
                global_confidence=0.2,
            )
            provider._log_low_confidence_if_needed(
                0.1,
                selected_match_source="global-top1",
                local_confidence=None,
                global_confidence=0.1,
            )
            provider._log_low_confidence_if_needed(
                0.5,
                selected_match_source="local",
                local_confidence=0.5,
                global_confidence=None,
            )
            provider._log_low_confidence_if_needed(
                0.29,
                selected_match_source="local",
                local_confidence=0.29,
                global_confidence=None,
            )

        self.assertEqual(warning.call_count, 2)
        self.assertIn("confidence=0.200", warning.call_args_list[0].args[0])
        self.assertIn("threshold=0.300", warning.call_args_list[0].args[0])

    def test_unsupported_zoom_is_not_replaced_by_manual_fallback(self) -> None:
        provider = MapMaskViewportProvider()
        unsupported = ViewportResult(
            viewport=None,
            mode="hybrid-auto-center",
            source="unsupported-bigmap-zoom",
            zoom_status="unsupported",
            overlay_hint="请使用左下角缩放按钮",
        )
        provider.hybrid_provider = Mock()
        provider.hybrid_provider.get_viewport.return_value = unsupported

        result = provider.get_viewport(mode="hybrid-auto-center")

        self.assertIs(result, unsupported)
        self.assertIsNone(result.viewport)
        self.assertEqual(result.zoom_status, "unsupported")
        self.assertEqual(result.overlay_hint, "请使用左下角缩放按钮")

    def test_miraland_zoom_profiles_use_measured_anchor_scales(self) -> None:
        self.assertAlmostEqual(
            _zoom_scale_for_level("miraland", "second"),
            2.784,
        )
        self.assertAlmostEqual(
            _zoom_scale_for_level("miraland", "third"),
            1.162,
        )
        self.assertAlmostEqual(_zoom_scale_for_level("miraland", "max"), 0.637)

    def test_hybrid_auto_center_is_the_default_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"WHIMBOX_MAP_MASK_VIEWPORT_MODE": ""},
            clear=False,
        ):
            self.assertEqual(_resolve_viewport_mode(), "hybrid-auto-center")

    def test_motion_detection_only_reports_current_frame_change(self) -> None:
        manual_provider = Mock()
        provider = HybridAutoCenterViewportProvider(manual_provider)
        still = np.zeros((180, 320), dtype=np.uint8)
        moved = np.full((180, 320), 255, dtype=np.uint8)

        initial = provider._detect_motion(still)
        moving = provider._detect_motion(moved)
        stable = provider._detect_motion(moved)

        self.assertEqual(initial, (None, False))
        self.assertTrue(moving[1])
        self.assertFalse(stable[1])

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
        provider._detect_zoom_level = Mock(
            return_value=_ZoomDetection(
                status="supported",
                level="max",
                reference_scale=0.637,
                confidence=1.0,
            )
        )
        provider._detect_motion = Mock(
            side_effect=[
                (0.0, False),
                (0.0, False),
                (20.0, True),
                (0.0, False),
            ]
        )
        provider._detect_tracking_first = Mock(
            side_effect=[
                {
                    "center_x": 16000.0,
                    "center_y": 14000.0,
                    "confidence": 0.4,
                    "local_confidence": None,
                    "global_confidence": 0.4,
                    "source": "global-top1",
                    "matching_status": "matching_provisional",
                    "matching_rejection_reason": "weak global match",
                },
                {
                    "center_x": 16000.0,
                    "center_y": 14000.0,
                    "confidence": 0.4,
                    "local_confidence": None,
                    "global_confidence": 0.4,
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

        pending = provider.get_viewport()
        first = provider.get_viewport()
        during_drag = provider.get_viewport()
        second = provider.get_viewport()
        self.assertEqual(provider._detect_tracking_first.call_count, 4)
        self.assertIsNone(pending.viewport)
        self.assertIsNotNone(first.viewport)
        self.assertIsNotNone(during_drag.viewport)
        self.assertIsNotNone(second.viewport)
        assert first.viewport is not None
        assert during_drag.viewport is not None
        assert second.viewport is not None
        self.assertNotEqual(during_drag.viewport, first.viewport)
        self.assertEqual(during_drag.center_x, 16100.0)
        self.assertEqual(during_drag.center_y, 14000.0)
        self.assertTrue(during_drag.motion_unstable)
        self.assertEqual(during_drag.center_accept_reason, "tracking-motion-active")
        self.assertFalse(during_drag.smoothing_applied)
        self.assertEqual(second.center_x, 16100.0)
        self.assertEqual(second.center_y, 14000.0)
        self.assertEqual(second.viewport, during_drag.viewport)
        self.assertEqual(second.center_accept_reason, "tracking-local-match")

        point = MapMaskPoint.from_dict(
            {
                **POINT,
                "image_x": 16100.0,
                "image_y": 14000.0,
            }
        )
        first_visible = point_to_visible(point, first.viewport)
        during_drag_visible = point_to_visible(point, during_drag.viewport)
        self.assertIsNotNone(first_visible)
        self.assertIsNotNone(during_drag_visible)
        assert first_visible is not None
        assert during_drag_visible is not None
        self.assertLess(during_drag_visible.screen_x, first_visible.screen_x)
        self.assertAlmostEqual(during_drag_visible.screen_y, first_visible.screen_y)


class DetectionWorkerLifecycleTests(unittest.TestCase):
    def test_wheel_blocking_requires_fresh_bigmap_and_game_foreground(self) -> None:
        service = MapMaskService()
        service.enabled = True
        service._wheel_bigmap_open = True
        service._wheel_bigmap_detection_monotonic = time.monotonic()

        with patch.object(HANDLE_OBJ, "is_foreground", return_value=True):
            self.assertTrue(service._should_block_mouse_wheel())
        with patch.object(HANDLE_OBJ, "is_foreground", return_value=False):
            self.assertFalse(service._should_block_mouse_wheel())

        service._wheel_bigmap_detection_monotonic = time.monotonic() - 1.0
        with patch.object(HANDLE_OBJ, "is_foreground", return_value=True):
            self.assertFalse(service._should_block_mouse_wheel())

    def test_blocked_wheel_hint_expires(self) -> None:
        service = MapMaskService()
        service._note_mouse_wheel_blocked()
        self.assertIn("不支持滚轮缩放", service._wheel_overlay_hint())

        service._last_blocked_wheel_monotonic = time.monotonic() - 3.0
        self.assertEqual(service._wheel_overlay_hint(), "")

    def test_visible_points_request_starts_worker_and_disable_stops_it(self) -> None:
        service = MapMaskService()
        service.provider = service.local_provider
        service.fallback_provider = service.local_provider
        service.enabled = True
        service.bigmap_state_provider.detect = Mock(
            return_value=BigMapDetectionState(
                is_bigmap_open=True,
                raw_is_bigmap_open=True,
                detection_mode="auto",
                detection_source="test",
                detection_confidence=1.0,
                detection_error="",
                last_detection_time="",
                last_successful_detection_time="",
                detection_duration_ms=0.0,
            )
        )
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
        service.provider = service.local_provider
        service.fallback_provider = service.local_provider
        service.enabled = True
        service.bigmap_state_provider.detect = Mock(
            return_value=BigMapDetectionState(
                is_bigmap_open=False,
                raw_is_bigmap_open=False,
                detection_mode="auto",
                detection_source="test",
                detection_confidence=1.0,
                detection_error="",
                last_detection_time="",
                last_successful_detection_time="",
                detection_duration_ms=0.0,
            )
        )

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
                {"WHIMBOX_MAP_MASK_LOCAL_POINTS": str(points_path)},
                clear=False,
            ):
                provider = LocalJsonProvider()
                service = MapMaskService()
                service.provider = provider
                service.fallback_provider = provider
                service.bigmap_state_provider.detect = Mock(
                    return_value=BigMapDetectionState(
                        is_bigmap_open=True,
                        raw_is_bigmap_open=True,
                        detection_mode="auto",
                        detection_source="test",
                        detection_confidence=1.0,
                        detection_error="",
                        last_detection_time="",
                        last_successful_detection_time="",
                        detection_duration_ms=0.0,
                    )
                )
                with patch.object(
                    provider,
                    "list_points",
                    wraps=provider.list_points,
                ) as list_points:
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
        self.assertEqual(list_points.call_count, 2)


if __name__ == "__main__":
    unittest.main()
