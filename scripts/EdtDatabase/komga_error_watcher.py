# -*- coding: utf-8 -*-
import sqlite3
import requests
import time
import sys
from pathlib import Path

# 路径加载逻辑
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    sys.path.append(str(Path("Z:/comic_tools/configs")))

add_config_to_path()
import config

class KomgaErrorWatcher:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.host = config.KOMGA_HOST
        self.auth = (config.KOMGA_USER, config.KOMGA_PASS)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.check_interval = 600 

    def print_existing_errors(self):
        """启动时先扫描一遍数据库，把现有的错误吐给 GUI"""
        print("[*] 正在加载数据库中的历史异常记录...", flush=True)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT title, komga_status, komga_error FROM sync_master WHERE komga_status != 'READY'")
            rows = cursor.fetchall()
            if rows:
                print(f"[!] 发现 {len(rows)} 条历史异常存量：", flush=True)
                for row in rows:
                    print(f"    - {row['title']} | {row['komga_status']}: {row['komga_error']}", flush=True)
            else:
                print("[√] 数据库暂无异常存量记录。", flush=True)
            conn.close()
        except Exception as e:
            print(f"[X] 加载历史异常失败: {e}", flush=True)

    def get_komga_errors(self):
        errors = {}
        url = f"{self.host}/api/v1/books?mediaStatus=ERROR&mediaStatus=UNSUPPORTED&size=1000"
        try:
            resp = self.session.get(url)
            if resp.status_code == 200:
                books = resp.json().get('content', [])
                for b in books:
                    errors[b['id']] = {
                        'status': b['media']['status'],
                        'comment': b['media'].get('comment', 'Unknown Error'),
                        'title': b['metadata']['title']
                    }
        except Exception as e:
            print(f"[X] API 请求异常: {e}", flush=True)
        return errors

    def run(self):
        # 1. 先报一次家底
        self.print_existing_errors()
        
        print(f"[*] Komga 错误监控已挂载，每 {self.check_interval}s 扫描一次 API", flush=True)
        while True:
            try:
                current_errors = self.get_komga_errors()
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # 检查已修复
                cursor.execute("SELECT komga_id, title FROM sync_master WHERE komga_status != 'READY'")
                db_errors = cursor.fetchall()
                for row in db_errors:
                    kid = row['komga_id']
                    if kid not in current_errors:
                        cursor.execute("UPDATE sync_master SET komga_status = 'READY', komga_error = '' WHERE komga_id = ?", (kid,))
                        print(f"\n[√] 异常已解除: {row['title']}", flush=True)

                # 更新新发现
                for kid, info in current_errors.items():
                    cursor.execute("SELECT komga_status, komga_error FROM sync_master WHERE komga_id = ?", (kid,))
                    row = cursor.fetchone()
                    if row:
                        if row['komga_status'] != info['status'] or row['komga_error'] != info['comment']:
                            cursor.execute(
                                "UPDATE sync_master SET komga_status = ?, komga_error = ? WHERE komga_id = ?",
                                (info['status'], info['comment'], kid)
                            )
                            print(f"\n[!] 发现文件异常: {info['title']}", flush=True)
                            print(f"    类型: {info['status']} | 原因: {info['comment']}", flush=True)

                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[X] 监控循环异常: {e}", flush=True)

            time.sleep(self.check_interval)

if __name__ == "__main__":
    KomgaErrorWatcher().run()