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

# === 全局视觉配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 专业级深色主题
COLOR_BG_MAIN = "#121212"
COLOR_BG_LEFT = "#1e1e1e"
COLOR_BG_RIGHT = "#181818"
COLOR_ACCENT = "#3B8ED0"        # 主题蓝
COLOR_CHART_FILL = "#1a2c38"    # 图表填充背景
COLOR_CHART_LINE = "#00E676"    # 荧光绿 (FPS)
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_GRAY = "#888888"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#FF2A6D"
COLOR_WARNING = "#F1C40F"

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
    # 优先 D/E 盘
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

# === 组件：全历史自动缩放示波器 (Infinity Scope) ===
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, height=120, **kwargs):
        super().__init__(master, height=height, bg="#000", highlightthickness=0, **kwargs)
        self.height = height
        # 不再限制 maxlen，记录全程历史
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
        
        # 动态量程：始终以当前最大值为基准，保证波形填满高度
        current_max = max(self.points)
        if current_max > self.max_val: self.max_val = current_max
        # 缓慢衰减 Y 轴上限
        else: self.max_val = max(10, self.max_val * 0.99)
        
        scale_y = (h - 20) / self.max_val
        
        # 网格线
        self.create_line(0, h/2, w, h/2, fill="#1a1a1a", dash=(2,4))
        self.create_line(0, h*0.25, w, h*0.25, fill="#1a1a1a", dash=(2,4))
        self.create_line(0, h*0.75, w, h*0.75, fill="#1a1a1a", dash=(2,4))

        # 核心算法：自动缩放 X 轴
        # 如果点数少于像素宽，每个点占一定宽度
        # 如果点数多于像素宽，则压缩步长
        # 始终让 第一个点在左边，最后一个点在右边
        if n < 2: return
        
        step_x = w / (n - 1)
        coords = []
        
        # 为了性能，如果点非常多，可以进行降采样（这里暂不做，几千个点Tkinter还能抗）
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 5
            coords.extend([x, y])
            
        # 绘制
        if len(coords) >= 4:
            # 填充背景 (模拟 Area Chart)
            poly_coords = [0, h] + coords + [w, h]
            # self.create_polygon(poly_coords, fill=COLOR_CHART_FILL, outline="") 
            self.create_line(coords, fill=COLOR_CHART_LINE, width=1.5, smooth=True)

