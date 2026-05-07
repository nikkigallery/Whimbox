from whimbox.ui.template.img_manager import LOG_WHEN_TRUE, LOG_ALL, LOG_NONE, LOG_WHEN_FALSE, ImgIcon
from whimbox.ui.template.button_manager import Button
from whimbox.ui.template.posi_manager import Area
from whimbox.ui.template.text_manager import Text
from whimbox.common.cvars import *
from whimbox.ui.template.img_manager import GameImg
from whimbox.common.logger import logger
import time

start_time = time.time()
# 很多界面左上角都有的文字标题区域
AreaPageTitleFeature = Area(anchor=ANCHOR_TOP_LEFT)

# 主界面、esc菜单
IconPageMainFeature = ImgIcon(print_log=LOG_NONE, threshold=0.90, gray_limit=(230, 255), anchor=ANCHOR_BOTTOM_LEFT)
IconDungeonFeature = ImgIcon(print_log=LOG_ALL, threshold=0.90, gray_limit=(230, 255), anchor=ANCHOR_TOP_LEFT)
ButtonDungeonQuitOK = Button(print_log=LOG_ALL, anchor=ANCHOR_CENTER)
AreaUITime = Area(anchor=ANCHOR_TOP_LEFT)
AreaEscEntrances = Area(anchor=ANCHOR_LEFT_CENTER)
# 商城抽卡特征
IconGachaFeature = ImgIcon(print_log=LOG_NONE, threshold=0.99, anchor=ANCHOR_TOP_RIGHT)
IconShopFeature = ImgIcon(print_log=LOG_NONE, threshold=0.99, anchor=ANCHOR_TOP_LEFT)
# 登录流程特征
# IconPageLoginFeature = ImgIcon(print_log=LOG_ALL, threshold=0.90, hsv_limit=([0, 0, 220], [179, 50, 255]))
AreaLoginOCR = Area(anchor=ANCHOR_BOTTOM_CENTER)
AreaLaunchButton = Area()
ButtonExit = Button(print_log=LOG_WHEN_TRUE, threshold=0.90, hsv_limit=([0,30,250], [179,60,255]), anchor=ANCHOR_BOTTOM_LEFT)
AreaExitBackLoginButton = Area(anchor=ANCHOR_CENTER)
TextExitBackLoginButton = Text("返回登录", cap_area = AreaExitBackLoginButton)
ButtonExitLogout = Button(print_log=LOG_WHEN_TRUE, threshold=0.90, hsv_limit=([0,0,200], [179,80,255]), anchor=ANCHOR_TOP_RIGHT)
ButtonLogin = Button(print_log=LOG_WHEN_TRUE, threshold=0.90, hsv_limit=([0,0,180], [30,255,255]), anchor=ANCHOR_BOTTOM_CENTER)
AreaLoginAccountList = Area(anchor=ANCHOR_CENTER)
AreaLoginAccountLoginButton = Area(anchor=ANCHOR_CENTER)
TextLoginAccountLoginButton = Text("登录", cap_area = AreaLoginAccountLoginButton)
# 聊天框特征
IconPageChatFeature = ImgIcon(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_LEFT)
ButtonPageChatClose = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_TOP_LEFT)
# 小月卡特征
IconDailyRewardFeature1 = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.90, hsv_limit=([20, 45, 230], [30, 95, 255]), anchor=ANCHOR_CENTER)
IconDailyRewardFeature2 = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99, anchor=ANCHOR_CENTER)


# loading界面
IconUILoading = ImgIcon(print_log=LOG_NONE, threshold=0.99)

