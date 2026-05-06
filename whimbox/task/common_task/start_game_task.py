
from whimbox.task.task_template import *
from whimbox.config.config import global_config
from whimbox.common.path_lib import find_game_launcher_folder
from whimbox.common.handle_lib import ProcessHandler
from whimbox.interaction.interaction_core import InteractionBGD
from whimbox.common.handle_lib import HANDLE_OBJ
from whimbox.ui.ui import ui_control
from whimbox.ui.ui_assets import *
from whimbox.interaction.interaction_core import itt
from whimbox.common.logger import logger

import os, time

class StartGameTask(TaskTemplate):
    def __init__(self, session_id):
        super().__init__(session_id=session_id, name="start_game_task")

    @register_step("启动叠纸启动器")
    def step1(self):
        # 判断游戏是否已经在运行
        HANDLE_OBJ.refresh_handle()
        if HANDLE_OBJ.get_handle():
            return
        
        # 判断启动器是否已经在运行
        launcher_handle = ProcessHandler(process_name="xstarter.exe")
        if not launcher_handle.get_handle():
            launcher_path = global_config.get("Whimbox", "launcher_path")
            if launcher_path == "":
                launcher_path = find_game_launcher_folder()
                launcher_path = os.path.join(launcher_path, "launcher.exe")
                if launcher_path == "":
                    self.task_stop("未能自动找到叠纸启动器路径，请手动打开游戏或在奇想盒设置中设置")
                    return
                else:
                    global_config.set("Whimbox", "launcher_path", launcher_path)
                    global_config.save()
            
            if not os.path.exists(launcher_path):
                self.task_stop("叠纸启动器路径不存在，请手动打开游戏或在奇想盒设置中设置")
                return
            if not os.path.isfile(launcher_path) or not os.path.basename(launcher_path).lower() == "launcher.exe":
                self.task_stop("请确认设置的叠纸启动器路径以launcher.exe结尾")
                return

            try:
                os.startfile(launcher_path)
            except Exception as e:
                logger.error(f"打开叠纸启动器失败: {e}")
                self.task_stop(f"打开叠纸启动器失败, 请手动打开游戏")
                return
            
            self.log_to_gui("等待叠纸启动器启动")
            launcher_handle = ProcessHandler(process_name="xstarter.exe")
            while not self.need_stop():
                time.sleep(1)
                if not launcher_handle.get_handle():
                    launcher_handle.refresh_handle()
                else:
                    break

        # 点击启动游戏按钮
        self.log_to_gui("叠纸启动器打开了")
        time.sleep(1) #稍等片刻，避免用户误操作
        launcher_handle.set_foreground()
        launcher_itt = InteractionBGD(launcher_handle)
        retry_time = 10
        while not self.need_stop() and retry_time > 0:
            time.sleep(1)
            text = launcher_itt.ocr_single_line(AreaLaunchButton).lower()
            logger.info(f"启动器按钮文字: {text}")
            if text == "":
                retry_time -= 1
                continue
            elif "运行中" in text:
                self.log_to_gui("游戏可能刚刚关闭，稍等片刻")
                time.sleep(5)
                continue
            elif "更新" in text:
                self.log_to_gui("更新游戏中……")
                launcher_handle.set_foreground()
                launcher_itt.move_and_click(AreaLaunchButton.center_position())
                while not self.need_stop():
                    time.sleep(1)
                    text = launcher_itt.ocr_single_line(AreaLaunchButton)
                    if "启动" in text:
                        self.log_to_gui("更新游戏完成")
                        break
            elif "启动" in text or "start" in text or "啟動" in text:
                launcher_handle.set_foreground()
                launcher_itt.move_and_click(AreaLaunchButton.center_position())
                self.log_to_gui("点击启动游戏按钮")
                break
        if retry_time <= 0:
            self.task_stop("未找到启动游戏按钮")
            return

    @register_step("等待游戏窗口出现……")
    def step2(self):
        retry_time = 20
        while not self.need_stop():
            if HANDLE_OBJ.is_alive():
                if not HANDLE_OBJ.is_foreground():
                    HANDLE_OBJ.set_foreground()
                retry_time -= 1
                shape_ok, width, height = HANDLE_OBJ.check_shape()
                if shape_ok:
                    break
                else:
                    self.log_to_gui(f"请等待游戏分辨率恢复正常……")
                    if retry_time <= 0:
                        self.task_stop(f"启动失败，当前游戏分辨率为:{width}x{height}，奇想盒只支持16:9或16:10的分辨率")
                        return
            else:
                HANDLE_OBJ.refresh_handle()
            time.sleep(5)

    @register_step("进入游戏")
    def step3(self):
        HANDLE_OBJ.set_foreground()
        # 判断游戏是否在加载中
        ui_control.ui_additional()

        # 检测是否在登录界面
        while not self.need_stop():
            time.sleep(3)

            # 可能因为更新，游戏重启了
            if not HANDLE_OBJ.is_alive():
                self.log_to_gui("游戏窗口已关闭")
                return "step2"

            # 检测是否已经进入游戏
            if ui_control.is_valid_page():
                self.update_task_result(status=STATE_TYPE_SUCCESS, message="已成功进入游戏")
                return STEP_NAME_FINISH

            text_box_dict = itt.ocr_and_detect_posi(AreaLoginOCR)
            logger.info(f"登录界面文字: {text_box_dict.keys()}")
            if (("确认" in text_box_dict) or ("同意" in text_box_dict)) and \
                ("退出游戏" not in text_box_dict) and ("账号登出" not in text_box_dict):
                self.log_to_gui("有确认按钮我直接点！")
                AreaLoginOCR.click(target_box=text_box_dict["确认"])
            elif "登录" in text_box_dict:
                self.log_to_gui("有登录按钮我直接点！")
                AreaLoginOCR.click(target_box=text_box_dict["登录"])
            elif "注册\\登录" in text_box_dict:
                self.log_to_gui("有登录按钮我直接点！")
                AreaLoginOCR.click(target_box=text_box_dict["注册\\登录"])
            elif "点击进入游戏" in text_box_dict:
                AreaLoginOCR.click(target_box=text_box_dict["点击进入游戏"])
                break
            else:
                itt.key_press('esc')
        # 不停点击，直到进入loading界面
        while not self.need_stop():
            time.sleep(1)
            itt.move_and_click((100, 100))
            if itt.get_img_existence(IconUILoading):
                break
    
    @register_step("加载游戏中……")
    def step4(self):
        while not self.need_stop():
            time.sleep(1)
            if not itt.get_img_existence(IconUILoading):
                self.log_to_gui("游戏加载完成")
                break
        # 不停点击，尝试点掉月卡界面，直到出现主界面
        self.log_to_gui("检测是否需要领取小月卡")
        times = 0
        while not self.need_stop():
            time.sleep(1)
            # 有些电脑比较卡，会在小月卡出现前卡出主界面特征，所以需要多次验证
            if itt.get_img_existence(IconPageMainFeature):
                times += 1
                if times > 3:
                    self.update_task_result(status=STATE_TYPE_SUCCESS, message="成功进入游戏")
                    break
            else:
                itt.move_and_click((1920/2, 1080/2))

    def handle_finally(self):
        pass

if __name__ == "__main__":
    start_game_task = StartGameTask(session_id="debug")
    start_game_task.task_run()

