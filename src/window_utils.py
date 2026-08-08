"""
window_utils.py - 窗口控制工具
负责:窗口查找、激活、置顶、固定位置、防息屏、获取客户区截图坐标。
所有 ROI 坐标基于【目标窗口客户区左上角(0,0)】。
"""
import time

try:
    import win32gui
    import win32con
    import win32ui
    import win32process
    import ctypes
    from ctypes import wintypes
    _WIN32 = True
except ImportError:
    _WIN32 = False

from logger import get_logger

log = get_logger()


# ============================================================
# 防息屏
# ============================================================
def prevent_sleep():
    """阻止系统休眠/息屏(挂机期间调用)"""
    if not _WIN32:
        return
    try:
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
        log.info("已阻止系统息屏")
    except Exception as e:
        log.warning(f"防息屏失败: {e}")


def allow_sleep():
    """恢复系统正常息屏策略"""
    if not _WIN32:
        return
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        log.info("已恢复系统息屏策略")
    except Exception:
        pass


# ============================================================
# 窗口查找
# ============================================================
def find_window(title_keywords):
    """
    按标题关键词查找窗口(模糊匹配,忽略大小写)。
    返回 hwnd 或 None。
    """
    if not _WIN32:
        return None
    results = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                tl = title.lower()
                for kw in title_keywords:
                    if kw.lower() in tl:
                        results.append((hwnd, title))
                        break

    win32gui.EnumWindows(_cb, None)
    if not results:
        return None
    # 优先返回可见且非最小化的窗口
    for hwnd, title in results:
        if not win32gui.IsIconic(hwnd):
            log.debug(f"找到窗口: {title} (hwnd={hwnd})")
            return hwnd
    return results[0][0]


def activate_window(hwnd):
    """激活窗口到前台并置顶"""
    if not _WIN32 or not hwnd:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
        # 多次尝试置顶(Windows 前台锁定限制)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        # 备用:用 AttachThreadInput 绕过前台限制
        try:
            fg = win32gui.GetForegroundWindow()
            if fg != hwnd:
                _force_foreground(hwnd)
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning(f"激活窗口失败: {e}")
        return False


def _force_foreground(hwnd):
    """通过 AttachThreadInput 强制置前台"""
    if not _WIN32:
        return
    try:
        foreground_hwnd = win32gui.GetForegroundWindow()
        foreground_tid = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
        target_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        if foreground_tid != target_tid:
            win32process.AttachThreadInput(foreground_tid, target_tid, True)
            win32gui.SetForegroundWindow(hwnd)
            win32process.AttachThreadInput(foreground_tid, target_tid, False)
        win32gui.BringWindowToTop(hwnd)
    except Exception as e:
        log.debug(f"force_foreground 失败(可忽略): {e}")


def get_client_rect_screen(hwnd):
    """
    获取窗口客户区在屏幕中的矩形(左上角坐标 + 宽高)。
    返回 (x, y, w, h),客户区左上角即 ROI 的 (0,0) 原点。
    """
    if not _WIN32 or not hwnd:
        return None
    try:
        # 客户区坐标
        l, t, r, b = win32gui.GetClientRect(hwnd)
        # 客户区左上角转屏幕坐标
        point = win32gui.ClientToScreen(hwnd, (l, t))
        w = r - l
        h = b - t
        return (point[0], point[1], w, h)
    except Exception as e:
        log.warning(f"获取客户区失败: {e}")
        return None


def move_window_top_left(hwnd, width=1920, height=1080):
    """将窗口移动到屏幕左上角并设置尺寸"""
    if not _WIN32 or not hwnd:
        return False
    try:
        win32gui.MoveWindow(hwnd, 0, 0, width, height, True)
        time.sleep(0.5)
        log.info(f"窗口已移至左上角 {width}x{height}")
        return True
    except Exception as e:
        log.warning(f"移动窗口失败: {e}")
        return False


def is_window_alive(hwnd):
    """窗口是否存在且可见"""
    if not _WIN32 or not hwnd:
        return False
    try:
        return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    except Exception:
        return False


def get_window_title(hwnd):
    if not _WIN32 or not hwnd:
        return ""
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""
