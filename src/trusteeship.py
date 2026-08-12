"""
trusteeship.py - 托管监控与收号
负责:2 小时计时、ESC 查看托管状态、读取剩余次数、
     判断是否收号、点"关"停止新匹配、等待当前比赛结束、关闭游戏。
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


class TrusteeshipMonitor:
    def __init__(self, cfg, hwnd):
        self.cfg = cfg
        self.hwnd = hwnd
        self.timing = cfg.get("timing", {})
        self.ts_cfg = cfg.get("trusteeship_status", {})
        self.shutdown_cfg = cfg.get("shutdown", {})
        self.start_time = None

    # ----------------------------------------------------------
    # 计时
    # ----------------------------------------------------------
    def mark_start(self):
        """标记托管开始时间(进入连续托管匹配后调用)"""
        self.start_time = time.time()
        log.info(f"⏱ 托管计时开始: {time.strftime('%H:%M:%S', time.localtime(self.start_time))}")

    def elapsed(self):
        if not self.start_time:
            return 0
        return time.time() - self.start_time

    def wait_until_2h(self):
        """
        等待托管满 2 小时。
        期间每隔一段时间做存活检查(游戏窗口还在)。
        """
        duration = self.timing.get("trusteeship_duration", 7200)
        log.info(f"⏱ 等待托管满 {duration}s ({duration//3600}h{(duration%3600)//60}m)")
        check_interval = 60  # 每 60s 检查一次游戏是否还活着
        while self.elapsed() < duration:
            remaining = duration - self.elapsed()
            if not window_utils.is_window_alive(self.hwnd):
                log.error("游戏窗口消失!可能崩溃或被关闭")
                return False
            # 每 10 分钟打印一次进度
            mins_done = int(self.elapsed() // 60)
            if mins_done % 10 == 0 and mins_done > 0:
                mins_left = int(remaining // 60)
                log.info(f"⏱ 托管进行中: 已 {mins_done} 分钟,剩余 {mins_left} 分钟")
            time.sleep(min(check_interval, remaining))
        log.info("⏱ 托管已满 2 小时,开始检查剩余次数")
        return True

    # ----------------------------------------------------------
    # ESC 查看托管状态
    # ----------------------------------------------------------
    def open_esc_menu(self):
        """按 ESC 打开系统菜单(托管状态界面)"""
        log.info("按 ESC 查看托管状态")
        window_utils.activate_window(self.hwnd)
        time.sleep(0.5)
        vision.press_key("escape")
        time.sleep(1.5)  # 等待菜单弹出
        return True

    def close_esc_menu(self):
        """关闭 ESC 菜单(再按一次 ESC)"""
        log.info("关闭 ESC 菜单")
        vision.press_key("escape")
        time.sleep(1.0)

    # ----------------------------------------------------------
    # 读取剩余托管次数
    # ----------------------------------------------------------
    def read_remaining(self):
        """读取剩余托管次数,返回 int 或 None"""
        return vision.read_remaining_trusteeship(self.hwnd, self.cfg)

    # ----------------------------------------------------------
    # 判断是否收号
    # ----------------------------------------------------------
    def should_stop(self):
        """
        检查剩余托管次数是否 <= 阈值。
        返回 True 表示应该收号。
        """
        threshold = self.ts_cfg.get("stop_threshold", 14)
        remaining = self.read_remaining()
        if remaining is None:
            log.warning("无法读取剩余次数,默认继续托管(稍后重试)")
            return False
        if remaining <= threshold:
            log.info(f"剩余 {remaining} <= {threshold},准备收号")
            return True
        log.info(f"剩余 {remaining} > {threshold},继续托管")
        return False

    # ----------------------------------------------------------
    # 点"关"停止新匹配
    # ----------------------------------------------------------
    def stop_new_matches(self):
        """点击连续托管右侧的"关/OFF"按钮,停止新匹配"""
        log.info("点击'关'按钮停止新匹配")
        # 优先 OCR 找"关"字
        r = vision.find_text(self.hwnd, "关", timeout=8, partial=False)
        if r:
            vision.click(r['x'], r['y'], hwnd=self.hwnd)
            log.info("已点击关按钮,停止新匹配")
            time.sleep(1.0)
            return True
        # 备用:找"OFF"
        if vision.click_text(self.hwnd, "OFF", timeout=3, partial=True):
            log.info("已点击OFF按钮")
            time.sleep(1.0)
            return True
        # 备用:找"关闭"
        if vision.click_text(self.hwnd, "关闭", timeout=3, partial=True):
            log.info("已点击关闭")
            time.sleep(1.0)
            return True
        log.error("关按钮未找到")
        Logger.screenshot("off_button_fail")
        return False

    # ----------------------------------------------------------
    # 等待当前比赛结束(双保险)
    # ----------------------------------------------------------
    def wait_match_end(self):
        """
        等待当前这场比赛打完。
        双保险判定(OCR):
          ① 结算页标志文字出现("当家球星"、"胜利"、"失败"、"结算")
          ② 或回到主菜单("开始比赛"、"我的球队")出现
        """
        max_wait = self.timing.get("match_end_max_wait", 1800)
        poll = self.timing.get("match_end_poll_interval", 30)
        log.info(f"等待当前比赛结束 超时={max_wait}s 轮询={poll}s")

        # 先关闭 ESC 菜单(点了关之后菜单可能还开着)
        self.close_esc_menu()
        time.sleep(2)

        # 结算页标志文字 + 主菜单标志文字
        end_texts = ["当家球星", "胜利", "失败", "结算", "比赛结束"]
        menu_texts = ["开始比赛", "我的球队", "球员交易"]

        start = time.time()
        last_log = 0
        while time.time() - start < max_wait:
            if not window_utils.is_window_alive(self.hwnd):
                log.warning("游戏窗口消失")
                return True
            # 检测结算页(OCR)
            r = vision.find_any_text(self.hwnd, end_texts, timeout=0,
                                     partial=True)
            if r:
                log.info(f"检测到比赛结算页 (OCR: {r[0]})")
                return True
            # 检测主菜单(OCR)
            r = vision.find_any_text(self.hwnd, menu_texts, timeout=0,
                                    partial=True)
            if r:
                log.info(f"检测到回到主菜单 (OCR: {r[0]})")
                return True
            # 进度日志
            if time.time() - last_log > 60:
                elapsed = int((time.time() - start) // 60)
                log.info(f"⏳ 等待比赛结束: 已 {elapsed} 分钟")
                last_log = time.time()
            time.sleep(poll)

        log.warning("等待比赛结束超时,将强制关闭游戏")
        return False

    # ----------------------------------------------------------
    # 关闭游戏
    # ----------------------------------------------------------
    def close_game(self):
        """关闭游戏(Alt+F4 + 确认弹窗)"""
        method = self.shutdown_cfg.get("method", "alt_f4")
        log.info(f"关闭游戏 方式={method}")

        if not window_utils.is_window_alive(self.hwnd):
            log.info("游戏已不在运行")
            return True

        window_utils.activate_window(self.hwnd)
        time.sleep(0.5)

        if method == "alt_f4":
            vision.hotkey("alt", "f4")
            time.sleep(2)
            # 处理"是否退出"确认弹窗
            if self.shutdown_cfg.get("confirm_dialog", True):
                self._confirm_exit()
        elif method == "taskkill":
            self._taskkill()
        elif method == "window_close":
            vision.hotkey("alt", "f4")  # 退化为 alt+f4
            time.sleep(2)
            if self.shutdown_cfg.get("confirm_dialog", True):
                self._confirm_exit()

        # 等待窗口关闭
        for _ in range(15):
            if not window_utils.is_window_alive(self.hwnd):
                log.info("游戏已关闭")
                return True
            time.sleep(1)
        # 强制结束
        log.warning("游戏未正常关闭,强制 taskkill")
        self._taskkill()
        time.sleep(2)
        return not window_utils.is_window_alive(self.hwnd)

    def _confirm_exit(self):
        """点击退出确认弹窗的"是"按钮"""
        log.info("处理退出确认弹窗")
        tpl = _tpl("confirm_yes.png")
        if os.path.exists(tpl):
            roi = self.shutdown_cfg.get("confirm_yes_roi", []) or None
            if vision.click_template(tpl, hwnd=self.hwnd, roi=roi, timeout=8):
                log.info("已点击确认退出")
                time.sleep(1.5)
                return True
        # 备用:按回车(默认聚焦"是")
        log.info("尝试按回车确认退出")
        vision.press_key("enter")
        time.sleep(1.5)
        return True

    def _taskkill(self):
        """强制结束游戏进程"""
        import subprocess
        try:
            # 通过窗口获取进程 ID
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(self.hwnd)
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True)
            log.info(f"已 taskkill PID={pid}")
        except Exception as e:
            log.warning(f"taskkill 失败: {e}")

    # ----------------------------------------------------------
    # 收号完整流程
    # ----------------------------------------------------------
    def shutdown_account(self):
        """
        收号完整流程:
        1. ESC 查看状态 → 读次数
        2. 若 <= 阈值: 点关 → 等比赛结束 → 关游戏
        3. 若 > 阈值: 等 10 分钟后复查,循环直到 <= 阈值
        返回 True 表示成功收号(游戏已关)。
        """
        recheck = self.timing.get("recheck_interval", 600)
        max_recheck_rounds = 12  # 最多复查 12 次(2 小时兜底)

        for round_n in range(1, max_recheck_rounds + 1):
            log.info(f"━━━ 收号检查 第 {round_n} 轮 ━━━")
            # 打开 ESC 菜单读次数
            self.open_esc_menu()
            time.sleep(1.0)
            remaining = self.read_remaining()

            if remaining is None:
                log.warning("读取次数失败,关闭菜单后重试")
                self.close_esc_menu()
                time.sleep(recheck)
                continue

            threshold = self.ts_cfg.get("stop_threshold", 14)
            if remaining <= threshold:
                # 满足收号条件
                log.info(f"剩余 {remaining} <= {threshold},开始收号")
                if not self.stop_new_matches():
                    log.warning("点关失败,关闭菜单重试")
                    self.close_esc_menu()
                    time.sleep(5)
                    continue
                # 关菜单,等比赛结束
                if not self.wait_match_end():
                    log.warning("等待比赛结束超时")
                # 关闭游戏
                self.close_game()
                return True
            else:
                # 继续托管,10 分钟后复查
                log.info(f"剩余 {remaining} > {threshold},继续托管,"
                         f"{recheck}s 后复查")
                self.close_esc_menu()
                time.sleep(recheck)

        log.error("收号复查超过最大轮次,强制关闭游戏")
        self.close_game()
        return True

    # ----------------------------------------------------------
    # 完整托管监控流程
    # ----------------------------------------------------------
    def run(self):
        """
        完整托管监控:2h 计时 → 检查 → 收号。
        返回 True 表示该账号托管并收号完成。
        """
        # 1. 标记开始
        self.mark_start()

        # 2. 等待 2 小时
        if not self.wait_until_2h():
            log.error("托管期间游戏异常,提前收号")
            self.close_game()
            return False

        # 3. 收号流程(含 10 分钟复查循环)
        return self.shutdown_account()
