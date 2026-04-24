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

# 修改 jump_gateway.py 中的 theater_mode 函数返回的 HTML 部分

@app.get("/jump", response_class=HTMLResponse)
def theater_mode(cid: str):
    kid = get_kid_by_cid(cid)
    if not kid: 
        raise HTTPException(status_code=404, detail="Book mapping not found.")

    komga_url = f"{config.KOMGA_EXTERNAL_BASE}/book/{kid}/read"
    calibre_book_url = f"{config.CALIBRE_WEB_EXTERNAL_BASE}/book/{cid}"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reading Mode</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
            body, html {{ margin: 0; padding: 0; height: 100%; overflow: hidden; background: #000; }}
            iframe {{ border: none; width: 100%; height: 100%; }}
            .exit-btn {{ 
                position: fixed; top: 15px; left: 15px; z-index: 9999; 
                width: 35px; height: 35px; line-height: 35px; text-align: center;
                background: rgba(0,0,0,0.5); color: white; border-radius: 50%;
                text-decoration: none; font-family: sans-serif; font-size: 20px;
                transition: background 0.3s;
            }}
            .exit-btn:hover {{ background: rgba(255,0,0,0.7); }}
        </style>
    </head>
    <body>
        <a href="{calibre_book_url}" class="exit-btn">✕</a>
        <iframe id="reader-frame" src="{komga_url}" allowfullscreen></iframe>

        <script>
            const iframe = document.getElementById('reader-frame');
            const backUrl = "{calibre_book_url}";

            // 1. 强力聚焦逻辑：确保用户进场就能直接翻页
            function doFocus() {{
                try {{
                    iframe.contentWindow.focus();
                }} catch (e) {{}}
            }}

            // 2. 劫持函数
            function setupIframeHijack() {{
                try {{
                    const iframeWin = iframe.contentWindow;

                    // 使用 true (capture 模式) 确保优先级高于 Komga 内部的监听器
                    iframeWin.addEventListener('keydown', function(e) {{
                        if (e.key === 'Escape') {{
                            // 彻底切断 Komga 内部的 Esc 逻辑（不会跳到 Komga 详情页了）
                            e.preventDefault();
                            e.stopImmediatePropagation(); 
                            window.location.href = backUrl;
                        }}
                    }}, true);

                    // 进场即聚焦
                    doFocus();
                }} catch (err) {{
                    console.error("Focus/Hijack failed. Check same-origin config.");
                }}
            }}

            // 监听加载完成
            iframe.onload = setupIframeHijack;

            // 兜底：防止 onload 触发时机过早导致的聚焦失败
            document.addEventListener('DOMContentLoaded', () => {{
                setTimeout(doFocus, 500);
                setTimeout(doFocus, 1500); // 针对 Komga 加载较慢的情况做二次聚焦
            }});
            
            // 如果用户点击了页面任何地方，确保焦点重新回到阅读器
            window.addEventListener('click', doFocus);
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    # 从 config 读取端口
    uvicorn.run(app, host="0.0.0.0", port=config.GATEWAY_PORT)