"""
probe.py - 视觉探针工具
=====================================
解决"盲人摸象"问题:让用户随时看到程序"看到"了什么。

用法:
  python tools/probe.py              # 截WeGame当前画面,OCR+标注保存
  python tools/probe.py --window     # 选窗口截(交互式)
  python tools/probe.py --click      # 手动点一下,看点击后画面变化
  python tools/probe.py --diff       # 截两张图对比变化(点击前后)

输出:
  debug/probe_<timestamp>/
    raw.png           - 原始截图
    annotated.png     - OCR标注图(绿框+文字)
    detections.json    - 所有检测结果(坐标+文字+置信度)
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import cv2
import numpy as np

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBUG_DIR = os.path.join(PROJ_ROOT, "debug")


def ensure_paddleocr():
    """尝试用 PaddleOCR,失败则回退 Tesseract"""
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
        print("✓ 使用 PaddleOCR 引擎")
        return ('paddle', ocr)
    except ImportError:
        print("⚠ PaddleOCR 未安装,回退 Tesseract")
        print("  安装 PaddleOCR: pip install paddleocr paddlepaddle")
        return ('tesseract', None)


def ocr_screen(img, engine):
    """用指定引擎 OCR,返回检测结果列表"""
    results = []
    if engine[0] == 'paddle' and engine[1]:
        # PaddleOCR
        paddle = engine[1]
        res = paddle.ocr(img, cls=False)
        if res and res[0]:
            for line in res[0]:
                bbox, (text, conf) = line
                x0, y0 = int(bbox[0][0]), int(bbox[0][1])
                x1, y1 = int(bbox[2][0]), int(bbox[2][1])
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                results.append({
                    'text': text, 'x': cx, 'y': cy,
                    'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
                    'confidence': float(conf)
                })
    else:
        # Tesseract
        import pytesseract
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 放大2x
        h, w = gray.shape[:2]
        gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        data = pytesseract.image_to_data(
            gray, lang='chi_sim+eng', config='--psm 11',
            output_type=pytesseract.Output.DICT)
        blocks = {}
        for i in range(len(data['text'])):
            t = data['text'][i].strip()
            if not t:
                continue
            key = (data['block_num'][i], data['line_num'][i])
            if key not in blocks:
                blocks[key] = {'texts': [], 'x': data['left'][i],
                               'y': data['top'][i],
                               'x1': data['left'][i] + data['width'][i],
                               'y1': data['top'][i] + data['height'][i],
                               'conf': float(data['conf'][i])}
            blocks[key]['texts'].append(t)
            blocks[key]['x'] = min(blocks[key]['x'], data['left'][i])
            blocks[key]['y'] = min(blocks[key]['y'], data['top'][i])
            blocks[key]['x1'] = max(blocks[key]['x1'], data['left'][i] + data['width'][i])
            blocks[key]['y1'] = max(blocks[key]['y1'], data['top'][i] + data['height'][i])
        for b in blocks.values():
            full = ''.join(b['texts']).replace(' ', '')
            results.append({
                'text': full,
                'x0': b['x'] // 2, 'y0': b['y'] // 2,
                'x1': b['x1'] // 2, 'y1': b['y1'] // 2,
                'x': (b['x'] + b['x1']) // 4,
                'y': (b['y'] + b['y1']) // 4,
                'confidence': b['conf'] / 100
            })
    return results


def find_numbers(detections):
    """从检测结果中找纯数字(≥6位)"""
    return [d for d in detections
            if d['text'].isdigit() and len(d['text']) >= 6]


def annotate(img, detections, numbers=None):
    """在图上画标注:绿框=文字,蓝框=数字,红框=点击建议"""
    canvas = img.copy()
    for d in detections:
        color = (0, 255, 0)  # 绿
        cv2.rectangle(canvas, (d['x0'], d['y0']), (d['x1'], d['y1']), color, 2)
        label = d['text'][:20]
        cv2.putText(canvas, label, (d['x0'], max(d['y0'] - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    if numbers:
        for n in numbers:
            cv2.rectangle(canvas, (n['x0'], n['y0']), (n['x1'], n['y1']),
                          (255, 0, 0), 3)  # 蓝
            cv2.putText(canvas, f"QQ:{n['text']}", (n['x0'], n['y1'] + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
    # 缩小显示
    h, w = canvas.shape[:2]
    max_w = 1600
    if w > max_w:
        scale = max_w / w
        canvas = cv2.resize(canvas, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    return canvas


def grab_window(hwnd):
    """截取窗口客户区"""
    import window_utils
    rect = window_utils.get_client_rect_screen(hwnd)
    if not rect:
        return None
    x, y, w, h = rect
    import mss
    with mss.MSS() as sct:
        monitor = {"left": x, "top": y, "width": w, "height": h}
        shot = sct.grab(monitor)
        return np.array(shot)[:, :, :3]


def probe_once(hwnd, tag="probe"):
    """执行一次探针:截图→OCR→标注→保存→显示"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(DEBUG_DIR, f"probe_{tag}_{ts}")
    os.makedirs(outdir, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"探针: {tag}")
    print(f"输出目录: {outdir}")
    print(f"{'='*50}")

    img = grab_window(hwnd)
    if img is None:
        print("✗ 截图失败")
        return

    # 保存原图
    raw_path = os.path.join(outdir, "raw.png")
    cv2.imwrite(raw_path, img)
    print(f"✓ 原图: {raw_path} ({img.shape[1]}x{img.shape[0]})")

    # OCR
    engine = ensure_paddleocr()
    detections = ocr_screen(img, engine)
    print(f"\nOCR 检测到 {len(detections)} 个文字块:")
    for d in sorted(detections, key=lambda x: (x['y'], x['x'])):
        print(f"  ({d['x']:5d},{d['y']:5d}) conf={d['confidence']:.2f}  {d['text']}")

    # 找数字
    numbers = find_numbers(detections)
    print(f"\n找到 {len(numbers)} 个QQ号:")
    for n in numbers:
        print(f"  QQ:{n['text']} 位置=({n['x']},{n['y']})")

    # 标注图
    annotated = annotate(img, detections, numbers)
    ann_path = os.path.join(outdir, "annotated.png")
    cv2.imwrite(ann_path, annotated)
    print(f"\n✓ 标注图: {ann_path}")

    # JSON
    data = {
        'timestamp': ts, 'tag': tag,
        'image_size': [img.shape[1], img.shape[0]],
        'detections': detections,
        'numbers': numbers
    }
    json_path = os.path.join(outdir, "detections.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON: {json_path}")

    # 显示
    cv2.imshow("Probe (按任意键关闭)", annotated)
    print("\n弹出窗口显示标注结果,按任意键关闭...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return outdir


def diff_mode(hwnd):
    """点击前后对比:截前→用户手动操作→截后→对比变化"""
    print("\n=== 变化检测模式 ===")
    print("1. 先截当前画面(操作前)")
    input("按回车截'操作前'画面...")
    ts1 = time.strftime("%Y%m%d_%H%M%S")
    img_before = grab_window(hwnd)
    if img_before is None:
        print("✗ 截图失败")
        return

    print("\n2. 现在手动操作(比如点下拉箭头)")
    print("   操作完后按回车截'操作后'画面")
    input("按回车截'操作后'画面...")
    img_after = grab_window(hwnd)
    if img_after is None:
        print("✗ 截图失败")
        return

    # 计算差异
    if img_before.shape == img_after.shape:
        diff = cv2.absdiff(img_before, img_after)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray_diff, 30, 255, cv2.THRESH_BINARY)
        # 找变化区域
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        changes = []
        for c in contours:
            if cv2.contourArea(c) > 100:
                x, y, w, h = cv2.boundingRect(c)
                changes.append({'x': x, 'y': y, 'w': w, 'h': h,
                                'cx': x + w//2, 'cy': y + h//2})

        # 在 after 图上标注变化区域(红框)
        annotated = img_after.copy()
        for ch in changes:
            cv2.rectangle(annotated, (ch['x'], ch['y']),
                          (ch['x']+ch['w'], ch['y']+ch['h']), (0, 0, 255), 3)

        # OCR 前后对比
        engine = ensure_paddleocr()
        det_before = ocr_screen(img_before, engine)
        det_after = ocr_screen(img_after, engine)

        texts_before = {d['text'] for d in det_before}
        texts_after = {d['text'] for d in det_after}
        new_texts = texts_after - texts_before
        gone_texts = texts_before - texts_after

        outdir = os.path.join(DEBUG_DIR, f"diff_{ts1}")
        os.makedirs(outdir, exist_ok=True)
        cv2.imwrite(os.path.join(outdir, "before.png"), img_before)
        cv2.imwrite(os.path.join(outdir, "after.png"), img_after)
        cv2.imwrite(os.path.join(outdir, "diff_annotated.png"), annotated)
        cv2.imwrite(os.path.join(outdir, "diff_raw.png"), diff)

        print(f"\n{'='*50}")
        print(f"变化检测结果 (输出: {outdir})")
        print(f"{'='*50}")
        print(f"\n变化区域: {len(changes)} 个")
        for ch in changes:
            print(f"  ({ch['cx']},{ch['cy']}) 尺寸={ch['w']}x{ch['h']}")
        print(f"\n新增文字: {new_texts if new_texts else '无'}")
        print(f"消失文字: {gone_texts if gone_texts else '无'}")
        print(f"\n操作后 OCR 结果:")
        for d in sorted(det_after, key=lambda x: (x['y'], x['x'])):
            tag = " [新增]" if d['text'] in new_texts else ""
            print(f"  ({d['x']:5d},{d['y']:5d})  {d['text']}{tag}")

        cv2.imshow("Before (按任意键看After)", annotate(img_before, det_before))
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        cv2.imshow("After + Changes (按任意键关闭)", annotated)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    else:
        print("✗ 两张图尺寸不同,无法对比")


def main():
    parser = argparse.ArgumentParser(description="视觉探针工具")
    parser.add_argument('--window', action='store_true', help='交互式选窗口')
    parser.add_argument('--diff', action='store_true', help='变化检测:操作前后对比')
    args = parser.parse_args()

    import window_utils

    # 找 WeGame 窗口
    hwnd = window_utils.find_window(["WeGame"])
    if not hwnd:
        print("✗ 未找到 WeGame 窗口")
        print("  如果 WeGame 窗口标题不同,请手动指定:")
        print("  修改 tools/probe.py 里的窗口关键词")
        return

    print(f"✓ WeGame 窗口: hwnd={hwnd}")
    window_utils.activate_window(hwnd)
    time.sleep(1)

    if args.diff:
        diff_mode(hwnd)
    else:
        probe_once(hwnd, tag="manual")


if __name__ == "__main__":
    main()
