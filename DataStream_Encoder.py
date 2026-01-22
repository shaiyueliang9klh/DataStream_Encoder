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

# Cyberpunk配色
COLOR_BG_MAIN = "#0f0f0f"      
COLOR_PANEL_LEFT = "#181818"   
COLOR_PANEL_RIGHT = "#121212"  
COLOR_ACCENT = "#00E5FF"       
COLOR_CHART_LINE = "#00FF9D"   
COLOR_TEXT_WHITE = "#EEEEEE"
COLOR_TEXT_GRAY = "#666666"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#FF2A6D"        

# 拖拽库
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

# === 硬件工具 ===
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
    # 暴力寻找 D/E 盘缓存
    drives = ["D", "E"]
    best = None
    
    for d in drives:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                if shutil.disk_usage(root).free > 10*1024**3:
                    best = root
                    break
            except: pass
            
    if not best: best = "C:\\" # 没办法才用C
    
    path = os.path.join(best, "_Ultra_Temp_Cache_")
    os.makedirs(path, exist_ok=True)
    return path

# === 示波器组件 ===
class SmoothScope(ctk.CTkCanvas):
    def __init__(self, master, height=140, **kwargs):
        super().__init__(master, height=height, bg="#000", highlightthickness=0, **kwargs)
        self.height = height
        self.points = deque([0]*100, maxlen=100)
        self.target_val = 0
        self.current_val = 0
        self.anim_running = False
        
    def push_data(self, val):
        self.target_val = val
        
    def start_animation(self):
        if not self.anim_running:
            self.anim_running = True
            self.animate()
            
    def stop_animation(self):
        self.anim_running = False
        
    def animate(self):
        if not self.anim_running: return
        self.current_val += (self.target_val - self.current_val) * 0.2
        self.points.append(self.current_val)
        self.draw()
        self.after(16, self.animate)
        
    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.height
        max_v = max(max(self.points), 10)
        scale = (h - 20) / max_v
        
        # 网格
        self.create_line(0, h/2, w, h/2, fill="#1a1a1a", width=1)
        for i in range(1, 5):
            x = w * (i/5)
            self.create_line(x, 0, x, h, fill="#1a1a1a", width=1)

        coords = []
        step = w / (len(self.points) - 1)
        for i, v in enumerate(self.points):
            x = i * step
            y = h - (v * scale) - 5
            coords.extend([x, y])
        
        self.create_line(coords, fill="#005522", width=4, smooth=True)
        self.create_line(coords, fill=COLOR_CHART_LINE, width=1.5, smooth=True)

