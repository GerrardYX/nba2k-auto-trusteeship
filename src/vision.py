"""
vision.py - 图像识别与 OCR 引擎(纯元素识别,无硬编码坐标)
核心能力:
  - OCR 文字查找/点击(find_text, click_text)
  - OCR 可视化调试(visual_debug,让用户看到程序识别到什么)
  - 屏幕截图(基于窗口客户区)
  - 模板匹配(备用,多尺度)
"""
import os
import time
import platform

import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
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
    # Windows 自动找 tesseract
    if platform.system() == "Windows":
        for p in [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
    _TESS = True
except ImportError:
    _TESS = False

import window_utils
from logger import get_logger, Logger

log = get_logger()


class VisionConfig:
    dry_run = False
    step_pause = False


def load_config(config_path="config/settings.yaml"):
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        rt = cfg.get("runtime", {})
        mode = rt.get("mode", "normal")
        VisionConfig.dry_run = (mode == "dry_run")
        VisionConfig.step_pause = (mode == "step_pause")
    except Exception as e:
        log.warning(f"加载配置失败: {e}")


# ============================================================
# 截图
# ============================================================
def grab_screen(region=None):
    if _MSS:
        with mss.MSS() as sct:
            if region:
                monitor = {"left": region[0], "top": region[1],
                           "width": region[2], "height": region[3]}
            else:
                monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            return np.array(shot)[:, :, :3]
    elif _PAG:
        im = pyautogui.screenshot(region=region if region else None)
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR) if _CV2 else None
    else:
        log.error("无可用截图库")
        return None


def grab_window(hwnd):
    rect = window_utils.get_client_rect_screen(hwnd)
    if not rect:
        return None
    x, y, w, h = rect
    return grab_screen((x, y, w, h)), rect


def save_screenshot(path, region=None):
    img = grab_screen(region)
    if img is not None and _CV2:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        cv2.imwrite(path, img)
        return True
    return False


Logger.set_screenshot_func(save_screenshot)


# ============================================================
# OCR 文字查找与点击(核心:纯元素识别)
# ============================================================
def _ocr_full(hwnd, roi=None):
    """对窗口截图做 OCR,返回所有文字块的列表"""
    if not _TESS or not _CV2:
        log.error("需要 pytesseract + opencv")
        return []

    result = grab_window(hwnd)
    if not result or result[0] is None:
        return []
    screen, _ = result

    search_area = screen
    off_x, off_y = 0, 0
    if roi:
        x0, y0, x1, y1 = roi
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(screen.shape[1], x1)
        y1 = min(screen.shape[0], y1)
        if x1 <= x0 or y1 <= y0:
            return []
        search_area = screen[y0:y1, x0:x1]
        off_x, off_y = x0, y0

    # 放大2x提升精度
    sh, sw = search_area.shape[:2]
    scaled = cv2.resize(search_area, (sw * 2, sh * 2),
                        interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)

    try:
        data = pytesseract.image_to_data(
            gray, lang='chi_sim+eng', config='--psm 11',
            output_type=pytesseract.Output.DICT)
    except Exception as e:
        log.error(f"OCR 失败(检查 Tesseract 安装): {e}")
        return []

    # 合并同行文字块
    blocks = {}
    for i in range(len(data['text'])):
        t = data['text'][i].strip()
        if not t:
            continue
        key = (data['block_num'][i], data['line_num'][i])
        if key not in blocks:
            blocks[key] = {'texts': [], 'x': data['left'][i], 'y': data['top'][i],
                           'x1': data['left'][i] + data['width'][i],
                           'y1': data['top'][i] + data['height'][i]}
        blocks[key]['texts'].append(t)
        blocks[key]['x'] = min(blocks[key]['x'], data['left'][i])
        blocks[key]['y'] = min(blocks[key]['y'], data['top'][i])
        blocks[key]['x1'] = max(blocks[key]['x1'], data['left'][i] + data['width'][i])
        blocks[key]['y1'] = max(blocks[key]['y1'], data['top'][i] + data['height'][i])

    results = []
    for key, b in blocks.items():
        full = ''.join(b['texts']).replace(' ', '')
        # 还原到原图坐标(除以2缩放 + 偏移)
        cx = int((b['x'] + b['x1']) / 2 / 2) + off_x
        cy = int((b['y'] + b['y1']) / 2 / 2) + off_y
        results.append({'text': full, 'x': cx, 'y': cy,
                        'x0': int(b['x'] / 2) + off_x,
                        'y0': int(b['y'] / 2) + off_y,
                        'x1': int(b['x1'] / 2) + off_x,
                        'y1': int(b['y1'] / 2) + off_y})
    return results


