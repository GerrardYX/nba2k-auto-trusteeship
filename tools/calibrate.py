"""
calibrate.py - Windows 端校准与模板采集工具
============================================================
这是整个项目能跑起来的关键工具。由于不同电脑分辨率/缩放/窗口位置不同,
所有 UI 元素的精确位置必须在你的 Windows 机器上现场标定。

功能:
  1. capture  - 对当前画面截图,你框选区域裁剪成模板(存入 images/)
  2. list     - 查看已有模板
  3. test     - 测试某个模板能否在当前画面匹配到(带可视化框)
  4. ocr      - 框选区域做 OCR 识别(用于校准托管次数区域)
  5. coords   - 点击采集坐标(用于账号列表位置)
  6. autorun  - 引导式完整校准(一步步带你走完全部模板)

用法:
  python tools/calibrate.py autorun       # 推荐:引导式完整校准
  python tools/calibrate.py capture wegame nba2k_icon
  python tools/calibrate.py test game start_match_button
  python tools/calibrate.py ocr
  python tools/calibrate.py coords
  python tools/calibrate.py list
"""
import argparse
import os
import sys
import time

# 加入 src 路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import cv2
import numpy as np

try:
    import mss
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("请先安装 pyyaml")
    sys.exit(1)

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    print("请先安装 pyautogui")
    sys.exit(1)

try:
    import pytesseract
    HAS_TESS = True
except ImportError:
    HAS_TESS = False
    print("⚠ 未安装 pytesseract,OCR 功能不可用")


PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_BASE = os.path.join(PROJ_ROOT, "images")
CONFIG_PATH = os.path.join(PROJ_ROOT, "config", "settings.yaml")


def grab_full():
    """截取全屏"""
    with mss.MSS() as sct:
        shot = sct.grab(sct.monitors[1])
        return np.array(shot)[:, :, :3]


def save_template(img, category, name):
    """保存模板到 images/<category>/<name>.png"""
    d = os.path.join(IMG_BASE, category)
    os.makedirs(d, exist_ok=True)
    if not name.endswith(".png"):
        name += ".png"
    path = os.path.join(d, name)
    cv2.imwrite(path, img)
    print(f"✓ 模板已保存: {path}")
    return path


