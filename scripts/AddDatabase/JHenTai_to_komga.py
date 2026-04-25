# -*- coding: utf-8 -*-
import os, re, sqlite3, shutil, zipfile, time, sys
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

# 1. 环境配置
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
from db_locker import SQLiteLock # 导入全局锁
from folder_inspector import FolderInspector

class SyncEngineV2:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.jhentai_db = config.JHENTAI_DB_LOCAL
        self.master_conn = None
        self.jhentai_conn = None

    def connect_dbs(self):
        try:
            self.master_conn = sqlite3.connect(self.db_path)
            self.master_conn.row_factory = sqlite3.Row
            os.makedirs(os.path.dirname(self.jhentai_db), exist_ok=True)
            shutil.copy2(config.JHENTAI_DB_SOURCE, self.jhentai_db)
            self.jhentai_conn = sqlite3.connect(self.jhentai_db)
            self.jhentai_conn.row_factory = sqlite3.Row
            return True
        except Exception as e:
            print(f"[X] 数据库连接失败: {e}")
            return False

    def extract_gid(self, folder_name):
        archive_match = re.match(r'^Archive - (\d+) -', folder_name)
        if archive_match: return archive_match.group(1), 'archive'
        gallery_match = re.match(r'^(\d+) -', folder_name)
        if gallery_match: return gallery_match.group(1), 'gallery'
        return None, None

    def get_metadata_from_jhentai(self, gid, table_type):
        t_primary = "archive_downloaded_v2" if table_type == 'archive' else "gallery_downloaded_v2"
        t_fallback = "gallery_downloaded_v2" if table_type == 'archive' else "archive_downloaded_v2"
        cursor = self.jhentai_conn.cursor()
        row = None
        for t in [t_primary, t_fallback]:
            cursor.execute(f"SELECT * FROM {t} WHERE gid = ?", (gid,))
            row = cursor.fetchone()
            if row: break
        if not row: return None
        # ... (此处保持你原来的元数据提取逻辑不变) ...
        row_data = dict(row)
        raw_tags_str = row_data.get('tags', "")
        tag_list = [t.strip() for t in raw_tags_str.split(',') if t.strip()]
        path_artist = "Unknown"
        for t in tag_list:
            if t.startswith('artist:'):
                path_artist = t.split(':', 1)[1]
                break
        if path_artist == "Unknown" and row_data.get('group_name'):
            path_artist = row_data.get('group_name')
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
            "Title": row_data.get('title'), "Writer": translated_artist, "Artist": translated_artist,
            "PathArtist": path_artist, "Genre": row_data.get('category', ''),
            "Tags": ",".join(translated_tags), "RawTags": raw_tags_str,
            "PageCount": row_data.get('page_count', 0),
            "Year": date_parts[0], "Month": date_parts[1], "Day": date_parts[2],
            "Web": row_data.get('gallery_url', ''), "Notes": f"gid:{gid}"
        }

    def generate_xml_content(self, meta):
        root = ET.Element("ComicInfo")
        xml_fields = ["Title", "Writer", "Artist", "Genre", "Tags", "PageCount", "Year", "Month", "Day", "Web", "Notes"]
        for field in xml_fields:
            sub = ET.SubElement(root, field)
            sub.text = str(meta.get(field, ''))
        return minidom.parseString(ET.tostring(root, 'utf-8')).toprettyxml(indent="  ")

    def run(self):
        # 1. 环境预检
        error_folders = FolderInspector().run_check()
        if not self.connect_dbs(): return

        # 获取原始文件夹列表
        raw_folders = [f for f in os.listdir(config.SOURCE_DIR) 
                      if os.path.isdir(os.path.join(config.SOURCE_DIR, f)) 
                      and f not in config.EXCLUDE_FOLDERS
                      and os.path.join(config.SOURCE_DIR, f) not in error_folders]

        print(f"[*] 发现 {len(raw_folders)} 个本地文件夹，正在进行优先级排序...")

        # --- 优先级对账手术开始 ---
        # gid_map 结构: { "gid": {"folder": "...", "type": "archive/gallery"} }
        gid_map = {}
        for folder in raw_folders:
            gid, gtype = self.extract_gid(folder)
            if not gid: continue
            
            # 如果这个 GID 还没出现过，或者 当前发现的是 Archive 而存的是 Gallery
            if gid not in gid_map:
                gid_map[gid] = {"folder": folder, "type": gtype}
            else:
                if gtype == 'archive' and gid_map[gid]['type'] == 'gallery':
                    print(f"    [优先] GID {gid} 发现 Archive 版本，将忽略 Gallery 版本")
                    gid_map[gid] = {"folder": folder, "type": gtype}
                elif gtype == 'gallery' and gid_map[gid]['type'] == 'archive':
                    # 如果已经存了 Archive，现在的 Gallery 就直接无视
                    continue
        # --- 优先级对账手术结束 ---

        print(f"[*] 对账完成。实际需处理书籍: {len(gid_map)} 本。")
        
        master_cursor = self.master_conn.cursor()

        # 全局加锁，进入正式入库流
        with SQLiteLock():
            # 遍历我们筛选过后的最优列表
            for idx, (gid, info) in enumerate(gid_map.items(), 1):
                folder = info['folder']
                table_type = info['type']

                # 剩下的逻辑保持不变：检查 mtime -> 元数据 -> Temp打包 -> Move -> SQL提交
                master_cursor.execute("SELECT mtime, komga_path FROM sync_master WHERE gid = ?", (gid,))
                existing = master_cursor.fetchone()
                
                full_source_path = os.path.join(config.SOURCE_DIR, folder)
                current_mtime = os.path.getmtime(full_source_path)

                if existing and existing['mtime'] == current_mtime:
                    if existing['komga_path'] and os.path.exists(existing['komga_path']):
                        continue

                meta = self.get_metadata_from_jhentai(gid, table_type)
                if not meta: continue

                safe_title = re.sub(r'[\\/:*?"<>|]', '_', meta['Title'])
                safe_author = re.sub(r'[\\/:*?"<>|]', '_', meta['PathArtist'])
                dest_dir = os.path.join(config.KOMGA_ROOT, safe_author, gid)
                os.makedirs(dest_dir, exist_ok=True)
                dest_file = os.path.join(dest_dir, f"{safe_title}.cbz")
                
                temp_cbz = os.path.join(config.TEMP_XML_DIR, f"packing_{gid}.cbz.tmp")
                print(f"[{idx}/{len(gid_map)}] 处理: {gid} ({info['type'].upper()}) | {meta['Title'][:25]}...")

                try:
                    with zipfile.ZipFile(temp_cbz, 'w', zipfile.ZIP_STORED) as zf:
                        zf.writestr("ComicInfo.xml", self.generate_xml_content(meta))
                        valid_exts = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}
                        imgs = sorted([i for i in os.listdir(full_source_path) if os.path.splitext(i)[1].lower() in valid_exts])
                        for img in imgs:
                            zf.write(os.path.join(full_source_path, img), img)

                    # 原子化移动
                    shutil.move(temp_cbz, dest_file)

                    # SQL 更新 (ON CONFLICT 保护 ID)
                    sql = '''
                        INSERT INTO sync_master (gid, folder_name, mtime, author, title, komga_path, last_sync, translate_tag, raw_tag)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(gid) DO UPDATE SET
                            folder_name=excluded.folder_name, mtime=excluded.mtime, author=excluded.author,
                            title=excluded.title, komga_path=excluded.komga_path, last_sync=excluded.last_sync,
                            translate_tag=excluded.translate_tag, raw_tag=excluded.raw_tag
                    '''
                    master_cursor.execute(sql, (
                        gid, folder, current_mtime, meta['Writer'], meta['Title'],
                        dest_file, time.strftime("%Y-%m-%d %H:%M:%S"), meta['Tags'], meta['RawTags']
                    ))
                    self.master_conn.commit()

                except Exception as e:
                    print(f"      [X] 失败: {e}")
                    if os.path.exists(temp_cbz): os.remove(temp_cbz)

        self.master_conn.close()
        self.jhentai_conn.close()
        print(f"[*] 任务圆满完成！")

if __name__ == '__main__':
    SyncEngineV2().run()