# 大地图相关
IconUIBigmap = ImgIcon(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_LEFT)
IconBigMapMaxScale = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.90, gray_limit=(155, 255), anchor=ANCHOR_BOTTOM_LEFT)
ButtonBigMapZoom = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_LEFT)
AreaBigMapTeleportButton = Area(anchor=ANCHOR_BOTTOM_RIGHT)
AreaBigMapRegionName = Area(anchor=ANCHOR_TOP_RIGHT)
AreaBigMapRegionSelect = Area(anchor=ANCHOR_TOP_RIGHT, expand=True)
IconBigMapHomeFeature = ImgIcon(threshold=0.90, hsv_limit=([10, 0, 190], [30, 80, 255]))
AreaBigMapTeleporterSelect = Area(anchor=ANCHOR_RIGHT_CENTER)
AreaBigMapMeteorText = Area(anchor=ANCHOR_TOP_LEFT)
# 大地图材料追踪
AreaBigMapMaterialTypeSelect = Area(anchor=ANCHOR_CENTER)
AreaBigMapMaterialSelect = Area(anchor=ANCHOR_CENTER)
AreaBigMapMaterialTrackConfirm = Area(anchor=ANCHOR_CENTER)

# 大世界采集、跳跃、移动、跳过等相关的UI
AreaDialog = Area(anchor=ANCHOR_CENTER, expand=True)
AreaPickup = Area(anchor=ANCHOR_CENTER, expand=True)
TextPickUp = Text("拾取", cap_area = AreaPickup)
IconPickupFeature = ImgIcon(print_log=LOG_NONE, threshold=0.75, gray_limit=(210, 255))
IconSetdownFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.75, gray_limit=(210, 255))
IconTalkFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.75, gray_limit=(210, 255))
IconSkip = ImgIcon(print_log=LOG_NONE, threshold=0.73, gray_limit=(210, 255), anchor=ANCHOR_BOTTOM_RIGHT)
IconClickSkip = ImgIcon(print_log=LOG_ALL, threshold=0.80, gray_limit=(210, 255), anchor=ANCHOR_BOTTOM_RIGHT)
AreaDialogSelection = Area(anchor=ANCHOR_RIGHT_CENTER)
IconSkipDialog = ImgIcon(print_log=LOG_NONE, threshold=0.73, gray_limit=(210, 255), anchor=ANCHOR_BOTTOM_RIGHT)
IconMovementWalk = ImgIcon(print_log=LOG_NONE, threshold=0.85, hsv_limit=([0, 0, 210], [180, 50, 255]), anchor=ANCHOR_BOTTOM_RIGHT)
AreaMaterialGetText = Area(anchor=ANCHOR_BOTTOM_LEFT)
AreaAbilityButton = Area(anchor=ANCHOR_BOTTOM_RIGHT)
AreaSubAbilityButton = Area(anchor=ANCHOR_BOTTOM_RIGHT)

# 钓鱼相关
IconFishingNoFish = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.90, hsv_limit=([0,0,175], [20,255,255]), anchor=ANCHOR_TOP_CENTER) # 鱼掉光时候的图标
AreaFishingDetection = Area(anchor=ANCHOR_CENTER, expand=True)  # B区域（鱼进度检测区域）
AreaFishingIcons = Area(anchor=ANCHOR_BOTTOM_RIGHT)
IconFishingHomeFeature = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255))      # 取消钓陨星
IconFishingMiralandFeature = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255))  # 取消钓鱼
IconFishingFinish = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255))  # 收竿图标
IconFishingStrike = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255)) # 提竿图标
IconFishingPullLine = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255))  # 大世界拉扯鱼线图标
IconFishingPullLineHome = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255))  # 家园拉扯鱼线图标
IconFishingReelIn = ImgIcon(print_log=LOG_NONE, threshold=0.80, gray_limit=(210, 255))  # 收线图标

# 幻境挑战页面
ButtonHuanjingGo = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
AreaHuanjingMonsterEntrace = Area(anchor=ANCHOR_CENTER)
TextHuanjingMonsterEntrace = Text("魔物试炼幻境", cap_area = AreaHuanjingMonsterEntrace)
AreaHuanjingBlessEntrace = Area(anchor=ANCHOR_CENTER)
TextHuanjingBlessEntrace = Text("祝福闪光幻境", cap_area = AreaHuanjingBlessEntrace)
AreaHuanjingZiyangEntrace = Area(anchor=ANCHOR_CENTER)
TextHuanjingZiyangEntrace = Text("奇想滋养幻境", cap_area = AreaHuanjingZiyangEntrace)
AreaHuanjingJihuaEntrace = Area(anchor=ANCHOR_CENTER)
TextHuanjingJihuaEntrace = Text("素材激化幻境", cap_area = AreaHuanjingJihuaEntrace)
AreaHuanjingBossEntrace = Area(anchor=ANCHOR_CENTER)
TextHuanjingBossEntrace = Text("心之突破幻境", cap_area = AreaHuanjingBossEntrace)

