# -*- coding: utf-8 -*-
import os
import re
import sqlite3
import shutil
import zipfile
import time
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

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
from folder_inspector import FolderInspector

# 处理 Windows 控制台编码
if os.name == 'nt':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

class SyncEngineV2:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.jhentai_db = config.JHENTAI_DB_LOCAL
        self.master_conn = None
        self.jhentai_conn = None

    def connect_dbs(self):
        """建立双库连接"""
        try:
            # 连接主索引库
            self.master_conn = sqlite3.connect(self.db_path)
            self.master_conn.row_factory = sqlite3.Row
            
            # 准备并连接 JHenTai 快照库
            local_db_dir = os.path.dirname(self.jhentai_db)
            os.makedirs(local_db_dir, exist_ok=True)
            shutil.copy2(config.JHENTAI_DB_SOURCE, self.jhentai_db)
            
            self.jhentai_conn = sqlite3.connect(self.jhentai_db)
            self.jhentai_conn.row_factory = sqlite3.Row
            return True
        except Exception as e:
            print(f"[X] 数据库连接失败: {e}")
            return False

    def extract_gid(self, folder_name):
        """从文件夹名提取 GID"""
        archive_match = re.match(r'^Archive - (\d+) -', folder_name)
        if archive_match: return archive_match.group(1), 'archive'
        gallery_match = re.match(r'^(\d+) -', folder_name)
        if gallery_match: return gallery_match.group(1), 'gallery'
        return None, None

    def get_metadata_from_jhentai(self, gid, table_type):
        """从 JHenTai 库抓取原始信息及汉化标签"""
        t_primary = "archive_downloaded_v2" if table_type == 'archive' else "gallery_downloaded_v2"
        t_fallback = "gallery_downloaded_v2" if table_type == 'archive' else "archive_downloaded_v2"
        
        cursor = self.jhentai_conn.cursor()
        row = None
        for t in [t_primary, t_fallback]:
            cursor.execute(f"SELECT * FROM {t} WHERE gid = ?", (gid,))
            row = cursor.fetchone()
            if row: break
        if not row: return None

        row_data = dict(row)
        raw_tags_str = row_data.get('tags', "")
        tag_list = [t.strip() for t in raw_tags_str.split(',') if t.strip()]

        # 路径作者 (英文)
        path_artist = "Unknown"
        for t in tag_list:
            if t.startswith('artist:'):
                path_artist = t.split(':', 1)[1]
                break
        if path_artist == "Unknown" and row_data.get('group_name'):
            path_artist = row_data.get('group_name')

        # 汉化处理
        translated_tags = []
        translated_artist = path_artist 
        if tag_list:
            conditions, params = [], []
            for t in tag_list:
                if ':' in t:
                    ns, key = t.split(':', 1)
                    conditions.append("(namespace = ? AND _key = ?)")
                    params.extend([ns, key])
            
            if conditions:
                # 假设汉化表也在 JHenTai 的 db.sqlite 里
                sql = f"SELECT namespace, _key, tagName FROM tag WHERE {' OR '.join(conditions)}"
                cursor.execute(sql, params)
                lookup = {f"{r['namespace']}:{r['_key']}": r['tagName'] for r in cursor.fetchall()}
                translated_tags = [lookup.get(t, t) for t in tag_list]
                for t in tag_list:
                    if t.startswith('artist:'):
                        translated_artist = lookup.get(t, path_artist)
                        break

        pub_time = row_data.get('publish_time', '2000-01-01')
        date_parts = (pub_time.split(" ")[0].split("-") + ["01", "01"])[:3]

        return {
            "Title": row_data.get('title'),
            "Writer": translated_artist,
            "Artist": translated_artist,
            "PathArtist": path_artist,
            "Genre": row_data.get('category', ''),
            "Tags": ",".join(translated_tags),
            "RawTags": raw_tags_str, # 存入数据库备查
            "PageCount": row_data.get('page_count', 0),
            "Year": date_parts[0], "Month": date_parts[1], "Day": date_parts[2],
            "Web": row_data.get('gallery_url', ''),
            "Notes": f"gid:{gid}"
        }

    def generate_xml_content(self, meta):
        root = ET.Element("ComicInfo")
        xml_fields = ["Title", "Writer", "Artist", "Genre", "Tags", "PageCount", "Year", "Month", "Day", "Web", "Notes"]
        for field in xml_fields:
            sub = ET.SubElement(root, field)
            sub.text = str(meta.get(field, ''))
        return minidom.parseString(ET.tostring(root, 'utf-8')).toprettyxml(indent="  ")

    def run(self):
        # 1. 预检
        error_folders = FolderInspector().run_check()
        if not self.connect_dbs(): return

        # 获取本地文件夹列表
        source_folders = [f for f in os.listdir(config.SOURCE_DIR) 
                         if os.path.isdir(os.path.join(config.SOURCE_DIR, f)) 
                         and f not in config.EXCLUDE_FOLDERS
                         and os.path.join(config.SOURCE_DIR, f) not in error_folders]

        print(f"[*] 发现 {len(source_folders)} 个本地文件夹，开始比对...")

        master_cursor = self.master_conn.cursor()

        for idx, folder in enumerate(source_folders, 1):
            gid, table_type = self.extract_gid(folder)
            if not gid: continue

            # 2. 从主库查询现有状态
            master_cursor.execute("SELECT mtime, komga_path FROM sync_master WHERE gid = ?", (gid,))
            existing = master_cursor.fetchone()
            
            full_source_path = os.path.join(config.SOURCE_DIR, folder)
            current_mtime = os.path.getmtime(full_source_path)

            # 判定：如果 mtime 没变 且 物理文件还在，跳过
            if existing and existing['mtime'] == current_mtime:
                if existing['komga_path'] and os.path.exists(existing['komga_path']):
                    continue

            # 3. 执行同步打包
            meta = self.get_metadata_from_jhentai(gid, table_type)
            if not meta: continue

            safe_title = re.sub(r'[\\/:*?"<>|]', '_', meta['Title'])
            safe_author = re.sub(r'[\\/:*?"<>|]', '_', meta['PathArtist'])
            dest_dir = os.path.join(config.KOMGA_ROOT, safe_author, gid)
            os.makedirs(dest_dir, exist_ok=True)
            dest_file = os.path.join(dest_dir, f"{safe_title}.cbz")

            print(f"[{idx}/{len(source_folders)}] 打包: {gid} | {meta['Title'][:30]}...")

            try:
                with zipfile.ZipFile(dest_file, 'w', zipfile.ZIP_STORED) as zf:
                    zf.writestr("ComicInfo.xml", self.generate_xml_content(meta))
                    valid_exts = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}
                    imgs = sorted([i for i in os.listdir(full_source_path) if os.path.splitext(i)[1].lower() in valid_exts])
                    for img in imgs:
                        zf.write(os.path.join(full_source_path, img), img)

                # 4. 【核心手术】更新数据库，利用 ON CONFLICT 保护 ID
                # 只有 gid 冲突时才更新其他字段，calibre_id 和 komga_id 将保持原样
                sql = '''
                    INSERT INTO sync_master (
                        gid, folder_name, mtime, author, title, 
                        komga_path, last_sync, translate_tag, raw_tag
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(gid) DO UPDATE SET
                        folder_name=excluded.folder_name,
                        mtime=excluded.mtime,
                        author=excluded.author,
                        title=excluded.title,
                        komga_path=excluded.komga_path,
                        last_sync=excluded.last_sync,
                        translate_tag=excluded.translate_tag,
                        raw_tag=excluded.raw_tag
                '''
                master_cursor.execute(sql, (
                    gid, folder, current_mtime, meta['Writer'], meta['Title'],
                    dest_file, time.strftime("%Y-%m-%d %H:%M:%S"),
                    meta['Tags'], meta['RawTags']
                ))
                self.master_conn.commit()

            except Exception as e:
                print(f"      [X] 失败: {e}")

        self.master_conn.close()
        self.jhentai_conn.close()
        print(f"[*] 任务圆满完成，Wasshoi！")

if __name__ == '__main__':
    SyncEngineV2().run()