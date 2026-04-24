# -*- coding: utf-8 -*-
import sqlite3
import requests
import time
import sys
import re
from pathlib import Path

# 路径加载
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    print("[!] 找不到 configs 目录")

add_config_to_path()
import config

class KomgaIDFetcher:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH # 使用 SQL 库
        self.host = config.KOMGA_HOST
        self.auth = (config.KOMGA_USER, config.KOMGA_PASS)

    def trigger_scan(self):
        """指令 Komga 扫描库文件"""
        print("[*] 指令 Komga 扫描库...")
        url = f"{self.host}/api/v1/libraries"
        try:
            response = requests.get(url, auth=self.auth)
            if response.status_code == 200:
                libs = response.json()
                for lib in libs:
                    scan_url = f"{self.host}/api/v1/libraries/{lib['id']}/scan"
                    requests.post(scan_url, auth=self.auth)
            else:
                print(f"[X] 获取库列表失败: {response.status_code}")
        except Exception as e:
            print(f"[X] 触发扫描异常: {e}")

    def fetch_and_update(self):
        """获取 Komga 数据并执行精准 SQL 更新"""
        print("[*] 正在同步 Komga 内部 ID (KID)...")
        url = f"{self.host}/api/v1/books?size=5000"
        try:
            response = requests.get(url, auth=self.auth)
            if response.status_code != 200: return

            books = response.json().get('content', [])
            komga_map = {}
            for b in books:
                gid_match = re.search(r'[/\\](\d+)[/\\]', b['url'])
                if gid_match: komga_map[gid_match.group(1)] = b['id']

            # 连接数据库进行对账
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 只查询已经在库里但 komga_id 可能需要更新的项目
            cursor.execute("SELECT gid, komga_id, title FROM sync_master")
            rows = cursor.fetchall()
            
            updated_count = 0
            for row in rows:
                gid = row['gid']
                if gid in komga_map:
                    new_kid = komga_map[gid]
                    if row['komga_id'] != new_kid:
                        # 精准更新这一行的 komga_id
                        cursor.execute("UPDATE sync_master SET komga_id = ? WHERE gid = ?", (new_kid, gid))
                        updated_count += 1
                        print(f"    [KID 更新] GID {gid}: {new_kid} | {row['title'][:20]}...")

            conn.commit()
            conn.close()
            print(f"[√] KID 同步完成。共更新 {updated_count} 处。")
        except Exception as e:
            print(f"[X] 同步异常: {e}")

    def run(self):
        self.trigger_scan()
        print("[*] 等待 Komga 写入数据库 (5s)...")
        time.sleep(5)
        self.fetch_and_update()

if __name__ == "__main__":
    KomgaIDFetcher().run()