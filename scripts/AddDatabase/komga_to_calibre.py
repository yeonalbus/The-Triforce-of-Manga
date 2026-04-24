# -*- coding: utf-8 -*-
import sqlite3
import os, re, zipfile, subprocess, sys
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

class KomgaToCalibre:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH

    def run(self):
        print("[*] 正在扫描数据库进行 Calibre 同步...")
        os.makedirs(config.TEMP_XML_DIR, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 只查找没有 calibre_id 的项目
        cursor.execute("SELECT * FROM sync_master WHERE calibre_id IS NULL OR calibre_id = 'null'")
        items = cursor.fetchall()

        for info in items:
            gid = info['gid']
            komga_path = info['komga_path']
            if not komga_path or not os.path.exists(komga_path): continue

            print(f"[*] 准备入库 Calibre: GID {gid}")
            try:
                # 1. 提取元数据
                temp_cbz = os.path.join(config.TEMP_XML_DIR, f"calibre_tmp_{gid}.cbz")
                with zipfile.ZipFile(komga_path, 'r') as src_zf:
                    xml_data = src_zf.read("ComicInfo.xml").decode('utf-8')
                    img_list = sorted([n for n in src_zf.namelist() if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif'))])
                    with zipfile.ZipFile(temp_cbz, 'w', zipfile.ZIP_STORED) as dst_zf:
                        dst_zf.writestr("ComicInfo.xml", xml_data)
                        if img_list: dst_zf.writestr(img_list[0], src_zf.read(img_list[0]))

                # 2. 调用 Calibre
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml_data)
                cmd = [
                    config.CALIBREDB_EXE, "add", temp_cbz,
                    "--with-library", config.TARGET_DIR,
                    "--authors", root.findtext('Artist', 'Unknown'),
                    "--title", root.findtext('Title', 'Unknown'),
                    "--tags", root.findtext('Tags', ''),
                    "--series", root.findtext('Title', 'Unknown'), "--duplicates"
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
                
                if res.returncode == 0:
                    cid_match = re.search(r'id:?\s*(\d+)', res.stdout + res.stderr, re.IGNORECASE)
                    new_cid = cid_match.group(1) if cid_match else "null"
                    
                    # 3. 精准回填 CID
                    cursor.execute("UPDATE sync_master SET calibre_id = ? WHERE gid = ?", (new_cid, gid))
                    conn.commit()
                    print(f"      [√] 入库成功! CID: {new_cid}")
                
                if os.path.exists(temp_cbz): os.remove(temp_cbz)
            except Exception as e:
                print(f"      [X] 失败: {e}")

        conn.close()

if __name__ == '__main__': KomgaToCalibre().run()