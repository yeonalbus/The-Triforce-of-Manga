# -*- coding: utf-8 -*-
import sqlite3
import requests
import time
import sys
import re
from pathlib import Path

# 路径加载保持不变
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
        self.db_path = config.SYNC_DB_PATH
        self.host = config.KOMGA_HOST
        self.auth = (config.KOMGA_USER, config.KOMGA_PASS)
        self.session = requests.Session()
        self.session.auth = self.auth

    def wait_for_komga_idle(self, timeout=300, interval=5):
        """轮询 Komga 任务队列，直到所有任务完成"""
        print("[*] 正在监控 Komga 后台任务...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 获取待处理任务数量
                resp = self.session.get(f"{self.host}/api/v1/tasks")
                if resp.status_code == 200:
                    task_count = resp.json().get('count', 0)
                    if task_count == 0:
                        print("[√] Komga 已空闲，准备开始同步。")
                        return True
                    print(f"    [等待] 尚有 {task_count} 个任务在队列中...")
                else:
                    print(f"[!] 无法获取任务状态: {resp.status_code}")
            except Exception as e:
                print(f"[X] 轮询异常: {e}")
            
            time.sleep(interval)
        
        print("[!] 轮询超时，Komga 可能仍在忙碌，尝试直接同步。")
        return False

    def trigger_scan(self):
        """指令 Komga 扫描库文件"""
        print("[*] 指令 Komga 扫描所有库...")
        try:
            response = self.session.get(f"{self.host}/api/v1/libraries")
            if response.status_code == 200:
                libs = response.json()
                for lib in libs:
                    self.session.post(f"{self.host}/api/v1/libraries/{lib['id']}/scan")
                return True
        except Exception as e:
            print(f"[X] 触发扫描失败: {e}")
        return False

    def get_all_books_map(self):
        """分页获取所有书籍并建立 GID -> KID 映射"""
        komga_map = {}
        page = 0
        size = 200 # 适中的单页大小
        
        print("[*] 正在从 API 抓取书籍元数据...")
        while True:
            url = f"{self.host}/api/v1/books?page={page}&size={size}"
            try:
                resp = self.session.get(url)
                if resp.status_code != 200: break
                
                data = resp.json()
                books = data.get('content', [])
                if not books: break
                
                for b in books:
                    # 这里的正则建议根据你的实际路径结构微调
                    gid_match = re.search(r'[/\\](\d+)[/\\]', b['url'])
                    if gid_match:
                        komga_map[gid_match.group(1)] = b['id']
                
                if data.get('last') is True: break
                page += 1
            except Exception as e:
                print(f"[X] 分页抓取异常 (Page {page}): {e}")
                break
        
        return komga_map

    def fetch_and_update(self):
        """执行 SQL 更新"""
        komga_map = self.get_all_books_map()
        if not komga_map:
            print("[X] 未能获取到任何有效的 Komga 映射数据。")
            return

        print(f"[*] 映射建立完成，捕获到 {len(komga_map)} 条有效路径 ID。")
        
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT gid, komga_id, title FROM sync_master")
            rows = cursor.fetchall()
            
            updated_count = 0
            for row in rows:
                gid = str(row['gid']) # 确保类型一致
                if gid in komga_map:
                    new_kid = komga_map[gid]
                    if row['komga_id'] != new_kid:
                        cursor.execute("UPDATE sync_master SET komga_id = ? WHERE gid = ?", (new_kid, gid))
                        updated_count += 1
                        # print(f"    [KID 更新] GID {gid}: {new_kid}")

            conn.commit()
            conn.close()
            print(f"[√] KID 同步完成。共更新 {updated_count} 条记录。")
        except Exception as e:
            print(f"[X] 数据库操作异常: {e}")

    def run(self):
        if self.trigger_scan():
            # 关键改进：等待任务完成而非固定延时
            self.wait_for_komga_idle()
            self.fetch_and_update()

if __name__ == "__main__":
    KomgaIDFetcher().run()