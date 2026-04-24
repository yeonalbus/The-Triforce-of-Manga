# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import sqlite3, os, sys
from pathlib import Path

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

app = FastAPI()

def get_kid_by_cid(cid):
    """手术：改为从 SQL 数据库获取对应的 komga_id"""
    try:
        if not os.path.exists(config.SYNC_DB_PATH): return None
        conn = sqlite3.connect(config.SYNC_DB_PATH)
        cursor = conn.cursor()
        # 精准匹配 calibre_id 字段
        cursor.execute("SELECT komga_id FROM sync_master WHERE calibre_id = ?", (str(cid),))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[X] Gateway DB Query Error: {e}")
        return None

@app.get("/jump", response_class=HTMLResponse)
def theater_mode(cid: str):
    kid = get_kid_by_cid(cid)
    if not kid: 
        raise HTTPException(status_code=404, detail="Book mapping not found.")

    # 使用 config 中定义的外部访问地址
    komga_url = f"{config.KOMGA_EXTERNAL_BASE}/book/{kid}/read"
    calibre_book_url = f"{config.CALIBRE_WEB_EXTERNAL_BASE}/book/{cid}"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reading Mode</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
            /* 你的样式保持不变 */
            body, html {{ margin: 0; padding: 0; height: 100%; overflow: hidden; background: #000; }}
            iframe {{ border: none; width: 100%; height: 100%; }}
            .exit-btn {{ position: fixed; top: 10px; left: 10px; z-index: 9999; ... }}
        </style>
    </head>
    <body>
        <a href="{calibre_book_url}" class="exit-btn">✕</a>
        <iframe src="{komga_url}" allowfullscreen></iframe>
        <script>
            window.addEventListener('keydown', function(e) {{
                if (e.key === 'Escape') {{ window.location.href = '{calibre_book_url}'; }}
            }});
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    # 从 config 读取端口
    uvicorn.run(app, host="0.0.0.0", port=config.GATEWAY_PORT)