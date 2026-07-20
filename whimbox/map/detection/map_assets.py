import numpy as np

from whimbox.map.detection.cvars import *
from whimbox.map.detection.utils import create_circle_mask
from whimbox.map.detection.utils import MapAsset

def create_minimap_mask():
    '''小地图遮罩，扣掉中心箭头，避免匹配上地图上的小建筑'''
    # Create outer circle mask (within MINIMAP_POSITION_RADIUS)
    outer_mask = create_circle_mask(h=MINIMAP_POSITION_RADIUS * 2, w=MINIMAP_POSITION_RADIUS * 2)
    # Create inner circle mask (within DIRECTION_RADIUS) to exclude
    inner_mask = create_circle_mask(h=MINIMAP_POSITION_RADIUS * 2, w=MINIMAP_POSITION_RADIUS * 2,  radius=DIRECTION_RADIUS)
    # Create ring mask: keep outer circle but exclude inner circle
    mask = outer_mask & ~inner_mask
    mask = (mask * 255).astype(np.uint8)
    return mask


def create_rotation_remap_table():
    d = MINIMAP_RADIUS * 2
    mx = np.zeros((d, d), dtype=np.float32)
    my = np.zeros((d, d), dtype=np.float32)
    for i in range(d):
        for j in range(d):
            mx[i, j] = d / 2 + i / 2 * np.cos(2 * np.pi * j / d)
            my[i, j] = d / 2 + i / 2 * np.sin(2 * np.pi * j / d)
    return mx, my


# 小地图遮罩，用于位置匹配
MiniMapMask = create_minimap_mask()
# 用于识别小地图的镜头朝向
RotationRemapTable = create_rotation_remap_table()

# 箭头旋转表
ArrowRotateMap = MapAsset("ArrowRotateMap")
ArrowRotateMapAll = MapAsset("ArrowRotateMapAll")

# 奇迹大陆地图，用于小地图位置匹配
MiraLandMap = MapAsset("w01_v12_luma_05x")
# 奇迹大陆地图，用于大地图匹配
MiraLandBigMap = MapAsset("w01_v12_luma_0125x")
# 奇迹大陆地图，可匹配位置遮罩
MiraLandBigMapMask = MapAsset("w01_v12_mask_0125x")

# 星海地图，用于小地图位置匹配
StarSeaMap = MapAsset("w14000000_v2_luma_05x")
# 星海地图，用于大地图匹配
StarSeaBigMap = MapAsset("w14000000_v2_luma_0125x")
# 星海地图，可匹配位置遮罩
StarSeaBigMapMask = MapAsset("w14000000_v2_mask_0125x")

# 家园地图，用于小地图位置匹配
HomeMap = MapAsset("w8000001_v1_luma_05x")
# 家园地图，用于大地图匹配
HomeBigMap = MapAsset("w8000001_v1_luma_0125x")
# 家园地图，可匹配位置遮罩
HomeBigMapMask = MapAsset("w8000001_v1_mask_0125x")

# 家园地图，用于小地图位置匹配
WanXiangMap = MapAsset("w4020034_luma_05x")
# 家园地图，用于大地图匹配
WanXiangBigMap = MapAsset("w4020034_luma_0125x")
# 家园地图，可匹配位置遮罩
WanXiangBigMapMask = MapAsset("w4020034_mask_0125x")

MAP_ASSETS_DICT = {
    MAP_NAME_MIRALAND: {
        "luma_05x": MiraLandMap,
        "luma_0125x": MiraLandBigMap,
        "mask_0125x": MiraLandBigMapMask
    },
    MAP_NAME_STARSEA: {
        "luma_05x": StarSeaMap,
        "luma_0125x": StarSeaBigMap,
        "mask_0125x": StarSeaBigMapMask
    },
    MAP_NAME_HOME: {
        "luma_05x": HomeMap,
        "luma_0125x": HomeBigMap,
        "mask_0125x": HomeBigMapMask
    },
    MAP_NAME_WANXIANG: {
        "luma_05x": WanXiangMap,
        "luma_0125x": WanXiangBigMap,
        "mask_0125x": WanXiangBigMapMask
    }
}