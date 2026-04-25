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
    """全局数据库通行证：支持自动排队与超时接管"""
    def __init__(self, timeout=60):
        self.timeout = timeout

    def __enter__(self):
        start_time = time.time()
        # 1. 排队逻辑：如果锁存在，就死等
        while os.path.exists(LOCK_FILE):
            if time.time() - start_time > self.timeout:
                print(f"[!] 通行证排队超时 ({self.timeout}s)，执行强行接管！")
                break
            time.sleep(0.5) # 每0.5秒探测一次，减少IO压力
        
        # 2. 抢占锁
        try:
            Path(LOCK_FILE).touch()
        except Exception as e:
            print(f"[X] 创建锁文件失败: {e}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 3. 无论脚本是否运行出错，最后都得交出通行证
        if os.path.exists(LOCK_FILE):
            try:
                os.remove(LOCK_FILE)
            except:
                pass