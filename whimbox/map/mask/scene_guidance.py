"""Bearing to the nearest selected, uncollected point in the current world."""

from bisect import bisect_left
import math
from operator import attrgetter

from whimbox.map.detection.cvars import GAMELOC_TO_PNGMAP_SCALE

from .models import MapMaskPoint


_PIXELS_PER_METRE = 100 * GAMELOC_TO_PNGMAP_SCALE


def nearest_scene_target(
    points: tuple[MapMaskPoint, ...],
    x: float,
    y: float,
    camera_bearing: float | None,
) -> dict | None:
    """Use the provider's X-sorted, progress-filtered point index."""
    split = bisect_left(points, x, key=attrgetter("image_x"))
    nearest = None
    distance_squared = math.inf
    for indices in (range(split - 1, -1, -1), range(split, len(points))):
        for index in indices:
            point = points[index]
            dx = point.image_x - x
            if dx * dx > distance_squared:
                break
            dy = point.image_y - y
            squared = dx * dx + dy * dy
            if squared < distance_squared or (
                squared == distance_squared and nearest is not None and point.id < nearest.id
            ):
                nearest = point
                distance_squared = squared

    if nearest is None:
        return None
    # North is up in the calibrated map image. Clockwise turns are positive.
    bearing = math.degrees(math.atan2(nearest.image_x - x, y - nearest.image_y)) % 360
    turn = None if camera_bearing is None else round((bearing - camera_bearing + 180) % 360 - 180)
    return {
        "id": nearest.id,
        "label_id": nearest.label_id,
        "name": nearest.name,
        "turn_deg": turn,
        "bearing_deg": round(bearing, 2) % 360,
        "distance_m": round(math.sqrt(distance_squared) / _PIXELS_PER_METRE),
    }
