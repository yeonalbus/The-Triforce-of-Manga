# -*- coding: utf-8 -*-
import customtkinter as ctk
from pystray import Icon, Menu, MenuItem
from PIL import Image
import subprocess
import threading
import os
import sys
import time
from pathlib import Path

# --- 环境初始化 ---
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    # 兜底路径
    sys.path.append(str(Path("Z:/comic_tools/configs")))

add_config_to_path()
try:
    import config
except ImportError:
    print("[!] 配置文件读取失败，请检查 configs 目录")
    sys.exit(1)

_GUI_DIR = Path(__file__).parent
_SCRIPTS_DIR = _GUI_DIR.parent

class ComicControlApp:
    def __init__(self):
        self.window = ctk.CTk()
        self.window.title("Comic-Tools 三体控制中心 v3.0")
        self.window.geometry("1200x850")
        ctk.set_appearance_mode("dark")
        
        # 进程管理：包含网关与四个核心健康监控 [cite: 14, 15]
        self.processes = {
            "gateway": None, 
            "error_watcher": None, 
            "patrol": None, 
            "janitor": None, 
            "tag_updater": None
        }
        self.current_task_proc = None 
        self.active_subprocesses = [] 
        
        self.tab_frames = {}
        self.health_logs = {}      
        self.health_indicators = {} 
        self.current_step_index = 0

        # 增量入库流水线步骤：已补全 K2C 入库 [cite: 3, 4]
        self.pipeline_steps = [
            ("异常扫描", "AddDatabase/folder_inspector.py"),
            ("J2K打包", "AddDatabase/JHenTai_to_komga.py"),
            ("K2C入库", "AddDatabase/komga_to_calibre.py"),
            ("抓取KID", "AddDatabase/komga_id_fetcher.py")
        ]

        self.setup_layout()
        self.create_tray_icon()
        self.show_frame("库健康中心") # 默认进入健康中心 [cite: 4]

        self.window.protocol('WM_DELETE_WINDOW', self.hide_window)

        self.log_dir = Path(config.SYNC_DB_PATH).parent / "logs"
        os.makedirs(self.log_dir, exist_ok=True)
        self.MAX_UI_LINES = 20  # 界面显示上限，超过则滚动删除旧行

    def setup_layout(self):
        self.window.grid_columnconfigure(1, weight=1)
        self.window.grid_rowconfigure(0, weight=1)

        # 1. 左侧导航边栏
        self.sidebar_frame = ctk.CTkFrame(self.window, width=170, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="COMIC TOOLS", font=ctk.CTkFont(size=18, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=20)

        # 【修改点 1】将“日志管理”直接加入核心列表，这样它会参与循环自动对齐
        tabs = ["网关监测", "库健康中心", "增量入库", "专家调试", "日志管理"] 
        self.nav_buttons = {}
        for i, name in enumerate(tabs):
            btn = ctk.CTkButton(self.sidebar_frame, corner_radius=0, height=45, text=name,
                                fg_color="transparent", text_color=("gray10", "gray90"),
                                hover_color=("gray70", "gray30"), anchor="w",
                                command=lambda n=name: self.show_frame(n))
            # 这里的 row 是 i+1，所以五个按钮占用了 row 1 到 row 5
            btn.grid(row=i+1, column=0, sticky="ew")
            self.nav_buttons[name] = btn

        # 【修改点 2】动态设置弹簧行。i+1 是最后一个按钮，所以让 i+2 成为伸缩空间
        # 这样 i+1 之前的按钮都会紧凑排列，而多余的空间会留给退出按钮上方
        self.sidebar_frame.grid_rowconfigure(len(tabs) + 1, weight=1)

        self.exit_btn = ctk.CTkButton(self.sidebar_frame, text="退出系统", fg_color="#8B0000", hover_color="#660000",
                                     command=self.quit_app)
        # 【修改点 3】将退出按钮放在弹簧行之后
        self.exit_btn.grid(row=len(tabs) + 2, column=0, padx=20, pady=20, sticky="ew")

        # 2. 内容容器
        self.container = ctk.CTkFrame(self.window, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_rowconfigure(0, weight=1)

        for name in tabs:
            frame = ctk.CTkFrame(self.container, fg_color="transparent")
            self.tab_frames[name] = frame

        self.setup_gateway_content()
        self.setup_health_content()
        self.setup_incremental_content()
        self.setup_debug_content()
        self.setup_log_viewer_content()

    # --- 1. 网关监测 ---
    def setup_gateway_content(self):
        tab = self.tab_frames["网关监测"]
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        
        box = ctk.CTkFrame(tab)
        box.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        box.grid_columnconfigure(1, weight=1)
        box.grid_rowconfigure(0, weight=1)

        ctrl = ctk.CTkFrame(box, width=220, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ns", padx=10, pady=20)
        
        ctk.CTkLabel(ctrl, text="API 跳转网关", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        self.gw_btn = ctk.CTkButton(ctrl, text="开启网关服务", command=self.toggle_gateway)
        self.gw_btn.pack(pady=10, padx=20)
        
        self.gw_log = ctk.CTkTextbox(box, border_width=1, font=("Consolas", 11))
        self.gw_log.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

    def toggle_gateway(self):
        key = "gateway"
        if self.processes[key] is None:
            script_path = _SCRIPTS_DIR / "Network/jump_gateway.py"
            self.processes[key] = self._safe_popen([sys.executable, "-u", str(script_path)])
            self.gw_btn.configure(text="关闭网关服务", fg_color="#8B0000")
            threading.Thread(target=self.read_logs_to_widget, args=(key, self.gw_log, "gateway"), daemon=True).start()
        else:
            self.processes[key].terminate()
            self.processes[key] = None
            self.gw_btn.configure(text="开启网关服务", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

    # --- 2. 库健康中心 ---
    def setup_health_content(self):
        tab = self.tab_frames["库健康中心"]
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        cards_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        services = [
            ("error_watcher", "Komga 坏档监控", "EdtDatabase/komga_error_watcher.py", "#FFA07A"),
            ("patrol", "库状态对账", "EdtDatabase/library_patrol.py", "#87CEFA"),
            ("janitor", "自动化销毁", "EdtDatabase/auto_janitor.py", "#FF6347"),
            ("tag_updater", "标签同步流", "EdtDatabase/tag_updater.py", "#98FB98")
        ]

        for i, (key, label, path, color) in enumerate(services):
            cards_frame.grid_columnconfigure(i, weight=1)
            card = ctk.CTkFrame(cards_frame, border_width=1, border_color="gray30")
            card.grid(row=0, column=i, padx=5, sticky="nsew")
            
            indicator = ctk.CTkLabel(card, text="●", text_color="gray", font=("Arial", 20))
            indicator.pack(side="top", pady=(5, 0))
            self.health_indicators[key] = indicator
            
            ctk.CTkLabel(card, text=label, font=("Microsoft YaHei", 12, "bold")).pack()
            
            btn = ctk.CTkButton(card, text="启动服务", height=28, font=("Arial", 11),
                               fg_color="#3B3B3B", hover_color=color,
                               command=lambda k=key, p=path: self.toggle_health_service(k, p))
            btn.pack(pady=10, padx=15)
            setattr(self, f"btn_{key}", btn)

        log_container = ctk.CTkFrame(tab)
        log_container.grid(row=1, column=0, sticky="nsew")
        log_container.grid_columnconfigure(0, weight=1)
        log_container.grid_rowconfigure(1, weight=1)

        self.log_mapping = {"坏档监控": "error_watcher", "对账巡逻": "patrol", "自动销毁": "janitor", "标签同步": "tag_updater"}
        self.log_switcher = ctk.CTkSegmentedButton(log_container, values=list(self.log_mapping.keys()),
                                                  command=self.switch_health_log)
        self.log_switcher.grid(row=0, column=0, pady=10)
        self.log_switcher.set("坏档监控")

        for k in self.log_mapping.values():
            txt = ctk.CTkTextbox(log_container, border_width=1, font=("Consolas", 11))
            self.health_logs[k] = txt
        
        self.switch_health_log("坏档监控")

    def switch_health_log(self, value):
        target_key = self.log_mapping[value]
        for txt in self.health_logs.values(): txt.grid_forget()
        self.health_logs[target_key].grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def toggle_health_service(self, key, script_path):
        btn = getattr(self, f"btn_{key}")
        if self.processes[key] is None:
            full_path = _SCRIPTS_DIR / script_path
            self.processes[key] = self._safe_popen([sys.executable, "-u", str(full_path)])
            self.health_indicators[key].configure(text_color="#00FF00") 
            btn.configure(text="停止服务", fg_color="#8B0000")
            threading.Thread(target=self.read_logs_to_widget, args=(key, self.health_logs[key], key), daemon=True).start()
        else:
            self.processes[key].terminate()
            self.processes[key] = None
            self.health_indicators[key].configure(text_color="gray")
            btn.configure(text="启动服务", fg_color="#3B3B3B")

    # --- 3. 增量入库 ---
    def setup_incremental_content(self):
        tab = self.tab_frames["增量入库"]
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        f = ctk.CTkFrame(tab, fg_color="transparent", width=260)
        f.grid(row=0, column=0, sticky="ns", pady=20)
        
        self.inc_log = ctk.CTkTextbox(tab, border_width=1, font=("Consolas", 12))
        self.inc_log.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkButton(f, text="⏹ 中断当前任务", fg_color="#D2691E", hover_color="#A0522D", 
                      command=lambda: self.interrupt_task(self.inc_log)).pack(pady=(0, 20), padx=30)

        ctk.CTkLabel(f, text="自动化流水线", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        ctk.CTkButton(f, text="【全自动】顺序同步", fg_color="#2c5f2d", command=self.run_pipeline).pack(pady=10, padx=30)
        
        ctk.CTkFrame(f, height=2, fg_color="gray50").pack(fill="x", pady=20, padx=20)
        
        self.next_step_btn = ctk.CTkButton(f, text="开始：异常扫描", fg_color="#3b5998", command=self.run_next_step)
        self.next_step_btn.pack(pady=10, padx=30)
        ctk.CTkButton(f, text="重置步骤", font=("Arial", 11), width=100, command=self.reset_steps).pack(pady=5)

    def run_pipeline(self):
        self.inc_log.delete("0.0", "end")
        def _pipe():
            self.log_to(self.inc_log, "==== 开启全自动同步流水线 ====")
            for name, path in self.pipeline_steps:
                if not self.window.winfo_exists(): break
                self.log_to(self.inc_log, f"--> 正在执行: {name}")
                self.current_task_proc = self._safe_popen([sys.executable, "-u", str(_SCRIPTS_DIR / path)])
                for line in iter(self.current_task_proc.stdout.readline, ''):
                    self.log_to(self.inc_log, f"  {line.strip()}")
                self.current_task_proc.wait()
                if self.current_task_proc is None or self.current_task_proc.returncode != 0:
                    self.log_to(self.inc_log, "[X] 流程异常或被手动中断")
                    return
            self.log_to(self.inc_log, "==== 流程全部圆满完成 ====")
            self.current_task_proc = None
        threading.Thread(target=_pipe, daemon=True).start()

    def run_next_step(self):
        if self.current_step_index >= len(self.pipeline_steps): return
        name, path = self.pipeline_steps[self.current_step_index]
        def _task():
            self.log_to(self.inc_log, f">>> 手动步骤启动: {name}")
            self.current_task_proc = self._safe_popen([sys.executable, "-u", str(_SCRIPTS_DIR / path)])
            for line in iter(self.current_task_proc.stdout.readline, ''):
                self.log_to(self.inc_log, f"    {line.strip()}")
            self.current_task_proc.wait()
            self.current_task_proc = None

        threading.Thread(target=_task, daemon=True).start()
        self.current_step_index += 1
        if self.current_step_index < len(self.pipeline_steps):
            self.next_step_btn.configure(text=f"下一步：{self.pipeline_steps[self.current_step_index][0]}")
        else:
            self.next_step_btn.configure(text="流程已结束", state="disabled")

    def reset_steps(self):
        self.current_step_index = 0
        self.next_step_btn.configure(text=f"开始：异常扫描", state="normal")
        # 重置时清空
        self.inc_log.delete("0.0", "end")
        self.log_to(self.inc_log, ">>> 步骤已重置，显示区已清空")

    # --- 4. 专家调试 ---
    def setup_debug_content(self):
        tab = self.tab_frames["专家调试"]
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        f = ctk.CTkFrame(tab, fg_color="transparent", width=260)
        f.grid(row=0, column=0, sticky="ns", pady=20)
        
        self.debug_log = ctk.CTkTextbox(tab, border_width=1, font=("Consolas", 12))
        self.debug_log.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(f, text="专家调试工具箱", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        
        # 数据修正组
        g1 = ctk.CTkFrame(f, fg_color="gray25")
        g1.pack(pady=10, padx=20, fill="x")
        ctk.CTkLabel(g1, text="数据与标签修正", font=("Arial", 11, "bold")).pack(pady=5)
        ctk.CTkButton(g1, text="手动：对账巡逻", command=lambda: self.run_once("EdtDatabase/library_patrol.py")).pack(pady=2, padx=10)
        ctk.CTkButton(g1, text="手动：物理销毁", command=lambda: self.run_once("EdtDatabase/auto_janitor.py")).pack(pady=2, padx=10)
        # 修正了之前的重复 pady 错误
        ctk.CTkButton(g1, text="手动：标签同步", command=lambda: self.run_once("EdtDatabase/tag_updater.py")).pack(pady=(2, 10), padx=10)

        # 网络与入库组：已补齐 K2C 入库 [cite: 28]
        g2 = ctk.CTkFrame(f, fg_color="gray25")
        g2.pack(pady=10, padx=20, fill="x")
        ctk.CTkLabel(g2, text="网络与入库调试", font=("Arial", 11, "bold")).pack(pady=5)
        scripts = [
            ("网关测通", "Network/jump_gateway.py"), 
            ("补丁注入", "Network/patch_calibre_web.py"),
            ("异常扫描", "AddDatabase/folder_inspector.py"),
            ("J2K打包", "AddDatabase/JHenTai_to_komga.py"), 
            ("K2C入库", "AddDatabase/komga_to_calibre.py"), 
            ("ID抓取", "AddDatabase/komga_id_fetcher.py")
        ]
        for name, path in scripts:
            ctk.CTkButton(g2, text=name, command=lambda p=path: self.run_once(p)).pack(pady=2, padx=10)
        ctk.CTkLabel(g2, text="", font=("Arial", 1)).pack(pady=5)

        ctk.CTkButton(f, text="⏹ 中断当前调试", fg_color="#D2691E", command=lambda: self.interrupt_task(self.debug_log)).pack(side="bottom", pady=20)

    def run_once(self, script_path):
        full_path = _SCRIPTS_DIR / script_path
        script_name = os.path.basename(script_path).replace(".py", "")
        
        def _task():
            # 记录到 debug 专用的持久化文件
            self.log_to(self.debug_log, f">>> 触发单次执行: {script_name}", log_file_name="debug_tools")
            # 这里统一使用 subprocess 执行，不带额外 args [cite: 29]
            self.current_task_proc = self._safe_popen([sys.executable, "-u", str(full_path)])
            for line in iter(self.current_task_proc.stdout.readline, ''):
                self.log_to(self.debug_log, f"    {line.strip()}", log_file_name="debug_tools")
            if self.current_task_proc:
                self.current_task_proc.wait() # [cite: 30]
            self.current_task_proc = None
        threading.Thread(target=_task, daemon=True).start()

    def _safe_popen(self, cmd_list):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0 # [cite: 10]
        )
        self.active_subprocesses.append(proc) # [cite: 10]
        return proc

    def log_to(self, text_widget, message, log_file_name=None):
        timestamp = time.strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] {message}\n"

        # 1. 如果需要持久化，写入物理文件
        if log_file_name:
            date_str = time.strftime('%Y-%m-%d')
            file_path = self.log_dir / f"{log_file_name}_{date_str}.log"
            try:
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(formatted_msg)
            except: pass

        # 2. 线程安全地更新 UI
        def _write():
            if not text_widget.winfo_exists(): return
            
            # 插入新内容
            text_widget.insert("end", formatted_msg)
            
            # 检查行数并清理 (关键优化)
            # 获取当前行数（index 'end' 返回 "line.char" 格式）
            line_count = int(text_widget.index('end-1c').split('.')[0])
            if line_count > self.MAX_UI_LINES:
                # 删除从第一行到溢出部分的文本，保持总量在 MAX_UI_LINES
                delete_until = float(line_count - self.MAX_UI_LINES + 1)
                text_widget.delete("1.0", f"{delete_until}.0")
            
            text_widget.see("end")

        self.window.after(0, _write)

    def interrupt_task(self, log_widget):
        if self.current_task_proc and self.current_task_proc.poll() is None:
            self.current_task_proc.terminate() # [cite: 25]
            self.log_to(log_widget, "!!! [手动中断] 任务已强行终止") # [cite: 26]
            self.current_task_proc = None

    def show_frame(self, name):
        for f in self.tab_frames.values(): f.grid_forget()
        self.tab_frames[name].grid(row=0, column=0, sticky="nsew") # [cite: 9]
        for btn_name, btn in self.nav_buttons.items():
            btn.configure(fg_color="transparent" if btn_name != name else "gray30")

    def read_logs_to_widget(self, key, widget, log_name):
        proc = self.processes[key]
        if proc:
            for line in iter(proc.stdout.readline, ''):
                # 将对应的服务 key 作为文件名
                self.log_to(widget, line.strip(), log_file_name=log_name)

    def create_tray_icon(self):
        img = Image.new('RGB', (64, 64), color=(73, 109, 137))
        menu = Menu(MenuItem('显示面板', self.show_window), MenuItem('彻底退出', self.quit_app))
        self.tray = Icon("ComicTools", img, "三体控制中心", menu) # [cite: 31]
        threading.Thread(target=self.tray.run, daemon=True).start()

    def hide_window(self): self.window.withdraw()
    def show_window(self): self.window.deiconify()

    def quit_app(self):
        print("[*] 正在安全关闭所有进程...")
        try: self.tray.stop()
        except: pass
        for p in self.active_subprocesses:
            try:
                if p.poll() is None: p.terminate() # [cite: 32]
            except: pass
        self.window.destroy()
        os._exit(0)

    # --- 5. 日志管理 (全量回溯) ---
    def setup_log_viewer_content(self):
        tab = self.tab_frames["日志管理"]
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # 左侧控制栏
        f = ctk.CTkFrame(tab, fg_color="transparent", width=260)
        f.grid(row=0, column=0, sticky="ns", pady=20)
        
        # 右侧全量日志显示区
        self.viewer_log = ctk.CTkTextbox(tab, border_width=1, font=("Consolas", 11))
        self.viewer_log.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(f, text="历史日志检索", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        
        # 1. 选择日志类型 (对应 log_file_name)
        ctk.CTkLabel(f, text="选择服务类型:", font=("Arial", 11)).pack(pady=(10, 0))
        self.log_type_var = ctk.StringVar(value="请选择类型")
        # 动态包含你所有的服务 key
        log_types = ["gateway", "error_watcher", "patrol", "janitor", "tag_updater", "debug_tools"]
        self.log_type_menu = ctk.CTkOptionMenu(f, values=log_types, variable=self.log_type_var, 
                                              command=self.refresh_log_file_list)
        self.log_type_menu.pack(pady=10, padx=20)

        # 2. 选择具体日期文件
        ctk.CTkLabel(f, text="选择日期文件:", font=("Arial", 11)).pack(pady=(10, 0))
        self.log_file_var = ctk.StringVar(value="请先选择类型")
        self.log_file_menu = ctk.CTkOptionMenu(f, values=[], variable=self.log_file_var)
        self.log_file_menu.pack(pady=10, padx=20)

        # 3. 功能按钮
        ctk.CTkButton(f, text="读取全量内容", command=self.load_log_content).pack(pady=20, padx=30)
        ctk.CTkButton(f, text="📂 打开日志目录", fg_color="gray30", command=self.open_log_dir).pack(pady=5, padx=30)
        
        ctk.CTkLabel(f, text="* 物理日志实时写入，\n界面仅显示最新动态。", 
                     font=("Arial", 10), text_color="gray").pack(side="bottom", pady=20)

    def refresh_log_file_list(self, choice):
        """根据选中的服务类型，扫描 logs 文件夹下的对应日期文件"""
        if not self.log_dir.exists(): return
        # 匹配 key_YYYY-MM-DD.log 格式的文件
        files = [f for f in os.listdir(self.log_dir) if f.startswith(choice) and f.endswith(".log")]
        files.sort(reverse=True) # 最近的日期排在最上面
        
        if files:
            self.log_file_menu.configure(values=files)
            self.log_file_var.set(files[0])
        else:
            self.log_file_menu.configure(values=["暂无历史日志"])
            self.log_file_var.set("暂无历史日志")

    def load_log_content(self):
        """物理读取硬盘文件并渲染到展示区"""
        filename = self.log_file_var.get()
        if "暂无" in filename or "请选择" in filename: return
        
        path = self.log_dir / filename
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                self.viewer_log.delete("1.0", "end")
                self.viewer_log.insert("end", content)
                self.viewer_log.see("end") # 自动滚动到底部
        except Exception as e:
            self.viewer_log.insert("end", f"\n[X] 日志读取失败: {e}")

    def open_log_dir(self):
        """一键直达 logs 文件夹"""
        if os.name == 'nt': os.startfile(self.log_dir)

if __name__ == "__main__":
    app = ComicControlApp()
    app.window.mainloop()