# -*- coding: utf-8 -*-
import sqlite3
import os, re, zipfile, subprocess, sys, time
from pathlib import Path

# 1. 环境配置 (统一双修路径)
def init_environment():
    p = Path(__file__).resolve()
    for parent in p.parents:
        configs_dir = parent / "configs"
        sql_edit_dir = parent / "scripts" / "SQLEdit"
        if configs_dir.exists(): sys.path.append(str(configs_dir))
        if sql_edit_dir.exists():
            sys.path.append(str(sql_edit_dir))
            return
    sys.path.append(str(Path("Z:/comic_tools/configs")))
    sys.path.append(str(Path("Z:/comic_tools/scripts/SQLEdit")))

init_environment()
import config
from db_locker import SQLiteLock # 导入全局通行证

class KomgaToCalibre:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH

    def run(self):
        print("[*] 正在扫描数据库进行 Calibre 同步...")
        os.makedirs(config.TEMP_XML_DIR, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # --- 步骤 1：获取待处理列表 (受保护的读取) ---
        with SQLiteLock():
            cursor.execute("SELECT * FROM sync_master WHERE calibre_id IS NULL OR calibre_id = 'null'")
            items = cursor.fetchall()

        if not items:
            print("[√] 没有需要入库 Calibre 的项目。")
            return

        for info in items:
            gid = info['gid']
            komga_path = info['komga_path']
            if not komga_path or not os.path.exists(komga_path): continue

            print(f"[*] 准备入库 Calibre: GID {gid} | {info['title'][:25]}...")
            
            # --- 步骤 2：建立临时缓冲 CBZ ---
            # 采用 .tmp 后缀防止 calibredb 读到正在写入的文件
            temp_cbz_staging = os.path.join(config.TEMP_XML_DIR, f"k2c_tmp_{gid}.cbz.tmp")
            temp_cbz_final = os.path.join(config.TEMP_XML_DIR, f"k2c_tmp_{gid}.cbz")
            
            try:
                # 从 Komga 源文件提取 ComicInfo 和 第一张图（用于封面）
                with zipfile.ZipFile(komga_path, 'r') as src_zf:
                    xml_data = src_zf.read("ComicInfo.xml").decode('utf-8')
                    img_list = sorted([n for n in src_zf.namelist() if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif'))])
                    
                    with zipfile.ZipFile(temp_cbz_staging, 'w', zipfile.ZIP_STORED) as dst_zf:
                        dst_zf.writestr("ComicInfo.xml", xml_data)
                        if img_list: 
                            dst_zf.writestr(img_list[0], src_zf.read(img_list[0]))
                
                # 原子重命名
                if os.path.exists(temp_cbz_final): os.remove(temp_cbz_final)
                os.rename(temp_cbz_staging, temp_cbz_final)

                # --- 步骤 3：调用 Calibre (耗时操作，不占锁) ---
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml_data)

                pub_date = info['pub_date'] if info['pub_date'] else f"{root.findtext('Year', '2000')}-01-01"
                lang = info['language'] if info['language'] else "ja"

                cmd = [
                    config.CALIBREDB_EXE, "add", temp_cbz_final,
                    "--with-library", config.TARGET_DIR,
                    "--authors", root.findtext('Artist', 'Unknown'),
                    "--title", root.findtext('Title', 'Unknown'),
                    "--tags", root.findtext('Tags', ''),
                    "--series", root.findtext('Title', 'Unknown'),
                    "--date", pub_date,
                    "--languages", lang,
                    "--duplicates"
                ]

                # 核心修改：添加 creationflags 以隐藏控制台窗口
                res = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    encoding='utf-8',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                
                if res.returncode == 0:
                    cid_match = re.search(r'id:?\s*(\d+)', res.stdout + res.stderr, re.IGNORECASE)
                    new_cid = cid_match.group(1) if cid_match else "null"
                    
                    # --- 步骤 4：回填 CID (受保护的写入) ---
                    with SQLiteLock():
                        cursor.execute("UPDATE sync_master SET calibre_id = ? WHERE gid = ?", (new_cid, gid))
                        conn.commit()
                    print(f"      [√] 入库成功! CID: {new_cid}")
                else:
                    print(f"      [X] Calibre 拒绝入库: {res.stderr}")

                # 清理
                if os.path.exists(temp_cbz_final): os.remove(temp_cbz_final)

            except Exception as e:
                print(f"      [X] 流程中断: {e}")
                if os.path.exists(temp_cbz_staging): os.remove(temp_cbz_staging)

        conn.close()
        print("[*] K2C 同步任务结束。")

if __name__ == '__main__': 
    KomgaToCalibre().run()