# -*- coding: utf-8 -*-
import os, sys, sqlite3, shutil, time
from pathlib import Path

# 环境配置加载
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

class LibraryPatrol:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.check_interval = 1800 # 巡逻频率可以低一点，比如 30 分钟一次

    def get_jh_data_map(self, cursor):
        """一次性抓取 JHentai 的 GID 及其对应的 Tags"""
        data_map = {}
        # 遍历下载列表的两个核心表
        for table in ["archive_downloaded_v2", "gallery_downloaded_v2"]:
            # 假设 tags 字段存储在这些表中
            cursor.execute(f"SELECT gid, tags FROM {table}")
            for row in cursor.fetchall():
                gid = str(row['gid'])
                # 记录该 GID 对应的原始标签字符串
                data_map[gid] = row['tags'] if row['tags'] else ""
        return data_map

    def prepare_jhentai_snapshot(self):
        """同步 JHenTai 数据库快照用于对账"""
        try:
            shutil.copy2(config.JHENTAI_DB_SOURCE, config.JHENTAI_DB_LOCAL)
            conn = sqlite3.connect(config.JHENTAI_DB_LOCAL)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            print(f"[X] 巡逻中止：无法获取 JHenTai 快照: {e}", flush=True)
            return None

    def get_active_gids(self, cursor):
        gids = set()
        for table in ["archive_downloaded_v2", "gallery_downloaded_v2"]:
            cursor.execute(f"SELECT gid FROM {table}")
            for row in cursor.fetchall():
                gids.add(str(row['gid']))
        return gids

    def run_patrol(self):
        print(f"[*] 启动库对账巡逻 (销毁判定 + Tag 比对)...", flush=True)
        jh_conn = self.prepare_jhentai_snapshot()
        if not jh_conn: return
        
        jh_data_map = self.get_jh_data_map(jh_conn.cursor())
        jh_conn.close()

        with SQLiteLock():
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("SELECT gid, folder_name, title, raw_tag, need_destroy, need_update_tag FROM sync_master")
                items = cursor.fetchall()

                change_detected = False
                # 新增计数器
                total_pending_destroy = 0
                total_pending_update = 0

                for item in items:
                    gid = str(item['gid'])
                    folder_name = item['folder_name']
                    
                    # --- 1. 销毁判定逻辑 ---
                    source_path = os.path.join(config.SOURCE_DIR, folder_name)
                    is_gone = (gid not in jh_data_map and not os.path.exists(source_path))
                    
                    # 状态切换逻辑
                    if is_gone and item['need_destroy'] == 0:
                        cursor.execute("UPDATE sync_master SET need_destroy = 1 WHERE gid = ?", (gid,))
                        print(f"[!] 新增待销毁: {item['title']}")
                        change_detected = True
                    elif not is_gone and item['need_destroy'] == 1:
                        cursor.execute("UPDATE sync_master SET need_destroy = 0 WHERE gid = ?", (gid,))
                        print(f"[-] 销毁标记撤销: {item['title']}")
                        change_detected = True

                    # --- 2. Tag 更新判定逻辑 ---
                    if not is_gone:
                        jh_tag_content = jh_data_map.get(gid, "")
                        if jh_tag_content != item['raw_tag']:
                            if item['need_update_tag'] == 0:
                                cursor.execute("UPDATE sync_master SET need_update_tag = 1 WHERE gid = ?", (gid,))
                                print(f"[!] 发现标签变动: {item['title']}")
                                change_detected = True
                        else:
                            if item['need_update_tag'] == 1:
                                cursor.execute("UPDATE sync_master SET need_update_tag = 0 WHERE gid = ?", (gid,))
                                print(f"[√] 标签已同步: {item['title']}")
                                change_detected = True

                    # --- 统计当前存量 (包含刚才更新的状态) ---
                    # 重新获取最新的状态用于统计
                    cursor.execute("SELECT need_destroy, need_update_tag FROM sync_master WHERE gid = ?", (gid,))
                    updated_status = cursor.fetchone()
                    if updated_status['need_destroy'] == 1: total_pending_destroy += 1
                    if updated_status['need_update_tag'] == 1: total_pending_update += 1

                conn.commit()
                conn.close()

                # --- 最终输出逻辑调整 ---
                if change_detected:
                    print(f"\n[i] 巡逻状态已更新。当前汇总：待销毁({total_pending_destroy}) | 待更标({total_pending_update})")
                elif (total_pending_destroy + total_pending_update) > 0:
                    # 有异常但无新变动，输出一行简要摘要，不刷屏
                    print(f"[·] 库中仍存在未处理项：待销毁({total_pending_destroy}) | 待更标({total_pending_update})", flush=True)
                else:
                    print("[√] 巡逻完成，数据库状态完全健康。", flush=True)

            except Exception as e:
                print(f"[X] 巡逻过程异常: {e}", flush=True)

    def run_forever(self):
        print(f"[*] 库巡逻后台已启动，巡检周期: {self.check_interval}s (约 {self.check_interval//60} 分钟)", flush=True)
        while True:
            self.run_patrol()
            time.sleep(self.check_interval)

if __name__ == "__main__":
    LibraryPatrol().run_forever()