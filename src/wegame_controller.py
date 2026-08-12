"""
wegame_controller.py - WeGame 登录控制
核心策略(按 Fable5 建议的优先级):
  1. DPI 感知(必须最先执行,否则坐标全错)
  2. 键盘直输 QQ号+密码(绕过下拉列表)
  3. 颜色检测找按钮(登录/启动按钮是色块,OCR 识别不了)
  4. 模板匹配兜底(图标类元素)
"""
import time
import ctypes
import platform

# ============================================================
# 必须最先执行:DPI 感知
# 否则高缩放屏(250%)上截图坐标和点击坐标差缩放倍数
# ============================================================
if platform.system() == "Windows":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import vision
import window_utils
from logger import get_logger, Logger

log = get_logger()


class WeGameController:
    def __init__(self, cfg):
        self.cfg = cfg
        self.hwnd = None

    def find(self):
        kws = self.cfg.get("wegame_window", {}).get("title_keywords", ["WeGame"])
        self.hwnd = window_utils.find_window(kws)
        if self.hwnd:
            log.info(f"WeGame 窗口已找到 (hwnd={self.hwnd})")
        return self.hwnd

    def activate(self):
        if not self.hwnd:
            self.find()
        if self.hwnd:
            window_utils.activate_window(self.hwnd)
            time.sleep(1)
            return True
        return False

    # ----------------------------------------------------------
    # 判断当前界面
    # ----------------------------------------------------------
    def is_login_page(self):
        r = vision.find_any_text(self.hwnd, ["扫码登录", "自动登录", "快速安全"],
                                 timeout=3, partial=True)
        if r:
            log.info(f"在登录界面 (检测到 {r[0]})")
            return True
        return False

    def is_main_page(self):
        r = vision.find_text(self.hwnd, "启动", timeout=3, partial=True)
        if r:
            log.info("在主界面(已登录)")
            return True
        return False

    # ----------------------------------------------------------
    # 登录界面:键盘直输 QQ号(绕过下拉列表)
    # ----------------------------------------------------------
    def login_with_account(self, account):
        """
        用键盘直接输入 QQ 号登录,绕过下拉列表。
        account: {'wegame_id': 'xxx', 'label': '账号1'}
        流程:
          1. 找账号输入框(OCR找当前QQ号→点击它→聚焦输入框)
          2. Ctrl+A 全选 → 输入目标 QQ号
          3. 找"登录"按钮(颜色检测)→ 点击
          4. 等待进入主界面
        """
        if not self.activate():
            return False

        qq = account.get("wegame_id", "")
        label = account.get("label", "")
        log.info(f"键盘直输登录 {label} (QQ:{qq})")

        # 1. 找账号输入框:OCR找当前显示的QQ号
        numbers = vision.find_all_numbers(self.hwnd, timeout=3)
        if numbers:
            n = numbers[0]
            log.info(f"找到账号框(QQ:{n['text']}) 点击聚焦")
            vision.click(n['x'], n['y'], hwnd=self.hwnd)
            time.sleep(0.5)
        else:
            log.warning("未找到QQ号,尝试点击中央区域")
            # 点击屏幕中央(登录框通常在中央)
            rect = window_utils.get_client_rect_screen(self.hwnd)
            if rect:
                vision.click(rect[2] // 2, rect[3] // 2, hwnd=self.hwnd)
                time.sleep(0.5)

        # 2. Ctrl+A 全选 → 输入QQ号
        log.info(f"输入QQ号 {qq}")
        vision.hotkey("ctrl", "a")
        time.sleep(0.2)
        # 用 pyautogui 输入数字(QQ号是纯数字,英文输入法即可)
        import pyautogui
        pyautogui.typewrite(qq, interval=0.03)
        time.sleep(0.3)

        # 3. 找并点击"登录"按钮
        # 优先:颜色检测(橙色/蓝色大色块)
        log.info("查找登录按钮")
        if not self._click_login_button():
            # 备用:OCR找"登录"文字
            if not vision.click_text(self.hwnd, "登录", timeout=5, partial=False):
                # 最后备用:按回车
                log.info("按回车键登录")
                vision.press_key("enter")
        time.sleep(2)

        # 4. 等待进入主界面
        return self.wait_account_logged_in(timeout=40)

    def _click_login_button(self):
        """用颜色检测找"登录"按钮(WeGame的登录按钮是橙色大色块)"""
        try:
            import cv2
            import numpy as np
            result = vision.grab_window(self.hwnd)
            if not result or result[0] is None:
                return False
            screen, _ = result

            # 转HSV
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            # 橙色范围(H: 10-25, S: 100-255, V: 100-255)
            lower = np.array([10, 100, 100])
            upper = np.array([25, 255, 255])
            mask = cv2.inRange(hsv, lower, upper)

            # 找轮廓
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                # 试蓝色范围(WeGame也可能是蓝色按钮)
                lower = np.array([100, 100, 100])
                upper = np.array([130, 255, 255])
                mask = cv2.inRange(hsv, lower, upper)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                log.warning("颜色检测未找到登录按钮")
                return False

            # 找最大的色块(按钮)
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            if area < 500:  # 太小,不是按钮
                log.warning(f"色块太小({area}),可能不是按钮")
                return False

            x, y, w, h = cv2.boundingRect(largest)
            cx = x + w // 2
            cy = y + h // 2
            log.info(f"颜色检测找到按钮 ({cx},{cy}) 尺寸={w}x{h} 面积={area}")
            vision.click(cx, cy, hwnd=self.hwnd)
            return True
        except Exception as e:
            log.warning(f"颜色检测失败: {e}")
            return False

    # ----------------------------------------------------------
    # 主界面:选NBA2K + 启动
    # ----------------------------------------------------------
    def select_game(self):
        if not self.activate():
            return False
        log.info("选择 NBA2K")
        r = vision.find_any_text(self.hwnd,
                                 ["NBA2K", "NBA 2K", "2KOL", "2K"],
                                 timeout=8, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            log.info(f"已点击 NBA2K")
            time.sleep(1.5)
            return True
        # 备用:展开"我的游戏"
        vision.click_text(self.hwnd, "我的游戏", timeout=3)
        time.sleep(1)
        r = vision.find_any_text(self.hwnd, ["NBA2K", "2KOL", "2K"],
                                 timeout=5, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            time.sleep(1.5)
            return True
        log.error("无法定位 NBA2K")
        Logger.screenshot("select_game_fail")
        return False

    def start_game(self):
        """启动游戏:先颜色检测找按钮,OCR兜底"""
        if not self.activate():
            return None
        log.info("启动游戏")

        # 优先:颜色检测找启动按钮
        if self._click_start_button():
            pass
        # 备用:OCR找"启动"
        elif vision.click_text(self.hwnd, "启动", timeout=5, partial=True):
            pass
        else:
            log.error("启动按钮未找到")
            Logger.screenshot("start_fail")
            return None

        log.info("等待游戏窗口启动...")
        gw = self.cfg.get("game_window", {})
        kws = gw.get("title_keywords", ["NBA2K", "2K"])
        timeout = self.cfg.get("timing", {}).get("game_launch_timeout", 120)
        start = time.time()
        while time.time() - start < timeout:
            gh = window_utils.find_window(kws)
            if gh:
                log.info(f"游戏窗口已启动 (hwnd={gh})")
                if gw.get("force_position", True):
                    ts = gw.get("target_client_size", [1920, 1080])
                    time.sleep(3)
                    window_utils.move_window_top_left(gh, ts[0], ts[1])
                return gh
            time.sleep(2)
        log.error("游戏启动超时")
        Logger.screenshot("launch_timeout")
        return None

    def _click_start_button(self):
        """颜色检测找启动按钮(WeGame启动按钮是蓝绿色大色块)"""
        try:
            import cv2
            import numpy as np
            result = vision.grab_window(self.hwnd)
            if not result or result[0] is None:
                return False
            screen, _ = result

            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            # 试多种颜色:蓝绿(启动)、橙色、蓝色
            color_ranges = [
                (np.array([85, 100, 100]), np.array([130, 255, 255]), "蓝绿"),
                (np.array([10, 100, 100]), np.array([25, 255, 255]), "橙"),
                (np.array([100, 100, 100]), np.array([130, 255, 255]), "蓝"),
                (np.array([45, 100, 100]), np.array([75, 255, 255]), "绿"),
            ]
            for lower, upper, name in color_ranges:
                mask = cv2.inRange(hsv, lower, upper)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    largest = max(contours, key=cv2.contourArea)
                    area = cv2.contourArea(largest)
                    if area > 2000:  # 够大才是按钮
                        x, y, w, h = cv2.boundingRect(largest)
                        # 检查宽高比(按钮通常宽>高)
                        if w > h and w > 50:
                            cx = x + w // 2
                            cy = y + h // 2
                            log.info(f"颜色检测({name})找到启动按钮 ({cx},{cy}) {w}x{h}")
                            vision.click(cx, cy, hwnd=self.hwnd)
                            return True
            log.warning("颜色检测未找到启动按钮")
            return False
        except Exception as e:
            log.warning(f"颜色检测失败: {e}")
            return False

    # ----------------------------------------------------------
    # 切换账号(从主界面回登录界面)
    # ----------------------------------------------------------
    def switch_to_account(self, account):
        """
        从已登录的主界面切换账号。
        流程:找"切换账号"文字→点击→回登录界面→键盘直输登录
        """
        if not self.activate():
            return False

        log.info(f"切换到 {account.get('label','')} (QQ:{account.get('wegame_id','')})")

        # 如果已在登录界面,直接登录
        if self.is_login_page():
            return self.login_with_account(account)

        # 在主界面:找"切换账号"或"切换"文字
        # 先试直接找(可能菜单已展开)
        if not vision.click_text(self.hwnd, "切换账号", timeout=3, partial=True):
            if not vision.click_text(self.hwnd, "切换", timeout=3, partial=True):
                # 菜单未展开,需要找头像区域
                # 用颜色检测找右上角头像(圆形色块)
                log.info("尝试定位头像...")
                # 用OCR找数字(QQ号)在右上角区域
                numbers = vision.find_all_numbers(self.hwnd, timeout=3)
                if numbers:
                    # 找最靠右的数字(通常在右上角)
                    rightmost = max(numbers, key=lambda n: n['x'])
                    vision.click(rightmost['x'], rightmost['y'], hwnd=self.hwnd)
                    log.info(f"点击右上角 {rightmost['text']}")
                    time.sleep(1.5)
                    # 再找"切换账号"
                    vision.click_text(self.hwnd, "切换账号", timeout=5, partial=True)
                else:
                    log.error("无法找到切换入口")
                    Logger.screenshot("switch_fail")
                    return False

        time.sleep(2)

        # 现在应该在登录界面了
        if self.is_login_page():
            return self.login_with_account(account)

        # 可能直接回到登录界面了
        log.info("尝试直接登录")
        return self.login_with_account(account)

    # ----------------------------------------------------------
    # 等待登录
    # ----------------------------------------------------------
    def wait_account_logged_in(self, timeout=40):
        log.info(f"等待登录完成 超时={timeout}s")
        start = time.time()
        while time.time() - start < timeout:
            # 检测主界面:有"启动"或"NBA2K"等文字
            r = vision.find_any_text(self.hwnd, ["启动", "NBA2K", "2K", "我的游戏"],
                                     timeout=0, partial=True)
            if r:
                log.info(f"✓ 登录成功 (检测到 {r[0]})")
                return True
            time.sleep(2)
        log.warning("等待登录超时")
        return False