def find_text(hwnd, text, roi=None, timeout=10, interval=0.8, partial=True):
    """
    OCR 查找文字,返回中心坐标或 None。
    partial: True=包含匹配(如"开始"匹配"开始比赛")
    """
    log.info(f"OCR 查找 [{text}] 超时={timeout}s")
    target = text.replace(' ', '')
    start = time.time()

    while True:
        blocks = _ocr_full(hwnd, roi)
        for b in blocks:
            if partial:
                match = target in b['text'] or b['text'] in target
            else:
                match = (b['text'] == target)
            if match:
                log.info(f"✓ 找到 [{text}] 于 ({b['x']},{b['y']}) 原文={b['text']}")
                return b
        if time.time() - start >= timeout:
            log.warning(f"✗ 未找到 [{text}]")
            if timeout > 0:
                Logger.screenshot(f"ocr_fail_{text}")
            return None
        time.sleep(interval)


def find_any_text(hwnd, texts, roi=None, timeout=10, interval=0.8, partial=True):
    """查找多个文字中任一"""
    log.info(f"OCR 查找任一 {texts} 超时={timeout}s")
    start = time.time()
    while time.time() - start < timeout:
        blocks = _ocr_full(hwnd, roi)
        for b in blocks:
            for t in texts:
                target = t.replace(' ', '')
                if partial:
                    match = target in b['text'] or b['text'] in target
                else:
                    match = (b['text'] == target)
                if match:
                    log.info(f"✓ 找到 [{t}] 于 ({b['x']},{b['y']})")
                    return (t, b)
        if timeout == 0:
            return None
        time.sleep(interval)
    log.warning(f"✗ 未找到 {texts}")
    return None


def find_all_numbers(hwnd, roi=None, timeout=5):
    """查找窗口中所有纯数字块(用于找QQ号),返回列表"""
    log.info(f"OCR 查找数字 超时={timeout}s")
    start = time.time()
    while True:
        blocks = _ocr_full(hwnd, roi)
        numbers = []
        for b in blocks:
            t = b['text']
            if t.isdigit() and len(t) >= 6:
                numbers.append(b)
        if numbers:
            numbers.sort(key=lambda a: a['y'])
            log.info(f"找到 {len(numbers)} 个数字: {[n['text'] for n in numbers]}")
            return numbers
        if time.time() - start >= timeout:
            return []
        time.sleep(0.5)


def click_text(hwnd, text, roi=None, timeout=10, partial=True):
    """OCR 查找文字并点击"""
    r = find_text(hwnd, text, roi=roi, timeout=timeout, partial=partial)
    if r:
        return click(r['x'], r['y'], hwnd=hwnd)
    return False


