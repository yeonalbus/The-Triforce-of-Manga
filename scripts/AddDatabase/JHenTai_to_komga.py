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
        language = "zh" if "language:chinese" in raw_tags_str.lower() else "ja"
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
        # --- 出版日期处理 ---
        pub_time = row_data.get('publish_time', '2000-01-01')
        # 格式化为 YYYY-MM-DD
        pub_date = pub_time.split(" ")[0] if " " in pub_time else pub_time
        date_parts = (pub_date.split("-") + ["01", "01"])[:3]
        return {
            "Title": row_data.get('title'), "Writer": translated_artist, "Artist": translated_artist,
            "PathArtist": path_artist, "Genre": row_data.get('category', ''),
            "Tags": ",".join(translated_tags), "RawTags": raw_tags_str,
            "PageCount": row_data.get('page_count', 0),
            "PubDate": pub_date,
            "Language": language,
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

        print(f"[*] 发现 {len(raw_folders)} 个本地文件夹，正在进行优先级对账...")

        # --- 优先级对账 (Archive 优先) ---
        gid_map = {}
        for folder in raw_folders:
            gid, gtype = self.extract_gid(folder)
            if not gid: continue
            if gid not in gid_map:
                gid_map[gid] = {"folder": folder, "type": gtype}
            else:
                if gtype == 'archive' and gid_map[gid]['type'] == 'gallery':
                    gid_map[gid] = {"folder": folder, "type": gtype}

        # --- 预过滤真正需要执行的任务 ---
        print(f"[*] 对账完成。全局共 {len(gid_map)} 本，正在扫描待处理增量...")
        todo_list = []
        master_cursor = self.master_conn.cursor()
        
        for gid, info in gid_map.items():
            full_source_path = os.path.join(config.SOURCE_DIR, info['folder'])
            current_mtime = os.path.getmtime(full_source_path)
            
            master_cursor.execute("SELECT mtime, komga_path, pub_date FROM sync_master WHERE gid = ?", (gid,))
            existing = master_cursor.fetchone()
            
            needs_sync = True
            if existing:
                # 判定条件：mtime 没变 且 文件存在 且 pub_date 已经有值（不是旧数据）
                if (existing['mtime'] == current_mtime and 
                    existing['komga_path'] and os.path.exists(existing['komga_path']) and 
                    existing['pub_date'] is not None):
                    needs_sync = False
            
            if needs_sync:
                todo_list.append((gid, info, current_mtime))

        total_todo = len(todo_list)
        if total_todo == 0:
            print("[√] 所有书籍均已是最新状态，无需执行打包。")
            return

        print(f"[*] 过滤完成。本次实际需执行任务: {total_todo} 本。")
        
        # 2. 全局加锁，执行正式入库流
        with SQLiteLock():
            for idx, (gid, info, current_mtime) in enumerate(todo_list, 1):
                folder = info['folder']
                table_type = info['type']
                full_source_path = os.path.join(config.SOURCE_DIR, folder)

                meta = self.get_metadata_from_jhentai(gid, table_type)
                if not meta: continue

                # --- 路径构建：这是之前漏掉的关键部分 ---
                # 清洗路径中的非法字符
                artist_clean = re.sub(r'[\\/:*?"<>|]', '_', meta['PathArtist'])
                title_clean = re.sub(r'[\\/:*?"<>|]', '_', meta['Title'])
                
                # 目标目录（按作者分类）
                dest_dir = os.path.join(config.KOMGA_STAGING, artist_clean)
                os.makedirs(dest_dir, exist_ok=True)
                
                # 最终文件名与临时文件名
                dest_file = os.path.join(dest_dir, f"{title_clean} - {gid}.cbz")
                temp_cbz = os.path.join(config.TEMP_XML_DIR, f"j2k_tmp_{gid}.cbz")

                print(f"[{idx}/{total_todo}] 处理: {gid} | {meta['Title'][:25]}...")

                try:
                    # 打包逻辑
                    with zipfile.ZipFile(temp_cbz, 'w', zipfile.ZIP_STORED) as zf:
                        zf.writestr("ComicInfo.xml", self.generate_xml_content(meta))
                        valid_exts = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}
                        imgs = sorted([i for i in os.listdir(full_source_path) 
                                     if os.path.splitext(i)[1].lower() in valid_exts])
                        for img in imgs:
                            zf.write(os.path.join(full_source_path, img), img)

                    # 原子化移动
                    if os.path.exists(dest_file): os.remove(dest_file)
                    shutil.move(temp_cbz, dest_file)

                    # SQL 更新
                    sql = '''
                        INSERT INTO sync_master (gid, folder_name, mtime, author, title, komga_path, last_sync, translate_tag, raw_tag, pub_date, language)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(gid) DO UPDATE SET
                            folder_name=excluded.folder_name, mtime=excluded.mtime, author=excluded.author,
                            title=excluded.title, komga_path=excluded.komga_path, last_sync=excluded.last_sync,
                            translate_tag=excluded.translate_tag, raw_tag=excluded.raw_tag,
                            pub_date=excluded.pub_date, language=excluded.language
                    '''
                    master_cursor.execute(sql, (
                        gid, folder, current_mtime, meta['Writer'], meta['Title'],
                        dest_file, time.strftime("%Y-%m-%d %H:%M:%S"), meta['Tags'], meta['RawTags'],
                        meta['PubDate'], meta['Language']
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