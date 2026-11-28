import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from whimbox.map.detection.cvars import MINIMAP_POSITION_SCALE_DICT, POSITION_SEARCH_SCALE
from whimbox.map.detection.map_assets import MAP_ASSETS_DICT
from whimbox.map.mask.minimap_recovery import NearbyRecovery, match_nearby
from whimbox.map.mask.minimap_tracker import MiniMapPositionTracker


class NearbyMatchTests(unittest.TestCase):
    def test_ambiguous_tiles_blank_frames_and_seeds_outside_atlas_are_withheld(self):
        rng = np.random.default_rng(254)
        tile = rng.integers(20, 235, (200, 200), dtype=np.uint8)
        scale = MINIMAP_POSITION_SCALE_DICT["miraland"] * POSITION_SEARCH_SCALE
        scaled = cv2.resize(tile, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        height, width = scaled.shape
        atlas = rng.integers(20, 235, (500, 500), dtype=np.uint8)
        y, left, right = 173, 135, 252
        anchor = (2 * (199 + width / 2), 2 * (y + height / 2))
        with patch.dict(MAP_ASSETS_DICT, {"miraland": {"luma_05x": SimpleNamespace(img=atlas)}}):
            atlas[y:y+height, left:left+width] = scaled
            match = match_nearby(tile, "miraland", anchor)
            self.assertIsNotNone(match)
            self.assertLess(np.linalg.norm(np.array(match[0]) - (2*left+width, 2*y+height)), 1.0)
            atlas[y:y+height, right:right+width] = scaled
            self.assertIsNone(match_nearby(tile, "miraland", anchor))
            self.assertIsNone(match_nearby(np.zeros_like(tile), "miraland", anchor))
            self.assertIsNone(match_nearby(tile, "miraland", (-1000, -1000)))

    def test_three_separate_consistent_probes_and_backoff(self):
        search = NearbyRecovery()
        first = ((1000, 1200), 0.8, 0.2)
        far = ((1100, 1200), 0.76, 0.1)
        with patch("whimbox.map.mask.minimap_recovery.match_nearby",
                   side_effect=[None, first, far, far, far]) as match:
            def probe(now):
                return search.probe(None, "miraland", (1000, 1200), now)
            self.assertIsNone(probe(1.0))
            self.assertIsNone(probe(1.1))
            self.assertEqual(match.call_count, 1)
            self.assertIsNone(probe(1.9))
            self.assertIsNone(probe(1.91))
            self.assertIsNone(probe(2.05))  # Inconsistent jump starts a new streak.
            self.assertIsNone(probe(2.20))
            self.assertEqual(probe(2.35), far)
            self.assertEqual(match.call_count, 5)


class TrackerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.detector = Mock()
        self.detector._get_minimap.side_effect = lambda image, radius: image
        self.detector.verify_position.return_value = True
        self.detector.init_position.side_effect = lambda pos: setattr(self.detector, "position", pos)
        self.detector._predict_position.return_value = (0.4, 0.08, (1000, 2000))
        self.tracker = MiniMapPositionTracker(self.detector)
        self.clock = 10.0
        self.image = np.zeros((200, 200), dtype=np.uint8)
        self.enterContext(patch("whimbox.map.mask.minimap_tracker.time.monotonic", side_effect=lambda:self.clock))
        self.enterContext(patch("whimbox.map.mask.minimap_tracker.rgb2luma", side_effect=lambda img:img))
        self.tracker.initialize((1000, 2000), "miraland")
        self.tick()

    def tick(self, elapsed=.1, world=True):
        self.clock += elapsed
        return self.tracker.update(self.image, is_main_world_open=world, track_heading=False)

    def test_lost_resumes_only_after_nearby_terrain_is_confirmed(self):
        self.detector._predict_position.return_value = (0.09, 0.01, (1000,2000))
        with patch("whimbox.map.mask.minimap_recovery.match_nearby", return_value=None) as match:
            self.tick()
            lost = self.tick(5.1)
            self.assertEqual(lost.status, "lost")
            self.assertIsNone(lost.viewport)
            self.assertIsNone(lost.position_x)
            match.return_value = ((1080,2021), .55, .17)
            self.assertIsNone(self.tick(1).viewport)
            self.assertIsNone(self.tick(.16).viewport)
            self.assertIsNone(self.tick(.02).viewport)
            resumed = self.tick(.16)
            self.assertEqual(resumed.status, "tracking")
            self.assertEqual((resumed.position_x,resumed.position_y), (1080,2021))
            self.assertIsNotNone(resumed.viewport)
            self.assertEqual(resumed.failure_count, 0)

    def test_menu_interrupts_pending_recovery_and_reset_discards_the_old_map(self):
        self.detector._predict_position.return_value = (0.05, 0.01, (1000,2000))
        with patch("whimbox.map.mask.minimap_recovery.match_nearby", return_value=None) as match:
            self.tick()
            self.tick(5.2)
            match.return_value = ((1090,2010), .6, .2)
            self.tick(.9)
            self.tick(.15)
            self.assertIsNone(self.tick(.2, world=False).viewport)
            self.assertIsNone(self.tick(.15).viewport)
            self.tracker.reset()
            calls = match.call_count
            self.assertEqual(self.tick(5).status, "uninitialized")
            self.assertEqual(match.call_count, calls)
            self.assertIsNone(self.tracker.snapshot(is_main_world_open=True, screen_width=1920, screen_height=1080).position_x)

    def test_time_in_a_menu_is_excluded_and_a_running_player_revalidates(self):
        self.tick(world=False)
        self.tick(.4)
        self.tick(world=False)
        self.tick(7,world=False)
        for step in (1,2,3):
            self.detector._predict_position.return_value = (.42,.08,(1000+6*step,2000))
            observation = self.tick(.12)
            self.assertEqual(observation.status, "tracking" if step==3 else "revalidating")
        self.assertEqual(observation.position_x,1018)

    def test_non_finite_match_cannot_replace_an_accepted_position(self):
        self.detector._predict_position.return_value = (float("nan"),0.2,(float("nan"),2000))
        snapshot = self.tick()
        self.assertEqual(snapshot.failure_count,1)
        self.assertEqual(snapshot.position_x,1000)
        self.assertIsNone(snapshot.camera_bearing)
