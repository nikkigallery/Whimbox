import threading
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import numpy as np

from test_map_mask import FakeMiniMapDetector, FakePearPalClient, MutablePearPalUserClient, viewport
from whimbox.map.mask.minimap_tracker import MiniMapPositionTracker
from whimbox.map.mask.models import MapMaskPoint
from whimbox.map.mask.pearpal_auth import PearPalAwardedState, PearPalCredentials
from whimbox.map.mask.pearpal_provider import OfficialPearPalProvider
from whimbox.map.mask.scene_guidance import nearest_scene_target
from whimbox.map.mask.service import MapMaskService


class NavigationTests(unittest.TestCase):
    def test_nearest_point_and_camera_turns(self):
        def point(id, x, y):
            return MapMaskPoint(id=id, name=id, label_id="star", map_name="miraland",
                                image_x=x, image_y=y)
        west, east = point("a", -1000, 0), point("b", 1000, 0)
        self.assertIsNone(nearest_scene_target((), 0, 0, 0))
        for camera, turn in [(0, -90), (90, -180), (180, 90), (270, 0)]:
            target = nearest_scene_target((west, east), 0, 0, camera)
            self.assertEqual((target["id"], target["turn_deg"], target["distance_m"]),
                             ("a", turn, 450))
        self.assertEqual(nearest_scene_target((west, east), 200, 0, 0)["id"], "b")
        for x, y, bearing in [(0, -30, 0), (30, 0, 90), (0, 30, 180), (-30, 0, 270), (30, -30, 45)]:
            target = nearest_scene_target((point("p", x, y),), 0, 0, None)
            self.assertEqual(target["bearing_deg"], bearing)
            self.assertIsNone(target["turn_deg"])

    def test_heading_uses_the_same_frame_and_is_dropped_when_unreliable(self):
        detector = FakeMiniMapDetector()
        detector.rotation_confidence = 0.8
        detector.update_rotation = Mock(return_value=-90.0)
        tracker = MiniMapPositionTracker(detector=detector)
        tracker.initialize((1000, 2000), "miraland")
        frame = np.zeros((200, 200), dtype=np.uint8)
        with patch("whimbox.map.mask.minimap_tracker.rgb2luma", side_effect=lambda im: im):
            first = tracker.update(frame, is_main_world_open=True, track_heading=True)
            self.assertEqual(first.camera_bearing, 90)
            detector.update_rotation.assert_called_once_with(frame, update_position=False)
            self.assertIsNone(tracker.update(frame, is_main_world_open=False).camera_bearing)
            tracker.initialize((1000, 2000), "miraland")
            detector.rotation_confidence = 0.0
            self.assertIsNone(tracker.update(frame, is_main_world_open=True, track_heading=True).camera_bearing)

    def test_failed_frames_never_extend_the_last_good_position_or_heading(self):
        detector = FakeMiniMapDetector()
        detector.rotation_confidence = 0.8
        detector.update_rotation = Mock(return_value=0.0)
        tracker = MiniMapPositionTracker(detector=detector)
        frame = np.zeros((200, 200), dtype=np.uint8)
        with patch("whimbox.map.mask.minimap_tracker.rgb2luma", side_effect=lambda im: im), \
                patch("whimbox.map.mask.minimap_tracker.time.monotonic") as clock:
            clock.return_value = 100.0
            tracker.initialize((1000, 2000), "miraland")
            self.assertLess(tracker.snapshot(is_main_world_open=True, screen_width=200,
                                            screen_height=200).position_sample_at, 0)
            def observe(when):
                clock.return_value = when
                return tracker.update(frame, is_main_world_open=True, track_heading=True)

            self.assertEqual(observe(100).camera_bearing, 0)
            detector.rotation_confidence = 0.05
            shaky = observe(100.2)
            self.assertEqual((shaky.camera_bearing, shaky.camera_sample_at, shaky.position_sample_at),
                             (0, 100, 100.2))
            detector.verify_result = False
            missed = observe(100.4)
            self.assertEqual((missed.camera_bearing, missed.camera_sample_at, missed.position_sample_at),
                             (0, 100, 100.2))
            self.assertIsNone(observe(100.61).camera_bearing)
            detector.verify_result = True
            detector.rotation_confidence = 0.85
            detector.update_rotation.return_value = -90
            self.assertEqual(observe(100.72).camera_bearing, 90)
            hidden = tracker.update(frame, is_main_world_open=False, track_heading=True)
            self.assertIsNone(hidden.camera_bearing)
            self.assertLess(hidden.position_sample_at, 0)


