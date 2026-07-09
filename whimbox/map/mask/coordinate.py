from __future__ import annotations

from .models import MapMaskPoint, MapMaskViewport, VisibleMapMaskPoint


def point_to_visible(
    point: MapMaskPoint,
    viewport: MapMaskViewport,
) -> VisibleMapMaskPoint | None:
    if viewport.image_width <= 0 or viewport.image_height <= 0:
        return None
    if viewport.screen_width <= 0 or viewport.screen_height <= 0:
        return None

    relative_x = (point.image_x - viewport.image_left) / viewport.image_width
    relative_y = (point.image_y - viewport.image_top) / viewport.image_height
    if relative_x < 0 or relative_x > 1 or relative_y < 0 or relative_y > 1:
        return None

    screen_x = viewport.screen_left + relative_x * viewport.screen_width
    screen_y = viewport.screen_top + relative_y * viewport.screen_height
    return VisibleMapMaskPoint(
        id=point.id,
        label_id=point.label_id,
        name=point.name,
        map_name=point.map_name,
        screen_x=screen_x,
        screen_y=screen_y,
        icon=point.icon,
        provider=point.provider,
        is_visible=True,
    )
