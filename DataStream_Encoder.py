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

# === 全局配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 配色方案
COLOR_BG_LEFT = "#202020"
COLOR_BG_RIGHT = "#181818"
COLOR_CARD_LEFT = "#2b2b2b"
COLOR_PANEL_RIGHT = "#222222"
COLOR_ACCENT = "#3B8ED0"
COLOR_CHART_LINE = "#00FF7F" # 荧光绿
COLOR_TEXT_GRAY = "#888888"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#E74C3C"

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

# === 硬件与工具 ===
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
    """检查 FFmpeg 是否存在"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except FileNotFoundError:
        return False
    except:
        return False

def get_smart_ssd_temp_dir():
    drives = [f"{d}" for d in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    best_drive = None
    max_free = 0
    fallback_drive = None 
    fallback_free = 0
    
    for drive in drives:
        root = f"{drive}:\\"
        if os.path.exists(root):
            try:
                free = shutil.disk_usage(root).free
                if free > fallback_free:
                    fallback_drive = root
                    fallback_free = free
                
                # 简单的 SSD 判定 (防止耗时过长)
                cmd = f"powershell -Command \"(Get-Partition -DriveLetter {drive} | Get-Disk).MediaType\""
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=si).stdout.strip()
                
                if "SSD" in result:
                    if free > max_free:
                        max_free = free
                        best_drive = root
            except: pass
    
    final_root = best_drive if best_drive else (fallback_drive if fallback_drive else "C:\\")
    if not best_drive and os.path.exists("C:\\"): final_root = "C:\\"

    temp_path = os.path.join(final_root, "_Ultra_Temp_Cache_")
    if not os.path.exists(temp_path):
        os.makedirs(temp_path, exist_ok=True)
    return temp_path

# === 示波器组件 ===
class Oscilloscope(ctk.CTkCanvas):
    def __init__(self, master, height=150, **kwargs):
        super().__init__(master, height=height, bg="#111", highlightthickness=0, **kwargs)
        self.height = height
        self.data_points = deque(maxlen=200) # 高分辨率
        self.max_val = 1
        self.after_id = None
        
    def add_point(self, value):
        self.data_points.append(value)
        self.draw()
        
    def clear(self):
        self.data_points.clear()
        self.delete("all")
        self.max_val = 1
        
    def draw(self):
        self.delete("all")
        if not self.data_points: return
        
        w = self.winfo_width()
        h = self.height
        
        curr = max(self.data_points)
        if curr > self.max_val: self.max_val = curr
        else: self.max_val = max(1, self.max_val * 0.995) 
        
        points = []
        n = len(self.data_points)
        x_step = w / (n - 1) if n > 1 else w
        
        # 网格
        self.create_line(0, h/2, w, h/2, fill="#222", dash=(4,4))
        self.create_line(0, h*0.25, w, h*0.25, fill="#222", dash=(4,4))
        self.create_line(0, h*0.75, w, h*0.75, fill="#222", dash=(4,4))

        # 波形
        for i, val in enumerate(self.data_points):
            x = i * x_step
            y = h - (val / self.max_val * (h - 20)) - 10
            points.extend([x, y])
            
        if len(points) >= 4:
            self.create_line(points, fill=COLOR_CHART_LINE, width=2, smooth=True)

# === 固定监控槽位 (Channel) ===
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, channel_id, **kwargs):
        super().__init__(master, fg_color=COLOR_PANEL_RIGHT, corner_radius=6, border_width=1, border_color="#333", **kwargs)
        self.channel_id = channel_id
        
        # 标题栏
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(5,0))
        
        self.lbl_title = ctk.CTkLabel(top, text=f"CHANNEL {channel_id}: IDLE", font=("Arial", 12, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        
        self.lbl_info = ctk.CTkLabel(top, text="--", font=("Consolas", 11), text_color="#555")
        self.lbl_info.pack(side="right")
        
        # 示波器
        self.scope = Oscilloscope(self, height=140)
        self.scope.pack(fill="both", expand=True, padx=1, pady=5)
        
        # 数据栏
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=10, pady=(0, 5))
        
        self.lbl_fps = ctk.CTkLabel(btm, text="FPS: 0", font=("Consolas", 14, "bold"), text_color="#444")
        self.lbl_fps.pack(side="left")
        
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#444")
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        self.lbl_title.configure(text=f"CH {self.channel_id}: {filename}", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=f"[{tag}] RUNNING", text_color="#EEE")
        self.lbl_fps.configure(text_color=COLOR_ACCENT)
        self.lbl_prog.configure(text_color="white")
        self.scope.clear()

    def update_stats(self, fps, percent):
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"FPS: {fps}")
        self.lbl_prog.configure(text=f"{int(percent*100)}%")

    def reset(self):
        self.lbl_title.configure(text=f"CHANNEL {self.channel_id}: IDLE", text_color="#555")
        self.lbl_info.configure(text="--", text_color="#555")
        self.lbl_fps.configure(text="FPS: 0", text_color="#444")
        self.lbl_prog.configure(text="0%", text_color="#444")
        self.scope.clear()

# === 任务卡片 ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD_LEFT, corner_radius=4, **kwargs)
        
        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(r1, text=f"{index}", font=("Arial", 12, "bold"), text_color="#666", width=20).pack(side="left")
        ctk.CTkLabel(r1, text=os.path.basename(filepath), font=("Arial", 12), text_color="#EEE").pack(side="left", padx=5)
        self.lbl_status = ctk.CTkLabel(r1, text="等待", font=("Arial", 11), text_color="#888")
        self.lbl_status.pack(side="right")
        
        self.progress = ctk.CTkProgressBar(self, height=3, corner_radius=2, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.pack(fill="x", padx=5, pady=(0, 5))

    def set_status(self, text, color="#888"):
        self.lbl_status.configure(text=text, text_color=color)
    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        
        self.title("Ultra Encoder v9 - Dual Scope Edition")
        self.geometry("1200x800")
        
        self.file_queue = [] 
        self.task_widgets = {}  
        self.active_procs = []
        self.active_temp_files = set()
        self.is_running = False
        self.stop_requested = False
        self.cpu_threads = os.cpu_count() or 16
        
        # 频道槽位锁
        self.slot_lock = threading.Lock()
        self.available_slots = [0, 1] # 两个通道 ID
        
        self.codec_var = ctk.StringVar(value="AVC (H.264)")
        
        self.setup_ui()
        
        # 启动后自动检查 FFmpeg 和 缓存
        self.after(500, self.startup_checks)
        threading.Thread(target=self.preload_monitor, daemon=True).start()
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def startup_checks(self):
        # 1. 检查 FFmpeg
        if not check_ffmpeg():
            messagebox.showerror("严重错误", "未检测到 FFmpeg！\n\n请确保已安装 FFmpeg 并将其 bin 目录添加到了系统环境变量 Path 中。\n或者将 ffmpeg.exe 复制到本脚本同一目录下。")
            self.run_btn.configure(state="disabled", text="FFmpeg 缺失")
            return

        # 2. 扫描缓存
        threading.Thread(target=self.scan_ssd, daemon=True).start()

    def scan_ssd(self):
        path = get_smart_ssd_temp_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"缓存: {self.temp_dir}"))

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=7)
        self.grid_rowconfigure(0, weight=1)

        # === 左侧任务区 ===
        left = ctk.CTkFrame(self, fg_color=COLOR_BG_LEFT, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        
        ctk.CTkLabel(left, text="TASK QUEUE", font=("Arial Black", 16), text_color="#FFF").pack(anchor="w", padx=15, pady=(15, 5))
        
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(btn_row, text="+ 添加", width=60, command=self.add_files, fg_color="#444").pack(side="left", padx=2)
        ctk.CTkButton(btn_row, text="清空", width=50, command=self.clear_all, fg_color="#444", hover_color=COLOR_ERROR).pack(side="left", padx=2)
        
        self.btn_cache = ctk.CTkButton(left, text="正在扫描缓存...", height=20, fg_color="#333", font=("Arial", 10), command=self.open_cache_dir)
        self.btn_cache.pack(fill="x", padx=15, pady=5)

        self.scroll_left = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll_left.pack(fill="both", expand=True, padx=5, pady=5)

        l_btm = ctk.CTkFrame(left, fg_color="#2b2b2b", corner_radius=0)
        l_btm.pack(fill="x", side="bottom")
        
        param_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        param_box.pack(fill="x", padx=10, pady=10)
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkLabel(param_box, text="CRF").pack(side="left")
        ctk.CTkSlider(param_box, from_=0, to=51, variable=self.crf_var, width=100).pack(side="left", padx=5)
        ctk.CTkLabel(param_box, textvariable=self.crf_var, font=("Arial", 12, "bold"), width=20).pack(side="left")
        
        self.use_gpu = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(param_box, text="GPU", variable=self.use_gpu, command=self.on_mode_change, width=50).pack(side="right")

        act_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        act_box.pack(fill="x", padx=10, pady=(0, 15))
        self.stop_btn = ctk.CTkButton(act_box, text="停止", command=self.stop, state="disabled", fg_color=COLOR_ERROR, width=60)
        self.stop_btn.pack(side="left", padx=5)
        self.run_btn = ctk.CTkButton(act_box, text="启动引擎", command=self.run, font=("Arial", 14, "bold"), fg_color=COLOR_ACCENT)
        self.run_btn.pack(side="right", fill="x", expand=True, padx=5)

        # === 右侧监控区 ===
        right = ctk.CTkFrame(self, fg_color=COLOR_BG_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=20, pady=15)
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Arial Black", 16), text_color=COLOR_ACCENT).pack(side="left")
        self.strategy_lbl = ctk.CTkLabel(r_head, text="Mode: GPU (Dual Channel)", text_color="#666")
        self.strategy_lbl.pack(side="right")

        # 两个固定的监控通道
        self.channels = []
        for i in range(2):
            ch = MonitorChannel(right, i+1)
            ch.pack(fill="both", expand=True, padx=20, pady=10)
            self.channels.append(ch)

        self.preload_var = ctk.BooleanVar(value=True)
        self.preset_var = ctk.StringVar(value="p6 (Better)")
        self.recalc_concurrency()

    # === 逻辑 ===
    def open_cache_dir(self):
        if os.path.exists(self.temp_dir):
            os.startfile(self.temp_dir)
            
    def on_mode_change(self):
        self.recalc_concurrency()

    def recalc_concurrency(self):
        if self.use_gpu.get():
            self.workers = 2
            self.strategy_lbl.configure(text="MODE: RTX 4080 (Dual Channel)")
            self.preset_var.set("p6 (Better)")
        else:
            self.workers = 2 # 为了UI好看，CPU模式也限制2个主显，后台可以多跑但只显示2个
            self.strategy_lbl.configure(text=f"MODE: CPU")
            self.preset_var.set("medium")

    def add_files(self): self.add_list(filedialog.askopenfilenames())
    def drop_file(self, event): self.add_list(self.tk.splitlist(event.data))

    def add_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                idx = len(self.file_queue)
                card = TaskCard(self.scroll_left, idx, f)
                card.pack(fill="x", pady=2)
                self.task_widgets[f] = card

    def clear_all(self):
        if self.is_running: return
        for w in self.task_widgets.values(): w.destroy()
        self.task_widgets = {}
        self.file_queue = []

    def preload_monitor(self):
        while True:
            if self.is_running and self.preload_var.get() and not self.stop_requested:
                if get_free_ram_gb() < 8.0:
                    time.sleep(2); continue
                target = None
                for f in self.file_queue:
                    w = self.task_widgets.get(f)
                    if w and w.lbl_status.cget("text") == "等待":
                        target = f; break
                if target:
                    w = self.task_widgets[target]
                    self.after(0, lambda: w.set_status("⚡ 预读", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_requested: return
                        self.after(0, lambda: w.set_status("🚀 就绪", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    def run(self):
        if not self.file_queue: return
        self.is_running = True
        self.stop_requested = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.recalc_concurrency()
        
        # 重置通道
        self.available_slots = [0, 1]
        for ch in self.channels: ch.reset()
        
        threading.Thread(target=self.worker_pool, daemon=True).start()

    def stop(self):
        self.stop_requested = True
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        self.active_procs = []
        threading.Thread(target=self.clean_cache).start()
        self.is_running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def clean_cache(self):
        time.sleep(0.5)
        for f in list(self.active_temp_files):
            try:
                if os.path.exists(f): os.remove(f)
            except: pass
        self.active_temp_files.clear()

    def worker_pool(self):
        # 错误捕获的关键
        try:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = [executor.submit(self.process_video, f) for f in self.file_queue]
                for fut in futures:
                    if self.stop_requested: break
                    try: fut.result() 
                    except Exception as e: print(f"Task Error: {e}")
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Engine Error", str(e)))

        if not self.stop_requested:
            self.after(0, lambda: messagebox.showinfo("完成", "队列已全部处理完毕"))
            self.is_running = False
            self.after(0, lambda: [self.run_btn.configure(state="normal"), self.stop_btn.configure(state="disabled")])

    def process_video(self, input_file):
        if self.stop_requested: return
        
        # 1. 获取显示通道 (Slot)
        slot_id = None
        with self.slot_lock:
            if self.available_slots:
                slot_id = self.available_slots.pop(0)
        
        # 如果没有空闲槽位（理论上不会，因为线程池限制了），就等待
        if slot_id is None: return 

        channel_ui = self.channels[slot_id]
        left_card = self.task_widgets[input_file]
        
        fname = os.path.basename(input_file)
        name, ext = os.path.splitext(fname)
        tag = "H264"
        temp_out = os.path.join(self.temp_dir, f"TEMP_{name}_{tag}{ext}")
        final_out = os.path.join(os.path.dirname(input_file), f"{name}_{tag}_V9{ext}")
        self.active_temp_files.add(temp_out)

        # 启动 UI
        self.after(0, lambda: [left_card.set_status("▶️ 运行", "#FFF"), 
                               channel_ui.activate(fname, "NVENC" if self.use_gpu.get() else "CPU")])

        # FFmpeg 命令
        cmd = ["ffmpeg", "-y", "-i", input_file]
        if self.use_gpu.get():
            cmd.extend(["-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(self.crf_var.get()), "-preset", self.preset_var.get().split(" ")[0], "-spatial-aq", "1"])
        else:
            cmd.extend(["-c:v", "libx264", "-crf", str(self.crf_var.get()), "-preset", self.preset_var.get().split(" ")[0]])
        cmd.extend(["-c:a", "copy", temp_output])

        # 执行
        try:
            duration = self.get_duration(input_file)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # 关键修复：捕获 FileNotFoundError
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                    universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=si)
            self.active_procs.append(proc)
            
            last_up = 0
            for line in proc.stdout:
                if self.stop_requested: break
                if "time=" in line and duration > 0:
                    tm = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    fm = re.search(r"fps=\s*(\d+)", line)
                    if tm:
                        h, m, s = map(float, tm.groups())
                        per = (h*3600 + m*60 + s) / duration
                        fps = int(fm.group(1)) if fm else 0
                        
                        now = time.time()
                        if now - last_up > 0.2:
                            self.after(0, lambda p=per: left_card.set_progress(p))
                            self.after(0, lambda f=fps, p=per: channel_ui.update_stats(f, p))
                            last_up = now

            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)

            if not self.stop_requested and proc.returncode == 0:
                if os.path.exists(temp_out): shutil.move(temp_out, final_out)
                if temp_out in self.active_temp_files: self.active_temp_files.remove(temp_out)
                
                orig = os.path.getsize(input_file)
                comp = os.path.getsize(final_out)
                saved = 100 - (comp/orig*100)
                self.after(0, lambda: [left_card.set_status(f"✅ -{saved:.1f}%", COLOR_SUCCESS), left_card.set_progress(1)])
            else:
                if os.path.exists(temp_out): os.remove(temp_out)
                self.after(0, lambda: left_card.set_status("❌ 中止", COLOR_ERROR))

        except FileNotFoundError:
            self.after(0, lambda: left_card.set_status("⚠️ 缺FFmpeg", COLOR_ERROR))
            messagebox.showerror("Error", "找不到 ffmpeg.exe，请检查环境变量！")
        except Exception as e:
             self.after(0, lambda: left_card.set_status("⚠️ 错误", COLOR_ERROR))
             print(e)

        # 释放通道
        self.after(0, channel_ui.reset)
        with self.slot_lock:
            self.available_slots.append(slot_id)
            self.available_slots.sort() # 保持顺序

    def get_duration(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()
