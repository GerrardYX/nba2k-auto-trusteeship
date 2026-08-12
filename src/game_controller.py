"""
game_controller.py - 游戏内导航控制
负责:关闭公告、主界面、开始比赛→排位赛S32→排位经理→连续托管→确认匹配。
核心改为 OCR 文字定位,不再依赖模板图片。
所有操作基于游戏窗口客户区坐标(左上角 0,0)。
"""
import os
import time

import vision
import window_utils
from logger import get_logger, Logger

log = get_logger()


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
        for i in range(max_rounds):
            # 公告弹窗的关闭按钮通常是个 × 图标,OCR 可能找不到
            # 尝试:1.找"关闭"文字 2.找×符号 3.按ESC
            r = vision.find_text(self.hwnd, "关闭", timeout=2, partial=True)
            if r:
                vision.click(r['x'], r['y'], hwnd=self.hwnd)
                log.info(f"已关闭公告弹窗 ({i+1})")
                time.sleep(1.5)
                continue
            # 尝试按 ESC 关闭
            vision.press_key("escape")
            time.sleep(1.0)
            # 再查一次
            r = vision.find_text(self.hwnd, "关闭", timeout=2, partial=True)
            if not r:
                log.info("无更多公告弹窗")
                break
        return True

    # ----------------------------------------------------------
    # 2. 等待进入游戏主界面
    # ----------------------------------------------------------
    def wait_main_menu(self, timeout=60):
        """等待游戏主界面出现(检测标志性文字)"""
        log.info(f"等待游戏主界面 超时={timeout}s")
        # 主界面标志:能看到"开始比赛"或"我的球队"
        r = vision.find_any_text(self.hwnd,
                                 ["开始比赛", "我的球队", "球员交易"],
                                 timeout=timeout, partial=True)
        if r:
            log.info(f"已进入游戏主界面 (检测到 {r[0]})")
            return True
        log.warning("未确认进入主界面")
        return False

    # ----------------------------------------------------------
    # 3. 点击"开始比赛"
    # ----------------------------------------------------------
    def click_start_match(self):
        """点击主界面下方"开始比赛"按钮"""
        log.info("点击开始比赛")
        if vision.click_text(self.hwnd, "开始比赛",
                              timeout=self._wait("ui_timeout")):
            log.info("已点击开始比赛")
            time.sleep(1.5)
            return True
        Logger.screenshot("start_match_fail")
        return False

    # ----------------------------------------------------------
    # 4. 点击"排位赛"页签
    # ----------------------------------------------------------
    def click_ranked_tab(self):
        """点击上方排位赛页签"""
        log.info("点击排位赛页签")
        # "排位赛S32" 或 "排位赛"
        if vision.click_text(self.hwnd, "排位赛",
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
        if vision.click_text(self.hwnd, "排位经理",
                              timeout=self._wait("ui_timeout")):
            log.info("已进入经理模式界面")
            time.sleep(1.5)
            return True
        # 备用:只找"经理"
        if vision.click_text(self.hwnd, "经理",
                              timeout=self._wait("ui_timeout")):
            log.info("已进入经理模式界面(模糊匹配)")
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
        # 先确认"连续托管"可见并点击
        if not vision.click_text(self.hwnd, "连续托管",
                                  timeout=self._wait("ui_timeout")):
            log.warning("未找到连续托管,尝试单字'托管'")
            if not vision.click_text(self.hwnd, "托管",
                                      timeout=self._wait("ui_timeout")):
                Logger.screenshot("trustee_option_fail")
                return False
        time.sleep(1.0)

        # 点击"进入"按钮(如果有)
        log.info("点击进入按钮")
        if vision.click_text(self.hwnd, "进入",
                              timeout=self._wait("ui_timeout")):
            log.info("已点击进入,开始匹配")
            return True
        # 某些版本点连续托管即直接进入
        log.info("无独立进入按钮,已直接进入匹配")
        return True

    # ----------------------------------------------------------
    # 7. 确认进入匹配/比赛
    # ----------------------------------------------------------
    def wait_matching_started(self, timeout=30):
        """确认已进入匹配/比赛状态"""
        log.info(f"等待匹配开始 超时={timeout}s")
        # 检测匹配中/比赛中的标志文字
        r = vision.find_any_text(self.hwnd,
                                 ["匹配中", "正在匹配", "比赛中", "第"],
                                 timeout=timeout, partial=True)
        if r:
            log.info(f"已进入匹配/比赛状态 (检测到 {r[0]})")
            return True
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
