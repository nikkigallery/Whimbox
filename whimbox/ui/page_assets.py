from whimbox.ui.page import UIPage, TitlePage
from whimbox.ui.ui_assets import *
from whimbox.common.keybind import keybind
import time

start_time = time.time()

page_loading = UIPage(check_icon=IconUILoading)

page_main = UIPage(check_icon=IconPageMainFeature)
page_chat = UIPage(check_icon=IconPageChatFeature)
page_bigmap = UIPage(check_icon=IconUIBigmap)
page_esc = TitlePage("美鸭梨")
page_daily_task = TitlePage("奇想日历")
page_zxxy = UIPage(check_icon=IconZxxyFeature)
page_xhsg = UIPage(check_icon=IconXhsgFeature)
page_dress = UIPage(check_icon=IconWardrobeFeature)
page_ability = UIPage(check_icon=IconAbilityFeature)
page_daily_reward_1 = UIPage(check_icon=IconDailyRewardFeature1)
page_daily_reward_2 = UIPage(check_icon=IconDailyRewardFeature2)
page_shop = UIPage(check_icon=IconShopFeature)
page_gacha = UIPage(check_icon=IconGachaFeature)
page_photo = UIPage(check_icon=IconPhotoFeature)
page_huanjing = TitlePage("幻境挑战")
page_huanjing_jihua = TitlePage("素材激化幻境")
page_huanjing_bless = TitlePage("祝福闪光幻境")
page_huanjing_monster = TitlePage("魔物试炼幻境")
page_huanjing_weekly = TitlePage("心之突破幻境")
page_monthly_pass = TitlePage("奇迹之旅")
page_event = TitlePage("活动大厅")
page_setting = TitlePage("设置")
page_play_music = TitlePage("演奏")

ui_page_dict = {
    "主界面": page_main,
    "聊天": page_chat,
    "地图": page_bigmap,
    "奇想日历": page_daily_task,
    "朝夕心愿": page_zxxy,
    "星海拾光": page_xhsg,
    "美鸭梨": page_esc,
    "拍照": page_photo,
    "幻境挑战": page_huanjing,
    "素材激化幻境": page_huanjing_jihua,
    "祝福闪光幻境": page_huanjing_bless,
    "魔物试炼幻境": page_huanjing_monster,
    "心之突破幻境": page_huanjing_weekly,
    "奇迹之旅": page_monthly_pass,
    "活动大厅": page_event,
    "设置": page_setting,
    "换装": page_dress,
    "能力配置": page_ability,
    "小月卡临取1": page_daily_reward_1,
    "小月卡临取1": page_daily_reward_2,
    "商城": page_shop,
    "共鸣": page_gacha,
    "演奏": page_play_music,
}

page_main.link(keybind.ref("KEYBIND_CHAT"), page_chat)
page_main.link(keybind.ref("KEYBIND_MAP"), page_bigmap)
page_main.link('esc', page_esc)
page_main.link(keybind.ref("KEYBIND_DAILY_TASK"), page_daily_task)
page_main.link(keybind.ref("KEYBIND_DRESS"), page_dress)
page_main.link(keybind.ref("KEYBIND_TAKE_PHOTO"), page_photo)
page_main.link(keybind.ref("KEYBIND_MONTHLY_PASS"), page_monthly_pass)
page_main.link(keybind.ref("KEYBIND_EVENT"), page_event)

page_chat.link(ButtonPageChatClose, page_main)
page_bigmap.link(keybind.ref("KEYBIND_MAP"), page_main)
page_esc.link('esc', page_main)

page_daily_task.link('esc', page_main)
page_daily_task.link(ButtonHuanjingGo, page_huanjing)
page_daily_task.link(ButtonZxxyEntrance, page_zxxy)
page_daily_task.link(ButtonXhsgEntrance, page_xhsg)

page_huanjing.link('esc', page_daily_task)
page_huanjing.link(TextHuanjingJihuaEntrace, page_huanjing_jihua)
page_huanjing.link(TextHuanjingBlessEntrace, page_huanjing_bless)
page_huanjing.link(TextHuanjingMonsterEntrace, page_huanjing_monster)
page_huanjing.link(TextHuanjingBossEntrace, page_huanjing_weekly)

page_huanjing_jihua.link('esc', page_huanjing)
page_huanjing_bless.link('esc', page_huanjing)
page_huanjing_monster.link('esc', page_huanjing)
page_huanjing_weekly.link('esc', page_huanjing)

page_zxxy.link("esc", page_daily_task)
page_xhsg.link("esc", page_daily_task)

page_dress.link("esc", page_main)
page_dress.link("e", page_ability)

page_ability.link("esc", page_main)

page_photo.link("esc", page_main)

page_monthly_pass.link("esc", page_main)

page_event.link('esc', page_main)

page_setting.link('esc', page_esc)

page_daily_reward_1.link(keybind.ref("KEYBIND_INTERACTION"), page_daily_reward_2)
page_daily_reward_2.link(keybind.ref("KEYBIND_INTERACTION"), page_main)

page_shop.link('esc', page_main)
page_gacha.link('esc', page_main)

page_play_music.link('esc', page_main)

logger.info(f"page_assets cost {round(time.time() - start_time, 2)}")
