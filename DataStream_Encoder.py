import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import re
import os
import time
import shutil
import ctypes
from concurrent.futures import ThreadPoolExecutor
from collections import deque

# === 全局视觉配置 (简约大气风) ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")  # 回归标准蓝

# Windows 11 风格配色
COLOR_BG_MAIN = "#202020"      # 标准深灰背景
COLOR_PANEL_LEFT = "#2b2b2b"   # 侧边栏稍亮
COLOR_PANEL_RIGHT = "#202020"  # 内容区
COLOR_CARD = "#333333"         # 卡片背景
COLOR_ACCENT = "#3B8ED0"       # 微软蓝
COLOR_CHART_BG = "#202020"     # 图表背景(透明化)
COLOR_CHART_LINE = "#61afef"   # 柔和蓝 (类似 VSCode)
COLOR_TEXT_MAIN = "#ffffff"
COLOR_TEXT_SUB = "#aaaaaa"
COLOR_SUCCESS = "#73c991"      # 柔和绿
COLOR_ERROR = "#f44747"        # 柔和红

# 拖拽支持
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class DnDWindow(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    HAS_DND = True
except ImportError:
    class DnDWindow(ctk.CTk): pass
    HAS_DND = False

# === 硬件底层 ===
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

def get_free_ram_gb():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except: return 16.0

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except: return False

def get_force_ssd_dir():
    drives = ["D", "E"]
    best = None
    for d in drives:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                if shutil.disk_usage(root).free > 20*1024**3:
                    best = root
                    break
            except: pass
    if not best: best = "C:\\" 
    path = os.path.join(best, "_Ultra_Temp_Cache_")
    os.makedirs(path, exist_ok=True)
    return path

# === 组件：极简示波器 (Clean Scope) ===
class CleanScope(ctk.CTkCanvas):
    def __init__(self, master, height=120, **kwargs):
        super().__init__(master, height=height, bg=COLOR_BG_MAIN, highlightthickness=0, **kwargs)
        self.height = height
        self.points = [] 
        self.max_val = 10
        self.after_id = None
        
    def add_point(self, val):
        self.points.append(val)
        self.draw()
        
    def clear(self):
        self.points = []
        self.max_val = 10
        self.delete("all")
        
    def draw(self):
        self.delete("all")
        if not self.points: return
        
        w = self.winfo_width()
        h = self.height
        n = len(self.points)
        
        current_max = max(self.points)
        if current_max > self.max_val: self.max_val = current_max
        else: self.max_val = max(10, self.max_val * 0.99)
        
        scale_y = (h - 20) / self.max_val
        
        # 极简网格 (只留中线)
        self.create_line(0, h/2, w, h/2, fill="#333", dash=(4,4), width=1)

        if n < 2: return
        
        step_x = w / (n - 1)
        coords = []
        
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
            
        if len(coords) >= 4:
            # 只画一条优雅的细线
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

# === 监控通道 (卡片式) ===
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=8, border_width=0, **kwargs)
        
        # 头部
        head = ctk.CTkFrame(self, fg_color="transparent", height=30)
        head.pack(fill="x", padx=15, pady=(10,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"通道 {ch_id} · 空闲", font=("微软雅黑", 12), text_color=COLOR_TEXT_SUB)
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="--", font=("Arial", 11), text_color=COLOR_TEXT_SUB)
        self.lbl_info.pack(side="right")
        
        # 示波器
        self.scope = CleanScope(self, height=110)
        self.scope.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 底部数据
        btm = ctk.CTkFrame(self, fg_color="transparent", height=20)
        btm.pack(fill="x", padx=15, pady=(0,10))
        self.lbl_fps = ctk.CTkLabel(btm, text="0 FPS", font=("Arial", 16, "bold"), text_color=COLOR_TEXT_MAIN)
        self.lbl_fps.pack(side="left")
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14), text_color=COLOR_TEXT_SUB)
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        self.lbl_title.configure(text=f"正在运行: {filename[:20]}", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color=COLOR_TEXT_MAIN)
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.scope.clear()

    def update_data(self, fps, prog):
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{fps} FPS")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")

    def reset(self):
        self.lbl_title.configure(text="通道 · 空闲", text_color=COLOR_TEXT_SUB)
        self.lbl_info.configure(text="--", text_color=COLOR_TEXT_SUB)
        self.lbl_fps.configure(text="0 FPS")
        self.lbl_prog.configure(text="0%", text_color=COLOR_TEXT_SUB)
        self.scope.clear()

