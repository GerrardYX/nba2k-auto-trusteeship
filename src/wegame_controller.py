"""
wegame_controller.py - WeGame 客户端控制(纯元素识别)
流程:
  登录界面:OCR找QQ号→点击目标账号→自动登录
  主界面:OCR找NBA2K→OCR找启动→点击
  切换账号:OCR找"切换账号"→回登录界面→选账号
"""
import time

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
        """登录界面:有'扫码登录'或'自动登录'文字"""
        r = vision.find_any_text(self.hwnd, ["扫码登录", "自动登录"],
                                 timeout=3, partial=True)
        if r:
            log.info(f"在登录界面 (检测到 {r[0]})")
            return True
        return False

    def is_main_page(self):
        """主界面:有'启动'按钮"""
        r = vision.find_text(self.hwnd, "启动", timeout=3, partial=True)
        if r:
            log.info("在主界面(已登录)")
            return True
        return False

    # ----------------------------------------------------------
    # 登录界面:选账号
    # ----------------------------------------------------------
    def select_account_on_login(self, account_index):
        """
        在登录界面选第 N 个账号并登录。
        1. 找QQ号 → 如果只有1个,点右侧箭头展开列表
        2. 列表展开后,点第N个账号
        3. 点"登录"按钮
        4. 等待进入主界面
        """
        if not self.activate():
            return False
        log.info(f"登录界面:选账号 #{account_index}")

        # 1. 展开账号列表(如果没展开)
        numbers = vision.find_all_numbers(self.hwnd, timeout=3)
        if len(numbers) <= 1:
            log.info("账号列表未展开,点击下拉箭头...")
            self._try_expand_list()
            time.sleep(1.5)
            numbers = vision.find_all_numbers(self.hwnd, timeout=3)

        if not numbers:
            log.error("未找到任何账号")
            Logger.screenshot("no_accounts")
            return False

        # 2. 选择账号
        if not self._select_from_numbers(numbers, account_index):
            return False

        # 3. 点击"登录"按钮(选完账号后需要点登录)
        time.sleep(1)
        log.info("点击登录按钮")
        if vision.click_text(self.hwnd, "登录", timeout=5, partial=False):
            log.info("已点击登录")
        else:
            # 备用:partial 匹配
            vision.click_text(self.hwnd, "登录", timeout=3, partial=True)

        # 4. 等待进入主界面
        return self.wait_account_logged_in(timeout=40)

    def _try_expand_list(self):
        """
        展开账号列表。
        WeGame登录界面默认只显示1个账号,旁边有下拉箭头。
        点击QQ号右侧(箭头位置)展开完整列表。
        """
        # 找当前账号的QQ号
        numbers = vision.find_all_numbers(self.hwnd, timeout=2)
        if not numbers:
            log.warning("未找到任何QQ号,无法定位箭头")
            return

        n = numbers[0]
        # 下拉箭头在QQ号右侧。偏移量基于数字宽度(相对元素,非硬编码坐标)
        num_width = n.get('x1', n['x']) - n.get('x0', n['x'])
        if num_width < 10:
            num_width = 100  # OCR没给宽度时的默认值
        # 箭头通常在数字右侧 10-30px 处
        arrow_x = n['x'] + num_width // 2 + 30
        arrow_y = n['y']
        log.info(f"点击下拉箭头(在 {n['text']} 右侧) ({arrow_x},{arrow_y})")
        vision.click(arrow_x, arrow_y, hwnd=self.hwnd)

    def _select_from_numbers(self, numbers, account_index):
        """从OCR找到的数字列表中选第N个,需要时滚动。返回 True/False"""
        visible_count = len(numbers)
        scroll_steps = self.cfg.get("account_list", {}).get("scroll_steps_for_tail", 3)

        if account_index <= visible_count:
            n = numbers[account_index - 1]
            log.info(f"点击账号 #{account_index}: {n['text']} ({n['x']},{n['y']})")
            vision.click(n['x'], n['y'], hwnd=self.hwnd)
            time.sleep(1)
            return True

        # 需要滚动
        log.info(f"账号 #{account_index} 在列表下方,滚动...")
        import pyautogui
        mid = numbers[len(numbers) // 2]
        vision.click(mid['x'], mid['y'], hwnd=self.hwnd)
        time.sleep(0.5)
        for _ in range(scroll_steps):
            if not vision.VisionConfig.dry_run:
                pyautogui.scroll(-3)
            else:
                log.info("[DRY-RUN] 向下滚动")
            time.sleep(0.3)
        time.sleep(0.5)

        numbers = vision.find_all_numbers(self.hwnd, timeout=3)
        if numbers and account_index <= len(numbers):
            n = numbers[account_index - 1]
            log.info(f"滚动后点击账号 #{account_index}: {n['text']}")
            vision.click(n['x'], n['y'], hwnd=self.hwnd)
            time.sleep(1)
            return True

        log.error("滚动后仍未找到目标账号")
        return False

    # ----------------------------------------------------------
    # 主界面:切换账号(回登录界面)
    # ----------------------------------------------------------
    def switch_to_account(self, account_index):
        """
        从主界面切换账号:找"切换账号"文字→点击→回登录界面→选账号
        """
        if not self.activate():
            return False
        log.info(f"切换到账号 #{account_index}")

        # 如果已在登录界面,直接选
        if self.is_login_page():
            return self.select_account_on_login(account_index)

        # 在主界面:找"切换账号"文字
        # WeGame主界面右上角点头像后弹出菜单含"切换账号"
        # 先试直接找"切换账号"(可能菜单已展开)
        r = vision.find_text(self.hwnd, "切换账号", timeout=3)
        if not r:
            # 菜单未展开,需要点头像
            # 头像旁边的文字:找窗口右上区域的文字点击
            log.info("菜单未展开,查找头像区域...")
            # 用OCR找右上角文字(账号名/ID等),点它展开菜单
            r = vision.find_text(self.hwnd, "切换", timeout=3)
            if r:
                vision.click(r['x'], r['y'], hwnd=self.hwnd)
                time.sleep(1)
            else:
                # 用 find_all_numbers 找右上角的账号ID
                numbers = vision.find_all_numbers(self.hwnd, timeout=3)
                if numbers:
                    # 点最右边的数字(通常在右上角)
                    rightmost = max(numbers, key=lambda n: n['x'])
                    vision.click(rightmost['x'], rightmost['y'], hwnd=self.hwnd)
                    log.info(f"点击右上角账号 {rightmost['text']}")
                    time.sleep(1.5)
                else:
                    log.error("无法找到头像/切换入口")
                    Logger.screenshot("switch_fail")
                    return False

        # 现在菜单应该展开了,找"切换账号"并点击
        if not vision.click_text(self.hwnd, "切换账号", timeout=5):
            vision.click_text(self.hwnd, "切换", timeout=3)
        time.sleep(2)

        # 回到登录界面,选账号
        return self.select_account_on_login(account_index)

    # ----------------------------------------------------------
    # 等待登录
    # ----------------------------------------------------------
    def wait_account_logged_in(self, timeout=40):
        """等待登录完成(检测主界面'启动'按钮)"""
        log.info(f"等待登录完成 超时={timeout}s")
        start = time.time()
        while time.time() - start < timeout:
            if vision.find_text(self.hwnd, "启动", timeout=0, partial=True):
                log.info("✓ 登录成功,WeGame主界面就绪")
                return True
            time.sleep(2)
        log.warning("等待登录超时")
        return False

    # ----------------------------------------------------------
    # 选游戏 + 启动
    # ----------------------------------------------------------
    def select_game(self):
        """OCR找NBA2K并点击"""
        if not self.activate():
            return False
        log.info("选择 NBA2K")
        r = vision.find_any_text(self.hwnd,
                                 ["NBA2K", "NBA 2K", "2KOL", "2KOnline", "2K"],
                                 timeout=8, partial=True)
        if r:
            vision.click(r[1]['x'], r[1]['y'], hwnd=self.hwnd)
            log.info(f"已点击 NBA2K (OCR: {r[0]})")
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
        """OCR找启动按钮并点击,返回游戏窗口hwnd"""
        if not self.activate():
            return None
        log.info("点击启动游戏")
        if not vision.click_text(self.hwnd, "启动", timeout=10):
            if not vision.click_text(self.hwnd, "开始游戏", timeout=5):
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