def interactive_crop(img, title="框选区域(拖拽选择,按回车确认)"):
    """
    交互式框选区域。用 OpenCV 窗口拖拽选择矩形。
    返回裁剪后的图像或 None。
    """
    roi = cv2.selectROI(title, img, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()
    if roi[2] == 0 or roi[3] == 0:
        print("未选择区域")
        return None
    x, y, w, h = roi
    return img[y:y+h, x:x+w]


def interactive_point(img, title="点击选择一个点(任意键确认)"):
    """交互式选择一个点坐标"""
    clicked = []
    def _on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked.append((x, y))
            cv2.circle(param[1], (x, y), 5, (0, 0, 255), -1)
            cv2.imshow(param[0], param[1])
    disp = img.copy()
    cv2.imshow(title, disp)
    cv2.setMouseCallback(title, _on_click, [title, disp])
    print("在窗口中点击目标位置,然后按任意键确认...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    return clicked[-1] if clicked else None


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"✓ 配置已保存: {CONFIG_PATH}")


# ============================================================
# 命令实现
# ============================================================
def cmd_capture(args):
    """截图并裁剪模板"""
    print(f"3 秒后截屏,请切到目标界面...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    img = grab_full()
    print("请在弹出的窗口中框选要作为模板的区域")
    cropped = interactive_crop(img, "框选模板区域")
    if cropped is not None:
        save_template(cropped, args.category, args.name)
    else:
        print("取消")


def cmd_test(args):
    """测试模板匹配"""
    tpl_path = os.path.join(IMG_BASE, args.category, args.name)
    if not tpl_path.endswith(".png"):
        tpl_path += ".png"
    if not os.path.exists(tpl_path):
        print(f"模板不存在: {tpl_path}")
        return
    template = cv2.imread(tpl_path)
    print("3 秒后截屏测试匹配...")
    time.sleep(3)
    screen = grab_full()

    # 灰度匹配
    s = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    t = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    print(f"最高置信度: {max_val:.4f}  位置: ({max_loc[0]+t.shape[1]//2}, {max_loc[1]+t.shape[0]//2})")
    threshold = args.threshold or 0.82
    if max_val >= threshold:
        print(f"✓ 匹配成功 (>= {threshold})")
    else:
        print(f"✗ 匹配失败 (< {threshold})")

    # 可视化
    disp = screen.copy()
    color = (0, 255, 0) if max_val >= threshold else (0, 0, 255)
    cv2.rectangle(disp, max_loc,
                  (max_loc[0]+t.shape[1], max_loc[1]+t.shape[0]), color, 3)
    cv2.putText(disp, f"{max_val:.3f}", (max_loc[0], max_loc[1]-10),
                cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    # 缩放显示(4K 太大)
    h, w = disp.shape[:2]
    if w > 1920:
        scale = 1920 / w
        disp = cv2.resize(disp, (int(w*scale), int(h*scale)))
    cv2.imshow("匹配结果(按任意键关闭)", disp)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def cmd_ocr(args):
    """框选区域做 OCR"""
    if not HAS_TESS:
        print("需要 pytesseract")
        return
    print("3 秒后截屏...")
    time.sleep(3)
    img = grab_full()
    print("框选要 OCR 的区域")
    cropped = interactive_crop(img, "框选 OCR 区域")
    if cropped is None:
        return
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    # 放大
    h, w = gray.shape[:2]
    gray = cv2.resize(gray, (w*3, h*3), interpolation=cv2.INTER_CUBIC)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    lang = "chi_sim+eng"
    config = "--psm 7"
    if args.digits:
        lang = "eng"
        config += " -c tessedit_char_whitelist=0123456789/"
    text = pytesseract.image_to_string(gray, lang=lang, config=config)
    print(f"OCR 结果: {text!r}")
    # 同时显示图像
    cv2.imshow("OCR 区域(按任意键关闭)", gray)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def cmd_coords(args):
    """采集点击坐标,写入配置"""
    print("3 秒后截屏...")
    time.sleep(3)
    img = grab_full()
    print("点击要采集的位置")
    pt = interactive_point(img, "点击目标位置")
    if pt:
        print(f"采集坐标: ({pt[0]}, {pt[1]})")
        cfg = load_config()
        # 写入指定配置项
        section, key = args.target.split(".")
        cfg.setdefault(section, {})[key] = [pt[0], pt[1]]
        save_config(cfg)


def cmd_list(args):
    """列出所有模板"""
    for cat in ["wegame", "game", "common"]:
        d = os.path.join(IMG_BASE, cat)
        if os.path.isdir(d):
            files = [f for f in os.listdir(d) if f.endswith(".png")]
            if files:
                print(f"\n[{cat}/] ({len(files)} 个)")
                for f in sorted(files):
                    print(f"  {f}")
            else:
                print(f"\n[{cat}/] (空)")


# ============================================================
# 引导式完整校准
# ============================================================
# 校准步骤定义:(步骤名, 分类, 模板名, 说明, 画面准备提示)
CALIBRATE_STEPS = [
    ("NBA2K图标", "wegame", "nba2k_icon",
     "WeGame 左侧游戏列表中的 NBA2K Online2 图标",
     "请打开 WeGame,停在主页(能看到左侧游戏列表)"),
    ("启动按钮", "wegame", "start_button",
     "WeGame 右下角'启动'按钮",
     "请选中 NBA2K,让右下角出现'启动'按钮"),
    ("头像按钮", "wegame", "avatar_button",
     "WeGame 右上角的账号头像(点开切换菜单)",
     "WeGame 主页,右上角头像区域"),
    ("切换账号菜单项", "wegame", "switch_account_item",
     "点开头像后弹出的'切换账号'菜单项文字",
     "请点开右上角头像,让菜单弹出,能看到'切换账号'"),
    ("公告关闭按钮", "game", "announcement_close",
     "游戏内公告弹窗右上角的关闭 × 按钮",
     "进入游戏,等公告弹窗出现"),
    ("主界面标志", "game", "main_menu_marker",
     "游戏主界面任意标志性元素(如左上角 LOGO 或玩家信息)",
     "关掉公告后,停在游戏主界面"),
    ("开始比赛按钮", "game", "start_match_button",
     "主界面下方'开始比赛'按钮",
     "停在游戏主界面,能看到底部菜单"),
    ("排位赛页签", "game", "ranked_tab",
     "点击开始比赛后,上方的'排位赛 S32'页签",
     "点开始比赛后,停留在模式选择界面"),
    ("排位经理入口", "game", "manager_entry",
     "排位赛界面左侧的'排位经理'入口",
     "进入排位赛界面,能看到左侧选项"),
    ("连续托管选项", "game", "continuous_trustee_option",
     "经理模式界面右侧'连续托管'选项文字",
     "进入经理模式界面,能看到连续托管/单场自动"),
    ("进入按钮", "game", "enter_button",
     "连续托管旁的'进入'按钮",
     "经理模式界面(如有独立进入按钮)"),
    ("关按钮(OFF)", "game", "off_button",
     "ESC 菜单中连续托管右侧的'关/OFF'按钮",
     "游戏中按 ESC,找到托管模式开关旁的'关'按钮"),
    ("比赛结算页", "game", "result_page",
     "比赛结束的结算页面标志性元素",
     "等一场比赛结束,停在结算页"),
]


def cmd_autorun(args):
    """引导式完整校准"""
    print("=" * 60)
    print("  引导式校准 - 一步步采集所有模板")
    print("=" * 60)
    print("说明:")
    print("  每一步会:1)提示你准备画面 2)3秒后截屏 3)你框选区域")
    print("  可随时按 Ctrl+C 跳过当前步骤(该模板留空,后续再补)")
    print("  已采集的步骤会跳过(除非加 --force)\n")

    skip_existing = not args.force
    todo = []
    for name, cat, fname, desc, prep in CALIBRATE_STEPS:
        path = os.path.join(IMG_BASE, cat, fname + ".png")
        if skip_existing and os.path.exists(path):
            print(f"  ✓ 已存在,跳过: {name}")
            continue
        todo.append((name, cat, fname, desc, prep))

    if not todo:
        print("\n所有模板已采集完成!")
        print("接下来请运行: python tools/calibrate.py ocr  (校准托管次数区域)")
        print("           以及: python tools/calibrate.py coords (校准账号列表位置)")
        return

    print(f"共 {len(todo)} 个模板待采集\n")

    for i, (name, cat, fname, desc, prep) in enumerate(todo, 1):
        print(f"\n{'─'*50}")
        print(f"步骤 {i}/{len(todo)}: {name}")
        print(f"说明: {desc}")
        print(f"准备: {prep}")
        print(f"{'─'*50}")
        try:
            input("准备好后按回车开始截屏...")
        except (EOFError, KeyboardInterrupt):
            print("跳过")
            continue

        try:
            print("3 秒后截屏...")
            for c in range(3, 0, -1):
                print(f"  {c}...")
                time.sleep(1)
            img = grab_full()
            print(f"请框选【{name}】区域,选好后按回车/空格确认")
            cropped = interactive_crop(img, f"框选: {name}")
            if cropped is not None:
                save_template(cropped, cat, fname)
                # 立即测试
                print("测试匹配...")
                t = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
                s = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                res = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                print(f"  自匹配置信度: {max_val:.4f} ({'✓良好' if max_val>0.9 else '⚠ 偏低,建议重选'})")
            else:
                print("未选择,跳过")
        except KeyboardInterrupt:
            print("跳过本步")

    print(f"\n{'='*50}")
    print("模板采集完成!")
    print(f"{'='*50}")
    print("\n后续校准:")
    print("  1. 托管次数区域: python tools/calibrate.py ocr --digits")
    print("     (在 ESC 菜单中框选剩余次数数字区域)")
    print("  2. 账号列表坐标: 手动编辑 config/settings.yaml 的 account_list")
    print("     或运行 python tools/calibrate.py coords --target account_list.first_item_y")
    print("\n全部完成后,用调试模式验证:")
    print("  python src/main.py --dry-run")


def main():
    parser = argparse.ArgumentParser(description="校准与模板采集工具")
    sub = parser.add_subparsers(dest="command")

    p_cap = sub.add_parser("capture", help="截图裁剪模板")
    p_cap.add_argument("category", choices=["wegame", "game", "common"])
    p_cap.add_argument("name", help="模板名(不含扩展名)")
    p_cap.set_defaults(func=cmd_capture)

    p_test = sub.add_parser("test", help="测试模板匹配")
    p_test.add_argument("category", choices=["wegame", "game", "common"])
    p_test.add_argument("name", help="模板名")
    p_test.add_argument("--threshold", type=float, default=None)
    p_test.set_defaults(func=cmd_test)

    p_ocr = sub.add_parser("ocr", help="框选区域 OCR")
    p_ocr.add_argument("--digits", action="store_true", help="只识别数字")
    p_ocr.set_defaults(func=cmd_ocr)

    p_coord = sub.add_parser("coords", help="采集坐标写入配置")
    p_coord.add_argument("--target", required=True, help="配置项 如 account_list.first_item_y")
    p_coord.set_defaults(func=cmd_coords)

    p_list = sub.add_parser("list", help="列出已有模板")
    p_list.set_defaults(func=cmd_list)

    p_auto = sub.add_parser("autorun", help="引导式完整校准(推荐)")
    p_auto.add_argument("--force", action="store_true", help="重新采集所有(含已有)")
    p_auto.set_defaults(func=cmd_autorun)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
