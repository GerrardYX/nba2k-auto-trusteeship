"""
wegame_controller.py - WeGame 客户端控制
负责:定位 WeGame 窗口、选择 NBA2K、启动游戏、切换账号。
"""
import os
import time

import vision
import window_utils
from logger import get_logger, Logger

log = get_logger()

# 模板目录
IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "wegame")


def _tpl(name):
    return os.path.join(IMG_DIR, name)


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
        点击左侧 NBA2K 图标,切换到游戏主页。
        """
        if not self.activate():
            return False
        log.info("选择 NBA2K Online2 游戏")
        # 点击 NBA2K 图标(模板匹配)
        tpl = _tpl("nba2k_icon.png")
        if os.path.exists(tpl):
            roi = self.wg_cfg.get("avatar_roi", [])  # 复用区域加速
            if vision.click_template(tpl, hwnd=self.hwnd, roi=roi or None, timeout=10):
                log.info("已点击 NBA2K 图标")
                time.sleep(1.5)
                return True
            log.warning("图标模板未匹配,尝试备用方式")
        # 备用:校准工具会写入图标坐标到坐标配置
        log.error("无法定位 NBA2K 图标,请运行校准工具或手动选中游戏")
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
        tpl = _tpl("start_button.png")
        if os.path.exists(tpl):
            roi = self.wg_cfg.get("start_button_roi", []) or None
            if not vision.click_template(tpl, hwnd=self.hwnd, roi=roi, timeout=10):
                log.error("启动按钮未匹配")
                Logger.screenshot("start_button_fail")
                return None
        else:
            log.error("缺少启动按钮模板,请运行校准工具")
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
            time.sleep(3)  # 等游戏完全加载
            window_utils.move_window_top_left(game_hwnd, ts[0], ts[1])
        return game_hwnd

    # ----------------------------------------------------------
    # 切换账号
    # ----------------------------------------------------------
    def switch_to_account(self, account_index):
        """
        切换到指定序号的账号(1~6)。
        流程:点右上角头像 → 点"切换账号" → 在账号列表选第 N 个(必要时滚动)。
        """
        if not self.activate():
            return False

        log.info(f"切换到账号 #{account_index}")

        # 1. 点击右上角头像(展开菜单)
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
        tpl = _tpl("avatar_button.png")
        if os.path.exists(tpl):
            roi = self.wg_cfg.get("avatar_roi", []) or None
            if vision.click_template(tpl, hwnd=self.hwnd, roi=roi, timeout=8):
                log.info("已点击头像菜单")
                time.sleep(1.0)
                return True
        log.error("头像按钮未匹配,请运行校准工具")
        Logger.screenshot("avatar_fail")
        return False

    def _click_switch_account_item(self):
        """点击"切换账号"菜单项"""
        tpl = _tpl("switch_account_item.png")
        if os.path.exists(tpl):
            roi = self.wg_cfg.get("switch_account_item_roi", []) or None
            if vision.click_template(tpl, hwnd=self.hwnd, roi=roi, timeout=8):
                log.info("已点击切换账号")
                time.sleep(1.5)
                return True
        # 备用:OCR 找"切换账号"文字
        log.warning("切换账号菜单项模板未匹配")
        Logger.screenshot("switch_account_fail")
        return False

    def _select_account_from_list(self, index):
        """
        在账号切换列表中选第 index 个(1~6)。
        自动检测列表位置:先截图 OCR 找账号 ID,定位每个条目坐标。
        一屏显示约 4 个,前 4 个直接点,后 2 个需向下滚动。
        """
        visible_count = 4
        first_y = self.acc_cfg.get("first_item_y", 0)
        item_h = self.acc_cfg.get("item_height", 80)
        list_roi = self.acc_cfg.get("list_roi", []) or None
        scroll_steps = self.acc_cfg.get("scroll_steps_for_tail", 3)

        # 如果没配置坐标,自动检测
        if first_y == 0 or not list_roi:
            log.info("未配置账号列表坐标,自动检测...")
            detected = self._detect_account_list()
            if detected:
                first_y, item_h, list_roi = detected
                log.info(f"自动检测到: first_y={first_y} item_h={item_h} list_roi={list_roi}")
            else:
                log.error("无法自动检测账号列表位置")
                Logger.screenshot("account_list_detect_fail")
                return False

        cx = (list_roi[0] + list_roi[2]) // 2

        if index <= visible_count:
            # 直接点击第 index 个
            y = first_y + (index - 1) * item_h
            log.info(f"点击账号 #{index} 列表位置 ({cx},{y})")
            vision.click(cx, y, hwnd=self.hwnd)
            time.sleep(2)
            return True
        else:
            # 需要先滚动
            log.info(f"账号 #{index} 在列表下方,滚动后选择")
            cy = (list_roi[1] + list_roi[3]) // 2
            import pyautogui
            vision.click(cx, cy, hwnd=self.hwnd)  # 先聚焦
            time.sleep(0.5)
            for _ in range(scroll_steps):
                if not vision.VisionConfig.dry_run:
                    pyautogui.scroll(-3)
                else:
                    log.info("[DRY-RUN] 向下滚动")
                time.sleep(0.3)
            time.sleep(0.5)
            visible_index = index - scroll_steps
            y = first_y + (visible_index - 1) * item_h
            log.info(f"滚动后点击账号 #{index} 位置 ({cx},{y})")
            vision.click(cx, y, hwnd=self.hwnd)
            time.sleep(2)
            return True

    def _detect_account_list(self):
        """
        自动检测账号列表位置:截图 WeGame 窗口,OCR 找账号 ID(QQ号)。
        返回 (first_y, item_height, list_roi) 或 None。
        """
        try:
            import pytesseract
            result = vision.grab_window(self.hwnd)
            if not result or result[0] is None:
                return None
            screen, _ = result
            gray = vision.cv2.cvtColor(screen, vision.cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(
                gray, lang='eng',
                config='--psm 11 -c tessedit_char_whitelist=0123456789',
                output_type=vision.pytesseract.Output.DICT)
            # 找纯数字、长度>=6的(账号ID)
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
            if len(accounts) < 2:
                log.warning(f"OCR 只找到 {len(accounts)} 个账号ID")
                if accounts:
                    # 只找到一个,也能用
                    pass
                else:
                    return None

            # 按Y排序
            accounts.sort(key=lambda a: a['cy'])
            y_vals = [a['cy'] for a in accounts]
            first_y = y_vals[0]
            # 条目高度 = 相邻账号的Y间距
            if len(y_vals) >= 2:
                gaps = [y_vals[i+1] - y_vals[i] for i in range(len(y_vals)-1)]
                item_h = int(sum(gaps) / len(gaps))
            else:
                item_h = 80

            # 列表区域
            list_x0 = min(a['left'] for a in accounts) - 60
            list_x1 = max(a['left'] + a['w'] for a in accounts) + 60
            list_y0 = first_y - item_h // 2
            list_y1 = y_vals[-1] + item_h // 2
            list_roi = [list_x0, list_y0, list_x1, list_y1]

            log.info(f"检测到 {len(accounts)} 个账号: {[a['text'] for a in accounts]}")
            return (first_y, item_h, list_roi)
        except Exception as e:
            log.warning(f"自动检测账号列表失败: {e}")
            return None

    # ----------------------------------------------------------
    # 确认账号已登录
    # ----------------------------------------------------------
    def wait_account_logged_in(self, timeout=30):
        """等待 WeGame 显示已登录状态(回到主页)"""
        log.info(f"等待账号登录完成 超时={timeout}s")
        start = time.time()
        while time.time() - start < timeout:
            # 登录后通常会回到 WeGame 主页,可检测"启动"按钮是否出现
            tpl = _tpl("start_button.png")
            if os.path.exists(tpl):
                roi = self.wg_cfg.get("start_button_roi", []) or None
                if vision.find_template(tpl, hwnd=self.hwnd, roi=roi):
                    log.info("账号已登录,WeGame 主页就绪")
                    return True
            time.sleep(2)
        log.warning("等待登录超时")
        Logger.screenshot("login_timeout")
        return False
