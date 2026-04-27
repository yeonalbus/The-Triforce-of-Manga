# -*- coding: utf-8 -*-
import os
import json
import sys
import sqlite3
import shutil
import time
from pathlib import Path

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
        self.error_file = config.ERROR_LOG_FILE # 对应 library\error_files.json
        self.source_dir = config.SOURCE_DIR
        self.db_path = config.SYNC_DB_PATH
        self.backup_dir = config.BACKUP_DIR
        
        os.makedirs(self.backup_dir, exist_ok=True)
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_master (
                gid TEXT PRIMARY KEY, folder_name TEXT, mtime REAL, author TEXT,
                title TEXT, komga_path TEXT, last_sync TEXT, calibre_id TEXT,
                komga_id TEXT, translate_tag TEXT DEFAULT '', raw_tag TEXT DEFAULT '',
                komga_status TEXT DEFAULT 'READY', komga_error TEXT DEFAULT ''
            )
        ''')
        new_columns = [
            ("need_destroy", "INTEGER DEFAULT 0"),
            ("need_update_tag", "INTEGER DEFAULT 0"),
            ("pub_date", "TEXT"),
            ("language", "TEXT")
        ]
        for col_name, col_def in new_columns:
            try:
                cursor.execute(f"ALTER TABLE sync_master ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError: pass
        conn.commit()
        conn.close()

    def backup_db(self):
        if os.path.exists(self.db_path):
            timestamp = time.strftime("%Y-%m-%d-%H%M")
            dest_path = os.path.join(self.backup_dir, f"sync_master-{timestamp}.db")
            shutil.copy2(self.db_path, dest_path)
            backups = sorted(Path(self.backup_dir).glob("sync_master-*.db"))
            if len(backups) > 30: os.remove(backups[0])

    def is_abnormal(self, folder_path):
        try:
            files = os.listdir(folder_path)
            return not any(os.path.splitext(f)[1].lower() in IMAGE_EXTS for f in files)
        except: return True

    def run_check(self):
        print(f"[*] 巡逻启动 | 目标: {self.source_dir}")
        self.backup_db()
        
        error_results = []
        current_folders = [f for f in os.listdir(self.source_dir)
                          if os.path.isdir(os.path.join(self.source_dir, f))
                          and f not in config.EXCLUDE_FOLDERS]

        for folder_name in current_folders:
            full_path = os.path.join(self.source_dir, folder_name)
            if self.is_abnormal(full_path):
                print(f"    [!] 发现异常: {folder_name}")
                error_results.append({
                    "folder_name": folder_name,
                    "path": full_path,
                    "check_time": time.strftime("%Y-%m-%d %H:%M:%S")
                })

        with open(self.error_file, 'w', encoding='utf-8') as f:
            json.dump(error_results, f, ensure_ascii=False, indent=2)
        
        print(f"[*] 巡逻结束。异常总数: {len(error_results)}")
        print(f"[*] 详细结果已写入: {self.error_file}")
        return error_results

if __name__ == "__main__":
    FolderInspector().run_check()