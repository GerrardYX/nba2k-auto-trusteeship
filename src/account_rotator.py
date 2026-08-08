"""
account_rotator.py - 账号轮转状态机
负责:读取账号列表、记录轮转进度(持久化)、决定下一个账号、跳过已完成。
"""
import json
import os
import time

import yaml
from logger import get_logger

log = get_logger()


class AccountRotator:
    def __init__(self, accounts_path="config/accounts.yaml", state_file="logs/state.json"):
        self.accounts_path = accounts_path
        self.state_file = state_file
        self.accounts = []
        self.state = {}
        self._load_accounts()
        self._load_state()

    def _load_accounts(self):
        with open(self.accounts_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self.accounts = data.get("accounts", [])
        self.start_from = data.get("start_from", 1)
        log.info(f"加载 {len(self.accounts)} 个账号")

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                log.info(f"恢复状态: 已完成 {self.state.get('completed', [])}, "
                         f"当前 {self.state.get('current', None)}")
            except Exception:
                self.state = {}
        self.state.setdefault("completed", [])
        self.state.setdefault("current", None)

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def get_start_index(self):
        """
        确定从哪个账号开始:
        - 优先恢复中断的 current(若存在且未完成)
        - 否则按顺序找第一个未完成的账号
        - 都没有则用配置的 start_from
        """
        cur = self.state.get("current")
        if cur and not self.is_completed(cur):
            return cur
        for a in self.accounts:
            if not self.is_completed(a["index"]):
                return a["index"]
        return self.start_from

    def get_account(self, index):
        """按 index 获取账号信息"""
        for a in self.accounts:
            if a["index"] == index:
                return a
        return None

    def is_completed(self, index):
        return index in self.state.get("completed", [])

    def mark_current(self, index):
        self.state["current"] = index
        self.save_state()

    def clear_current(self):
        """清空当前进行中的账号(失败或中断后调用,便于重试)"""
        self.state["current"] = None
        self.save_state()

    def mark_completed(self, index):
        if index not in self.state["completed"]:
            self.state["completed"].append(index)
        self.state["current"] = None
        self.save_state()
        label = self.get_account(index)
        lbl = label.get("label", f"账号{index}") if label else f"账号{index}"
        log.info(f"✓ {lbl} (#{index}) 托管收号完成")

    def all_completed(self):
        return len(self.state.get("completed", [])) >= len(self.accounts)

    def reset(self):
        """重置状态(从头开始)"""
        self.state = {"completed": [], "current": None}
        self.save_state()
        log.info("状态已重置")

    def remaining(self):
        """未完成的账号数"""
        return len(self.accounts) - len(self.state.get("completed", []))

    def summary(self):
        done = self.state.get("completed", [])
        total = len(self.accounts)
        labels = []
        for a in self.accounts:
            mark = "✓" if a["index"] in done else "○"
            labels.append(f"{mark}{a['label']}")
        return f"进度 {len(done)}/{total}: " + " ".join(labels)