class CollectionNavigationTests(unittest.TestCase):
    def setUp(self):
        self.client = MutablePearPalUserClient()
        self.empty = PearPalAwardedState(frozenset(), frozenset())
        self.client.awarded_state = self.empty
        self.provider = OfficialPearPalProvider(
            enabled=True, client=FakePearPalClient(), user_client=self.client,
            background=False, auth_background=False, refresh_background=False,
        )
        self.clock = 100.0
        mocked_time = patch("whimbox.map.mask.pearpal_provider.time.monotonic",
                            side_effect=lambda: self.clock)
        mocked_time.start()
        self.addCleanup(mocked_time.stop)
        self.credentials = PearPalCredentials(token="unit-test", openid="12405094")
        self.provider.authenticate(self.credentials)
        self.provider.list_points()

    def tick(self, when, *, bigmap=False):
        self.clock = when
        self.provider.note_overlay_activity(is_bigmap_open=bigmap)

    def test_only_opening_the_big_map_refreshes_progress(self):
        self.client.awarded_state = PearPalAwardedState(frozenset({"100"}), frozenset())
        for when in (135, 195, 405, 900):
            self.tick(when)
        self.assertEqual(self.client.calls, 1)
        self.assertIn("pearpal:100", {p.id for p in self.provider.list_points()})
        self.tick(901, bigmap=True)
        self.tick(1800, bigmap=True)
        self.assertEqual(self.client.calls, 2)
        self.assertEqual(self.provider.get_user_status()["last_refresh_reason"], "map-open")
        self.assertNotIn("pearpal:100", {p.id for p in self.provider.list_points()})

    def navigation_view(self):
        service = MapMaskService()
        service.enabled = True
        service.provider = service.official_provider = self.provider
        service._touch_detection_worker = Mock()
        star = self.provider.list_points(label_ids=["pearpal_star"])[0]
        view = viewport()
        view = replace(view, image_left=star.image_x-200, image_top=star.image_y-200,
                       image_width=400, image_height=400, screen_width=200, screen_height=200)
        pose = Mock(status="tracking", failure_count=0, map_name=view.map_name,
                    position_x=star.image_x, position_y=star.image_y,
                    camera_bearing=0, camera_sample_at=self.clock, position_sample_at=self.clock)
        state = Mock(is_map_open=True, display_mode="minimap")
        state.to_dict.return_value = {}
        service._build_state = Mock(return_value=(state, view, Mock(detection_error=""), pose))
        def visible(labels=("pearpal_star", "pearpal_box"), enabled=True, compass=True):
            return service.get_visible_points(label_ids=list(labels), scene_guidance=enabled, compass_fallback=compass)
        return star, pose, state, visible

    def test_progress_filters_arrows_and_map_markers_together(self):
        star, pose, state, visible = self.navigation_view()
        self.assertEqual(visible()["scene_target"]["id"], star.id)
        self.assertEqual(visible(["pearpal_box"])["scene_target"]["id"], "pearpal:201")
        self.assertNotIn("scene_target", visible([]))
        self.assertNotIn("scene_target", visible(enabled=False))
        self.assertIn(star.id, [p["id"] for p in visible()["points"]])
        self.client.awarded_state = PearPalAwardedState(frozenset({"100"}), frozenset())
        self.tick(150, bigmap=True)
        self.assertNotIn("scene_target", visible())  # A frozen position expires even with zero reported failures.
        pose.position_sample_at = self.clock
        self.assertIsNone(visible()["scene_target"]["turn_deg"])
        self.assertNotIn("scene_target", visible(compass=False))
        pose.camera_sample_at = self.clock
        self.assertEqual(visible()["scene_target"]["id"], "pearpal:201")
        self.assertNotIn(star.id, [p["id"] for p in visible()["points"]])
        pose.failure_count = 1
        self.assertEqual(visible()["scene_target"]["id"], "pearpal:201")
        pose.position_sample_at = self.clock - 1
        self.assertNotIn("scene_target", visible())
        pose.failure_count = 0
        pose.position_sample_at = self.clock
        pose.status = "lost"
        self.assertNotIn("scene_target", visible())
        pose.status = "tracking"
        state.display_mode = "bigmap"
        self.assertNotIn("scene_target", visible())
        state.display_mode = "minimap"
        self.provider.disconnect_user()
        self.assertNotIn("scene_target", visible())

    def test_seven_refused_openings_keep_the_authenticated_filtered_snapshot(self):
        star, pose, _, visible = self.navigation_view()
        def target():
            pose.position_sample_at = pose.camera_sample_at = self.clock
            return visible()["scene_target"]

        self.assertFalse(target()["progress_cached"])
        self.client.error = ConnectionRefusedError(10061, "connection refused")
        for opening in range(7):
            self.tick(101 + 2 * opening, bigmap=True)
            self.tick(102 + 2 * opening)
            self.assertEqual(target()["id"], star.id)
            self.assertTrue(target()["progress_cached"])
        self.assertEqual(self.client.calls, 8)  # Login plus seven M openings, regardless of HUD reads.
        self.client.error = None
        self.client.awarded_state = PearPalAwardedState(frozenset({"100"}), frozenset())
        self.tick(118, bigmap=True)
        self.assertEqual(target()["id"], "pearpal:201")
        self.assertFalse(target()["progress_cached"])
        self.assertNotIn(star.id, {p["id"] for p in visible()["points"]})
        self.assertEqual(self.client.calls, 9)

    def test_cached_progress_is_bound_to_login_region_and_filter(self):
        _, _, _, visible = self.navigation_view()
        self.client.error = ValueError("offline")
        self.tick(self.clock, bigmap=True)
        self.assertTrue(visible()["scene_target"]["progress_cached"])
        self.provider.set_hide_awarded(False)
        self.assertNotIn("scene_target", visible())
        self.provider.set_hide_awarded(True)
        self.provider.set_region("oversea")
        self.assertNotIn("scene_target", visible())
        self.provider.authenticate(self.credentials)
        self.assertNotIn("scene_target", visible())  # This login has never synced successfully.

    def test_failure_waits_for_the_next_open_or_manual_refresh(self):
        self.client.error = ValueError("offline")
        self.tick(101, bigmap=True)
        self.tick(160, bigmap=True)
        self.tick(300)
        self.tick(1500)
        self.assertEqual(self.client.calls, 2)
        self.assertTrue(self.provider.list_points(label_ids=["pearpal_star"]))
        self.client.error = None
        self.tick(1501, bigmap=True)
        self.provider.refresh_user_state()
        self.assertEqual(self.client.calls, 4)
        self.assertEqual(self.provider.get_user_status()["last_refresh_reason"], "manual")

    def test_slow_request_serializes_one_read_per_reopening(self):
        started, release = threading.Event(), threading.Event()
        workers = []
        def fetch(credentials):
            workers.append(threading.current_thread())
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test did not release fetch")
            return self.empty
        self.provider._refresh_background = True
        with patch.object(self.client, "fetch_awarded_state", side_effect=fetch):
            self.provider.refresh_user_state()
            try:
                self.assertTrue(started.wait(timeout=2))
                for opened in [True, True, False, True, True, False]:
                    self.provider.note_overlay_activity(is_bigmap_open=opened)
                self.assertEqual(len(workers), 1)
            finally:
                release.set()
            workers[0].join(timeout=2)
        self.assertEqual(workers, [workers[0]] * 3)
        self.assertFalse(self.provider.get_user_status()["refreshing"])

    def test_logout_drops_queued_openings_and_the_old_result(self):
        started, release = threading.Event(), threading.Event()
        workers = []
        def fetch(credentials):
            workers.append(threading.current_thread())
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test did not release fetch")
            return PearPalAwardedState(frozenset({"100"}), frozenset())
        self.provider._refresh_background = True
        with patch.object(self.client, "fetch_awarded_state", side_effect=fetch):
            self.tick(101, bigmap=True)
            try:
                self.assertTrue(started.wait(timeout=2))
                self.tick(102)
                self.tick(103, bigmap=True)
                self.provider.clear_login_information()
                self.tick(104)
                self.tick(105, bigmap=True)
            finally:
                release.set()
            workers[0].join(timeout=2)
        self.assertEqual(len(workers), 1)
        self.assertEqual(self.provider.get_user_status()["awarded_star_count"], 0)

    def test_detection_worker_only_rearms_after_confirmed_world(self):
        service = MapMaskService()
        service.enabled = True
        service.use_sample_viewport = False
        service.official_provider = self.provider
        service._detection_last_activity = self.clock
        service._detection_map_name = "miraland"
        service._mouse_wheel_guard = Mock()
        service.minimap_tracker = Mock(needs_calibration=False)
        service.region_detector.update = Mock(return_value=("miraland", False))
        frames = ["world", "map", "map", "details", "error", "map", "world", "map", "map"]
        def map_icon(captured_image):
            if captured_image == "error":
                raise ValueError("unreadable frame")
            return captured_image == "map"
        service.bigmap_state_provider._detect_with_whimbox_page = map_icon
        service.bigmap_state_provider._detect_main_world_with_whimbox_page = lambda captured_image: captured_image == "world"
        seen = []
        def capture():
            image = frames[len(seen)]
            seen.append(image)
            return image
        def between_frames(_delay):
            if len(seen) == len(frames):
                service.enabled = False
        service._detection_wake.wait = between_frames
        with patch("whimbox.interaction.interaction_core.itt.capture", side_effect=capture):
            service._detection_loop()
        self.assertEqual(seen, frames)
        self.assertEqual(self.client.calls, 3)  # Login plus two genuine openings.
        self.tick(101, bigmap=True)
        self.assertEqual(self.client.calls, 3)
