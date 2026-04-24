# -*- coding: utf-8 -*-
import os, shutil, re
from pathlib import Path
import sys

# 导入 config
def load_config():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            break
load_config()
import config

def apply_patch():
    target = config.CALIBRE_WEB_DETAIL_HTML
    backup = target + ".bak"
    
    if not os.path.exists(target):
        print(f"[X] 找不到模板文件: {target}")
        return

    # 1. 备份逻辑
    if not os.path.exists(backup):
        shutil.copy2(target, backup)

    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()

    # 2. 匹配 Calibre-Web 原生的阅读链接
    pattern = r'href="{{ url_for\(\'web\.read_book\', book_id=entry\.id, book_format=entry\.reader_list\[0\]\) }}"'
    # 替换为 config 中定义的网关模版
    replacement = f'href="{config.GATEWAY_URL_TEMPLATE}"'
    
    new_content = re.sub(pattern, replacement, content)

    if new_content == content:
        print("[!] 补丁已应用过或格式不匹配")
    else:
        with open(target, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[√] 成功! 链接已指向网关: {config.SERVER_IP}:{config.GATEWAY_PORT}")

if __name__ == "__main__":
    apply_patch()