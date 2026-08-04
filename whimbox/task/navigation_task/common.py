import math


# 自动寻路时，当距离传送点offset内，就不传送了
# 记录路线时，当起点距离传送点offset外，就不予记录
not_teleport_offset = 30


def resolve_loop_return_mode(start_point, end_point):
    """根据循环起点属性和首尾距离自动判断返回方式。坐标必须是图片地图坐标。"""
    if start_point.action == "TELEPORT":
        return "teleport"

    distance = math.dist(start_point.position[:2], end_point.position[:2])
    if distance < not_teleport_offset:
        return "nearby"
    raise ValueError(
        f"循环分段无法返回起点：起点不是传送点，"
        f"且循环首尾距离相差太远"
    )