# ============================================================
# 可视化调试:让用户看到程序"看到"了什么
# ============================================================
def visual_debug(hwnd, title="OCR Debug"):
    """
    截图窗口,OCR 识别所有文字,画框标注,显示给用户。
    让用户直观看到程序识别到了哪些文字、在什么位置。
    纯鼠标关闭(点击窗口按任意键或关闭)。
    """
    if not _CV2 or not _TESS:
        log.error("需要 cv2 + pytesseract")
        return

    result = grab_window(hwnd)
    if not result or result[0] is None:
        log.error("截图失败")
        return
    screen, _ = result

    # 缩小显示(4K等大图)
    h, w = screen.shape[:2]
    max_w = 1600
    scale = 1.0
    disp = screen
    if w > max_w:
        scale = max_w / w
        disp = cv2.resize(screen, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_AREA)

    blocks = _ocr_full(hwnd)
    # 在缩小图上画框
    for b in blocks:
        x0 = int(b['x0'] * scale)
        y0 = int(b['y0'] * scale)
        x1 = int(b['x1'] * scale)
        y1 = int(b['y1'] * scale)
        cv2.rectangle(disp, (x0, y0), (x1, y1), (0, 255, 0), 2)
        # 标注文字(缩小后可能太小,截断)
        label = b['text'][:15]
        cv2.putText(disp, label, (x0, max(y0 - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

    log.info(f"OCR 识别到 {len(blocks)} 个文字块")
    for b in blocks:
        log.info(f"  ({b['x']},{b['y']}) {b['text']}")

    cv2.imshow(title, disp)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# ============================================================
# 点击
# ============================================================
def click(x, y, hwnd=None, button="left", clicks=1, delay_before=0.2):
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
        input(f"[STEP] 即将点击 ({x},{y}) 回车继续...")

    if not _PAG:
        log.error("需要 pyautogui")
        return False

    time.sleep(delay_before)
    pyautogui.click(screen_x, screen_y, clicks=clicks, button=button, _pause=False)
    log.debug(f"点击 ({x},{y}) -> 屏幕({screen_x},{screen_y})")
    return True


def click_relative_to(element, dx, dy, hwnd=None):
    """
    在找到的元素旁边点击(相对偏移)。
    element: find_text 返回的 {'x','y',...}
    dx, dy: 相对元素中心的偏移(像素)
    用于点击元素旁边的图标(如账号号旁边的下拉箭头)。
    """
    x = element['x'] + dx
    y = element['y'] + dy
    log.info(f"在元素 {element.get('text','')} 旁偏移({dx},{dy}) 点击 ({x},{y})")
    return click(x, y, hwnd=hwnd)


def press_key(key, presses=1, interval=0.1):
    if VisionConfig.dry_run:
        log.info(f"[DRY-RUN] 按键 {key}")
        return True
    if not _PAG:
        return False
    if VisionConfig.step_pause:
        input(f"[STEP] 按键 {key} 回车继续...")
    for _ in range(presses):
        pyautogui.press(key, _pause=False)
        time.sleep(interval)
    return True


def hotkey(*keys):
    if VisionConfig.dry_run:
        log.info(f"[DRY-RUN] 组合键 {keys}")
        return True
    if not _PAG:
        return False
    if VisionConfig.step_pause:
        input(f"[STEP] 组合键 {keys} 回车继续...")
    pyautogui.hotkey(*keys, _pause=False)
    return True


# ============================================================
# OCR 数字识别
# ============================================================
def ocr_region(hwnd, roi, digit_only=False, scale=2, psm=7):
    if not _TESS or not _CV2:
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
    if scale != 1:
        h, w = region.shape[:2]
        region = cv2.resize(region, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    config = f"--psm {psm}"
    if digit_only:
        config += " -c tessedit_char_whitelist=0123456789/"
    lang = "eng" if digit_only else "chi_sim+eng"
    try:
        text = pytesseract.image_to_string(gray, lang=lang, config=config)
        return text.strip()
    except Exception as e:
        log.warning(f"OCR 失败: {e}")
        return ""


def read_remaining_trusteeship(hwnd, cfg):
    """
    读取剩余托管次数。
    用 OCR 在全窗口找 X/Y 格式的数字(如 15/20)。
    """
    ts = cfg.get("trusteeship_status", {})
    max_games = ts.get("max_games", 20)
    fmt = ts.get("display_format", "remaining/max")
    roi = ts.get("remaining_count_roi", [])

    if roi:
        text = ocr_region(hwnd, roi, digit_only=True, scale=3, psm=7)
    else:
        # 自动:在所有OCR文字块里找 X/Y 格式
        log.info("自动搜索托管次数...")
        blocks = _ocr_full(hwnd)
        import re
        for b in blocks:
            m = re.search(r'(\d+)\s*/\s*(\d+)', b['text'])
            if m:
                text = b['text']
                log.info(f"找到数字: {text} 于 ({b['x']},{b['y']})")
                break
        else:
            text = ""

    log.info(f"托管次数 OCR: {text!r}")

    import re
    m = re.search(r'(\d+)\s*/\s*(\d+)', text.replace(' ', ''))
    if m:
        first = int(m.group(1))
        second = int(m.group(2))
        remaining = first if fmt == "remaining/max" else second - first
        log.info(f"托管次数: {first}/{second} 剩余={remaining}")
        return remaining

    m = re.search(r'\d+', text.replace(' ', ''))
    if m:
        val = int(m.group())
        remaining = val if fmt == "remaining/max" else max_games - val
        log.info(f"托管次数: {val} 剩余={remaining}")
        return remaining

    log.warning("无法解析托管次数")
    return None
