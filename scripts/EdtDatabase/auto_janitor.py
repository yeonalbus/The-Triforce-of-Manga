# -*- coding: utf-8 -*-
import os, sys, sqlite3, shutil, subprocess, time
from pathlib import Path

# 环境配置加载
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    sys.path.append(str(Path("Z:/comic_tools/configs")))

add_config_to_path()
import config

# 延续原来的安全锁逻辑
LOCK_FILE = os.path.join(os.path.dirname(config.SYNC_DB_PATH), ".lock")

class AutoJanitor:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.interval = 1800  # 30分钟巡检一次

    def _acquire_lock(self):
        if os.path.exists(LOCK_FILE): return False
        Path(LOCK_FILE).touch()
        return True

    def _release_lock(self):
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)

    def prepare_jhentai_snapshot(self):
        """对账第一标准：JHenTai 快照"""
        try:
            shutil.copy2(config.JHENTAI_DB_SOURCE, config.JHENTAI_DB_LOCAL)
            conn = sqlite3.connect(config.JHENTAI_DB_LOCAL)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            print(f"[X] 快照失败: {e}", flush=True)
            return None

    def get_active_gids(self, cursor):
        gids = set()
        for table in ["archive_downloaded_v2", "gallery_downloaded_v2"]:
            cursor.execute(f"SELECT gid FROM {table}")
            for row in cursor.fetchall():
                gids.add(str(row['gid']))
        return gids

    def execute_destruction(self, item, cursor):
        """安全保护逻辑：延续原来那一套"""
        gid = str(item['gid'])
        folder_name = item['folder_name']
        cid = item['calibre_id']
        kpath = item['komga_path']

        print(f"\n[!] 执行自动销毁: {item['title']}")
        
        # 1. 移除 Calibre 记录
        if cid and str(cid) != "None" and str(cid) != "null":
            try:
                subprocess.run([config.CALIBREDB_EXE, "remove", str(cid), "--with-library", config.TARGET_DIR], 
                               capture_output=True, check=True)
                print(f"    [√] Calibre 记录已抹除 (ID: {cid})")
            except Exception as e:
                print(f"    [X] Calibre 移除失败: {e}")

        # 2. 移除 Komga 物理文件 (.cbz)
        if kpath and os.path.exists(kpath):
            try:
                os.remove(kpath)
                print(f"    [√] Komga 物理文件已清理")
            except Exception as e:
                print(f"    [X] 文件删除失败: {e}")

        # 3. 移除 SQL 主表记录
        cursor.execute("DELETE FROM sync_master WHERE gid = ?", (gid,))
        print(f"    [√] 数据库记录已注销")

    def run_cycle(self):
        if not self._acquire_lock():
            print("[!] 维护锁存在，跳过本次循环", flush=True)
            return

        print(f"[*] {time.strftime('%Y-%m-%d %H:%M:%S')} 开启自动化巡逻与维护...", flush=True)
        jh_conn = self.prepare_jhentai_snapshot()
        if not jh_conn: 
            self._release_lock()
            return

        jh_gids = self.get_active_gids(jh_conn.cursor())
        jh_conn.close()

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 这里的逻辑是以 JHenTai 为第一标准进行对账
            cursor.execute("SELECT gid, folder_name, title, calibre_id, komga_path FROM sync_master")
            items = cursor.fetchall()

            destroyed_count = 0
            for item in items:
                gid = str(item['gid'])
                folder_name = item['folder_name']
                
                # 安全保护逻辑核心：JHenTai 没了 且 物理源文件夹也没了
                source_path = os.path.join(config.SOURCE_DIR, folder_name)
                if gid not in jh_gids and not os.path.exists(source_path):
                    self.execute_destruction(item, cursor)
                    destroyed_count += 1

            conn.commit()
            conn.close()
            if destroyed_count > 0:
                print(f"[*] 本轮清理完毕，共移除 {destroyed_count} 个死项。", flush=True)
            else:
                print("[√] 库状态健康，未发现待处理项。", flush=True)

        except Exception as e:
            print(f"[X] 自动维护异常: {e}", flush=True)
        finally:
            self._release_lock()

    def start(self):
        print(f"[*] 自动化清理服务已就绪，运行周期: {self.interval}s (约 {self.interval//60} 分钟)", flush=True)
        while True:
            self.run_cycle()
            time.sleep(self.interval)

if __name__ == "__main__":
    AutoJanitor().start()