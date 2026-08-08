"""
vision.py - 图像识别与 OCR 引擎
负责:屏幕截图、模板匹配、OCR 读数、等待元素、点击。
所有 ROI 坐标基于【目标窗口客户区左上角(0,0)】。
"""
import os
import time

import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # 禁用移到左上角触发异常
    pyautogui.PAUSE = 0.1
    _PAG = True
except ImportError:
    _PAG = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

try:
    import mss
    _MSS = True
except ImportError:
    _MSS = False

try:
    import pytesseract
    _TESS = True
except ImportError:
    _TESS = False

import window_utils
from logger import get_logger, Logger

log = get_logger()


# ============================================================
# 配置
# ============================================================
class VisionConfig:
    confidence_threshold = 0.82
    grayscale = True
    multi_scale = True
    scale_range = (0.5, 2.0)
    scale_steps = 10
    dry_run = False  # True 时只识别不点击
    step_pause = False  # True 时每步暂停等回车


def load_config(config_path="config/settings.yaml"):
    """从 settings.yaml 加载视觉配置"""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        v = cfg.get("vision", {})
        VisionConfig.confidence_threshold = v.get("confidence_threshold", 0.82)
        VisionConfig.grayscale = v.get("grayscale", True)
        VisionConfig.multi_scale = v.get("multi_scale", True)
        VisionConfig.scale_range = tuple(v.get("scale_range", [0.5, 2.0]))
        VisionConfig.scale_steps = v.get("scale_steps", 10)
        rt = cfg.get("runtime", {})
        mode = rt.get("mode", "normal")
        VisionConfig.dry_run = (mode == "dry_run")
        VisionConfig.step_pause = (mode == "step_pause")
    except Exception as e:
        log.warning(f"加载视觉配置失败,使用默认: {e}")


# ============================================================
# 截图
# ============================================================
def grab_screen(region=None):
    """
    截取屏幕区域。
    region: (left, top, width, height) 屏幕物理坐标。None=全屏。
    返回 numpy BGR 图像。
    """
    if _MSS:
        with mss.mss() as sct:
            if region:
                monitor = {"left": region[0], "top": region[1],
                           "width": region[2], "height": region[3]}
            else:
                monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            img = np.array(shot)
            # BGRA -> BGR
            return img[:, :, :3]
    elif _PAG:
        im = pyautogui.screenshot(region=region if region else None)
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR) if _CV2 else None
    else:
        log.error("无可用截图库(mss/pyautogui)")
        return None


def grab_window(hwnd):
    """截取指定窗口的客户区"""
    rect = window_utils.get_client_rect_screen(hwnd)
    if not rect:
        return None
    x, y, w, h = rect
    return grab_screen((x, y, w, h)), rect


def save_screenshot(path, region=None):
    """保存截图到文件(供 logger 调用)"""
    img = grab_screen(region)
    if img is not None and _CV2:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        cv2.imwrite(path, img)
        return True
    return False


# 注册截图函数到 logger
Logger.set_screenshot_func(save_screenshot)


# ============================================================
# 模板匹配
# ============================================================
def _match_single(screen, template, threshold, grayscale):
    """单尺度模板匹配,返回 (cx, cy, confidence) 或 None"""
    if screen is None or template is None:
        return None
    if grayscale:
        s = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        t = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    else:
        s, t = screen, template
    if s.shape[0] < t.shape[0] or s.shape[1] < t.shape[1]:
        return None
    res = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    if max_val >= threshold:
        cx = max_loc[0] + t.shape[1] // 2
        cy = max_loc[1] + t.shape[0] // 2
        return (cx, cy, float(max_val))
    return None


