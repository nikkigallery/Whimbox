"""Reacquire a missing minimap fix near its last known position, without moving the player."""
from __future__ import annotations

import math

import cv2
import numpy as np

from whimbox.map.detection.cvars import MINIMAP_POSITION_SCALE_DICT, MOVE_SPEED, POSITION_SEARCH_SCALE


_SEARCH_RADIUS = 200  # full-resolution map pixels around the last accepted fix
_MIN_SCORE = 0.22
_MIN_PEAK_MARGIN = 0.06
_PEAK_SEPARATION = 16  # closer peaks belong to the same map feature
_RETRY_INTERVAL = 0.8
_CONFIRM_INTERVAL = 0.14
_CONFIRM_SAMPLES = 3


def consistent_motion(previous, current, elapsed: float) -> bool:
    """Allow short, continuous movement between samples, including while running."""
    return 0 <= elapsed <= 0.75 and math.dist(previous, current) <= 3.0 + min(18.0, MOVE_SPEED * elapsed)


def match_nearby(minimap, map_name, anchor):
    from whimbox.map.detection.map_assets import MAP_ASSETS_DICT, MiniMapMask

    if minimap.shape != MiniMapMask.shape or not all(map(math.isfinite, anchor)):
        return None
    atlas = MAP_ASSETS_DICT[map_name]["luma_05x"].img
    scale = MINIMAP_POSITION_SCALE_DICT[map_name] * POSITION_SEARCH_SCALE
    tile = cv2.resize(minimap, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    mask = cv2.resize(MiniMapMask, (tile.shape[1], tile.shape[0]), interpolation=cv2.INTER_NEAREST)
    if cv2.meanStdDev(tile, mask=mask)[1].item() < 2.0:
        return None

    th, tw = tile.shape
    cx, cy = (value * POSITION_SEARCH_SCALE for value in anchor)
    radius = _SEARCH_RADIUS * POSITION_SEARCH_SCALE
    x0, y0 = max(0, math.floor(cx - tw / 2 - radius)), max(0, math.floor(cy - th / 2 - radius))
    x1 = min(atlas.shape[1], math.ceil(cx + tw / 2 + radius))
    y1 = min(atlas.shape[0], math.ceil(cy + th / 2 + radius))
    if x1 - x0 < tw or y1 - y0 < th:
        return None
    scores = cv2.matchTemplate(atlas[y0:y1, x0:x1], tile, cv2.TM_CCOEFF_NORMED, mask=mask)
    # OpenCV's masked normalization can produce non-finite scores on blank map areas.
    scores[~np.isfinite(scores) | (np.abs(scores) > 1.001)] = -1.0
    _, best, _, (x, y) = cv2.minMaxLoc(scores)
    if best < _MIN_SCORE:
        return None
    position = ((x0 + x + tw / 2) / POSITION_SEARCH_SCALE,
                (y0 + y + th / 2) / POSITION_SEARCH_SCALE)
    if math.dist(position, anchor) > _SEARCH_RADIUS:
        return None
    # Suppress the winning feature before measuring the best alternative location.
    separation = max(1, round(_PEAK_SEPARATION * POSITION_SEARCH_SCALE))
    cv2.circle(scores, (x, y), separation, -1.0, thickness=-1)
    margin = best - cv2.minMaxLoc(scores)[1]
    return (position, best, margin) if margin >= _MIN_PEAK_MARGIN else None


class NearbyRecovery:
    def __init__(self):
        self.reset()

    def reset(self):
        self.next_probe = 0.0
        self.previous = None
        self.previous_at = 0.0
        self.matches = 0

    def missed(self, now):
        self.reset()
        self.next_probe = now + _RETRY_INTERVAL

    def probe(self, minimap, map_name, anchor, now):
        if now < self.next_probe:
            return None
        self.next_probe = now + _RETRY_INTERVAL
        match = match_nearby(minimap, map_name, anchor)
        if match is None:
            self.missed(now)
            return None
        position, _, _ = match
        if self.previous is None or not consistent_motion(self.previous, position, now - self.previous_at):
            self.matches = 0
        self.previous, self.previous_at = position, now
        self.matches += 1
        if self.matches < _CONFIRM_SAMPLES:
            self.next_probe = now + _CONFIRM_INTERVAL
            return None
        self.reset()
        return match
