# -*- coding: utf-8 -*-
# 路径：Z:\comic_tools\scripts\SQLEdit\db_locker.py
import os, time, sys
from pathlib import Path

# 环境配置加载
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
add_config_to_path()
import config

# 统一锁文件位置，使用主数据库同级目录
LOCK_FILE = os.path.join(os.path.dirname(config.SYNC_DB_PATH), ".lock")

class SQLiteLock:
    def __init__(self, timeout=60):
        self.timeout = timeout

    def _is_pid_running(self, pid):
        """检查进程是否还在运行"""
        if pid < 0: return False
        try:
            # 信号 0 不会杀死进程，但会检查进程是否存在
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def __enter__(self):
        start_time = time.time()
        
        # 增加逻辑：如果锁存在，先看一眼是谁拿着锁
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, 'r') as f:
                    old_pid = int(f.read().strip())
                # 如果持有锁的进程已经死了，直接物理消失
                if not self._is_pid_running(old_pid):
                    print(f"[*] 检测到残留锁 (PID: {old_pid} 已失效)，正在强制清除...")
                    os.remove(LOCK_FILE)
            except Exception:
                # 如果读文件出错了（比如文件为空），也视作无效锁
                pass

        while os.path.exists(LOCK_FILE):
            if time.time() - start_time > self.timeout:
                print(f"[!] 通行证排队超时，执行强行接管！")
                break
            time.sleep(0.5)
        
        # 抢占锁时，把自己的 PID 写入
        try:
            with open(LOCK_FILE, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            print(f"[X] 创建锁文件失败: {e}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if os.path.exists(LOCK_FILE):
            try:
                # 校验一下是不是自己加的锁（防止误删别人的）
                with open(LOCK_FILE, 'r') as f:
                    content = f.read().strip()
                if content == str(os.getpid()):
                    os.remove(LOCK_FILE)
            except:
                pass