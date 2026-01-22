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

# === 核心配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 配色方案 (Cyberpunk Data)
COLOR_BG = "#1a1a1a"
COLOR_CARD = "#2b2b2b"
COLOR_ACCENT = "#3B8ED0"
COLOR_CHART_LINE = "#00FF7F" # 春日绿 (SpringGreen)
COLOR_CHART_BG = "#111111"
COLOR_SUCCESS = "#2ECC71"
COLOR_TEXT_GRAY = "#AAAAAA"
COLOR_ERROR = "#E74C3C"  # <--- 补上了这个缺失的定义

# 尝试导入拖拽库
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

# === 硬件工具库 ===

# 1. 内存检测
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def get_free_ram_gb():
    """获取当前可用物理内存 (GB)"""
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except:
        return 16.0 # 获取失败则假设有16G

# 2. 格式化文件大小
def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    i = int(os.math.floor(os.math.log(size_bytes, 1024)))
    p = os.math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, ("B", "KB", "MB", "GB", "TB")[i])

# === 自定义组件：实时折线图 ===
class MiniChart(ctk.CTkCanvas):
    def __init__(self, master, width=120, height=40, **kwargs):
        super().__init__(master, width=width, height=height, bg=COLOR_CHART_BG, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.data_points = deque(maxlen=30)
        self.max_val = 1
        
    def add_point(self, value):
        self.data_points.append(value)
        self.draw()
        
    def draw(self):
        self.delete("all")
        if not self.data_points: return
        
        current_max = max(self.data_points)
        if current_max > self.max_val: self.max_val = current_max
        else: self.max_val = max(1, self.max_val * 0.99)
        
        points = []
        n_points = len(self.data_points)
        x_step = self.width / (max(n_points - 1, 1))
        
        for i, val in enumerate(self.data_points):
            x = i * x_step
            y = self.height - (val / self.max_val * (self.height - 4))
            points.extend([x, y])
            
        if len(points) >= 4:
            self.create_line(points, fill=COLOR_CHART_LINE, width=1.5, smooth=True)

# === 任务卡片组件 ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#333", **kwargs)
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        
        self.grid_columnconfigure(2, weight=1)
        
        # 左侧信息
        info_box = ctk.CTkFrame(self, fg_color="transparent")
        info_box.grid(row=0, column=0, rowspan=2, padx=10, pady=5, sticky="w")
        
        self.lbl_idx = ctk.CTkLabel(info_box, text=f"{index}", font=("Arial", 14, "bold"), text_color="#555", width=25)
        self.lbl_idx.pack(side="left")
        
        text_box = ctk.CTkFrame(info_box, fg_color="transparent")
        text_box.pack(side="left", padx=5)
        self.lbl_name = ctk.CTkLabel(text_box, text=self.filename, font=("Roboto Medium", 12), anchor="w", text_color="white")
        self.lbl_name.pack(anchor="w")
        self.lbl_status = ctk.CTkLabel(text_box, text="等待中...", font=("Arial", 11), text_color=COLOR_TEXT_GRAY, anchor="w")
        self.lbl_status.pack(anchor="w")

        # 中间折线图
        self.chart_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.chart_frame.grid(row=0, column=1, rowspan=2, padx=10)
        self.chart = MiniChart(self.chart_frame, width=100, height=35)

        # 右侧数据
        self.lbl_stats = ctk.CTkLabel(self, text="", font=("Consolas", 11), text_color=COLOR_ACCENT, anchor="e")
        self.lbl_stats.grid(row=0, column=2, padx=15, pady=5, sticky="e")
        
        # 底部进度条
        self.progress = ctk.CTkProgressBar(self, height=3, corner_radius=0, progress_color=COLOR_ACCENT)
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def enable_chart(self):
        self.chart.pack()

    def update_chart_data(self, fps):
        self.chart.add_point(fps)

    def set_status(self, text, color=COLOR_TEXT_GRAY):
        self.lbl_status.configure(text=text, text_color=color)

    def set_progress(self, val):
        self.progress.set(val)

    def show_final_stats(self, original, compressed):
        if original > 0:
            ratio = (compressed / original) * 100
            saved = 100 - ratio
            text = f"{format_size(original)} -> {format_size(compressed)} (-{saved:.1f}%)"
            self.lbl_stats.configure(text=text)
            self.lbl_stats.configure(text_color=COLOR_SUCCESS if saved > 0 else COLOR_TEXT_GRAY)

# === 主程序 ===
class ModernEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        
        self.title("Ultra Encoder v6.1 - 修正版")
        self.geometry("1100x800")
        
        self.file_queue = [] 
        self.task_widgets = {} 
        self.active_procs = []
        self.is_running = False
        self.stop_requested = False
        self.cpu_threads = os.cpu_count() or 16
        
        # 默认临时目录：当前脚本所在目录 (不再瞎猜是Z盘了)
        self.temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_Ultra_Temp_Cache_")
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir, exist_ok=True)
            
        self.setup_ui()
        
        threading.Thread(target=self.preload_monitor, daemon=True).start()
        self.recalc_concurrency()
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def setup_ui(self):
        # 顶栏
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=15)
        
        # 左侧标题区域
        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="ULTRA ENCODER", font=("Arial Black", 22), text_color=COLOR_ACCENT).pack(anchor="w")
        
        # 缓存盘设置区域
        cache_box = ctk.CTkFrame(title_box, fg_color="#333", corner_radius=6)
        cache_box.pack(anchor="w", pady=(5,0))
        
        self.cache_lbl = ctk.CTkLabel(cache_box, text=f"缓存位置: {self.temp_dir}", font=("Arial", 10), text_color="lightgray")
        self.cache_lbl.pack(side="left", padx=(10, 5))
        
        # === 修复功能：手动更改缓存盘按钮 ===
        ctk.CTkButton(cache_box, text="更改", width=40, height=20, font=("Arial", 10), 
                      fg_color="#555", hover_color="#666", command=self.change_temp_dir).pack(side="left", padx=(0, 5), pady=2)

        # 右侧硬件开关
        hw_box = ctk.CTkFrame(top, fg_color="#222", corner_radius=20)
        hw_box.pack(side="right")
        
        self.use_gpu = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(hw_box, text="RTX 4080 (GPU)", variable=self.use_gpu, command=self.on_mode_change, font=("Arial", 12, "bold")).pack(side="left", padx=15, pady=8)
        
        self.preload_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(hw_box, text="智能内存预读", variable=self.preload_var).pack(side="left", padx=15, pady=8)

        # 参数栏
        param_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD)
        param_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        self.strategy_lbl = ctk.CTkLabel(param_frame, text="初始化...", text_color="#888", font=("Arial", 11))
        self.strategy_lbl.pack(anchor="w", padx=15, pady=(8, 0))

        grid = ctk.CTkFrame(param_frame, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(grid, text="CRF 画质:").pack(side="left", padx=5)
        self.crf_var = ctk.IntVar(value=23)
        self.crf_slider = ctk.CTkSlider(grid, from_=0, to=51, variable=self.crf_var, number_of_steps=51, width=180)
        self.crf_slider.pack(side="left", padx=5)
        self.crf_val = ctk.CTkLabel(grid, text="23", width=30, font=("Arial", 12, "bold"))
        self.crf_val.pack(side="left")
        self.crf_var.trace("w", lambda *a: self.crf_val.configure(text=f"{self.crf_var.get()}"))
        
        # 默认使用 H.264
        self.codec_var = ctk.StringVar(value="AVC (H.264)")
        ctk.CTkComboBox(grid, values=["AVC (H.264)", "HEVC (H.265)"], variable=self.codec_var, width=140).pack(side="right", padx=5)
        
        self.preset_var = ctk.StringVar(value="p6 (Better)")
        self.preset_combo = ctk.CTkComboBox(grid, values=["p7 (Best)", "p6 (Better)", "p4 (Medium)"], variable=self.preset_var, width=140)
        self.preset_combo.pack(side="right", padx=5)

        # 任务列表
        list_area = ctk.CTkFrame(self, fg_color="transparent")
        list_area.pack(fill="both", expand=True, padx=20, pady=5)
        
        hdr = ctk.CTkFrame(list_area, fg_color="transparent", height=30)
        hdr.pack(fill="x", pady=(0, 5))
        ctk.CTkButton(hdr, text="📂 源目录", command=self.open_source, width=80, fg_color="#444").pack(side="right", padx=5)
        ctk.CTkButton(hdr, text="清空", command=self.clear_all, width=60, fg_color=COLOR_ERROR).pack(side="right", padx=5)
        ctk.CTkButton(hdr, text="+ 添加", command=self.add_files, width=80).pack(side="right", padx=5)
        ctk.CTkLabel(hdr, text="任务监控面板", font=("Arial", 14, "bold")).pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(list_area, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True)

        # 底部栏
        btm = ctk.CTkFrame(self, fg_color="#111", height=70, corner_radius=0)
        btm.pack(fill="x", side="bottom")
        
        self.total_prog = ctk.CTkProgressBar(btm, height=4, progress_color=COLOR_ACCENT)
        self.total_prog.set(0)
        self.total_prog.pack(fill="x")
        
        ctrl = ctk.CTkFrame(btm, fg_color="transparent")
        ctrl.pack(fill="x", padx=20, pady=15)
        
        self.status_txt = ctk.CTkLabel(ctrl, text="就绪", font=("Arial", 13))
        self.status_txt.pack(side="left")
        
        self.stop_btn = ctk.CTkButton(ctrl, text="⏹ 停止", command=self.stop, state="disabled", fg_color=COLOR_ERROR, width=80)
        self.stop_btn.pack(side="right", padx=10)
        
        self.run_btn = ctk.CTkButton(ctrl, text="🚀 启动引擎", command=self.run, font=("Arial", 14, "bold"), width=150)
        self.run_btn.pack(side="right")

    # === 功能实现 ===
    
    def change_temp_dir(self):
        """手动选择 SSD 缓存目录"""
        if self.is_running:
            messagebox.showwarning("提示", "任务运行中无法更改缓存目录")
            return
        
        new_dir = filedialog.askdirectory(title="请选择一个 SSD 硬盘作为临时缓存目录")
        if new_dir:
            # 创建缓存子目录
            cache_path = os.path.join(new_dir, "_Ultra_Temp_Cache_")
            try:
                os.makedirs(cache_path, exist_ok=True)
                self.temp_dir = cache_path
                self.cache_lbl.configure(text=f"缓存位置: {self.temp_dir}")
                messagebox.showinfo("成功", f"缓存目录已切换至:\n{self.temp_dir}\n\n压制时将使用该磁盘读写，完成后移回源目录。")
            except Exception as e:
                messagebox.showerror("错误", f"无法创建目录: {str(e)}")

    def on_mode_change(self):
        self.recalc_concurrency()
        if self.use_gpu.get():
            self.preset_combo.configure(values=["p7 (Best)", "p6 (Better)", "p4 (Medium)"])
            self.preset_var.set("p6 (Better)")
        else:
            self.preset_combo.configure(values=["veryslow", "slower", "medium", "fast", "ultrafast"])
            self.preset_var.set("medium")

    def recalc_concurrency(self):
        if self.use_gpu.get():
            self.workers = 2
            t = "⚡ GPU 模式: 锁定 2 并发 (RTX 4080 双芯片)"
        else:
            calc = max(1, (self.cpu_threads - 4) // 7)
            self.workers = min(calc, 5)
            t = f"🐢 CPU 模式: 智能分配 {self.workers} 并发"
        self.strategy_lbl.configure(text=t)

    def open_source(self):
        if self.file_queue:
            path = os.path.dirname(self.file_queue[0])
            if os.path.exists(path):
                os.startfile(path)
        else:
            os.startfile(os.path.expanduser("~"))

    def add_files(self):
        self.add_files_list(filedialog.askopenfilenames())

    def drop_file(self, event):
        self.add_files_list(self.tk.splitlist(event.data))

    def add_files_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                idx = len(self.file_queue)
                card = TaskCard(self.scroll, idx, f)
                card.pack(fill="x", pady=5)
                self.task_widgets[f] = card

    def clear_all(self):
        if self.is_running: return
        for w in self.task_widgets.values(): w.destroy()
        self.task_widgets = {}
        self.file_queue = []
        self.total_prog.set(0)

    # === 智能预读 ===
    def preload_monitor(self):
        while True:
            if self.is_running and self.preload_var.get() and not self.stop_requested:
                free_ram = get_free_ram_gb()
                if free_ram < 8.0:
                    time.sleep(2)
                    continue

                target = None
                for f in self.file_queue:
                    widget = self.task_widgets.get(f)
                    if widget and widget.lbl_status.cget("text") == "等待中...":
                        target = f
                        break
                
                if target:
                    self.perform_cache(target)
                else:
                    time.sleep(1)
            else:
                time.sleep(1)

    def perform_cache(self, fpath):
        try:
            widget = self.task_widgets[fpath]
            self.after(0, lambda: widget.set_status("⚡ 内存缓冲中...", COLOR_ACCENT))
            
            size = os.path.getsize(fpath)
            if size > 50*1024*1024:
                with open(fpath, 'rb') as f:
                    while chunk := f.read(32*1024*1024):
                        if self.stop_requested: return
                        
            self.after(0, lambda: widget.set_status("🚀 就绪 (内存驻留)", COLOR_SUCCESS))
        except: pass

    # === 压制核心 ===
    def run(self):
        if not self.file_queue: return
        self.is_running = True
        self.stop_requested = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.recalc_concurrency()
        threading.Thread(target=self.worker_pool, daemon=True).start()

    def stop(self):
        self.stop_requested = True
        self.status_txt.configure(text="正在停止...")
        for p in self.active_procs:
            try: 
                p.terminate()
                p.kill()
            except: pass
        self.active_procs = []
        self.is_running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def worker_pool(self):
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.process_video, f) for f in self.file_queue]
            for fut in futures:
                if self.stop_requested: break
                try: fut.result() 
                except: pass
        
        if not self.stop_requested:
            self.after(0, lambda: messagebox.showinfo("完成", "所有任务处理完毕！"))
            self.after(0, lambda: [self.run_btn.configure(state="normal"), self.stop_btn.configure(state="disabled")])
            self.is_running = False

    def process_video(self, input_file):
        if self.stop_requested: return
        
        widget = self.task_widgets[input_file]
        name, ext = os.path.splitext(os.path.basename(input_file))
        tag = "H264" if "H.264" in self.codec_var.get() else "H265"
        
        # 使用当前设置的 SSD 缓存目录
        temp_output = os.path.join(self.temp_dir, f"TEMP_{name}_{tag}{ext}")
        final_output = os.path.join(os.path.dirname(input_file), f"{name}_{tag}_V6{ext}")
        
        try:
            original_size = os.path.getsize(input_file)
        except: original_size = 0
        
        self.after(0, lambda: [widget.set_status("▶️ 压制中 (SSD加速)", "#3498DB"), widget.enable_chart()])

        cmd = ["ffmpeg", "-y", "-i", input_file]
        crf = self.crf_var.get()
        preset = self.preset_var.get().split(" ")[0]
        
        if self.use_gpu.get():
            codec = "h264_nvenc" if "H.264" in self.codec_var.get() else "hevc_nvenc"
            cmd.extend(["-c:v", codec, "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(crf), "-preset", preset, "-spatial-aq", "1"])
        else:
            codec = "libx264" if "H.264" in self.codec_var.get() else "libx265"
            cmd.extend(["-c:v", codec, "-crf", str(crf), "-preset", preset])
            
        cmd.extend(["-c:a", "copy", temp_output])

        duration = self.get_duration(input_file)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)
        self.active_procs.append(proc)
        
        last_chart_update = 0
        
        for line in proc.stdout:
            if self.stop_requested: break
            
            if "time=" in line:
                time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                if time_match and duration > 0:
                    h, m, s = map(float, time_match.groups())
                    percent = (h*3600 + m*60 + s) / duration
                    
                    fps_match = re.search(r"fps=\s*(\d+)", line)
                    fps = int(fps_match.group(1)) if fps_match else 0
                    
                    now = time.time()
                    if now - last_chart_update > 0.5:
                        self.after(0, lambda w=widget, f=fps: w.update_chart_data(f))
                        last_chart_update = now
                    
                    self.after(0, lambda w=widget, p=percent, f=fps: [
                        w.set_progress(p),
                        w.set_status(f"▶️ Speed: {f} fps | SSD Temp", "#3498DB")
                    ])
        
        proc.wait()
        if proc in self.active_procs: self.active_procs.remove(proc)
        
        if not self.stop_requested and proc.returncode == 0:
            try:
                # 完成后，从 SSD 移动回源目录 (瞬间完成)
                if os.path.exists(temp_output):
                    shutil.move(temp_output, final_output)
                    
                final_size = os.path.getsize(final_output)
                self.after(0, lambda: [
                    widget.set_status("✅ 完成 (已移回源盘)", COLOR_SUCCESS),
                    widget.set_progress(1),
                    widget.show_final_stats(original_size, final_size)
                ])
                
                done = sum(1 for w in self.task_widgets.values() if "完成" in w.lbl_status.cget("text"))
                self.after(0, lambda: [
                    self.total_prog.set(done / len(self.file_queue)),
                    self.status_txt.configure(text=f"进度: {done}/{len(self.file_queue)}")
                ])
            except Exception as e:
                self.after(0, lambda: widget.set_status(f"⚠️ 移动失败: {str(e)}", COLOR_ERROR))
        else:
             if os.path.exists(temp_output): os.remove(temp_output)

    def get_duration(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

if __name__ == "__main__":
    app = ModernEncoderApp()
    app.mainloop()