# === 监控通道 ===
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#222", corner_radius=6, border_width=1, border_color="#333", **kwargs)
        
        # 头部
        head = ctk.CTkFrame(self, fg_color="transparent", height=20)
        head.pack(fill="x", padx=10, pady=(5,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"CHANNEL {ch_id} // IDLE", font=("Consolas", 11, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="--", font=("Arial", 10), text_color="#444")
        self.lbl_info.pack(side="right")
        
        # 示波器
        self.scope = InfinityScope(self, height=100)
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        
        # 底部数据
        btm = ctk.CTkFrame(self, fg_color="transparent", height=20)
        btm.pack(fill="x", padx=10, pady=(0,5))
        self.lbl_fps = ctk.CTkLabel(btm, text="0", font=("Impact", 18), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 9), text_color="#444").pack(side="left", padx=(5,0), pady=(5,0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 12, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        self.lbl_title.configure(text=f"ACTIVE: {filename[:15]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=f"[{tag}]", text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.scope.clear()

    def update_data(self, fps, prog):
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{fps}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")

    def reset(self):
        self.lbl_title.configure(text="CHANNEL // IDLE", text_color="#555")
        self.lbl_info.configure(text="--", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.scope.clear()

# === 任务卡片 ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color="#2b2b2b", corner_radius=4, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        
        # 序号
        ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 16), text_color="#444").grid(row=0, column=0, rowspan=2, padx=8)
        
        # 文件名
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("Arial", 11), text_color="#CCC", anchor="w").grid(row=0, column=1, sticky="w", padx=2, pady=(4,0))
        
        # 状态
        self.lbl_status = ctk.CTkLabel(self, text="WAITING", font=("Arial", 9), text_color="#666", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=2, pady=(0,4))
        
        # 进度条
        self.progress = ctk.CTkProgressBar(self, height=2, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew")

    def set_status(self, text, color="#666"):
        self.lbl_status.configure(text=text, text_color=color)
    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v12 - Infinity Monitor")
        self.geometry("1300x850")
        self.configure(fg_color=COLOR_BG_MAIN)
        
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.temp_files = set()
        self.running = False
        self.stop_flag = False
        self.slot_lock = threading.Lock()
        
        # 动态通道管理
        self.monitor_slots = [] # 存放 MonitorChannel 对象
        self.available_indices = [] # 存放空闲的 index
        self.current_workers = 2
        
        self.temp_dir = ""
        
        self.setup_ui()
        self.after(200, self.sys_check)
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def sys_check(self):
        self.set_global_status("正在检查系统环境...")
        if not check_ffmpeg():
            messagebox.showerror("Error", "FFmpeg Not Found!")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.preload_worker, daemon=True).start()

    def scan_disk(self):
        self.set_global_status("正在扫描最佳缓存磁盘...")
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.lbl_cache.configure(text=f"SSD CACHE: {path}"))
        self.set_global_status("系统就绪")

    def set_global_status(self, text):
        self.lbl_global_status.configure(text=f"STATUS: {text}")

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3) # 左侧 30%
        self.grid_columnconfigure(1, weight=7) # 右侧 70%
        self.grid_rowconfigure(1, weight=1) # 内容区拉伸

        # === 顶部通栏状态条 ===
        top_bar = ctk.CTkFrame(self, fg_color="#1a1a1a", height=30, corner_radius=0)
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.lbl_global_status = ctk.CTkLabel(top_bar, text="STATUS: INITIALIZING...", font=("Consolas", 10), text_color="#AAA")
        self.lbl_global_status.pack(side="left", padx=10)
        self.lbl_cache = ctk.CTkLabel(top_bar, text="CACHE: --", font=("Consolas", 10), text_color="#666")
        self.lbl_cache.pack(side="right", padx=10)

        # === 左侧面板 (控制台) ===
        left = ctk.CTkFrame(self, fg_color=COLOR_BG_LEFT, corner_radius=0)
        left.grid(row=1, column=0, sticky="nsew")
        
        # 标题区
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=15, pady=15)
        ctk.CTkLabel(l_head, text="TASK QUEUE", font=("Impact", 20), text_color="#FFF").pack(anchor="w")
        
        # 列表操作
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(btn_row, text="+ 导入", width=70, fg_color="#333", command=self.add_file).pack(side="left", padx=2)
        ctk.CTkButton(btn_row, text="清空", width=60, fg_color="#333", hover_color=COLOR_ERROR, command=self.clear_all).pack(side="left", padx=2)
        
        # 滚动列表
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 左侧底部参数区 (重构)
        l_btm = ctk.CTkFrame(left, fg_color="#252525", corner_radius=0)
        l_btm.pack(fill="x", side="bottom")
        
        # 1. 编码器选择 (Segmented Button 更美观)
        ctk.CTkLabel(l_btm, text="CODEC", font=("Arial", 10, "bold"), text_color="#666").pack(anchor="w", padx=15, pady=(10,0))
        self.codec_var = ctk.StringVar(value="H.264")
        self.seg_codec = ctk.CTkSegmentedButton(l_btm, values=["H.264", "H.265"], variable=self.codec_var, selected_color=COLOR_ACCENT)
        self.seg_codec.pack(fill="x", padx=15, pady=5)
        
        # 2. CRF
        ctk.CTkLabel(l_btm, text="QUALITY (CRF)", font=("Arial", 10, "bold"), text_color="#666").pack(anchor="w", padx=15, pady=(5,0))
        crf_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        crf_box.pack(fill="x", padx=10, pady=5)
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkSlider(crf_box, from_=0, to=51, variable=self.crf_var, number_of_steps=51, progress_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(crf_box, textvariable=self.crf_var, width=25, font=("Arial", 12, "bold"), text_color="#FFF").pack(side="right")
        
        # 3. 并发数与GPU
        hw_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        hw_box.pack(fill="x", padx=15, pady=10)
        
        # 并发数选择 (动态触发右侧重建)
        ctk.CTkLabel(hw_box, text="WORKERS:", font=("Arial", 10)).pack(side="left")
        self.worker_var = ctk.StringVar(value="2")
        self.seg_worker = ctk.CTkSegmentedButton(hw_box, values=["1", "2", "3", "4"], variable=self.worker_var, width=100, 
                                               command=self.update_monitor_layout, selected_color=COLOR_ACCENT)
        self.seg_worker.pack(side="left", padx=5)

        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(hw_box, text="GPU", variable=self.gpu_var, progress_color=COLOR_ACCENT).pack(side="right")

        # 启动按钮
        act_box = ctk.CTkFrame(l_btm, fg_color="#111", corner_radius=0)
        act_box.pack(fill="x", side="bottom")
        self.btn_stop = ctk.CTkButton(act_box, text="STOP", fg_color="#222", width=60, hover_color=COLOR_ERROR, state="disabled", command=self.stop)
        self.btn_stop.pack(side="left", padx=10, pady=15)
        self.btn_run = ctk.CTkButton(act_box, text="START ENGINE", font=("Arial", 13, "bold"), fg_color=COLOR_ACCENT, text_color="#000", height=35, command=self.run)
        self.btn_run.pack(side="right", fill="x", expand=True, padx=(0,15), pady=15)

        # === 右侧面板 (动态监控) ===
        self.right = ctk.CTkFrame(self, fg_color=COLOR_BG_RIGHT, corner_radius=0)
        self.right.grid(row=1, column=1, sticky="nsew")
        
        # 监控区容器 (Scrollable)
        self.monitor_scroll = ctk.CTkScrollableFrame(self.right, fg_color="transparent")
        self.monitor_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 初始构建 2 个通道
        self.update_monitor_layout()

    # === 核心逻辑 ===
    def update_monitor_layout(self, val=None):
        """根据选择的并发数，动态重建右侧监控面板"""
        if self.running:
            messagebox.showwarning("Warning", "请先停止任务再修改并发数")
            self.seg_worker.set(str(self.current_workers))
            return

        try:
            n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        
        # 清空旧通道
        for ch in self.monitor_slots:
            ch.destroy()
        self.monitor_slots.clear()
        
        # 重建新通道
        for i in range(n):
            ch = MonitorChannel(self.monitor_scroll, i+1)
            ch.pack(fill="x", pady=5) # 垂直堆叠
            self.monitor_slots.append(ch)
            
        self.set_global_status(f"监控布局已更新: {n} 通道")

    def open_cache(self):
        if self.temp_dir and os.path.exists(self.temp_dir): os.startfile(self.temp_dir)
    def add_file(self): self.add_list(filedialog.askopenfilenames())
    def drop_file(self, event): self.add_list(self.tk.splitlist(event.data))
    
    def add_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                card = TaskCard(self.scroll, len(self.file_queue), f)
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
                    if w and w.lbl_status.cget("text") == "WAITING":
                        target = f; break
                if target:
                    w = self.task_widgets[target]
                    self.after(0, lambda: w.set_status("CACHING", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_flag: return
                        self.after(0, lambda: w.set_status("READY", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    # === 执行引擎 ===
    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        
        self.btn_run.configure(state="disabled", text="RUNNING...")
        self.btn_stop.configure(state="normal", fg_color=COLOR_ERROR)
        self.seg_worker.configure(state="disabled") # 锁定并发选择
        self.seg_codec.configure(state="disabled")
        
        # 初始化通道池
        self.available_indices = list(range(self.current_workers))
        for ch in self.monitor_slots: ch.reset()
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.set_global_status("正在中止所有进程...")
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        threading.Thread(target=self.clean_junk).start()
        self.running = False
        self.reset_ui_state()

    def reset_ui_state(self):
        self.btn_run.configure(state="normal", text="START ENGINE")
        self.btn_stop.configure(state="disabled", fg_color="#222")
        self.seg_worker.configure(state="normal")
        self.seg_codec.configure(state="normal")
        self.set_global_status("就绪")

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
            self.after(0, lambda: messagebox.showinfo("DONE", "All tasks finished."))
            self.running = False
            self.after(0, self.reset_ui_state)

    def scroll_to_card(self, card):
        """自动滚动列表以显示当前任务"""
        try:
            # 这是一个简单的近似滚动，CTkScrollableFrame 没有直接的 scroll_to_widget
            # 我们通过计算 widget 位置来滚动
            self.scroll._parent_canvas.yview_moveto(0) # 先回到顶部
            # 这里为了简化，不做复杂计算，只在添加新任务时稍微动一下
            # 更好的交互是高亮当前卡片
            card.configure(fg_color="#333") 
        except: pass

    def process(self, input_file):
        if self.stop_flag: return
        
        # 1. 申请通道
        my_slot_idx = None
        while my_slot_idx is None and not self.stop_flag:
            with self.slot_lock:
                if self.available_indices:
                    my_slot_idx = self.available_indices.pop(0)
            if my_slot_idx is None: time.sleep(0.1)

        if self.stop_flag: return

        ch_ui = self.monitor_slots[my_slot_idx]
        card = self.task_widgets[input_file]
        
        # 2. 自动聚焦
        self.after(0, lambda: self.scroll_to_card(card))
        self.set_global_status(f"正在压制: {os.path.basename(input_file)}")

        fname = os.path.basename(input_file)
        name, ext = os.path.splitext(fname
