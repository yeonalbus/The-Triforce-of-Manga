# -*- coding: utf-8 -*-
import sqlite3
import requests
import time
import sys
import re
from pathlib import Path

# 路径加载
def init_environment():
    p = Path(__file__).resolve()
    # 向上寻找项目根目录 (即包含 configs 或 scripts 的目录)
    for parent in p.parents:
        configs_dir = parent / "configs"
        sql_edit_dir = parent / "scripts" / "SQLEdit" # 路径：scripts/SQLEdit
        
        # 如果找到了 configs 目录，添加它
        if configs_dir.exists():
            sys.path.append(str(configs_dir))
        
        # 如果找到了 SQLEdit 目录，添加它
        if sql_edit_dir.exists():
            sys.path.append(str(sql_edit_dir))
            return # 关键路径都找到了，退出循环

    # --- 兜底逻辑：如果自动化寻找失败，手动指定 Z 盘路径 ---
    sys.path.append(str(Path("Z:/comic_tools/configs")))
    sys.path.append(str(Path("Z:/comic_tools/scripts/SQLEdit")))

init_environment()
import config
from db_locker import SQLiteLock  # 现在你可以直接这样导出了！

class KomgaIDFetcher:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.host = config.KOMGA_HOST.rstrip('/')
        self.auth = (config.KOMGA_USER, config.KOMGA_PASS)
        self.session = requests.Session()
        self.session.auth = self.auth
        # 增加标准请求头
        self.session.headers.update({"Accept": "application/json"})

    def trigger_scan(self):
        """指令 Komga 扫描所有库"""
        print("[*] 指令 Komga 扫描所有库...", flush=True)
        try:
            response = self.session.get(f"{self.host}/api/v1/libraries", timeout=10)
            if response.status_code == 200:
                libs = response.json()
                for lib in libs:
                    self.session.post(f"{self.host}/api/v1/libraries/{lib['id']}/scan")
                return True
        except Exception as e:
            print(f"[X] 触发扫描失败: {e}", flush=True)
        return False

    def get_all_books_map(self):
        r"""
        基于固定路径深度提取 GID：
        路径结构示例: Z:\Komga\38\3745952\[38]xxx.cbz
        拆分后倒数第 2 位永远是 GID 文件夹名
        """
        komga_map = {}
        page = 0
        size = 500
        
        print("[*] 正在从 API 抓取书籍元数据并解析目录结构...", flush=True)
        while True:
            url = f"{self.host}/api/v1/books?page={page}&size={size}"
            try:
                resp = self.session.get(url, timeout=20)
                if resp.status_code != 200: break
                
                data = resp.json()
                books = data.get('content', [])
                if not books: break
                
                for b in books:
                    file_url = b['url']
                    # 使用斜杠或反斜杠拆分路径，并过滤掉空字符串
                    parts = [p for p in re.split(r'[/\\]', file_url) if p]
                    
                    # 根据你的路径结构：
                    # parts[-1] 是文件名 (如: [38]xxx.cbz)
                    # parts[-2] 是 GID 文件夹 (如: 3745952)
                    if len(parts) >= 2:
                        gid = parts[-2]
                        # 只有当倒数第二级目录全是数字时才认为是有效的 GID
                        if gid.isdigit():
                            komga_map[gid] = b['id']
                        else:
                            # 调试用：如果这一层不是数字，说明目录结构可能超出了预期
                            # print(f"    [跳过] 路径结构异常: {file_url}")
                            pass
                
                if data.get('last') is True: break
                page += 1
            except Exception as e:
                print(f"[X] API 抓取异常: {e}", flush=True)
                break
        
        return komga_map

    def check_and_update(self):
        """执行一次对账更新，并返回当前数据库中仍然缺失 KID 的数量"""
        komga_map = self.get_all_books_map()
        if not komga_map:
            return -1 # 表示获取失败

        with SQLiteLock():
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 1. 尝试更新
                cursor.execute("SELECT gid, komga_id FROM sync_master")
                rows = cursor.fetchall()
                
                updated_count = 0
                for row in rows:
                    gid = str(row['gid'])
                    if gid in komga_map:
                        new_kid = komga_map[gid]
                        if row['komga_id'] != new_kid:
                            cursor.execute("UPDATE sync_master SET komga_id = ? WHERE gid = ?", (new_kid, gid))
                            updated_count += 1
                
                conn.commit()
                
                # 2. 查询还剩多少个空坑
                cursor.execute("SELECT COUNT(*) FROM sync_master WHERE komga_id IS NULL OR komga_id = ''")
                missing_count = cursor.fetchone()[0]
                
                conn.close()
                return missing_count

            except Exception as e:
                print(f"[X] 数据库操作异常: {e}", flush=True)
                return -1

    def run(self):
        if not self.trigger_scan():
            return

        print("[*] 扫描已触发，进入数据对账循环（10s/次）...", flush=True)
        max_attempts = 3600  # 安全阈值：最多等 60 分钟，防止有文件永远扫不出来导致死循环
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            missing = self.check_and_update()
            
            if missing == 0:
                print(f"[√] 所有书籍 ID 已同步完成。", flush=True)
                break
            elif missing == -1:
                print("    [!] 数据读取异常，稍后重试...", flush=True)
            else:
                print(f"    [循环 {attempt}] 还有 {missing} 本书尚未抓取到 ID，等待 Komga 录入...", flush=True)
            
            time.sleep(10)
        
        if attempt >= max_attempts:
            print("[!] 到达最大等待时间，部分书籍可能未被 Komga 正确识别。", flush=True)

if __name__ == "__main__":
    KomgaIDFetcher().run()