# === 监控通道 ===
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color=COLOR_PANEL_RIGHT, corner_radius=8, border_width=1, border_color="#222", **kwargs)
        
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=12, pady=8)
        
        self.lbl_title = ctk.CTkLabel(head, text=f"CHANNEL {ch_id} // STANDBY", font=("Consolas", 12, "bold"), text_color="#444")
        self.lbl_title.pack(side="left")
        self.lbl_tag = ctk.CTkLabel(head, text="--", font=("Arial", 10), text_color="#333")
        self.lbl_tag.pack(side="right")
        
        self.scope = SmoothScope(self, height=130)
        self.scope.pack(fill="both", expand=True, padx=2, pady=2)
        
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=12, pady=8)
        self.lbl_fps = ctk.CTkLabel(btm, text="000", font=("Impact", 24), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10), text_color="#444").pack(side="left", padx=(5,0), pady=(10,0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 16, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def active(self, name, tag):
        self.lbl_title.configure(text=f"ACTIVE // {name[:20]}...", text_color=COLOR_ACCENT)
        self.lbl_tag.configure(text=f"[{tag}]", text_color="#FFF")
        self.lbl_fps.configure(text_color=COLOR_CHART_LINE)
        self.lbl_prog.configure(text_color="#FFF")
        self.scope.start_animation()

    def update(self, fps, prog):
        self.scope.push_data(fps)
        self.lbl_fps.configure(text=f"{fps:03d}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")

    def reset(self):
        self.lbl_title.configure(text="CHANNEL // STANDBY", text_color="#444")
        self.lbl_tag.configure(text="--", text_color="#333")
        self.lbl_fps.configure(text="000", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.scope.push_data(0)
        self.scope.stop_animation()

# === 任务卡片 ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color="#222", corner_radius=6, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 18), text_color="#444").grid(row=0, column=0, rowspan=2, padx=10)
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("Arial", 11, "bold"), text_color="#DDD", anchor="w").grid(row=0, column=1, sticky="w", padx=5, pady=(5,0))
        self.lbl_status = ctk.CTkLabel(self, text="WAITING", font=("Arial", 9), text_color="#666", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,5))
        self.progress = ctk.CTkProgressBar(self, height=2, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#333")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def set_status(self, text, col="#666"):
        self.lbl_status.configure(text=text, text_color=col)
    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v11 - Fixed Edition")
        self.geometry("1280x850")
        self.configure(fg_color=COLOR_BG_MAIN)
        
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.temp_files = set()
        self.running = False
        self.stop_flag = False
        self.slot_lock = threading.Lock()
        
        # 初始默认 2 线程
        self.workers = 2
        
        self.setup_ui()
        self.after(200, self.sys_check)
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("Error", "FFmpeg Not Found!")
            self.btn_run.configure(state="disabled", text="NO FFMPEG")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.preload_worker, daemon=True).start()

    def scan_disk(self):
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"CACHE: {path}"))

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=7)
        self.grid_rowconfigure(0, weight=1)

        # === 左侧 ===
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        
        ctk.CTkLabel(left, text="ULTRA ENCODER", font=("Impact", 24), text_color="#FFF").pack(anchor="w", padx=20, pady=(25, 5))
        
        self.btn_cache = ctk.CTkButton(left, text="SCANNING...", fg_color="#222", hover_color="#333", 
                                     font=("Consolas", 10), height=24, anchor="w", command=self.open_cache)
        self.btn_cache.pack(fill="x", padx=20, pady=(15, 10))
        
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(btns, text="+ IMPORT", width=80, fg_color="#333", command=self.add_file).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="CLEAR", width=60, fg_color="#333", hover_color=COLOR_ERROR, command=self.clear_all).pack(side="left", padx=2)
        
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=5, pady=10)
        
        l_btm = ctk.CTkFrame(left, fg_color="#111", corner_radius=0)
        l_btm.pack(fill="x", side="bottom")
        
        # 参数行 1: CRF & GPU
        p_box1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        p_box1.pack(fill="x", padx=20, pady=(15, 5))
        
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkLabel(p_box1, text="CRF").pack(side="left")
        ctk.CTkSlider(p_box1, from_=0, to=51, variable=self.crf_var, width=100, progress_color=COLOR_ACCENT).pack(side="left", padx=10)
        ctk.CTkLabel(p_box1, textvariable=self.crf_var, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="left")
        
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(p_box1, text="GPU", variable=self.gpu_var, progress_color=COLOR_ACCENT, button_color="#FFF").pack(side="right")

        # 参数行 2: 编码格式 & 并发数
        p_box2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        p_box2.pack(fill="x", padx=20, pady=(5, 15))
        
        # 编码格式选择
        self.codec_var = ctk.StringVar(value="H.265 (HEVC)") # 默认改回 H.265
        ctk.CTkComboBox(p_box2, values=["H.264 (AVC)", "H.265 (HEVC)"], variable=self.codec_var, width=120).pack(side="left")
        
        # 并发数滑块
        ctk.CTkLabel(p_box2, text="并发:").pack(side="left", padx=(10, 5))
        self.worker_var = ctk.IntVar(value=2)
        ctk.CTkComboBox(p_box2, values=["1", "2", "3", "4"], variable=self.worker_var, width=60).pack(side="left")

        # 启动按钮
        act_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        act_box.pack(fill="x", padx=20, pady=(0, 25))
        self.btn_stop = ctk.CTkButton(act_box, text="ABORT", fg_color="#222", width=60, hover_color=COLOR_ERROR, state="disabled", command=self.stop)
        self.btn_stop.pack(side="left")
        self.btn_run = ctk.CTkButton(act_box, text="INITIALIZE SYSTEM", font=("Arial", 13, "bold"), fg_color=COLOR_ACCENT, text_color="#000", command=self.run)
        self.btn_run.pack(side="right", fill="x", expand=True, padx=(10,0))

        # === 右侧 ===
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        ctk.CTkLabel(right, text="SYSTEM MONITOR", font=("Arial Black", 16), text_color="#333").pack(anchor="w", padx=30, pady=(25, 10))
        
        self.ch_uis = []
        for i in range(2): # 依然只显示2个大窗口，多余任务后台排队或逻辑分配
            ch = MonitorChannel(right, i+1)
            ch.pack(fill="both", expand=True, padx=30, pady=10)
            self.ch_uis.append(ch)
            
        ctk.CTkFrame(right, fg_color="transparent", height=20).pack()

    # === 逻辑 ===
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
                    self.after(0, lambda: w.set_status("CACHING...", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_flag: return
                        self.after(0, lambda: w.set_status("READY", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        
        # 获取用户选择的并发数
        try:
            self.workers = int(self.worker_var.get())
        except:
            self.workers = 2

        self.btn_run.configure(state="disabled", text="RUNNING")
        self.btn_stop.configure(state="normal", fg_color=COLOR_ERROR)
        
        self.slots = [0, 1]
        for ch in self.ch_uis: ch.reset()
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        threading.Thread(target=self.clean_junk).start()
        self.running = False
        self.btn_run.configure(state="normal", text="INITIALIZE SYSTEM")
        self.btn_stop.configure(state="disabled", fg_color="#222")

    def clean_junk(self):
        time.sleep(0.5)
        for f in list(self.temp_files):
            try: os.remove(f)
            except: pass
        self.temp_files.clear()

    def engine(self):
        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = [pool.submit(self.process, f) for f in self.file_queue]
                for fut in futures:
                    if self.stop_flag: break
                    try: fut.result()
                    except Exception as e: print(e)
        except: pass
        
        if not self.stop_flag:
            self.after(0, lambda: messagebox.showinfo("DONE", "All tasks finished."))
            self.running = False
            self.after(0, lambda: [
                self.btn_run.configure(state="normal", text="INITIALIZE SYSTEM"),
                self.btn_stop.configure(state="disabled", fg_color="#222")
            ])

    def process(self, input_file):
        if self.stop_flag: return
        
        # 获取显示槽位 (仅用于UI展示，不阻塞实际后台任务)
        my_slot = None
        with self.slot_lock:
            if self.slots: my_slot = self.slots.pop(0)
            
        card = self.task_widgets[input_file]
        ch_ui = self.ch_uis[my_slot] if my_slot is not None else None
        
        fname = os.path.basename(input_file)
        name, ext = os.path.splitext(fname)
        
        # 获取编码格式
        codec_sel = self.codec_var.get()
        is_h265 = "H.265" in codec_sel
        tag = "HEVC" if is_h265 else "AVC"
        
        temp_out = os.path.join(self.temp_dir, f"TMP_{name}_{tag}{ext}")
        final_out = os.path.join(os.path.dirname(input_file), f"{name}_{tag}_V11{ext}")
        
        self.temp_files.add(temp_out)
        
        self.after(0, lambda: card.set_status("ENCODING", "#FFF"))
        if ch_ui:
            self.after(0, lambda: ch_ui.active(fname, f"{tag} | GPU" if self.gpu_var.get() else f"{tag} | CPU"))
        
        cmd = ["ffmpeg", "-y", "-i", input_file]
        crf = str(self.crf_var.get())
        
        # === 动态切换编码器 ===
        if self.gpu_var.get():
            encoder = "hevc_nvenc" if is_h265 else "h264_nvenc"
            cmd.extend(["-c:v", encoder, "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", crf, 
                        "-preset", "p6", "-spatial-aq", "1"])
        else:
            encoder = "libx265" if is_h265 else "libx264"
            cmd.extend(["-c:v", encoder, "-crf", crf, "-preset", "medium"])
        
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
                        if now - last_t > 0.05:
                            self.after(0, lambda p=prog: card.set_progress(p))
                            if ch_ui:
                                self.after(0, lambda f=fps, p=prog: ch_ui.update(f, p))
                            last_t = now
            
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)

            if not self.stop_flag and proc.returncode == 0:
                if os.path.exists(temp_out): shutil.move(temp_out, final_out)
                if temp_out in self.temp_files: self.temp_files.remove(temp_out)
                
                orig = os.path.getsize(input_file)
                new = os.path.getsize(final_out)
                sv = 100 - (new/orig*100)
                self.after(0, lambda: [card.set_status(f"DONE -{sv:.1f}%", COLOR_SUCCESS), card.set_progress(1)])
            else:
                self.after(0, lambda: card.set_status("FAILED", COLOR_ERROR))

        except Exception as e:
            print(e)
            self.after(0, lambda: card.set_status("ERROR", COLOR_ERROR))
        
        # 释放通道
        if ch_ui:
            self.after(0, ch_ui.reset)
            with self.slot_lock:
                self.slots.append(my_slot)
                self.slots.sort()

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
