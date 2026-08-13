# 项目交接文档 — 给接手开发的 Agent

## 项目概述
NBA2K Online2 多账号连续托管自动化工具。在 Windows 上自动轮转 6 个 WeGame 账号,每个账号进游戏挂机 2 小时后收号,循环直到 6 个账号全部完成。

GitHub 仓库: https://github.com/GerrardYX/nba2k-auto-trusteeship
代码已 clone 到: C:\Users\Administrator\nba2k-auto-trusteeship

## 当前状态(截至 2026-08-12)

### 已完成
- 项目骨架完整(src/ 7个模块 + tools/ 2个工具 + config/)
- OCR 文字识别引擎(Tesseract)
- DPI 感知(SetProcessDpiAwareness)
- 键盘直输登录(绕过下拉列表)
- 颜色检测找按钮(登录/启动)
- 防息屏、状态持久化、断点续跑
- 视觉探针工具(tools/probe.py)
- 校准工具(tools/calibrate.py)

### 已验证能工作
- ✅ WeGame 窗口查找(hwnd)
- ✅ OCR 能识别"自动登录"、"扫码登录"(判断在登录界面)
- ✅ OCR 能找到 QQ 号"1084987493"(纯数字≥6位)
- ✅ 防息屏、状态持久化

### 当前卡点
1. **WeGame 登录**:键盘直输 QQ 号的逻辑已写好但**未实测**(DPI 修复后可能就能用了)
2. **"启动"按钮**:OCR 找不到(是图片渲染按钮),改用颜色检测,未实测
3. **账号切换**:从主界面回登录界面的流程未实测

## 技术栈
- Python 3.14(Windows 上实际运行版本,注意 paddlepaddle 不支持 3.14)
- opencv-python(注意:用完整版不是 headless,校准工具需要 GUI)
- pytesseract + Tesseract OCR(已安装在 C:\Program Files\Tesseract-OCR,含中文包)
- pyautogui, pywin32, mss, Pillow, pyyaml

## 核心设计决策(重要!)

### 1. DPI 感知(最关键)
程序最开头必须执行:
```python
ctypes.windll.shcore.SetProcessDpiAwareness(2)
```
否则在 250% 缩放屏上,截图坐标和点击坐标差 2.5 倍,所有点击都会偏。

### 2. 元素定位策略(混合方案,按优先级)
按 Fable5 建议的决策链:
1. **键盘直输**(账号/密码框)→ 绕过所有列表交互
2. **颜色检测**(大色块按钮,如"登录""启动")→ HSV inRange + findContours
3. **模板匹配**(图标类小目标,如箭头)→ cv2.matchTemplate 多尺度
4. **OCR**(Tesseract)→ 只用于文字识别和状态验证

### 3. 跨分辨率
- 两台电脑:2560×1440 和 3840×2160
- 所有坐标基于 WeGame 窗口客户区(非全屏坐标)
- 模板匹配用多尺度搜索(0.8x~1.5x)

## 完整流程
```
每个账号:
  1. WeGame 登录界面 → 找账号框 → Ctrl+A → 输入QQ号 → 点"登录"按钮
  2. 主界面 → 找"NBA2K" → 点"启动"按钮
  3. 游戏启动 → 关公告 → "开始比赛" → "排位赛" → "排位经理" → "连续托管" → "进入"
  4. 托管2h → ESC → OCR读剩余次数 → ≤14点"关" → 等比赛结束 → Alt+F4关游戏
  5. 回WeGame → "切换账号" → 回登录界面 → 下一个账号
```

## 账号列表(6个,按顺序)
1. 3797341146
2. 3128628019
3. 2325467435
4. 782738645
5. 3838904066
6. 1084987493

## WeGame 登录界面 UI
- 账号输入框:显示当前 QQ 号后几位,右侧有下拉箭头(图标,非文字)
- 密码框:显示密码圆点
- "记住密码" / "自动登录" 勾选框
- "登录"按钮:橙色大色块(颜色检测可找)
- 底部:"快速安全登录"、"手机扫码登录"文字

## NBA2K 游戏内 UI
- 公告弹窗:有 × 关闭按钮
- 主界面:底部有"开始比赛"、"球员交易"、"俱乐部"等菜单
- 模式选择:上方有"排位赛 S32"页签
- 排位赛界面:左侧有"排位经理"入口
- 经理模式:右侧有"连续托管(X/20)"选项和"进入"按钮
- ESC菜单:顶部有"托管模式开关"和剩余次数,"关/OFF"按钮
- 连续托管(15/20):15=剩余场次,20=上限,阈值14
- 比赛结算页:有"当家球星"等文字

## 文件结构
```
src/
  main.py              - 入口,编排整体流程
  wegame_controller.py - WeGame 登录/启动游戏/切换账号
  game_controller.py   - 游戏内导航(全OCR找文字)
  trusteeship.py       - 2h计时/读次数/收号
  vision.py            - OCR+截图+点击+颜色检测
  window_utils.py      - 窗口控制/防息屏
  account_rotator.py   - 账号轮转状态机
  logger.py            - 日志+异常截图
tools/
  probe.py             - 视觉探针(截图+OCR标注+变化检测)
  calibrate.py         - 模板采集工具
config/
  settings.yaml        - 主配置
  accounts.yaml        - 6个账号
```

## 开发优先级
1. **先让 WeGame 登录稳定**(键盘直输 + 颜色检测找登录按钮)
2. **再让游戏启动稳定**(颜色检测找启动按钮)
3. **然后做游戏内导航**(OCR找文字:开始比赛→排位赛→排位经理→连续托管)
4. **最后做托管监控**(2h计时→ESC→读次数→收号→关游戏→切换账号)

## 调试方法
- `python tools/probe.py` — 截图+OCR标注,看程序"看到"什么
- `python tools/probe.py --diff` — 点击前后对比,看变化
- `python src/main.py --dry-run` — 只识别不点击(注意:dry-run测不了需要点击的流程)
- `python src/main.py --account 1` — 只跑第1个账号(真实运行)
- 出错截图自动存在 logs/screenshot_*.png

## 已知问题和注意事项
1. Python 3.14 太新,paddlepaddle 不支持。如果要换 PaddleOCR,需要装 Python 3.12
2. Tesseract 中文识别不稳定,同一张图多次结果可能不同
3. WeGame 的按钮是图片渲染的(CEF),OCR 对渲染文字识别率差
4. 颜色检测阈值可能需要根据实际画面调整
5. 远程桌面(UU远程)的分辨率和实机不同,开发时注意
6. pyautogui.typewrite 只能输入 ASCII,输入 QQ 号(纯数字)没问题,但中文需要其他方式

## 配置文件关键项(config/settings.yaml)
- display.scaling_percent: 250
- game_window.title_keywords: ["NBA2K", "2K"]
- trusteeship_status.display_format: "remaining/max" (15=剩余)
- trusteeship_status.stop_threshold: 14
- timing.trusteeship_duration: 7200 (2小时)
- timing.recheck_interval: 600 (10分钟复查)
