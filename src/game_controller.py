"""
game_controller.py - 游戏内导航控制
负责:关闭公告、主界面、开始比赛→排位赛S32→排位经理→连续托管→确认匹配。
所有操作基于游戏窗口客户区坐标(左上角 0,0)。
"""
import os
import time

import vision
import window_utils
from logger import get_logger, Logger

log = get_logger()

IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "game")


def _tpl(name):
    return os.path.join(IMG_DIR, name)


class GameController:
    def __init__(self, cfg, hwnd):
        self.cfg = cfg
        self.hwnd = hwnd
        self.groi = cfg.get("game_roi", {})
        self.timing = cfg.get("timing", {})

    def _roi(self, key):
        r = self.groi.get(key, [])
        return r if r else None

    def _wait(self, key):
        return self.timing.get(key, 15)

    # ----------------------------------------------------------
    # 窗口
    # ----------------------------------------------------------
    def activate(self):
        return window_utils.activate_window(self.hwnd)

    def alive(self):
        return window_utils.is_window_alive(self.hwnd)

    # ----------------------------------------------------------
    # 1. 关闭公告弹窗
    # ----------------------------------------------------------
    def close_announcement(self, max_rounds=3):
        """关闭游戏公告弹窗(可能有多个,循环关闭)"""
        log.info("检查并关闭公告弹窗")
        tpl = _tpl("announcement_close.png")
        if not os.path.exists(tpl):
            log.warning("缺少公告关闭按钮模板")
            return False

        for i in range(max_rounds):
            r = vision.find_template(tpl, hwnd=self.hwnd,
                                     roi=self._roi("announcement_close"))
            if r:
                vision.click(r["x"], r["y"], hwnd=self.hwnd)
                log.info(f"已关闭公告弹窗 ({i+1})")
                time.sleep(1.5)
            else:
                log.info("无更多公告弹窗")
                break
        return True

    # ----------------------------------------------------------
    # 2. 等待进入游戏主界面
    # ----------------------------------------------------------
    def wait_main_menu(self, timeout=60):
        """等待游戏主界面出现(检测标志性元素)"""
        log.info(f"等待游戏主界面 超时={timeout}s")
        tpl = _tpl("main_menu_marker.png")  # 主界面标志元素
        if os.path.exists(tpl):
            r = vision.wait_for(tpl, hwnd=self.hwnd, timeout=timeout,
                                roi=self._roi("start_match_button"))
            if r:
                log.info("已进入游戏主界面")
                return True
        # 备用:直接尝试找"开始比赛"按钮
        tpl2 = _tpl("start_match_button.png")
        if os.path.exists(tpl2):
            r = vision.wait_for(tpl2, hwnd=self.hwnd, timeout=timeout)
            if r:
                log.info("已进入游戏主界面(检测到开始比赛)")
                return True
        log.warning("未确认进入主界面")
        return False

    # ----------------------------------------------------------
    # 3. 点击"开始比赛"
    # ----------------------------------------------------------
    def click_start_match(self):
        """点击主界面下方"开始比赛"按钮"""
        log.info("点击开始比赛")
        tpl = _tpl("start_match_button.png")
        if not os.path.exists(tpl):
            log.error("缺少开始比赛按钮模板")
            return False
        if vision.click_template(tpl, hwnd=self.hwnd,
                                 roi=self._roi("start_match_button"),
                                 timeout=self._wait("ui_timeout")):
            log.info("已点击开始比赛")
            time.sleep(1.5)
            return True
        Logger.screenshot("start_match_fail")
        return False

    # ----------------------------------------------------------
    # 4. 点击"排位赛 S32"页签
    # ----------------------------------------------------------
    def click_ranked_tab(self):
        """点击上方排位赛页签"""
        log.info("点击排位赛 S32 页签")
        tpl = _tpl("ranked_tab.png")
        if not os.path.exists(tpl):
            log.error("缺少排位赛页签模板")
            return False
        if vision.click_template(tpl, hwnd=self.hwnd,
                                 roi=self._roi("ranked_tab"),
                                 timeout=self._wait("ui_timeout")):
            log.info("已进入排位赛界面")
            time.sleep(1.5)
            return True
        Logger.screenshot("ranked_tab_fail")
        return False

    # ----------------------------------------------------------
    # 5. 点击"排位经理"
    # ----------------------------------------------------------
    def click_manager_mode(self):
        """点击左侧排位经理入口"""
        log.info("点击排位经理")
        tpl = _tpl("manager_entry.png")
        if not os.path.exists(tpl):
            log.error("缺少排位经理入口模板")
            return False
        if vision.click_template(tpl, hwnd=self.hwnd,
                                 roi=self._roi("manager_entry"),
                                 timeout=self._wait("ui_timeout")):
            log.info("已进入经理模式界面")
            time.sleep(1.5)
            return True
        Logger.screenshot("manager_fail")
        return False

    # ----------------------------------------------------------
    # 6. 选择"连续托管"并进入
    # ----------------------------------------------------------
    def select_continuous_trusteeship(self):
        """选择连续托管选项并点击进入"""
        log.info("选择连续托管")
        # 先确认"连续托管"选项可见
        tpl = _tpl("continuous_trustee_option.png")
        if not os.path.exists(tpl):
            log.error("缺少连续托管选项模板")
            return False
        if not vision.click_template(tpl, hwnd=self.hwnd,
                                     roi=self._roi("continuous_trustee_option"),
                                     timeout=self._wait("ui_timeout")):
            Logger.screenshot("trustee_option_fail")
            return False
        time.sleep(1.0)

        # 点击"进入"按钮
        log.info("点击进入按钮")
        enter_tpl = _tpl("enter_button.png")
        if os.path.exists(enter_tpl):
            if vision.click_template(enter_tpl, hwnd=self.hwnd,
                                     roi=self._roi("enter_button"),
                                     timeout=self._wait("ui_timeout")):
                log.info("已点击进入,开始匹配")
                return True
            Logger.screenshot("enter_fail")
            return False
        else:
            # 某些版本点连续托管即直接进入
            log.info("无独立进入按钮,已直接进入匹配")
            return True

    # ----------------------------------------------------------
    # 7. 确认进入匹配/比赛
    # ----------------------------------------------------------
    def wait_matching_started(self, timeout=30):
        """确认已进入匹配/比赛状态"""
        log.info(f"等待匹配开始 超时={timeout}s")
        tpl = _tpl("matching_indicator.png")
        if os.path.exists(tpl):
            r = vision.wait_for(tpl, hwnd=self.hwnd, timeout=timeout,
                                roi=self._roi("matching_indicator"))
            if r:
                log.info("已进入匹配/比赛状态")
                return True
        # 匹配界面可能无明显标志,等待一段时间默认成功
        log.info("未检测到匹配标志,等待后默认进入托管")
        time.sleep(5)
        return True

    # ----------------------------------------------------------
    # 完整导航流程:主界面 → 连续托管匹配
    # ----------------------------------------------------------
    def navigate_to_trusteeship(self):
        """从主界面导航到连续托管并开始匹配"""
        steps = [
            ("关闭公告", self.close_announcement),
            ("等待主界面", self.wait_main_menu),
            ("开始比赛", self.click_start_match),
            ("排位赛页签", self.click_ranked_tab),
            ("排位经理", self.click_manager_mode),
            ("连续托管", self.select_continuous_trusteeship),
            ("等待匹配", self.wait_matching_started),
        ]
        for name, fn in steps:
            log.info(f"--- 步骤: {name} ---")
            if not fn():
                log.error(f"步骤失败: {name}")
                return False
            delay = self.cfg.get("runtime", {}).get("step_delay", 1.0)
            time.sleep(delay)
        log.info("导航完成:已进入连续托管匹配")
        return True
