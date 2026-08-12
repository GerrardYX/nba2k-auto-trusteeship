"""
wegame_controller.py - WeGame 客户端控制
流程:登录界面选账号 → 登录 → 选 NBA2K → 启动游戏
       关游戏后 → 头像 → 切换账号 → 回登录界面 → 下一个账号
核心用 OCR 文字定位,不依赖模板图片。
"""
import os
import time

import vision
import window_utils
from logger import get_logger, Logger

log = get_logger()


class WeGameController:
    def __init__(self, cfg):
        self.cfg = cfg
        self.wg_cfg = cfg.get("wegame_window", {})
        self.acc_cfg = cfg.get("account_list", {})
        self.hwnd = None

    # ----------------------------------------------------------
    # 窗口管理
    # ----------------------------------------------------------
    def find(self):
        kws = self.wg_cfg.get("title_keywords", ["WeGame"])
        self.hwnd = window_utils.find_window(kws)
        if self.hwnd:
            log.info(f"WeGame 窗口已找到 (hwnd={self.hwnd})")
        else:
            log.warning("未找到 WeGame 窗口")
        return self.hwnd

    def activate(self):
        if not self.hwnd:
            self.find()
        if self.hwnd:
            window_utils.activate_window(self.hwnd)
            time.sleep(1.0)
            return True
        return False

    # ----------------------------------------------------------
    # 判断当前在哪个界面
    # ----------------------------------------------------------
    def is_login_page(self):
        """判断是否在 WeGame 登录界面"""
        # 登录界面有"扫码登录"或"自动登录"等文字
        r = vision.find_any_text(self.hwnd,
                                 ["扫码登录", "自动登录", "QQ扫码"],
                                 timeout=3, partial=True)
        if r:
            log.info(f"当前在 WeGame 登录界面 (检测到 {r[0]})")
            return True
        return False

    def is_main_page(self):
        """判断是否在 WeGame 主界面(已登录)"""
        r = vision.find_text(self.hwnd, "启动", timeout=3, partial=True)
        if r:
            log.info("当前在 WeGame 主界面(已登录)")
            return True
        return False

    # ----------------------------------------------------------
    # 登录界面:选账号
    # ----------------------------------------------------------
    def select_account_on_login(self, account_index):
        """
        在 WeGame 登录界面选择第 N 个账号。
        1. 找账号切换箭头/区域,点击展开账号列表
        2. 在列表中选第 N 个(需滚动选第5/6个)
        3. 等待自动登录
        """
        if not self.activate():
            return False

        log.info(f"登录界面:选择账号 #{account_index}")

        # 1. 展开账号列表(如果没展开)
        self._expand_account_list()

        # 2. 选择账号
        if not self._click_account_in_list(account_index):
            return False

        # 3. 等待登录完成
        return self.wait_account_logged_in(timeout=40)

    def _expand_account_list(self):
        """展开账号列表(找切换箭头或已展开的列表)"""
        # 先检查账号列表是否已展开(能否直接看到账号ID)
        detected = self._detect_account_list()
        if detected:
            log.info("账号列表已展开")
            return True

        log.info("账号列表未展开,尝试展开...")
        # 找账号切换箭头——可能是图标,OCR找不到
        # 尝试1:找"切换账号"文字
        if vision.click_text(self.hwnd, "切换账号", timeout=3):
            log.info("点击了切换账号")
            time.sleep(1.5)
            return True

        # 尝试2:找"账号"文字
        if vision.click_text(self.hwnd, "账号", timeout=2):
            log.info("点击了账号切换")
            time.sleep(1.5)
            return True

        # 尝试3:登录界面的账号切换箭头通常在账号头像旁边
        # 找已登录账号的头像/名字区域,点击它展开列表
        # 用 OCR 找 QQ 号(当前登录的账号)
        r = vision.find_text(self.hwnd, "3797", timeout=3, partial=True)
        if r:
            # 点击这个账号附近,展开列表
            vision.click(r['x'], r['y'], hwnd=self.hwnd)
            log.info(f"点击当前账号展开列表 ({r['x']},{r['y']})")
            time.sleep(1.5)
            return True

        # 尝试4:在登录界面中央偏上区域点击(账号切换箭头常见位置)
        rect = window_utils.get_client_rect_screen(self.hwnd)
        if rect:
            w = rect[2]
            h = rect[3]
            # 账号切换区域通常在中央偏上
            vision.click(w // 2, int(h * 0.35), hwnd=self.hwnd)
            log.info(f"尝试点击中央偏上区域 ({w//2},{int(h*0.35)})")
            time.sleep(1.5)
            return True

        log.warning("无法确定账号切换箭头位置")
        return True  # 继续尝试选账号

    # ----------------------------------------------------------
    # 账号列表检测和选择
    # ----------------------------------------------------------
    def _detect_account_list(self):
        """
        OCR 检测账号列表,找账号ID(QQ号)。
        返回 [(id, x, y), ...] 或 None。
        """
        try:
            result = vision.grab_window(self.hwnd)
            if not result or result[0] is None:
                return None
            screen, _ = result
            import cv2
            import pytesseract
            gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(
                gray, lang='eng',
                config='--psm 11 -c tessedit_char_whitelist=0123456789',
                output_type=pytesseract.Output.DICT)
            accounts = []
            for i in range(len(data['text'])):
                t = data['text'][i].strip()
                if t and t.isdigit() and len(t) >= 6:
                    cx = data['left'][i] + data['width'][i] // 2
                    cy = data['top'][i] + data['height'][i] // 2
                    accounts.append({'id': t, 'x': cx, 'y': cy,
                                     'left': data['left'][i],
                                     'top': data['top'][i],
                                     'w': data['width'][i],
                                     'h': data['height'][i]})
            if accounts:
                accounts.sort(key=lambda a: a['y'])
                log.info(f"检测到 {len(accounts)} 个账号: {[a['id'] for a in accounts]}")
                return accounts
            return None
        except Exception as e:
            log.warning(f"检测账号列表失败: {e}")
            return None

    def _click_account_in_list(self, index):
        """在账号列表中点击第 index 个(1~6)"""
        visible_count = 4
        scroll_steps = self.acc_cfg.get("scroll_steps_for_tail", 3)

        accounts = self._detect_account_list()
        if not accounts:
            log.error("未检测到账号列表")
            Logger.screenshot("account_list_fail")
            return False

        if index <= len(accounts):
            # 直接点第 index 个
            acc = accounts[index - 1]
            log.info(f"点击账号 #{index}: {acc['id']} ({acc['x']},{acc['y']})")
            vision.click(acc['x'], acc['y'], hwnd=self.hwnd)
            time.sleep(2)
            return True
        elif index > visible_count:
            # 需要滚动
            log.info(f"账号 #{index} 在列表下方,滚动后选择")
            import pyautogui
            # 在列表中央滚动
            mid_y = accounts[len(accounts)//2]['y']
            mid_x = accounts[len(accounts)//2]['x']
            vision.click(mid_x, mid_y, hwnd=self.hwnd)
            time.sleep(0.5)
            for _ in range(scroll_steps):
                if not vision.VisionConfig.dry_run:
                    pyautogui.scroll(-3)
                else:
                    log.info("[DRY-RUN] 向下滚动")
                time.sleep(0.3)
            time.sleep(0.5)
            # 重新检测
            accounts = self._detect_account_list()
            if accounts and index <= len(accounts):
                acc = accounts[index - 1]
                log.info(f"滚动后点击账号 #{index}: {acc['id']}")
                vision.click(acc['x'], acc['y'], hwnd=self.hwnd)
                time.sleep(2)
                return True
            log.error("滚动后仍未找到目标账号")
            return False
        return False

    # ----------------------------------------------------------
    # 已登录:切换账号(回登录界面)
    # ----------------------------------------------------------
    def switch_to_account(self, account_index):
        """
        从已登录的 WeGame 主界面切换到指定账号。
        流程:点头像 → 切换账号 → 回登录界面 → 选账号
        """
        if not self.activate():
            return False

        log.info(f"切换到账号 #{account_index}")

        # 判断当前在哪个界面
        if self.is_login_page():
            # 已在登录界面,直接选账号
            log.info("已在登录界面,直接选账号")
            return self.select_account_on_login(account_index)

        # 在主界面,需要先回登录界面
        # 1. 点击右上角头像
        log.info("点击右上角头像展开菜单")
        rect = window_utils.get_client_rect_screen(self.hwnd)
        if rect:
            w = rect[2]
            vision.click(w - 30, 20, hwnd=self.hwnd)
            time.sleep(1.0)

        # 2. 点击"切换账号"
        log.info("点击切换账号")
        if not vision.click_text(self.hwnd, "切换账号", timeout=8):
            # 备用:只找"切换"
            if not vision.click_text(self.hwnd, "切换", timeout=3):
                log.error("切换账号菜单项未找到")
                Logger.screenshot("switch_account_fail")
                return False
        time.sleep(2)

        # 3. 现在应该回到登录界面,选账号
        return self.select_account_on_login(account_index)

    # ----------------------------------------------------------
    # 等待登录完成
    # ----------------------------------------------------------
    def wait_account_logged_in(self, timeout=40):
        """等待 WeGame 登录完成(检测主页"启动"按钮出现)"""
        log.info(f"等待账号登录完成 超时={timeout}s")
        start = time.time()
        while time.time() - start < timeout:
            if vision.find_text(self.hwnd, "启动", timeout=0, partial=True):
                log.info("账号已登录,WeGame 主页就绪")
                return True
            time.sleep(2)
        log.warning("等待登录超时")
        Logger.screenshot("login_timeout")
        return False

    # ----------------------------------------------------------
    # 选游戏 + 启动
    # ----------------------------------------------------------
    def select_game(self):
        """在 WeGame 主界面选择 NBA2K Online2"""
        if not self.activate():
            return False
        log.info("选择 NBA2K Online2 游戏")

        # 方法1:OCR 找 NBA2K 文字
        r = vision.find_any_text(self.hwnd,
                                 ["NBA2K", "NBA 2K", "2KOL", "2KOnline"],
                                 timeout=8, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            log.info(f"已点击 NBA2K (OCR: {r[0]})")
            time.sleep(1.5)
            return True

        # 方法2:展开"我的游戏"后找
        log.info("尝试展开我的游戏")
        vision.click_text(self.hwnd, "我的游戏", timeout=5)
        time.sleep(1.0)
        r = vision.find_any_text(self.hwnd,
                                 ["NBA2K", "2KOL", "2K"],
                                 timeout=5, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            log.info("已点击 NBA2K")
            time.sleep(1.5)
            return True

        log.error("无法定位 NBA2K")
        Logger.screenshot("select_game_fail")
        return False

    def start_game(self):
        """点击启动按钮,返回游戏窗口 hwnd"""
        if not self.activate():
            return None
        log.info("点击启动游戏按钮")

        if not vision.click_text(self.hwnd, "启动", timeout=10):
            if not vision.click_text(self.hwnd, "开始游戏", timeout=5):
                log.error("启动按钮未找到")
                Logger.screenshot("start_button_fail")
                return None

        log.info("等待游戏窗口启动...")
        gw_cfg = self.cfg.get("game_window", {})
        kws = gw_cfg.get("title_keywords", ["NBA2K", "2K"])
        timeout = self.cfg.get("timing", {}).get("game_launch_timeout", 120)

        start = time.time()
        game_hwnd = None
        while time.time() - start < timeout:
            game_hwnd = window_utils.find_window(kws)
            if game_hwnd:
                log.info(f"游戏窗口已启动 (hwnd={game_hwnd})")
                break
            time.sleep(2)

        if not game_hwnd:
            log.error("游戏启动超时")
            Logger.screenshot("game_launch_timeout")
            return None

        if gw_cfg.get("force_position", True):
            ts = gw_cfg.get("target_client_size", [1920, 1080])
            time.sleep(3)
            window_utils.move_window_top_left(game_hwnd, ts[0], ts[1])
        return game_hwnd
