# -*- coding: utf-8 -*-
import os
import json
import sys
import sqlite3
import shutil
import time
from pathlib import Path

# --- 路径初始化 ---
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    print("[!] 找不到 configs 目录")

add_config_to_path()
import config

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.avif'}

class FolderInspector:
    def __init__(self):
        self.error_file = config.ERROR_LOG_FILE
        self.source_dir = config.SOURCE_DIR
        self.db_path = config.SYNC_DB_PATH
        self.backup_dir = config.BACKUP_DIR
        
        # 确保环境就绪
        os.makedirs(self.backup_dir, exist_ok=True)
        self.init_db()
        self.error_list = self.load_errors()

    def init_db(self):
        """数据库架构升级：增加增量更新逻辑"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. 确保基础表存在 (保持最原始的结构)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_master (
                gid TEXT PRIMARY KEY,
                folder_name TEXT,
                mtime REAL,
                author TEXT,
                title TEXT,
                komga_path TEXT,
                last_sync TEXT,
                calibre_id TEXT DEFAULT NULL,
                komga_id TEXT DEFAULT NULL,
                translate_tag TEXT DEFAULT '',
                raw_tag TEXT DEFAULT ''
            )
        ''')

        # 2. 动态检查并增加新字段 (解决语法错误并兼容旧表)
        # 我们不再依赖 CREATE TABLE 更新，而是手动 ALTER TABLE
        new_columns = [
            ("komga_status", "TEXT DEFAULT 'READY'"),
            ("komga_error", "TEXT DEFAULT ''")
        ]

        for col_name, col_def in new_columns:
            try:
                # 尝试增加字段，如果字段已存在，SQLite 会抛出异常，我们 catch 住即可
                cursor.execute(f"ALTER TABLE sync_master ADD COLUMN {col_name} {col_def}")
                print(f"    [架构更新] 成功增加字段: {col_name}")
            except sqlite3.OperationalError:
                # 错误信息通常是 "duplicate column name"，说明已经加过了，直接跳过
                pass

        conn.commit()
        conn.close()

    def backup_db(self):
        """自动快照：每次启动流水线时保留备份"""
        if os.path.exists(self.db_path):
            timestamp = time.strftime("%Y-%m-%d-%H%M")
            backup_name = f"sync_master-{timestamp}.db"
            dest_path = os.path.join(self.backup_dir, backup_name)
            shutil.copy2(self.db_path, dest_path)
            
            # 自动清理过旧备份 (保留 30 个，给足后悔药)
            backups = sorted(Path(self.backup_dir).glob("sync_master-*.db"))
            if len(backups) > 30:
                os.remove(backups[0])

    def load_errors(self):
        if os.path.exists(self.error_file):
            with open(self.error_file, 'r', encoding='utf-8') as f:
                try: return json.load(f)
                except: return []
        return []

    def is_abnormal(self, folder_path):
        try:
            files = os.listdir(folder_path)
            has_images = any(os.path.splitext(f)[1].lower() in IMAGE_EXTS for f in files)
            return not has_images
        except Exception:
            return True

    def run_check(self):
        print(f"[*] 巡逻启动 | 数据库: {os.path.basename(self.db_path)}")
        self.backup_db()
        
        valid_errors = []
        for path in self.error_list:
            if os.path.exists(path):
                if self.is_abnormal(path):
                    valid_errors.append(path)
                else:
                    print(f"    [-] 异常解除: {os.path.basename(path)}")
            else:
                print(f"    [-] 路径消失: {os.path.basename(path)}")
        
        current_folders = [os.path.join(self.source_dir, f) for f in os.listdir(self.source_dir)
                          if os.path.isdir(os.path.join(self.source_dir, f))
                          and f not in config.EXCLUDE_FOLDERS]

        for folder_path in current_folders:
            if self.is_abnormal(folder_path):
                if folder_path not in valid_errors:
                    print(f"    [!] 发现异常: {os.path.basename(folder_path)}")
                    valid_errors.append(folder_path)

        with open(self.error_file, 'w', encoding='utf-8') as f:
            json.dump(valid_errors, f, ensure_ascii=False, indent=2)
        
        print(f"[*] 巡逻结束。当前异常文件夹总数: {len(valid_errors)}")
        return valid_errors

if __name__ == "__main__":
    FolderInspector().run_check()