# 祝福闪光幻境相关
AreaBlessHuanjingLevelsSelect = Area(anchor=ANCHOR_TOP_LEFT, expand=True)
AreaBlessHuanjingDifficulty3 = Area(anchor=ANCHOR_TOP_RIGHT)
TextBlessHuanjingDifficulty3 = Text("困难", cap_area=AreaBlessHuanjingDifficulty3)
ButtonBlessHuanjingQuickPlay = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_RIGHT)
ButtonBlessHuanjingNumMax = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
ButtonHuanjingConfirm = Button(print_log=LOG_ALL, threshold=0.99, anchor=ANCHOR_CENTER)
ButtonHuanjingCancel = Button(print_log=LOG_ALL, threshold=0.99, anchor=ANCHOR_CENTER)

# 素材激化幻境相关
ButtonJihuaInnerGo = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_RIGHT)
AreaTextJihuatai = Area(anchor=ANCHOR_CENTER, expand=True)
TextJihuatai = Text("打开素材激化台", cap_area = AreaTextJihuatai)
AreaJihuaTargetSelect = Area(anchor=ANCHOR_TOP_RIGHT)
AreaJihuaCostSelect = Area(anchor=ANCHOR_TOP_LEFT, expand=True)
ButtonJihuaNumMax = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
ButtonJihuaNumConfirm = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
ButtonJihuaFinallyConfirm = Button(print_log=LOG_WHEN_TRUE, threshold=0.99, anchor=ANCHOR_BOTTOM_RIGHT)
AreaJihuaNumOrQualityChooseButton = Area(anchor=ANCHOR_BOTTOM_LEFT)
AreaJihuaNumOrQualityChooseList = Area(anchor=ANCHOR_BOTTOM_LEFT)
ButtonJihuaSort = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_LEFT)
AreaJihuaFirstMaterial = Area(anchor=ANCHOR_TOP_LEFT)

# 魔物试炼幻境相关
# 基本可以复用祝福闪光幻境

# 每周幻境相关
AreaWeeklyCountText = Area(anchor=ANCHOR_CENTER)

# 美鸭梨挖掘相关
ButtonDigGather = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_RIGHT_CENTER)
ButtonDigGatherConfirm = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
ButtonDigAgain = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
AreaDigingNumText = Area(anchor=ANCHOR_RIGHT_CENTER)
AreaDigMainTypeSelect = Area()
AreaDigSubTypeSelect = Area()
AreaDigItemSelect = Area()
ButtonDigConfirm = Button(print_log=LOG_WHEN_TRUE)
ButtonDigTime20h = Button(print_log=LOG_WHEN_TRUE, threshold=0.95)

# 朝夕心愿相关
AreaZxxyEnergy = Area(anchor=ANCHOR_CENTER)
ButtonZxxyEntrance = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
IconZxxyFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.90, gray_limit=(180, 255), anchor=ANCHOR_RIGHT_CENTER)
AreaZxxyScore = Area(anchor=ANCHOR_RIGHT_CENTER)
AreaZxxyRewards = Area(anchor=ANCHOR_RIGHT_CENTER)
AreaZxxyTaskText = Area(anchor=ANCHOR_BOTTOM_CENTER)
IconZxxyTaskFinished = ImgIcon(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_CENTER)

# 星海拾光相关
ButtonXhsgEntrance = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
IconXhsgFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.90, hsv_limit=([10, 40, 150], [35, 150, 255]), anchor=ANCHOR_BOTTOM_CENTER)
AreaXhsgScore = Area(anchor=ANCHOR_RIGHT_CENTER)
AreaXhsgRewards = Area(anchor=ANCHOR_RIGHT_CENTER)
AreaXhsgTaskText = Area(anchor=ANCHOR_BOTTOM_CENTER)
IconXhsgTaskFinished = ImgIcon(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_CENTER)
ButtonXhsgBooklookLike = Button(print_log=LOG_ALL, threshold=0.90, hsv_limit=([0, 0, 140], [179, 255, 255]), anchor=ANCHOR_BOTTOM_RIGHT)
IconXhsgGroupChatFeature = ImgIcon(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_TOP_LEFT)
TextChangeMusic = Text("更改音乐", cap_area = AreaPickup)
TextTransAnimal = Text("变身", cap_area = AreaPickup)
ButtonXhsgBottleClose = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
TextDeliveryBottle = Text("投递", cap_area = AreaPickup)
GameImgStarCrystal = GameImg(name="T_UI_map_img_icon_star_02")

