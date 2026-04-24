# -*- coding: utf-8 -*-
import os

# ============================================================
# [ 第一部分：核心路径配置 ] - 💡 首次部署必须修改
# ============================================================

# 1. 漫画存储相关 (建议使用绝对路径或映射驱动器)
SOURCE_DIR = r'Z:\Comics'            # JHenTai 下载目录 (原始数据源)
KOMGA_ROOT = r"Z:\Komga"             # Komga 映射根目录 (处理后的 CBZ 存放处)
TARGET_DIR = r'Z:\CalibreLibrary'    # Calibre 书库目录 (用于 Calibre-Web 前端展示)

# 2. 外部程序数据库路径
JHENTAI_DB_SOURCE = r"...\db.sqlite"   # JHenTai 原始数据库位置
CALIBRE_WEB_DETAIL_HTML = r"...\Calibre-Web\_internal\cps\templates\detail.html" # Calibre-Web 模板路径

# ============================================================
# [ 第二部分：网络与 API 配置 ] - 📡 影响三体联动跳转
# ============================================================

# 1. 服务器网络标识
SERVER_IP = "192.x.x.x"         # 宿主机局域网 IP (用于生成跳转链接)

# 2. Komga API 服务配置
KOMGA_HOST = "http://localhost:25600/komga"
KOMGA_USER = "admin"
KOMGA_PASS = "admin123"           # 提示：若公开分享代码，请注意脱敏
KOMGA_LIBRARY_ID = "123"   # Komga 目标库 ID

# 3. 跳转网关高级配置
GATEWAY_PORT = 8085                  # jump_gateway.py 监听的端口
# 外部访问基准地址 (影响网关跳回功能)
KOMGA_EXTERNAL_BASE = f"http://{SERVER_IP}/komga" 
CALIBRE_WEB_EXTERNAL_BASE = f"http://{SERVER_IP}"
# 自动生成的补丁模板链接
GATEWAY_URL_TEMPLATE = f"http://{SERVER_IP}:{GATEWAY_PORT}/jump?cid={{{{ entry.id }}}}"


# ============================================================
# [ 第三部分：系统内部逻辑 ] - ⚙️ 除非结构调整，否则无需改动
# ============================================================

# 项目根目录自动推导
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SELF_DIR)

# 内部数据库与备份目录
LIBRARY_DIR = os.path.join(_BASE_DIR, "library")
SYNC_DB_PATH = os.path.join(LIBRARY_DIR, "sync_master.db")     # 核心索引 SQL
BACKUP_DIR = os.path.join(LIBRARY_DIR, "backup")
JHENTAI_DB_LOCAL = os.path.join(LIBRARY_DIR, "jhentai_snapshot.db") # 数据库快照

# 资源与日志文件
DB_PATH = os.path.join(LIBRARY_DIR, "db.raw.json")              # 标签翻译库
ERROR_LOG_FILE = os.path.join(LIBRARY_DIR, "error_files.json") 
TEMP_XML_DIR = os.path.join(_BASE_DIR, "temp_xml")             # 临时轻量化目录


# ============================================================
# [ 第四部分：工具与策略开关 ] - 🔧 进阶微调
# ============================================================

# 命令行执行工具
CALIBREDB_EXE = 'calibredb'
SEVEN_ZIP_PATH = '7z'
ZIP_ARGS = ['-tzip', '-mx0', '-y']   # -mx0 为存储模式，速度最快

# 业务开关
ENABLE_TRANSLATION = True            # 是否开启标签汉化
EXCLUDE_FOLDERS = ['.thumb', '@eaDir', '#recycle'] # 忽略的系统文件夹