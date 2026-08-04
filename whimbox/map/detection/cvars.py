MAP_NAME_UNSUPPORTED = "unsupported"
MAP_NAME_MIRALAND = "miraland"
MAP_NAME_STARSEA = "starsea"
# MAP_NAME_WISHFIELD = "wishfield"
# MAP_NAME_ITZALAN = "itzalan"
MAP_NAME_FIREWORK = "firework"  # 花焰群岛
MAP_NAME_SERNITY = "sernity"    # 无忧岛
MAP_NAME_DANQING = "danqing"    # 丹青屿
MAP_NAME_WANXIANG = "wanxiang"  # 万相境
MAP_NAME_HOME = "home"
REGION_NAME_HOME = "家园"

REGION_NAME_TO_MAP_NAME_DICT = {
    MAP_NAME_MIRALAND: ["纪念山地", "花愿镇", "微风绿野", "小石树田村", "石树田无人区", "祈愿树林", "巨木之森", "伊地峡谷", "蜗牛城", "埋骨地", "磐城"],
    MAP_NAME_STARSEA: ["星海"],
    MAP_NAME_FIREWORK: ["花焰群岛"],
    MAP_NAME_SERNITY: ["无忧岛"],
    MAP_NAME_DANQING: ["丹青屿"],
    MAP_NAME_WANXIANG: ["万相境"],
}

UNSUPPORTED_REGIN_LIST = ["蜗牛城", "花焰群岛", "无忧岛", "丹青屿"]

GAMELOC_TO_PNGMAP_SCALE = 2/90
GAMELOC_TO_PNGMAP_OFFSET_DICT = {
    MAP_NAME_MIRALAND: (20819, 21099),
    MAP_NAME_STARSEA: (2448, 1051),
    MAP_NAME_HOME: (1989, 1243),
    MAP_NAME_WANXIANG: (1950, 987),
}

# 预计最大移动速度
MOVE_SPEED = 100

# Magic numbers for 1920x1080 desktop
MINIMAP_CENTER = (79 + 102, 20 + 102)
MINIMAP_RADIUS = 102
MINIMAP_POSITION_RADIUS = 100
MINIMAP_POSITION_SCALE_DICT = {
    MAP_NAME_MIRALAND: 0.975,
    MAP_NAME_STARSEA: 0.8,
    MAP_NAME_HOME: 0.8,
    MAP_NAME_WANXIANG: 0.8,
}

# Downscale png map and minimap for faster run
POSITION_SEARCH_SCALE = 0.5
# Search the area that is 1.3x minimap
POSITION_SEARCH_RADIUS = 1.3
# Can't figure out why but the result_of_0.5_lookup_scale + 0.5 ~= result_of_1.0_lookup_scale
POSITION_MOVE = (0.5, 0.5)

DIRECTION_SIMILARITY_COLOR = (155, 255, 255)
# Radius to search direction arrow, about 15px
DIRECTION_RADIUS = 13
# Downscale direction arrows for faster run
DIRECTION_SEARCH_SCALE = 0.5
# Scale to png
DIRECTION_ROTATION_SCALE = 1.0

# Downscale png map to run faster
BIGMAP_SEARCH_SCALE = 0.125
# Magic number that resize a 1920*1080 screenshot to luma_05x_png
BIGMAP_POSITION_SCALE_DICT = {
    MAP_NAME_MIRALAND: 0.637,
    MAP_NAME_STARSEA: 0.62,
    MAP_NAME_HOME: 0.61,
    MAP_NAME_WANXIANG: 0.62,
}