# 换装界面
IconWardrobeFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99, anchor=ANCHOR_TOP_CENTER)

# 能力配置界面
AreaWardrobeTab3 = Area(anchor=ANCHOR_TOP_CENTER)
TextWardrobeAbilityTab = Text("能力配置", cap_area = AreaWardrobeTab3)
IconAbilityFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99, anchor=ANCHOR_TOP_CENTER)
ButtonAbilityConfig = ImgIcon(print_log=LOG_ALL, threshold=0.99, anchor=ANCHOR_BOTTOM_RIGHT)
ButtonAbilityChangeList = Button(print_log=LOG_WHEN_TRUE, threshold=0.75, gray_limit=(250, 255), anchor=ANCHOR_TOP_RIGHT)
IconAbilityFloat = ImgIcon()    # 泡泡套跳跃
IconAbilityWing = ImgIcon()    # 飞鸟套跳跃
IconAbilityAnimal = ImgIcon()    # 清洁
IconAbilityInsect = ImgIcon()      # 捕虫
IconAbilityFish = ImgIcon()     # 钓鱼
IconAbilityRhythms = ImgIcon()  # 万物交响
IconAbilityFly = ImgIcon()      # 滑翔
IconAbilitySmall = ImgIcon()    # 变小
IconAbilityBig = ImgIcon()    # 变大
IconAbilityStick = ImgIcon()    # 黏黏爪
IconAbilityFlourish = ImgIcon()    # 芳间巡游
IconAbilityShapeshifting = ImgIcon()    # 化万相
IconAbilityStarCollect = ImgIcon() # 采星
AreaAbilityChange = Area(anchor=ANCHOR_RIGHT_CENTER)
ButtonAbilitySave = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_RIGHT)
AreaAbilityPlanChangeButton = Area(anchor=ANCHOR_TOP_LEFT)
AreaAbilityPlan1Button = Area(anchor=ANCHOR_TOP_LEFT)
AreaAbilityPlan2Button = Area(anchor=ANCHOR_TOP_LEFT)
AreaAbilityPlan3Button = Area(anchor=ANCHOR_TOP_LEFT)

# 素材相关
IconMaterialTypeAnimal = ImgIcon(print_log=LOG_WHEN_TRUE)
IconMaterialTypePlant = ImgIcon(print_log=LOG_WHEN_TRUE)
IconMaterialTypeInsect = ImgIcon(print_log=LOG_WHEN_TRUE)
IconMaterialTypeFish = ImgIcon(print_log=LOG_WHEN_TRUE)
IconMaterialTypeMonster = ImgIcon(print_log=LOG_WHEN_TRUE)
IconMaterialTypeOther = ImgIcon(print_log=LOG_WHEN_TRUE)
IconMaterialTypeDig1 = ImgIcon(print_log=LOG_WHEN_TRUE)

# 拍照相关
IconPhotoFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.90, gray_limit=(250, 255), anchor=ANCHOR_RIGHT_CENTER)
IconPhotoEdit = ImgIcon(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_RIGHT)
ButtonPhotoDelete = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_LEFT)
ButtonPhotoDeleteConfirm = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)

# 大月卡，奇迹之旅
AreaMonthlyStart = Area(anchor=ANCHOR_CENTER)
TextMonthlyStart = Text("开启探索", cap_area=AreaMonthlyStart)
ButtonMonthlyPassAward = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)
AreaMonthlyPassTab1 = Area(anchor=ANCHOR_TOP_CENTER)
TextMonthlyPassTab1 = Text("旅行秘宝", cap_area=AreaMonthlyPassTab1)
AreaMonthlyPassTab2 = Area(anchor=ANCHOR_TOP_CENTER)
TextMonthlyPassTab2 = Text("旅行任务", cap_area=AreaMonthlyPassTab2)

