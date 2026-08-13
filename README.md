![logo](/docs/logo.png)
~~不会画画，先放个红温星在这里凑合一下~~
# Whimbox · 奇想盒
Whimbox，基于大语言模型和图像识别技术的AI智能体，辅助你游玩无限暖暖！\
想了解更多？请前往[奇想盒主页](https://nikkigallery.vip/whimbox/)

## 如何运行
❗奇想盒2.0已经上线啦，请通过奇想盒app运行，[奇想盒app项目地址](https://github.com/nikkigallery/whimbox_app)

❗本项目为奇想盒后端，已不再提供UI界面，仅负责rpc服务、大模型调用、工具调用

✅ 如果你想用命令行的方式运行一条龙，你可以这样做
1. 先保证通过奇想盒app能够正常运行一条龙
2. 在一条龙配置中勾选“启动奇想盒时，自动运行一条龙”
3. 通过命令行启动`whimbox_app.exe`

✅ 如果你想一条龙运行完成后自动关闭游戏和奇想盒：
1. 在一条龙配置中，勾选“一条龙结束后，关闭游戏和奇想盒”


## 如何开发
1. 本项目仅支持python3.12
2. 等我梳理项目框架...


## 已有功能
* 每日任务
    * 美鸭梨挖掘
    * 素材激化幻境
    * 闪光祝福幻境
    * 魔物试炼幻境
    * 周本
    * 完成朝夕心愿
    * 完成星海拾光
    * 收集星光结晶
    * 领取大月卡
    * 奇迹之冠巅峰赛
* 自动小功能
    * 自动对话、自动采集、自动钓鱼、自动清洁跳过
* 自动跑图
    * 跑图路线录制、编辑
    * 自动跑图（暂时只支持大世界和星海）
    * 自动采集、捕虫、清洁、钓鱼
* 录制宏
    * 录制操作和播放操作（不支持视角转动的操作）
* 自动弹琴
    * MIDI乐谱转奇想盒脚本
* AI对话
    * 通过自然语言让奇想盒执行上述功能
    * 一定程度上支持SKILL
    * 通过微信远程控制奇想盒

## 未来计划
1. 大模型能力扩展：脚本运行异常，大模型接管进行纠错
2. 悬浮窗显示网页，方便视频跟跑和查看美鸭梨地图

## 注意事项
* Whimbox不会修改游戏文件、读写游戏内存，只会截图和模拟鼠标键盘，理论上不会被封号。但游戏的用户条款非常完善，涵盖了所有可能出现的情况。所以使用Whimbox导致的一切后果请自行承担。
* 由于游戏本身已经消耗PC的大量性能，图像识别还会额外消耗性能，所以目前仅支持中高配PC运行，功能完善后会开发云游戏版本。
* Whimbox目前仅支持标准16:9分辨率运行的游戏。

## 致谢
感谢各个大世界游戏开源项目的先行者，供Whimbox学习参考。
* [原神小助手·GIA](https://github.com/infstellar/genshin_impact_assistant)
* [更好的原神·BetterGI](https://github.com/babalae/better-genshin-impact)

感谢openclaw和nanobot项目，为奇想盒的AI注入灵魂
* [openclaw](https://github.com/openclaw/openclaw)
* [nanobot](https://github.com/HKUDS/nanobot)

感谢chatgpt、cursor、claude、codex等各种AI模型和AI编程工具

## 加入开发
项目还有大量功能需要开发和适配。如果你对此感兴趣，欢迎加入一起研究。开发Q群：821908945。

### 项目结构
```
Whinbox/
├── whimbox/                        
│   ├── ability/                  # 能力切换模块
│   ├── action/                   # 动作模块（拾取、钓鱼、战斗等等）
│   ├── agent_workspace/          # 大模型上下文管理
│   ├── api/                      # ocr，yolo等第三方模型
│   ├── assets/                   # 地图、特征截图、配置文件、文件模板等资源
│   ├── common/                   # 公共模块（日志、工具等等）
│   ├── config/                   # 全局配置模块
│   ├── dev_tool/                 # 开发工具
│   ├── interaction/              # 交互核心模块（截图、操作）
│   ├── map/                      # 地图模块（小地图识别，大地图操作）
│   ├── task/                     # 任务模块（各种功能脚本，供agent调用）
│   ├── ui/                       # 游戏UI的识别和操作
│   ├── view_and_move/            # 视角和移动模块
│   ├── main.py                   # 程序入口
│   ├── agent.py                  # 大模型agent
│   └── rpc_server.py             # 与前端通信的rpc服务器
├── configs/                      # 配置文件
│   ├── agent_workspace/          # 存放agent的记忆
│   └── config.json               # 项目的配置文件
├── scripts/                      # 自动跑图和宏的脚本仓库
├── logs/                         # 日志文件
└── build.bat                     # 一键打包脚本
```
