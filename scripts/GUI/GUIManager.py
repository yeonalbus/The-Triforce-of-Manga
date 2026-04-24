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

# --- 路径与环境初始化 ---
def add_config_to_path():
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "configs").exists():
            sys.path.append(str(parent / "configs"))
            return
    print("[!] 找不到 configs 目录")

add_config_to_path()
try:
    import config
except ImportError:
    print("[!] 配置文件读取失败")
    sys.exit(1)

_GUI_DIR = Path(__file__).parent
_SCRIPTS_DIR = _GUI_DIR.parent

class ComicControlApp:
    def __init__(self):
        self.window = ctk.CTk()
        self.window.title("Comic-Tools 三体控制中心")
        self.window.geometry("1100x700")
        ctk.set_appearance_mode("dark")
        
        # 进程管理
        self.processes = {"gateway": None, "inspector": None}
        self.current_task_proc = None # 追踪当前运行的增量/DEBUG任务
        self.active_subprocesses = [] 
        
        self.tab_frames = {}
        self.tab_logs = {}
        self.current_step_index = 0
        self.pipeline_steps = [
            ("异常扫描", "AddDatabase/folder_inspector.py"),
            ("J2K打包", "AddDatabase/JHenTai_to_komga.py"),
            ("K2C入库", "AddDatabase/komga_to_calibre.py"),
            ("抓取KID", "AddDatabase/komga_id_fetcher.py")
        ]

        self.setup_layout()
        self.create_tray_icon()
        self.show_frame("后台常驻")

        self.window.protocol('WM_DELETE_WINDOW', self.hide_window)

    def setup_layout(self):
        self.window.grid_columnconfigure(1, weight=1)
        self.window.grid_rowconfigure(0, weight=1)

        # 1. 左侧导航边栏
        self.sidebar_frame = ctk.CTkFrame(self.window, width=160, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="COMIC TOOLS", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 20))

        tabs = [("后台常驻", "home"), ("增量更新", "sync"), ("DEBUG", "bug")]
        for i, (name, icon) in enumerate(tabs):
            btn = ctk.CTkButton(self.sidebar_frame, corner_radius=0, height=45, border_spacing=10, 
                                text=name, fg_color="transparent", text_color=("gray10", "gray90"),
                                hover_color=("gray70", "gray30"), anchor="w",
                                command=lambda n=name: self.show_frame(n))
            btn.grid(row=i+1, column=0, sticky="ew")

        self.exit_btn = ctk.CTkButton(self.sidebar_frame, text="退出整个程序", fg_color="#8B0000", hover_color="#660000",
                                     command=self.quit_app)
        self.exit_btn.grid(row=6, column=0, padx=20, pady=20, sticky="ew")

        # 2. 右侧内容容器
        self.container = ctk.CTkFrame(self.window, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.container.grid_columnconfigure(1, weight=1)
        self.container.grid_rowconfigure(0, weight=1)

        for name in ["后台常驻", "增量更新", "DEBUG"]:
            frame = ctk.CTkFrame(self.container, fg_color="transparent")
            self.tab_frames[name] = frame
            frame.grid_columnconfigure(0, minsize=260)
            frame.grid_columnconfigure(1, weight=1)
            frame.grid_rowconfigure(0, weight=1)
            
            log_box = ctk.CTkTextbox(frame, border_width=1, font=("Consolas", 12))
            log_box.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
            self.tab_logs[name] = log_box

        self.setup_resident_content()
        self.setup_incremental_content()
        self.setup_debug_content()

    def show_frame(self, name):
        for f in self.tab_frames.values(): f.grid_forget()
        self.tab_frames[name].grid(row=0, column=0, columnspan=2, sticky="nsew")

    # --- 核心辅助 ---

    def _safe_popen(self, cmd_list):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8" 
        proc = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace',
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        self.active_subprocesses.append(proc)
        return proc

    def log_to(self, tab_name, message):
        def _write():
            self.tab_logs[tab_name].insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.tab_logs[tab_name].see("end")
        self.window.after(0, _write)

    def interrupt_task(self, tab_name):
        """中断当前正在执行的任务"""
        if self.current_task_proc and self.current_task_proc.poll() is None:
            self.current_task_proc.terminate()
            self.log_to(tab_name, "!!! [手动中断] 正在强行终止当前任务... !!!")
            self.current_task_proc = None
        else:
            self.log_to(tab_name, "[!] 当前没有正在运行的可中断任务。")

    # --- 常驻服务 ---

    def setup_resident_content(self):
        f = ctk.CTkFrame(self.tab_frames["后台常驻"], fg_color="transparent")
        f.grid(row=0, column=0, sticky="n", pady=20)
        ctk.CTkLabel(f, text="常驻服务管理", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        ctk.CTkButton(f, text="网关 (Port 8085)", command=lambda: self.toggle_service("gateway", "Network/jump_gateway.py", "后台常驻")).pack(pady=10, padx=30)
        ctk.CTkButton(f, text="巡逻 (Auto Inspector)", command=lambda: self.toggle_service("inspector", "AddDatabase/folder_inspector.py", "后台常驻")).pack(pady=10, padx=30)

    def toggle_service(self, key, script_path, tab_name):
        if self.processes[key] is None:
            full_path = _SCRIPTS_DIR / script_path
            self.processes[key] = self._safe_popen([sys.executable, str(full_path)])
            self.log_to(tab_name, f"服务 {key} 已挂载启动")
            threading.Thread(target=self.read_logs, args=(key, tab_name), daemon=True).start()
        else:
            self.processes[key].terminate()
            self.processes[key] = None
            self.log_to(tab_name, f"服务 {key} 已通过指令停止")

    def read_logs(self, key, tab_name):
        proc = self.processes[key]
        if proc:
            for line in iter(proc.stdout.readline, ''):
                self.log_to(tab_name, f"({key}) {line.strip()}")

    # --- 增量更新 (Tab 2) ---

    def setup_incremental_content(self):
        f = ctk.CTkFrame(self.tab_frames["增量更新"], fg_color="transparent")
        f.grid(row=0, column=0, sticky="n", pady=20)
        
        # 中断按钮置顶
        ctk.CTkButton(f, text="⏹ 中断当前任务", fg_color="#D2691E", hover_color="#A0522D", 
                      command=lambda: self.interrupt_task("增量更新")).pack(pady=(0, 20), padx=30)

        ctk.CTkLabel(f, text="工作流向导", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        ctk.CTkButton(f, text="【全自动】顺序同步", fg_color="#2c5f2d", command=self.run_pipeline).pack(pady=10, padx=30)
        ctk.CTkFrame(f, height=2, fg_color="gray50").pack(fill="x", pady=20, padx=20)
        self.next_step_btn = ctk.CTkButton(f, text="开始第一步：异常扫描", fg_color="#3b5998", command=self.run_next_step)
        self.next_step_btn.pack(pady=10, padx=30)
        ctk.CTkButton(f, text="重置向导", font=("Arial", 11), width=100, command=self.reset_steps).pack(pady=5)

    def run_pipeline(self):
        def _pipe():
            self.log_to("增量更新", "==== 开启自动化流水线 ====")
            for name, path in self.pipeline_steps:
                if self.window.winfo_exists(): # 检查GUI是否还在
                    self.log_to("增量更新", f"--> 正在运行: {name}")
                    self.current_task_proc = self._safe_popen([sys.executable, str(_SCRIPTS_DIR / path)])
                    for line in iter(self.current_task_proc.stdout.readline, ''): 
                        self.log_to("增量更新", f"  {line.strip()}")
                    
                    self.current_task_proc.wait()
                    # 如果是被中断的，poll() 会有值但通常不是 0
                    if self.current_task_proc is None:
                        return # 已被手动中断置空
                    
                    if self.current_task_proc.returncode != 0:
                        self.log_to("增量更新", f"[X] {name} 流程异常或被中断")
                        self.current_task_proc = None
                        return
            self.log_to("增量更新", "==== 所有同步任务已完成 ====")
            self.current_task_proc = None
            
        threading.Thread(target=_pipe, daemon=True).start()

    def run_next_step(self):
        if self.current_step_index >= len(self.pipeline_steps): return
        name, path = self.pipeline_steps[self.current_step_index]
        
        # 内部包装 run_once 的逻辑，以便能被中断
        def _task():
            self.log_to("增量更新", f">>> 指引步骤启动: {name}")
            self.current_task_proc = self._safe_popen([sys.executable, str(_SCRIPTS_DIR / path)])
            for line in iter(self.current_task_proc.stdout.readline, ''):
                self.log_to("增量更新", f"    {line.strip()}")
            self.current_task_proc.wait()
            self.log_to("增量更新", f"<<< 步骤结束 (Code: {self.current_task_proc.returncode if self.current_task_proc else 'Killed'})")
            self.current_task_proc = None

        threading.Thread(target=_task, daemon=True).start()
        
        self.current_step_index += 1
        if self.current_step_index < len(self.pipeline_steps):
            self.next_step_btn.configure(text=f"下一步：{self.pipeline_steps[self.current_step_index][0]}")
        else:
            self.next_step_btn.configure(text="全流程已跑完", state="disabled")

    def reset_steps(self):
        self.current_step_index = 0
        self.next_step_btn.configure(text=f"开始第一步：{self.pipeline_steps[0][0]}", state="normal")

    # --- DEBUG (Tab 3) ---

    def setup_debug_content(self):
        f = ctk.CTkFrame(self.tab_frames["DEBUG"], fg_color="transparent")
        f.grid(row=0, column=0, sticky="n", pady=20)
        
        # 中断按钮置顶
        ctk.CTkButton(f, text="⏹ 中断调试任务", fg_color="#D2691E", hover_color="#A0522D", 
                      command=lambda: self.interrupt_task("DEBUG")).pack(pady=(0, 20), padx=30)

        ctk.CTkLabel(f, text="独立工具调试", font=("Microsoft YaHei", 16, "bold")).pack(pady=10)
        scripts = [("网关测试", "Network/jump_gateway.py"), ("补丁注入", "Network/patch_calibre_web.py"),
                   ("异常扫描", "AddDatabase/folder_inspector.py"), ("J2K打包", "AddDatabase/JHenTai_to_komga.py"),
                   ("K2C入库", "AddDatabase/komga_to_calibre.py"), ("ID抓取", "AddDatabase/komga_id_fetcher.py"),
                   ("全量维护", "EdtDatabase/maintenance.py")]
        for name, path in scripts:
            args = ["--force"] if "maintenance" in path else []
            ctk.CTkButton(f, text=name, fg_color="#4a4a4a", command=lambda p=path, a=args: self.run_once(p, a, "DEBUG")).pack(pady=5, padx=30)

    def run_once(self, script_path, args, tab_name):
        full_path = _SCRIPTS_DIR / script_path
        def _task():
            self.log_to(tab_name, f">>> 单点任务启动: {os.path.basename(script_path)}")
            self.current_task_proc = self._safe_popen([sys.executable, str(full_path)] + args)
            for line in iter(self.current_task_proc.stdout.readline, ''):
                self.log_to(tab_name, f"    {line.strip()}")
            
            if self.current_task_proc:
                self.current_task_proc.wait()
                self.log_to(tab_name, f"<<< 任务结束 (ExitCode: {self.current_task_proc.returncode if self.current_task_proc else 'Killed'})")
            self.current_task_proc = None
            
        threading.Thread(target=_task, daemon=True).start()

    # --- 托盘与退出 ---

    def create_tray_icon(self):
        img = Image.new('RGB', (64, 64), color=(73, 109, 137))
        menu = Menu(MenuItem('显示面板', self.show_window), MenuItem('强制退出', self.quit_app))
        self.tray = Icon("ComicTools", img, "三体控制中心", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def hide_window(self): self.window.withdraw()
    def show_window(self): self.window.deiconify()

    def quit_app(self):
        print("[*] 执行清场...")
        try: self.tray.stop()
        except: pass
        if self.current_task_proc: self.current_task_proc.terminate()
        for p in self.active_subprocesses:
            try:
                if p.poll() is None: p.terminate()
            except: pass
        self.window.destroy()
        os._exit(0)

if __name__ == "__main__":
    app = ComicControlApp()
    app.window.mainloop()