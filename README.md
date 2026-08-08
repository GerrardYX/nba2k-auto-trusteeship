# NBA2K Online2 多账号连续托管自动化

自动轮转 6 个 WeGame 账号,在 NBA2K Online2 中进入「排位经理 - 连续托管」模式挂机,2 小时后检查剩余托管次数,≤14 则收号(停止新匹配→等当前比赛结束→关游戏),>14 则每 10 分钟复查,直到 6 个账号全部完成。

> ⚠️ **风险提示**:本工具是个人挂机辅助,利用游戏自带的连续托管功能在多账号间轮转。游戏自动化可能触及腾讯/2K 服务条款,多账号短时切换存在一定风控风险。**请先用一个不重要的账号跑通全流程,确认无误再放开 6 个号。作者不对封号等后果负责。**

---

## 工作原理

```
每个账号循环:
  ① WeGame 切换账号(按固定顺序,需滑动选第5/6个)
  ② 选 NBA2K → 点启动 → 等游戏窗口出现
  ③ 游戏内导航:关公告 → 主界面 → 开始比赛 → 排位赛S32 → 排位经理 → 连续托管 → 进入匹配
  ④ 托管计时 2 小时
  ⑤ ESC 查看托管状态 → OCR 读取剩余次数
       ├─ 剩余 ≤14:点"关"停止新匹配 → 等当前比赛结束 → Alt+F4 关游戏
       └─ 剩余 >14:关菜单继续托管,10 分钟后复查
  ⑥ 回 WeGame,切换下一个账号
  循环直到 6 个账号全部完成
```

**技术栈**:Python + OpenCV(模板匹配)+ PyTesseract(OCR 读托管次数)+ PyWin32(窗口控制)+ PyAutoGUI(点击/按键)+ MSS(截图)。

所有 UI 定位采用**图像模板匹配 + 多尺度搜索**,不硬编码坐标,适配不同分辨率/缩放。窗口模式下程序会把游戏窗口固定到屏幕左上角,消除位置漂移。

---

## 环境要求

- Windows 10/11
- Python 3.10+(已测 3.13)
- WeGame 已登录(6 个账号密码已保存)
- 游戏设为**窗口模式**(1920×1080),不要全屏
- 屏幕分辨率 3840×2160,缩放 250%(其他分辨率需重新校准)

---

## 快速开始

### 1. 安装依赖

```bash
# 克隆项目
git clone https://github.com/GerrardYX/nba2k-auto-trusteeship.git
cd nba2k-auto-trusteeship

# 安装依赖
pip install -r requirements.txt
```

