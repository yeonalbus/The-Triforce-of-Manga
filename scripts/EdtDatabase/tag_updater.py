# -*- coding: utf-8 -*-
import os, sys, sqlite3, shutil, subprocess, zipfile, time, requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

# 环境配置加载
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    sys.path.append(str(Path("Z:/comic_tools/configs")))

add_config_to_path()
import config

class TagUpdater:
    def __init__(self):
        self.db_path = config.SYNC_DB_PATH
        self.jhentai_db = config.JHENTAI_DB_LOCAL
        self.host = config.KOMGA_HOST.rstrip('/')
        self.auth = (config.KOMGA_USER, config.KOMGA_PASS)
        self.interval = 12 * 3600

    def get_translated_tags(self, gid):
        """复用 J2K 逻辑：从 JHenTai 获取并翻译标签"""
        try:
            # 建立 JHenTai 快照连接
            jh_conn = sqlite3.connect(self.jhentai_db)
            jh_conn.row_factory = sqlite3.Row
            cursor = jh_conn.cursor()

            # 1. 寻找 GID 所在表
            row = None
            for t in ["archive_downloaded_v2", "gallery_downloaded_v2"]:
                cursor.execute(f"SELECT tags FROM {t} WHERE gid = ?", (gid,))
                row = cursor.fetchone()
                if row: break
            
            if not row or not row['tags']: 
                jh_conn.close()
                return None, None

            raw_tags_str = row['tags']
            tag_list = [t.strip() for t in raw_tags_str.split(',') if t.strip()]

            # 2. 汉化查表逻辑
            conditions, params = [], []
            for t in tag_list:
                if ':' in t:
                    ns, key = t.split(':', 1)
                    conditions.append("(namespace = ? AND _key = ?)")
                    params.extend([ns, key])
            
            translated_tags = []
            if conditions:
                sql = f"SELECT namespace, _key, tagName FROM tag WHERE {' OR '.join(conditions)}"
                cursor.execute(sql, params)
                lookup = {f"{r['namespace']}:{r['_key']}": r['tagName'] for r in cursor.fetchall()}
                translated_tags = [lookup.get(t, t) for t in tag_list]
            else:
                translated_tags = tag_list

            jh_conn.close()
            return raw_tags_str, ",".join(translated_tags)
        except Exception as e:
            print(f"    [X] J2K 转换异常: {e}")
            return None, None

    def update_cbz_comicinfo(self, cbz_path, translated_tags):
        """物理 CBZ 内部 ComicInfo.xml 的安全覆盖注入"""
        if not os.path.exists(cbz_path): return False
        
        temp_cbz = cbz_path + ".tmp"
        temp_xml = "ComicInfo.xml"
        try:
            # 1. 提取并准备新的 XML 内容
            root = None
            with zipfile.ZipFile(cbz_path, 'r') as z:
                if "ComicInfo.xml" in z.namelist():
                    content = z.read("ComicInfo.xml")
                    root = ET.fromstring(content)
            
            if root is None: root = ET.Element("ComicInfo")
            tags_node = root.find("Tags")
            if tags_node is None: tags_node = ET.SubElement(root, "Tags")
            tags_node.text = translated_tags
            xml_str = minidom.parseString(ET.tostring(root, 'utf-8')).toprettyxml(indent="  ")

            # 2. 重建压缩包：过滤掉旧的 ComicInfo.xml
            with zipfile.ZipFile(cbz_path, 'r') as zin:
                with zipfile.ZipFile(temp_cbz, 'w', zipfile.ZIP_STORED) as zout:
                    # 写入新的 XML
                    zout.writestr("ComicInfo.xml", xml_str)
                    # 复制其他所有文件
                    for item in zin.infolist():
                        if item.filename != 'ComicInfo.xml':
                            zout.writestr(item, zin.read(item.filename))

            # 3. 原子化替换
            os.replace(temp_cbz, cbz_path)
            return True
        except Exception as e:
            print(f"    [X] CBZ 注入失败: {e}")
            if os.path.exists(temp_cbz): os.remove(temp_cbz)
            return False

    def refresh_komga_metadata(self, kid):
        """指令 Komga 重新解析该书籍的元数据"""
        url = f"{self.host}/api/v1/books/{kid}/metadata/refresh"
        try:
            r = requests.post(url, auth=self.auth, timeout=10)
            return r.status_code == 204
        except:
            return False

    def run_sync(self):
        print(f"[*] {time.strftime('%Y-%m-%d')} 开始每日标签同步流...")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. 抓取所有需要更新的项目
        cursor.execute("SELECT * FROM sync_master WHERE need_update_tag = 1")
        tasks = cursor.fetchall()
        
        if not tasks:
            print("[√] 今日无待更新标签，辛苦了。")
            return

        for row in tasks:
            gid = row['gid']
            print(f"--> 同步中: {row['title']}")

            # 2. 获取最新翻译内容
            raw_t, trans_t = self.get_translated_tags(gid)
            if not trans_t: continue

            # 3. 更新物理 CBZ (Komga 的源)
            if row['komga_path']:
                if self.update_cbz_comicinfo(row['komga_path'], trans_t):
                    print("    [√] CBZ ComicInfo 已更新")
                    # 如果有 KID，顺便让 Komga 刷新
                    if row['komga_id']:
                        self.refresh_komga_metadata(row['komga_id'])

            # 4. 更新 Calibre 记录
            if row['calibre_id'] and row['calibre_id'] != 'null':
                try:
                    # Calibre 标签通常用逗号分隔
                    tags_arg = trans_t.replace(';', ',')
                    subprocess.run([
                        config.CALIBREDB_EXE, "set_metadata", str(row['calibre_id']),
                        "--with-library", config.TARGET_DIR,
                        "--field", f"tags:{tags_arg}"
                    ], capture_output=True, check=True, 
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0) # 注入隐身符
                    print(f"    [√] Calibre 数据库已同步 (ID: {row['calibre_id']})")
                except Exception as e:
                    print(f"    [X] Calibre 更新失败: {e}")

            # 5. 回填数据库并清除标记
            cursor.execute("""
                UPDATE sync_master 
                SET raw_tag = ?, translate_tag = ?, need_update_tag = 0 
                WHERE gid = ?
            """, (raw_t, trans_t, gid))
            conn.commit()

        conn.close()
        print("[*] 同步任务圆满结束。")

    def run_forever(self):
            print(f"[*] 标签同步后台已启动，维护周期: {self.interval}s (约 {self.interval//3600} 小时)", flush=True)
            while True:
                self.run_sync()
                # 执行完一次同步后，打印提示并进入休眠
                print(f"[*] 本轮同步完成，将在 {self.interval//3600} 小时后开启下一轮...", flush=True)
                time.sleep(self.interval)

if __name__ == "__main__":
    TagUpdater().run_forever()