# === 左侧任务项 (极简列表) ===
class TaskItem(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=4, **kwargs) # 透明背景
        self.grid_columnconfigure(1, weight=1)
        
        # 序号
        ctk.CTkLabel(self, text=f"{index}", font=("Arial", 12), text_color=COLOR_TEXT_SUB, width=30).grid(row=0, column=0, padx=5)
        
        # 文件名
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("微软雅黑", 12), text_color=COLOR_TEXT_MAIN, anchor="w").grid(row=0, column=1, sticky="w", padx=5)
        
        # 状态文字
        self.lbl_status = ctk.CTkLabel(self, text="等待中", font=("微软雅黑", 11), text_color=COLOR_TEXT_SUB, anchor="e")
        self.lbl_status.grid(row=0, column=2, padx=10)

        # 细进度条
        self.progress = ctk.CTkProgressBar(self, height=2, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(5,0))

    def set_status(self, text, color=COLOR_TEXT_SUB):
        self.lbl_status.configure(text=text, text_color=color)
    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v13")
        self.geometry("1200x800")
        self.configure(fg_color=COLOR_BG_MAIN)
        
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.temp_files = set()
        self.running = False
        self.stop_flag = False
        self.slot_lock = threading.Lock()
        
        self.monitor_slots = []
        self.available_indices = []
        self.current_workers = 2
        self.temp_dir = ""
        
        self.setup_ui()
        self.after(200, self.sys_check)
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def sys_check(self):
        self.set_status_bar("系统自检中...")
        if not check_ffmpeg():
            messagebox.showerror("错误", "未检测到 FFmpeg！")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.preload_worker, daemon=True).start()

    def scan_disk(self):
        self.set_status_bar("扫描最佳缓存磁盘...")
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"SSD 缓存: {path}"))
        self.set_status_bar("就绪")

    def set_status_bar(self, text):
        self.lbl_global_status.configure(text=text)

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=7)
        self.grid_rowconfigure(1, weight=1)

        # === 顶部导航栏 (更薄，更现代) ===
        nav = ctk.CTkFrame(self, fg_color=COLOR_BG_MAIN, height=40, corner_radius=0)
        nav.grid(row=0, column=0, columnspan=2, sticky="ew")
        
        ctk.CTkLabel(nav, text="Ultra Encoder", font=("Segoe UI", 16, "bold"), text_color=COLOR_TEXT_MAIN).pack(side="left", padx=20)
        self.lbl_global_status = ctk.CTkLabel(nav, text="正在初始化...", font=("微软雅黑", 12), text_color=COLOR_TEXT_SUB)
        self.lbl_global_status.pack(side="left", padx=20)
        
        self.btn_cache = ctk.CTkButton(nav, text="检测中...", fg_color="transparent", hover_color="#333", 
                                     text_color=COLOR_TEXT_SUB, font=("Consolas", 11), height=24, command=self.open_cache)
        self.btn_cache.pack(side="right", padx=20)

        # === 左侧任务栏 (深灰背景) ===
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0)
        left.grid(row=1, column=0, sticky="nsew")
        
        # 操作区
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(tools, text="添加文件", width=100, height=32, command=self.add_file).pack(side="left", padx=(0,5))
        ctk.CTkButton(tools, text="清空", width=60, height=32, fg_color="transparent", border_width=1, border_color="#555", 
                     hover_color="#444", text_color="#ccc", command=self.clear_all).pack(side="left")

        # 列表区
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 左侧底部 (设置区)
        l_btm = ctk.CTkFrame(left, fg_color="transparent")
        l_btm.pack(fill="x", side="bottom", padx=15, pady=20)
        
        # 参数设置
        ctk.CTkLabel(l_btm, text="编码配置", font=("微软雅黑", 12, "bold"), text_color=COLOR_TEXT_SUB).pack(anchor="w", pady=(0,10))
        
        # 1. 格式
        self.codec_var = ctk.StringVar(value="H.264")
        self.seg_codec = ctk.CTkSegmentedButton(l_btm, values=["H.264", "H.265"], variable=self.codec_var)
        self.seg_codec.pack(fill="x", pady=5)
        
        # 2. CRF
        rf_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        rf_box.pack(fill="x", pady=5)
        ctk.CTkLabel(rf_box, text="画质 (CRF)", font=("微软雅黑", 11), text_color=COLOR_TEXT_SUB).pack(side="left")
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkLabel(rf_box, textvariable=self.crf_var, font=("Arial", 11, "bold"), text_color=COLOR_ACCENT).pack(side="right")
        ctk.CTkSlider(l_btm, from_=0, to=51, variable=self.crf_var).pack(fill="x", pady=0)
        
        # 3. 硬件与并发
        hw_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        hw_box.pack(fill="x", pady=15)
        
        self.worker_var = ctk.StringVar(value="2")
        ctk.CTkLabel(hw_box, text="并发数:", font=("微软雅黑", 11), text_color=COLOR_TEXT_SUB).pack(side="left")
        self.seg_worker = ctk.CTkSegmentedButton(hw_box, values=["1", "2", "3", "4"], variable=self.worker_var, 
                                               command=self.update_monitor_layout, width=120)
        self.seg_worker.pack(side="left", padx=10)
        
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(hw_box, text="GPU", variable=self.gpu_var, font=("Arial", 11)).pack(side="right")

        # 开始按钮
        self.btn_run = ctk.CTkButton(l_btm, text="开始压制", height=40, font=("微软雅黑", 14, "bold"), command=self.run)
        self.btn_run.pack(fill="x", pady=(10, 0))
        self.btn_stop = ctk.CTkButton(l_btm, text="停止", height=30, fg_color="transparent", text_color=COLOR_ERROR, hover_color="#331111", state="disabled", command=self.stop)
        self.btn_stop.pack(fill="x", pady=(5, 0))

        # === 右侧面板 (纯净监控区) ===
        self.right = ctk.CTkFrame(self, fg_color=COLOR_BG_MAIN, corner_radius=0)
        self.right.grid(row=1, column=1, sticky="nsew")
        
        self.monitor_scroll = ctk.CTkScrollableFrame(self.right, fg_color="transparent")
        self.monitor_scroll.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.update_monitor_layout()

    # === 逻辑核心 ===
    def update_monitor_layout(self, val=None):
        if self.running:
            messagebox.showwarning("提示", "运行中无法修改并发数")
            self.seg_worker.set(str(self.current_workers))
            return

        try: n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        
        for ch in self.monitor_slots: ch.destroy()
        self.monitor_slots.clear()
        
        for i in range(n):
            ch = MonitorChannel(self.monitor_scroll, i+1)
            ch.pack(fill="x", pady=8)
            self.monitor_slots.append(ch)

    def open_cache(self):
        if self.temp_dir and os.path.exists(self.temp_dir): os.startfile(self.temp_dir)
    def add_file(self): self.add_list(filedialog.askopenfilenames())
    def drop_file(self, event): self.add_list(self.tk.splitlist(event.data))
    
    def add_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                card = TaskItem(self.scroll, len(self.file_queue), f)
                card.pack(fill="x", pady=2)
                self.task_widgets[f] = card

    def clear_all(self):
        if self.running: return
        for w in self.task_widgets.values(): w.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()

    # === 预读 ===
    def preload_worker(self):
        while True:
            if self.running and not self.stop_flag:
                if get_free_ram_gb() < 8.0: 
                    time.sleep(2); continue
                target = None
                for f in self.file_queue:
                    w = self.task_widgets.get(f)
                    if w and w.lbl_status.cget("text") == "等待中":
                        target = f; break
                if target:
                    w = self.task_widgets[target]
                    self.after(0, lambda: w.set_status("预读中", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_flag: return
                        self.after(0, lambda: w.set_status("就绪", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    # === 执行 ===
    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        
        self.btn_run.configure(state="disabled", text="运行中...")
        self.btn_stop.configure(state="normal")
        self.seg_worker.configure(state="disabled")
        self.seg_codec.configure(state="disabled")
        
        self.available_indices = list(range(self.current_workers))
        for ch in self.monitor_slots: ch.reset()
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.set_status_bar("正在停止...")
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        threading.Thread(target=self.clean_junk).start()
        self.running = False
        self.reset_ui_state()

    def reset_ui_state(self):
        self.btn_run.configure(state="normal", text="开始压制")
        self.btn_stop.configure(state="disabled")
        self.seg_worker.configure(state="normal")
        self.seg_codec.configure(state="normal")
        self.set_status_bar("就绪")

    def clean_junk(self):
        time.sleep(0.5)
        for f in list(self.temp_files):
            try: os.remove(f)
            except: pass
        self.temp_files.clear()

    def engine(self):
        try:
            with ThreadPoolExecutor(max_workers=self.current_workers) as pool:
                futures = [pool.submit(self.process, f) for f in self.file_queue]
                for fut in futures:
                    if self.stop_flag: break
                    try: fut.result()
                    except Exception as e: print(e)
        except: pass
        
        if not self.stop_flag:
            self.after(0, lambda: messagebox.showinfo("完成", "所有任务已完成"))
            self.running = False
            self.after(0, self.reset_ui_state)

    def scroll_to_card(self, card):
        try: card.configure(fg_color="#333") 
        except: pass

    def process(self, input_file):
        if self.stop_flag: return
        
        my_slot_idx = None
        while my_slot_idx is None and not self.stop_flag:
            with self.slot_lock:
                if self.available_indices:
                    my_slot_idx = self.available_indices.pop(0)
            if my_slot_idx is None: time.sleep(0.1)

        if self.stop_flag: return

        ch_ui = self.monitor_slots[my_slot_idx]
        card = self.task_widgets[input_file]
        
        self.after(0, lambda: self.scroll_to_card(card))
        self.set_status_bar(f"正在处理: {os.path.basename(input_file)}")

        fname = os.path.basename(input_file)
        # !!! 修复了之前的 SyntaxError Bug !!!
        name, ext = os.path.splitext(fname)
        
        codec_sel = self.codec_var.get()
        is_h265 = "H.265" in codec_sel
        tag = "HEVC" if is_h265 else "AVC"
        
        temp_out = os.path.join(self.temp_dir, f"TMP_{name}_{tag}{ext}")
        final_out = os.path.join(os.path.dirname(input_file), f"{name}_{tag}_V13{ext}")
        self.temp_files.add(temp_out)
        
        self.after(0, lambda: card.set_status("处理中...", COLOR_ACCENT))
        self.after(0, lambda: ch_ui.activate(fname, f"{tag} | {'GPU' if self.gpu_var.get() else 'CPU'}"))
        
        cmd = ["ffmpeg", "-y", "-i", input_file]
        crf = str(self.crf_var.get())
        
        if self.gpu_var.get():
            enc = "hevc_nvenc" if is_h265 else "h264_nvenc"
            cmd.extend(["-c:v", enc, "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", crf, "-preset", "p6", "-spatial-aq", "1"])
        else:
            enc = "libx265" if is_h265 else "libx264"
            cmd.extend(["-c:v", enc, "-crf", crf, "-preset", "medium"])
        
        cmd.extend(["-c:a", "copy", temp_out])

        try:
            duration = self.get_dur(input_file)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                    universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=si)
            self.active_procs.append(proc)
            
            last_t = 0
            for line in proc.stdout:
                if self.stop_flag: break
                if "time=" in line and duration > 0:
                    tm = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    fm = re.search(r"fps=\s*(\d+)", line)
                    if tm:
                        h, m, s = map(float, tm.groups())
                        prog = (h*3600 + m*60 + s) / duration
                        fps = int(fm.group(1)) if fm else 0
                        
                        now = time.time()
                        if now - last_t > 0.1: 
                            self.after(0, lambda p=prog: card.set_progress(p))
                            self.after(0, lambda f=fps, p=prog: ch_ui.update_data(f, p))
                            last_t = now
            
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)

            if not self.stop_flag and proc.returncode == 0:
                if os.path.exists(temp_out): shutil.move(temp_out, final_out)
                if temp_out in self.temp_files: self.temp_files.remove(temp_out)
                
                orig = os.path.getsize(input_file)
                new = os.path.getsize(final_out)
                sv = 100 - (new/orig*100)
                self.after(0, lambda: [card.set_status(f"完成 -{sv:.1f}%", COLOR_SUCCESS), card.set_progress(1)])
            else:
                self.after(0, lambda: card.set_status("失败", COLOR_ERROR))

        except Exception as e:
            print(e)
            self.after(0, lambda: card.set_status("错误", COLOR_ERROR))
        
        self.after(0, ch_ui.reset)
        with self.slot_lock:
            self.available_indices.append(my_slot_idx)
            self.available_indices.sort()
            
        self.set_status_bar("就绪")

    def get_dur(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()
