"""
main.py - 主入口,编排整体流程

流程概览(每个账号):
  1. WeGame 切换到该账号(首个账号若已登录则跳过切换)
  2. 选 NBA2K → 启动游戏
  3. 游戏内导航:关公告 → 主界面 → 开始比赛 → 排位赛S32 → 排位经理 → 连续托管 → 匹配
  4. 托管监控:计时 2h → ESC 读次数 → ≤14 收号 / >14 每10分钟复查
  5. 收号:点关 → 等比赛结束 → Alt+F4 关游戏
  6. 回到 WeGame,切换下一个账号
  循环直到 6 个账号全部完成。

用法:
  python src/main.py                 # 正常运行
  python src/main.py --dry-run       # 调试模式(只识别不点击)
  python src/main.py --step          # 单步模式(每步暂停)
  python src/main.py --account 3     # 只跑第 3 个账号
  python src/main.py --reset         # 重置进度从头开始
"""
import argparse
import os
import sys
import time

import yaml

# 确保能 import 同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import window_utils
import vision
from logger import Logger, get_logger
from wegame_controller import WeGameController
from game_controller import GameController
from trusteeship import TrusteeshipMonitor
from account_rotator import AccountRotator

log = get_logger()


def load_config(path="config/settings.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_account(cfg, wg, account, is_first=False):
    """
    运行单个账号的完整流程。
    返回 True 表示成功完成。
    """
    idx = account["index"]
    label = account.get("label", f"账号{idx}")
    log.info(f"\n{'='*60}")
    log.info(f"▶ 开始处理 {label} (#{idx})")
    log.info(f"{'='*60}")

    # 1. 切换账号(首个账号若 WeGame 已登录可跳过)
    if not is_first:
        log.info(">>> 步骤1: 切换账号")
        if not wg.switch_to_account(idx):
            log.error(f"切换到 {label} 失败")
            return False
        # 等待登录完成
        if not wg.wait_account_logged_in(timeout=40):
            log.warning("登录确认超时,继续尝试")
    else:
        log.info(">>> 步骤1: 首个账号,确认 WeGame 已就绪")
        if not wg.find():
            log.error("WeGame 未运行,请先打开 WeGame")
            return False
        wg.activate()

    # 2. 启动游戏
    log.info(">>> 步骤2: 启动游戏")
    game_hwnd = wg.start_game()
    if not game_hwnd:
        log.error(f"启动游戏失败 ({label})")
        return False

    # 3. 游戏内导航到连续托管
    log.info(">>> 步骤3: 游戏内导航到连续托管")
    gc = GameController(cfg, game_hwnd)
    if not gc.navigate_to_trusteeship():
        log.error(f"导航失败 ({label})")
        Logger.screenshot(f"nav_fail_{label}")
        # 尝试关闭游戏后继续下一个
        tm = TrusteeshipMonitor(cfg, game_hwnd)
        tm.close_game()
        return False

    # 4. 托管监控 + 收号
    log.info(">>> 步骤4: 托管监控(2小时计时 + 收号)")
    tm = TrusteeshipMonitor(cfg, game_hwnd)
    tm.mark_start()
    success = tm.run()

    if success:
        log.info(f"✓ {label} 全流程完成")
    else:
        log.warning(f"⚠ {label} 流程异常,已尝试关闭游戏")
    return success


def main():
    parser = argparse.ArgumentParser(description="NBA2K Online2 多账号连续托管自动化")
    parser.add_argument("--dry-run", action="store_true", help="调试模式:只识别不点击")
    parser.add_argument("--step", action="store_true", help="单步模式:每步暂停等回车")
    parser.add_argument("--account", type=int, help="只运行指定序号的账号(1~6)")
    parser.add_argument("--reset", action="store_true", help="重置进度,从头开始")
    parser.add_argument("--config", default="config/settings.yaml", help="配置文件路径")
    args = parser.parse_args()

    # 初始化日志
    Logger.setup(args.config)
    log = get_logger()
    log.info("=" * 60)
    log.info("NBA2K Online2 多账号连续托管自动化 启动")
    log.info("=" * 60)

    # 加载配置
    cfg = load_config(args.config)

    # 运行模式覆盖
    if args.dry_run:
        cfg.setdefault("runtime", {})["mode"] = "dry_run"
        log.info("⚠ 运行模式: DRY-RUN(只识别不点击)")
    if args.step:
        cfg.setdefault("runtime", {})["mode"] = "step_pause"
        log.info("⚠ 运行模式: STEP(单步暂停)")

    # 初始化视觉配置
    vision.load_config(args.config)
    if args.dry_run:
        vision.VisionConfig.dry_run = True
    if args.step:
        vision.VisionConfig.step_pause = True

    # 防息屏
    if cfg.get("runtime", {}).get("prevent_sleep", True):
        window_utils.prevent_sleep()

    # 账号轮转
    state_file = cfg.get("runtime", {}).get("state_file", "logs/state.json")
    rotator = AccountRotator("config/accounts.yaml", state_file)
    if args.reset:
        rotator.reset()

    # WeGame 控制器
    wg = WeGameController(cfg)

    # 确定要运行的账号
    if args.account:
        accounts_to_run = [rotator.get_account(args.account)]
        if not accounts_to_run[0]:
            log.error(f"账号 #{args.account} 不存在")
            return
    else:
        start_idx = rotator.get_start_index()
        accounts_to_run = [a for a in rotator.accounts
                           if a["index"] >= start_idx
                           and not rotator.is_completed(a["index"])]

    if not accounts_to_run:
        log.info("所有账号已完成,无需运行")
        log.info(rotator.summary())
        return

    log.info(f"本次将运行 {len(accounts_to_run)} 个账号")
    log.info(rotator.summary())

    # 首个账号标记
    is_first = (not args.account) and (rotator.get_start_index() == 1
                                        and not rotator.state.get("completed"))

    # 主循环
    for i, account in enumerate(accounts_to_run):
        idx = account["index"]
        if rotator.is_completed(idx) and not args.account:
            continue

        rotator.mark_current(idx)
        account_success = False
        try:
            account_success = run_account(cfg, wg, account,
                                          is_first=(i == 0 and is_first))
        except KeyboardInterrupt:
            log.info("用户中断,保存状态退出")
            rotator.save_state()
            window_utils.allow_sleep()
            return
        except Exception as e:
            log.error(f"{account.get('label')} 异常: {e}", exc_info=True)
            Logger.screenshot(f"crash_{account.get('label')}")

        if account_success:
            rotator.mark_completed(idx)
        else:
            # 失败不标记完成,清空 current 以便下次运行重试该账号
            log.warning(f"⚠ {account.get('label')} 未成功,下次运行将重试。继续下一个账号")
            rotator.clear_current()
            # 尝试清理:关闭可能残留的游戏窗口
            try:
                kws = cfg.get("game_window", {}).get("title_keywords", ["NBA2K"])
                gh = window_utils.find_window(kws)
                if gh:
                    tm = TrusteeshipMonitor(cfg, gh)
                    tm.close_game()
            except Exception:
                pass

        log.info(rotator.summary())
        time.sleep(3)

    # 完成
    log.info("=" * 60)
    if rotator.all_completed():
        log.info("🎉 所有账号托管收号完成!")
    else:
        log.info(f"本次运行结束。{rotator.summary()}")
    log.info("=" * 60)

    window_utils.allow_sleep()


if __name__ == "__main__":
    main()