def _match_multi_scale(screen, template, threshold, grayscale, scale_range, steps):
    """多尺度模板匹配"""
    if screen is None or template is None:
        return None
    best = None
    best_conf = threshold
    th, tw = template.shape[:2]
    for scale in np.linspace(scale_range[0], scale_range[1], steps):
        nw, nh = int(tw * scale), int(th * scale)
        if nw < 5 or nh < 5:
            continue
        if nw > screen.shape[1] or nh > screen.shape[0]:
            continue
        scaled = cv2.resize(template, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        r = _match_single(screen, scaled, best_conf, grayscale)
        if r and r[2] > best_conf:
            best_conf = r[2]
            best = r
    return best


def find_template(template_path, hwnd=None, roi=None, threshold=None):
    """
    在窗口客户区(或指定 ROI)中查找模板图像。
    template_path: 模板图片路径
    hwnd: 目标窗口;None=全屏
    roi: [x0,y0,x1,y1] 客户区内坐标;None=全窗口
    返回 {'x','y','confidence','rect'} (客户区坐标) 或 None
    """
    if not _CV2:
        log.error("需要 opencv")
        return None
    if not os.path.exists(template_path):
        log.warning(f"模板不存在: {template_path}")
        return None

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        log.warning(f"无法读取模板: {template_path}")
        return None

    th = threshold or VisionConfig.confidence_threshold

    # 截图
    if hwnd:
        result = grab_window(hwnd)
        if not result or result[0] is None:
            return None
        screen, win_rect = result
        offset_x, offset_y = 0, 0  # 客户区坐标,左上角为0
    else:
        screen = grab_screen()
        if screen is None:
            return None
        win_rect = None
        offset_x, offset_y = 0, 0

    # 裁剪 ROI
    if roi:
        x0, y0, x1, y1 = roi
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(screen.shape[1], x1)
        y1 = min(screen.shape[0], y1)
        if x1 <= x0 or y1 <= y0:
            log.warning(f"ROI 无效: {roi}")
            return None
        search_area = screen[y0:y1, x0:x1]
        offset_x, offset_y = x0, y0
    else:
        search_area = screen

    # 匹配
    if VisionConfig.multi_scale:
        match = _match_multi_scale(search_area, template, th,
                                   VisionConfig.grayscale,
                                   VisionConfig.scale_range,
                                   VisionConfig.scale_steps)
    else:
        match = _match_single(search_area, template, th, VisionConfig.grayscale)

    if match:
        cx, cy, conf = match
        # 还原到客户区坐标
        gx = cx + offset_x
        gy = cy + offset_y
        log.debug(f"匹配成功 [{os.path.basename(template_path)}] "
                  f"置信度={conf:.3f} 位置=({gx},{gy})")
        return {
            "x": gx, "y": gy, "confidence": conf,
            "rect": [gx - template.shape[1]//2, gy - template.shape[0]//2,
                     gx + template.shape[1]//2, gy + template.shape[0]//2]
        }
    log.debug(f"未匹配 [{os.path.basename(template_path)}] 阈值={th}")
    return None


def find_any(templates, hwnd=None, roi=None, threshold=None):
    """在多个模板中找第一个匹配的,返回 (template_path, result) 或 None"""
    for tp in templates:
        r = find_template(tp, hwnd=hwnd, roi=roi, threshold=threshold)
        if r:
            return (tp, r)
    return None


# ============================================================
# 等待元素
# ============================================================
def wait_for(template_path, hwnd=None, roi=None, timeout=15, interval=0.8, threshold=None):
    """
    等待模板出现。返回 result 或 None(超时)。
    """
    log.info(f"等待元素 [{os.path.basename(template_path)}] 超时={timeout}s")
    start = time.time()
    while time.time() - start < timeout:
        r = find_template(template_path, hwnd=hwnd, roi=roi, threshold=threshold)
        if r:
            return r
        time.sleep(interval)
    log.warning(f"等待超时 [{os.path.basename(template_path)}]")
    Logger.screenshot(f"timeout_{os.path.basename(template_path)}")
    return None


def wait_for_any(templates, hwnd=None, roi=None, timeout=15, interval=0.8, threshold=None):
    """等待多个模板中任一出现。返回 (template_path, result) 或 None"""
    names = [os.path.basename(t) for t in templates]
    log.info(f"等待任一元素 {names} 超时={timeout}s")
    start = time.time()
    while time.time() - start < timeout:
        r = find_any(templates, hwnd=hwnd, roi=roi, threshold=threshold)
        if r:
            return r
        time.sleep(interval)
    log.warning(f"等待超时 {names}")
    Logger.screenshot("timeout_multi")
    return None


# ============================================================
# 点击
# ============================================================
def click(x, y, hwnd=None, button="left", clicks=1, delay_before=0.2):
    """
    点击客户区坐标 (x,y)。
    若提供 hwnd,坐标会转换为屏幕坐标后点击。
    dry_run 模式下只移动不点击。
    """
    # 转换为屏幕坐标
    if hwnd:
        rect = window_utils.get_client_rect_screen(hwnd)
        if rect:
            screen_x = rect[0] + x
            screen_y = rect[1] + y
        else:
            screen_x, screen_y = x, y
    else:
        screen_x, screen_y = x, y

    if VisionConfig.dry_run:
        log.info(f"[DRY-RUN] 点击 ({x},{y}) -> 屏幕({screen_x},{screen_y}) [不执行]")
        if _PAG:
            pyautogui.moveTo(screen_x, screen_y)
        return True

    if VisionConfig.step_pause:
        input(f"[STEP] 即将点击 ({x},{y}) 屏幕({screen_x},{screen_y}) 回车继续...")

    if not _PAG:
        log.error("需要 pyautogui 才能点击")
        return False

    time.sleep(delay_before)
    pyautogui.click(screen_x, screen_y, clicks=clicks, button=button,
                    _pause=False)
    log.debug(f"点击 ({x},{y}) -> 屏幕({screen_x},{screen_y})")
    return True


def click_template(template_path, hwnd=None, roi=None, timeout=15, threshold=None):
    """查找模板并点击其中心。返回 True/False"""
    r = wait_for(template_path, hwnd=hwnd, roi=roi, timeout=timeout, threshold=threshold)
    if r:
        return click(r["x"], r["y"], hwnd=hwnd)
    return False


def press_key(key, presses=1, interval=0.1):
    """按键"""
    if VisionConfig.dry_run:
        log.info(f"[DRY-RUN] 按键 {key} [不执行]")
        return True
    if not _PAG:
        log.error("需要 pyautogui")
        return False
    if VisionConfig.step_pause:
        input(f"[STEP] 即将按键 {key} 回车继续...")
    for _ in range(presses):
        pyautogui.press(key, _pause=False)
        time.sleep(interval)
    log.debug(f"按键 {key}x{presses}")
    return True


def hotkey(*keys):
    """组合键,如 hotkey('alt','f4')"""
    if VisionConfig.dry_run:
        log.info(f"[DRY-RUN] 组合键 {keys} [不执行]")
        return True
    if not _PAG:
        log.error("需要 pyautogui")
        return False
    if VisionConfig.step_pause:
        input(f"[STEP] 即将组合键 {keys} 回车继续...")
    pyautogui.hotkey(*keys, _pause=False)
    log.debug(f"组合键 {keys}")
    return True


# ============================================================
# OCR 数字识别
# ============================================================
def ocr_region(hwnd, roi, digit_only=False, scale=2, psm=7):
    """
    OCR 识别窗口客户区 ROI 内的文字。
    roi: [x0,y0,x1,y1]
    digit_only: True 只识别数字
    返回识别到的字符串(已 strip)。
    """
    if not _TESS or not _CV2:
        log.error("需要 pytesseract + opencv")
        return ""

    result = grab_window(hwnd)
    if not result or result[0] is None:
        return ""
    screen, _ = result

    x0, y0, x1, y1 = roi
    x0, y0 = max(0, x0), max(0, y0)
    x1 = min(screen.shape[1], x1)
    y1 = min(screen.shape[0], y1)
    region = screen[y0:y1, x0:x1]
    if region.size == 0:
        return ""

    # 放大
    if scale != 1:
        h, w = region.shape[:2]
        region = cv2.resize(region, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    # 二值化(对数字更稳)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    config = f"--psm {psm}"
    if digit_only:
        config += " -c tessedit_char_whitelist=0123456789/"

    lang = "eng" if digit_only else "chi_sim+eng"
    try:
        text = pytesseract.image_to_string(gray, lang=lang, config=config)
        text = text.strip()
        log.debug(f"OCR roi={roi} -> {text!r}")
        return text
    except Exception as e:
        log.warning(f"OCR 失败: {e}")
        return ""


def read_number(hwnd, roi, scale=3, psm=7):
    """从 ROI 读取一个整数,返回 int 或 None"""
    text = ocr_region(hwnd, roi, digit_only=True, scale=scale, psm=psm)
    if not text:
        return None
    # 提取第一个数字
    import re
    m = re.search(r"\d+", text.replace(" ", ""))
    if m:
        try:
            return int(m.group())
        except ValueError:
            return None
    return None


def read_remaining_trusteeship(hwnd, cfg):
    """
    读取剩余托管次数。
    根据 settings.yaml 的 trusteeship_status 配置解析。
    返回 remaining (int) 或 None。
    """
    ts = cfg.get("trusteeship_status", {})
    roi = ts.get("remaining_count_roi", [])
    if not roi:
        log.warning("未配置托管次数 ROI,请运行校准工具")
        return None

    max_games = ts.get("max_games", 20)
    fmt = ts.get("display_format", "remaining/max")

    text = ocr_region(hwnd, roi, digit_only=True, scale=3, psm=7)
    log.info(f"托管次数 OCR 原文: {text!r}")

    import re
    # 匹配 X/Y 或单个 X
    m = re.search(r"(\d+)\s*/\s*(\d+)", text.replace(" ", ""))
    if m:
        first = int(m.group(1))
        second = int(m.group(2))
        if fmt == "current/max":
            remaining = second - first
        else:  # remaining/max
            remaining = first
        log.info(f"托管次数: 显示={first}/{second} 格式={fmt} 剩余={remaining}")
        return remaining

    # 单数字
    m = re.search(r"\d+", text.replace(" ", ""))
    if m:
        val = int(m.group())
        if fmt == "current/max":
            remaining = max_games - val
        else:
            remaining = val
        log.info(f"托管次数: 单值={val} 剩余={remaining}")
        return remaining

    log.warning(f"无法解析托管次数: {text!r}")
    return None
