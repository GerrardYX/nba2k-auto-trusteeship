"""
wegame_controller.py - WeGame 客户端控制
负责:定位 WeGame 窗口、选择 NBA2K、启动游戏、切换账号。
核心改为 OCR 文字定位 + 账号列表自动检测,不依赖模板图片。
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
        """查找 WeGame 窗口"""
        kws = self.wg_cfg.get("title_keywords", ["WeGame"])
        self.hwnd = window_utils.find_window(kws)
        if self.hwnd:
            log.info(f"WeGame 窗口已找到 (hwnd={self.hwnd})")
        else:
            log.warning("未找到 WeGame 窗口")
        return self.hwnd

    def activate(self):
        """激活 WeGame 到前台"""
        if not self.hwnd:
            self.find()
        if self.hwnd:
            window_utils.activate_window(self.hwnd)
            time.sleep(1.0)
            return True
        return False

    # ----------------------------------------------------------
    # 选游戏 + 启动
    # ----------------------------------------------------------
    def select_game(self):
        """
        在 WeGame 中选择 NBA2K Online2。
        优先用 OCR 找"NBA2K"文字;找不到则找游戏列表区域点击。
        """
        if not self.activate():
            return False
        log.info("选择 NBA2K Online2 游戏")

        # 方法1:OCR 找 "NBA2K" 或 "2K" 文字
        r = vision.find_any_text(self.hwnd,
                                 ["NBA2K", "NBA 2K", "2KOL", "2KOnline"],
                                 timeout=8, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            log.info(f"已点击 NBA2K (OCR匹配: {r[0]})")
            time.sleep(1.5)
            return True

        # 方法2:在左侧菜单找"我的游戏"展开后找
        log.info("OCR 未直接找到 NBA2K,尝试展开我的游戏")
        vision.click_text(self.hwnd, "我的游戏", timeout=5)
        time.sleep(1.0)
        r = vision.find_any_text(self.hwnd,
                                 ["NBA2K", "2KOL", "2K"],
                                 timeout=5, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            log.info(f"已点击 NBA2K (展开后匹配)")
            time.sleep(1.5)
            return True

        log.error("无法定位 NBA2K 图标")
        Logger.screenshot("select_game_fail")
        return False

    def start_game(self):
        """
        点击"启动"按钮启动游戏。
        返回游戏窗口 hwnd 或 None。
        """
        if not self.activate():
            return None
        log.info("点击启动游戏按钮")

        # OCR 找"启动"文字
        if not vision.click_text(self.hwnd, "启动", timeout=10):
            # 备用:找"开始游戏"
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

        # 固定窗口位置
        if gw_cfg.get("force_position", True):
            ts = gw_cfg.get("target_client_size", [1920, 1080])
            time.sleep(3)
            window_utils.move_window_top_left(game_hwnd, ts[0], ts[1])
        return game_hwnd

    # ----------------------------------------------------------
    # 切换账号
    # ----------------------------------------------------------
    def switch_to_account(self, account_index):
        """
        切换到指定序号的账号(1~6)。
        流程:点右上角头像 → 点"切换账号" → 在账号列表选第 N 个。
        """
        if not self.activate():
            return False

        log.info(f"切换到账号 #{account_index}")

        # 1. 点击右上角头像(展开菜单)
        #    头像是图标不是文字,先尝试找已知文字"切换账号"附近点击
        #    或找右上角区域点击
        if not self._click_avatar_menu():
            return False

        # 2. 点击"切换账号"菜单项
        if not self._click_switch_account_item():
            return False

        time.sleep(2)
        # 3. 在账号列表中选择
        return self._select_account_from_list(account_index)

    def _click_avatar_menu(self):
        """点击右上角头像展开菜单"""
        log.info("点击头像菜单")
        # 先试找"切换账号"——如果已经能看到说明菜单已展开
        r = vision.find_text(self.hwnd, "切换账号", timeout=2)
        if r:
            log.info("菜单已展开(直接看到切换账号)")
            return True
        # 头像是图标,OCR找不到。用窗口右上角点击
        rect = window_utils.get_client_rect_screen(self.hwnd)
        if rect:
            x, y, w, h = rect
            # 右上角偏内一点
            vision.click(w - 30, 20, hwnd=self.hwnd)
            log.info(f"已点击右上角头像区域 ({w-30},{20})")
            time.sleep(1.0)
            return True
        log.error("无法定位头像区域")
        return False

    def _click_switch_account_item(self):
        """点击"切换账号"菜单项"""
        log.info("点击切换账号")
        if vision.click_text(self.hwnd, "切换账号", timeout=8):
            log.info("已点击切换账号")
            time.sleep(1.5)
            return True
        # 备用:只找"切换"
        if vision.click_text(self.hwnd, "切换", timeout=5):
            log.info("已点击切换(模糊匹配)")
            time.sleep(1.5)
            return True
        log.error("切换账号菜单项未找到")
        Logger.screenshot("switch_account_fail")
        return False

    def _select_account_from_list(self, index):
        """
        在账号切换列表中选第 index 个(1~6)。
        自动检测列表位置:OCR 找账号 ID(QQ号),定位每个条目坐标。
        """
        visible_count = 4
        scroll_steps = self.acc_cfg.get("scroll_steps_for_tail", 3)

        # 自动检测账号列表
        log.info("自动检测账号列表位置...")
        detected = self._detect_account_list()
        if not detected:
            log.error("无法自动检测账号列表")
            Logger.screenshot("account_list_detect_fail")
            return False

        first_y, item_h, list_roi = detected
        cx = (list_roi[0] + list_roi[2]) // 2
        log.info(f"列表: first_y={first_y} item_h={item_h} center_x={cx}")

        if index <= visible_count:
            y = first_y + (index - 1) * item_h
            log.info(f"点击账号 #{index} 位置 ({cx},{y})")
            vision.click(cx, y, hwnd=self.hwnd)
            time.sleep(2)
            return True
        else:
            log.info(f"账号 #{index} 在列表下方,滚动后选择")
            cy = (list_roi[1] + list_roi[3]) // 2
            import pyautogui
            vision.click(cx, cy, hwnd=self.hwnd)
            time.sleep(0.5)
            for _ in range(scroll_steps):
                if not vision.VisionConfig.dry_run:
                    pyautogui.scroll(-3)
                else:
                    log.info("[DRY-RUN] 向下滚动")
                time.sleep(0.3)
            time.sleep(0.5)
            # 滚动后重新检测
            detected2 = self._detect_account_list()
            if detected2:
                first_y, item_h, list_roi = detected2
                cx = (list_roi[0] + list_roi[2]) // 2
            visible_index = index - scroll_steps
            y = first_y + (visible_index - 1) * item_h
            log.info(f"滚动后点击账号 #{index} 位置 ({cx},{y})")
            vision.click(cx, y, hwnd=self.hwnd)
            time.sleep(2)
            return True

    def _detect_account_list(self):
        """
        自动检测账号列表:截图 OCR 找账号 ID(QQ号)。
        返回 (first_y, item_height, list_roi) 或 None。
        """
        try:
            result = vision.grab_window(self.hwnd)
            if not result or result[0] is None:
                return None
            screen, _ = result
            gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            data = vision.pytesseract.image_to_data(
                gray, lang='eng',
                config='--psm 11 -c tessedit_char_whitelist=0123456789',
                output_type=vision.pytesseract.Output.DICT)
            accounts = []
            for i in range(len(data['text'])):
                t = data['text'][i].strip()
                if t and t.isdigit() and len(t) >= 6:
                    cy = data['top'][i] + data['height'][i] // 2
                    accounts.append({
                        'text': t, 'left': data['left'][i],
                        'top': data['top'][i], 'w': data['width'][i],
                        'h': data['height'][i], 'cy': cy
                    })
            if not accounts:
                log.warning("OCR 未找到账号 ID")
                return None
            accounts.sort(key=lambda a: a['cy'])
            y_vals = [a['cy'] for a in accounts]
            first_y = y_vals[0]
            if len(y_vals) >= 2:
                gaps = [y_vals[i+1] - y_vals[i] for i in range(len(y_vals)-1)]
                item_h = int(sum(gaps) / len(gaps))
            else:
                item_h = 80
            list_x0 = min(a['left'] for a in accounts) - 60
            list_x1 = max(a['left'] + a['w'] for a in accounts) + 60
            list_y0 = first_y - item_h // 2
            list_y1 = y_vals[-1] + item_h // 2
            log.info(f"检测到 {len(accounts)} 个账号: {[a['text'] for a in accounts]}")
            return (first_y, item_h, [list_x0, list_y0, list_x1, list_y1])
        except Exception as e:
            log.warning(f"自动检测账号列表失败: {e}")
            return None

    # ----------------------------------------------------------
    # 确认账号已登录
    # ----------------------------------------------------------
    def wait_account_logged_in(self, timeout=30):
        """等待 WeGame 显示已登录状态(检测"启动"按钮出现)"""
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
