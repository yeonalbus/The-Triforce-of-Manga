# -*- coding: utf-8 -*-
import os, sys, sqlite3, shutil, subprocess, argparse, time
from pathlib import Path

# 1. 环境配置
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    print("[!] 找不到 configs 目录")

add_config_to_path()
import config

# 锁文件现在放在主库同级目录
LOCK_FILE = os.path.join(os.path.dirname(config.SYNC_DB_PATH), ".lock")

class TaskLock:
    def __enter__(self):
        if os.path.exists(LOCK_FILE):
            print(f"[!] 终止：维护锁已存在 {LOCK_FILE}")
            sys.exit(0)
        Path(LOCK_FILE).touch()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)

class LibraryJanitor:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH

    def prepare_jhentai_snapshot(self):
        """同步数据库快照"""
        try:
            shutil.copy2(config.JHENTAI_DB_SOURCE, config.JHENTAI_DB_LOCAL)
            conn = sqlite3.connect(config.JHENTAI_DB_LOCAL)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            print(f"[X] 快照失败: {e}")
            return None

    def get_active_jhentai_gids(self, cursor):
        """获取 JHenTai 中仍存在的 GID"""
        gids = set()
        for table in ["archive_downloaded_v2", "gallery_downloaded_v2"]:
            cursor.execute(f"SELECT gid FROM {table}")
            for row in cursor.fetchall():
                gids.add(str(row['gid']))
        return gids

    def run_maintenance(self):
        print("[*] 启动 SQL 维护清理任务...")
        jh_conn = self.prepare_jhentai_snapshot()
        if not jh_conn: return
        
        jh_gids = self.get_active_jhentai_gids(jh_conn.cursor())
        jh_conn.close()

        # 连接主库
        master_conn = sqlite3.connect(self.db_path)
        master_conn.row_factory = sqlite3.Row
        cursor = master_conn.cursor()
        
        cursor.execute("SELECT gid, folder_name, calibre_id, komga_path FROM sync_master")
        all_items = cursor.fetchall()
        
        removed_count = 0
        for item in all_items:
            gid = str(item['gid'])
            folder_name = item['folder_name']
            cid = item['calibre_id']
            kpath = item['komga_path']
            
            # 判定删除条件：JHenTai 库里没了 且 物理源文件夹也没了
            source_path = os.path.join(config.SOURCE_DIR, folder_name)
            if gid not in jh_gids and not os.path.exists(source_path):
                print(f"    [-] 清理死项: {folder_name} (GID: {gid})")
                
                # 1. 移除 Calibre 记录
                if cid and str(cid) != "null":
                    subprocess.run([config.CALIBREDB_EXE, "remove", str(cid), "--with-library", config.TARGET_DIR], capture_output=True)
                
                # 2. 移除 Komga 物理文件
                if kpath and os.path.exists(kpath):
                    try: os.remove(kpath)
                    except: pass
                
                # 3. 移除 SQL 记录
                cursor.execute("DELETE FROM sync_master WHERE gid = ?", (gid,))
                removed_count += 1

        master_conn.commit()
        master_conn.close()
        print(f"[*] 维护结束。从数据库中移除了 {removed_count} 条失效记录。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.force:
        with TaskLock():
            LibraryJanitor().run_maintenance()
    else:
        print("[*] 请使用 --force 参数运行维护逻辑。")