还需安装 **Tesseract OCR**(用于读托管次数):
- 下载:[UB-Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
- 安装时勾选 **Chinese (Simplified)** 语言包
- 安装后把 `tesseract.exe` 路径加入系统 PATH,或在 `src/vision.py` 顶部加:
  ```python
  pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
  ```

### 2. 校准模板(关键!)

由于不同电脑的分辨率/缩放/窗口位置不同,所有 UI 元素必须**在你的机器上现场采集**:

```bash
python tools/calibrate.py autorun
```

这会一步步引导你:提示准备画面 → 3秒倒计时截屏 → 你用鼠标框选区域 → 自动保存为模板并测试匹配。覆盖全部 13 个关键元素(启动按钮、公告×、开始比赛、排位赛页签、连续托管、关按钮、结算页等)。

已采集的步骤会自动跳过,可中断后重新运行续采。加 `--force` 重新采集全部。

校准完成后,还需手动指定两个坐标(编辑 `config/settings.yaml`):
- `account_list.first_item_y`:账号列表第一个条目的中心 Y 坐标
- `account_list.list_roi`:账号列表的区域 `[x0,y0,x1,y1]`
- `trusteeship_status.remaining_count_roi`:ESC 菜单中剩余次数数字的区域

可用辅助工具采集:
```bash
python tools/calibrate.py coords --target account_list.first_item_y
python tools/calibrate.py ocr --digits   # 框选托管次数区域,验证OCR能否读出
```

### 3. 调试模式验证(强烈建议)

先用**只识别不点击**的模式跑一遍,确认每个元素都能识别到:

```bash
python src/main.py --dry-run
```

屏幕上会显示匹配框(绿色=成功),鼠标移动到目标位置但不点击。逐个确认无误后再进入正式运行。

也可用单步模式(每步暂停等回车):
```bash
python src/main.py --step
```

### 4. 正式运行

```bash
python src/main.py
```

程序会:
- 防止系统息屏
- 从第 1 个账号开始(可通过 `--account 3` 指定,或编辑 `config/accounts.yaml` 的 `start_from`)
- 每个账号跑满 2 小时后收号
- 中断后再次运行会从断点续跑(状态存于 `logs/state.json`)
- 全部完成后自动恢复息屏策略

**常用参数:**
```bash
python src/main.py --dry-run          # 调试:只识别不点击
python src/main.py --step             # 单步:每步暂停
python src/main.py --account 3        # 只跑第3个账号
python src/main.py --reset            # 重置进度从头开始
```

---

## 配置说明

### config/settings.yaml

主配置文件,所有参数集中管理:

| 配置项 | 说明 |
|--------|------|
| `display` | 屏幕分辨率与缩放比例 |
| `game_window` | 游戏窗口标题关键词、目标尺寸 |
| `wegame_window` | WeGame 窗口、启动按钮/头像区域 |
| `account_list` | 账号列表的条目高度、首项 Y 坐标、列表 ROI、滚动步数 |
| `game_roi` | 游戏内各按钮的搜索区域(留空则全窗口搜索) |
| `trusteeship_status` | **托管次数读取**:剩余次数 ROI、显示格式、阈值 |
| `timing` | 2小时计时、10分钟复查、比赛结束轮询等 |
| `shutdown` | 关游戏方式(Alt+F4)、确认弹窗 |
| `vision` | 模板匹配置信度阈值、多尺度搜索 |
| `runtime` | 运行模式、防息屏、状态文件 |

### 托管次数显示格式(重要,需确认)

截图显示 `连续托管(15/20)`。程序需知道 15 和 20 分别代表什么:

- `display_format: "remaining/max"` — 15 是**剩余**,20 是上限。程序直接读 15 作为剩余次数。**(默认)**
- `display_format: "current/max"` — 15 是**已用**,20 是上限。程序计算 `剩余 = 20 - 15 = 5`。

请在校准时用 `python tools/calibrate.py ocr --digits` 框选该区域,确认读出的数字含义。如果 15 代表剩余,保持默认;如果代表已用,改为 `current/max`。

阈值 `stop_threshold: 14` 表示剩余 ≤14 时收号。

### config/accounts.yaml

6 个账号的顺序与标签(仅用于日志,不含密码):
```yaml
accounts:
  - index: 1
    label: "账号1"
    wegame_id: "3797341146"
  ...
```

---

## 目录结构

```
nba2k-auto-trusteeship/
├── config/
│   ├── settings.yaml          # 主配置
│   └── accounts.yaml          # 账号列表
├── images/                    # 模板图片(校准后生成)
│   ├── wegame/                # WeGame 相关模板
│   ├── game/                  # 游戏内模板
│   └── common/
├── src/
│   ├── main.py                # 入口,编排整体流程
│   ├── account_rotator.py     # 账号轮转状态机(支持断点续跑)
│   ├── wegame_controller.py   # WeGame 启动/切换账号
│   ├── game_controller.py     # 游戏内导航
│   ├── trusteeship.py         # 2h计时/读次数/收号
│   ├── vision.py              # 图像匹配 + OCR
│   ├── window_utils.py        # 窗口控制/防息屏
│   └── logger.py              # 日志 + 出错截图
├── tools/
│   └── calibrate.py           # 校准与模板采集工具
├── logs/                      # 运行日志 + 异常截图 + 状态
├── docs/
├── requirements.txt
└── README.md
```

---

## 故障排查

| 问题 | 解决 |
|------|------|
| 模板匹配不到 | 运行 `python tools/calibrate.py test <cat> <name>` 查看匹配置信度;置信度低则重新采集模板 |
| OCR 读不到托管次数 | 用 `calibrate.py ocr --digits` 框选区域测试;确保区域只含数字,不含背景 |
| 游戏窗口找不到 | 确认游戏窗口标题包含 `settings.yaml` 里 `title_keywords` 的关键词 |
| Alt+F4 后弹窗没点掉 | 校准 `confirm_yes.png` 模板,或程序会自动按回车兜底 |
| WeGame 切换账号后没回前台 | 程序会自动查找并激活 WeGame 窗口;若任务栏自动隐藏影响,可临时关闭自动隐藏 |
| 程序中断了 | 直接重新运行,会从 `logs/state.json` 续跑;加 `--reset` 从头开始 |

**出错时**会自动截图保存到 `logs/screenshot_*.png`,配合 `logs/run.log` 排查。

---

## 开发说明

- 所有坐标基于**目标窗口客户区左上角 (0,0)**,窗口移动不影响识别
- 图像匹配默认开启多尺度搜索(0.5x~2.0x),适配缩放差异,但较慢;校准准确后可在配置里关闭 `multi_scale` 提速
- 状态持久化:`logs/state.json` 记录已完成账号,中断后 `python src/main.py` 自动续跑
- 日志:`logs/run.log` 全量记录;控制台彩色输出

---

## License

仅供个人学习使用。