# 奇迹之冠
AreaMiraCrownOverview = Area(anchor=ANCHOR_CENTER)
AreaMiraCrownEntrance = Area(anchor=ANCHOR_TOP_LEFT)
ButtonMiraCrownQuickReward = Button(anchor=ANCHOR_CENTER, print_log=LOG_ALL)
ButtonMiraCrownRank = Button(anchor=ANCHOR_TOP_CENTER, print_log=LOG_ALL, gray_limit=(50, 255))
AreaMiraCrownSecondDoor = Area(anchor=ANCHOR_CENTER)
AreaMiraCrownThirdDoor = Area(anchor=ANCHOR_CENTER)
ButtonMiraCrownStartChallenge = Button(anchor=ANCHOR_BOTTOM_RIGHT, print_log=LOG_ALL)
AreaMiraCrownAutoMatchButton = Area(anchor=ANCHOR_TOP_RIGHT)
ButtonMiraCrownNextStep = Button(anchor=ANCHOR_BOTTOM_LEFT, print_log=LOG_ALL)
ButtonMiraCrownConfirmMatch = Button(anchor=ANCHOR_BOTTOM_LEFT, print_log=LOG_ALL)
ButtonMiraCrownSkipAll = Button(anchor=ANCHOR_TOP_RIGHT, print_log=LOG_ALL, threshold=0.80, hsv_limit=([20,20,180], [30,100,255]))

# 活动相关
# 1.11大富翁活动
ButtonMonopolyEntrance = Button(print_log=LOG_WHEN_TRUE)
ButtonMonopolyConfirmDailyAward = Button(print_log=LOG_WHEN_TRUE)
ButtonMonopolySendBullet = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)
ButtonMonopolyCloseBullet = Button(print_log=LOG_WHEN_TRUE)
AreaMonopolyDiceNum = Area()
IconMonopolyMapFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99)
IconMonopolyMapFeature2 = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99)
IconMonopolyNikkiFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99)
ButtonMonopolyRollDice = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)
ButtonMonopolyStopFunBox = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)
AreaMonopolyFunboxOptions = Area()
ButtonMonopolyStartQuestion = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)
# IconMonopolyQuestionFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99)
AreaMonopolyQuestion = Area()
AreaMonopolyAnswer = Area()
ButtonMonopolyLeaveGrid = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)
ButtonMonopolyConfirmEvent = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)
IconMonopolyTicketFeature = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99)
ButtonMonopolyTaskFull = Button(print_log=LOG_WHEN_TRUE, threshold=0.99)

# 小游戏相关
ButtonMinigameQuit = Button(print_log=LOG_ALL, threshold=0.99, anchor=ANCHOR_CENTER)
ButtonMinigameRetry = Button(print_log=LOG_ALL, threshold=0.99, anchor=ANCHOR_CENTER)
ButtonMinigameRetryOk = Button(print_log=LOG_ALL, threshold=0.99, anchor=ANCHOR_CENTER)
AreaMinigameEscSelect = Area(anchor=ANCHOR_BOTTOM_RIGHT)

# 使用物品相关
ButtonItemSetting = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_BOTTOM_CENTER, threshold=0.80, gray_limit=(210, 255))
ButtonItemFinishSetting = Button(print_log=LOG_ALL, anchor=ANCHOR_BOTTOM_RIGHT, threshold=0.97)
ButtonItemPlaceableItem = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_RIGHT_CENTER, threshold=0.80, gray_limit=(250, 255))
AreaItemFirstItem = Area(anchor=ANCHOR_TOP_RIGHT)
IconItemCantPlace = ImgIcon(print_log=LOG_WHEN_TRUE, threshold=0.99, hsv_limit=([0,0,210], [179,130,255]), anchor=ANCHOR_TOP_CENTER)
ButtonItemLanternConfirm = Button(print_log=LOG_WHEN_TRUE, anchor=ANCHOR_CENTER)

logger.info(f"ui_assets cost {round(time.time() - start_time, 2)}")