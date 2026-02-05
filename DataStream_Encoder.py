import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import os
import time
import shutil
import ctypes
from concurrent.futures import ThreadPoolExecutor
import http.server
import socketserver
from http import HTTPStatus
from functools import partial  # [v68 Fix]: 引入 partial 解决闭包问题

# === 全局视觉配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# [v67]: 动态计算内存限制
def get_total_ram_gb():
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys / (1024**3)
    except:
        return 16.0

# [v68]: 新增显存检测
def get_free_vram_gb():
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"]
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        output = subprocess.check_output(cmd, startupinfo=si, encoding="utf-8").strip()
        # nvidia-smi returns MiB
        return float(output) / 1024.0
    except:
        return 999.0 # 无法检测时假设无限，避免误判

TOTAL_RAM = get_total_ram_gb()
MAX_RAM_LOAD_GB = max(4.0, TOTAL_RAM - 12.0) 
SAFE_RAM_RESERVE = 6.0  

print(f"[System] RAM: {TOTAL_RAM:.1f}GB | Cache Limit: {MAX_RAM_LOAD_GB:.1f}GB")

COLOR_BG_MAIN = "#121212"
COLOR_PANEL_LEFT = "#1a1a1a"
COLOR_PANEL_RIGHT = "#0f0f0f"
COLOR_CARD = "#2d2d2d"
COLOR_ACCENT = "#3B8ED0"
COLOR_ACCENT_HOVER = "#36719f"
COLOR_CHART_LINE = "#00E676"
COLOR_READY_RAM = "#00B894" 
COLOR_SUCCESS = "#2ECC71" 
COLOR_MOVING = "#F1C40F"  
COLOR_READING = "#9B59B6" 
COLOR_RAM     = "#3498DB" 
COLOR_SSD_CACHE = "#E67E22" 
COLOR_DIRECT  = "#1ABC9C" 
COLOR_PAUSED = "#7f8c8d"  
COLOR_ERROR = "#FF4757"   

STATUS_WAIT = 0
STATUS_CACHING = 1   
STATUS_READY = 2     
STATUS_RUN = 3       
STATUS_DONE = 5
STATUS_ERR = -1

PRIORITY_NORMAL = 0x00000020
PRIORITY_ABOVE = 0x00008000
PRIORITY_HIGH = 0x00000080

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

# === Windows 功耗管理 ===
class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong)]

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def set_execution_state(enable=True):
    try:
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except: pass

def disable_power_throttling(process_handle=None):
    try:
        PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
        PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
        ProcessPowerThrottling = 0x22
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION
        state.StateMask = 0 
        if process_handle is None:
            process_handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetProcessInformation(process_handle, ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state))
    except: pass

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

# === 内存流媒体服务器 ===
class RamHttpHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass 
    def do_GET(self):
        data = self.server.ram_data
        if not data:
            self.send_error(HTTPStatus.NOT_FOUND, "No data loaded")
            return
        file_size = len(data)
        start, end = 0, file_size - 1
        if "Range" in self.headers:
            range_header = self.headers["Range"]
            try:
                range_val = range_header.split("=")[1]
                start_str, end_str = range_val.split("-")
                if start_str: start = int(start_str)
                if end_str: end = int(end_str)
            except: pass
        chunk_len = (end - start) + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if "Range" in self.headers else HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(chunk_len))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        try: self.wfile.write(data[start : end + 1])
        except (ConnectionResetError, BrokenPipeError): pass

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True 

def start_ram_server(ram_data):
    server = ThreadedHTTPServer(('127.0.0.1', 0), RamHttpHandler)
    server.ram_data = ram_data
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread

def get_free_ram_gb():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except: return 8.0 

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except: return False

# === 磁盘检测工具 ===
drive_type_cache = {}
def is_drive_ssd(path):
    root = os.path.splitdrive(os.path.abspath(path))[0].upper()
    if not root: return False
    drive_letter = root 
    if drive_letter in drive_type_cache: return drive_type_cache[drive_letter]
    is_ssd = False
    try:
        h_vol = ctypes.windll.kernel32.CreateFileW(f"\\\\.\\{drive_letter}", 0x80, 0x3, None, 3, 0, None)
        if h_vol != -1:
            class STORAGE_PROPERTY_QUERY(ctypes.Structure):
                _fields_ = [("PropertyId", ctypes.c_uint), ("QueryType", ctypes.c_uint), ("AdditionalParameters", ctypes.c_byte * 1)]
            query = STORAGE_PROPERTY_QUERY()
            query.PropertyId = 7 
            class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
                _fields_ = [("Version", ctypes.c_ulong), ("Size", ctypes.c_ulong), ("IncursSeekPenalty", ctypes.c_bool)]
            out = DEVICE_SEEK_PENALTY_DESCRIPTOR()
            bytes_returned = ctypes.c_ulong()
            ret = ctypes.windll.kernel32.DeviceIoControl(h_vol, 0x002D1400, ctypes.byref(query), ctypes.sizeof(query),
                                                         ctypes.byref(out), ctypes.sizeof(out), ctypes.byref(bytes_returned), None)
            ctypes.windll.kernel32.CloseHandle(h_vol)
            if ret:
                is_ssd = not out.IncursSeekPenalty
                drive_type_cache[drive_letter] = is_ssd
                return is_ssd
    except: pass
    drive_type_cache[drive_letter] = False
    return False

def is_bus_usb(path):
    try:
        root = os.path.splitdrive(os.path.abspath(path))[0].upper()
        if ctypes.windll.kernel32.GetDriveTypeW(root + "\\") == 2: return True
        h_vol = ctypes.windll.kernel32.CreateFileW(f"\\\\.\\{root}", 0, 0x3, None, 3, 0, None)
        if h_vol == -1: return False
        class STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong), ("Size", ctypes.c_ulong), ("DeviceType", ctypes.c_byte), 
                        ("DeviceTypeModifier", ctypes.c_byte), ("RemovableMedia", ctypes.c_bool), 
                        ("CommandQueueing", ctypes.c_bool), ("VendorIdOffset", ctypes.c_ulong), 
                        ("ProductIdOffset", ctypes.c_ulong), ("ProductRevisionOffset", ctypes.c_ulong), 
                        ("SerialNumberOffset", ctypes.c_ulong), ("BusType", ctypes.c_int)]
        out = STORAGE_DEVICE_DESCRIPTOR()
        bytes_returned = ctypes.c_ulong()
        query = ctypes.create_string_buffer(12) 
        ret = ctypes.windll.kernel32.DeviceIoControl(h_vol, 0x002D1400, query, 12, ctypes.byref(out), ctypes.sizeof(out), ctypes.byref(bytes_returned), None)
        ctypes.windll.kernel32.CloseHandle(h_vol)
        if ret:
            if out.BusType in [7, 1, 13]: return True
            if out.RemovableMedia: return True
        return False
    except: return False

def find_best_cache_drive(source_drive_letter=None, manual_override=None):
    if manual_override and os.path.exists(manual_override):
        return manual_override

    drives = [f"{chr(i)}:\\" for i in range(65, 91) if os.path.exists(f"{chr(i)}:\\")]
    candidates = []

    for root in drives:
        try:
            d_letter = os.path.splitdrive(root)[0].upper()
            total, used, free = shutil.disk_usage(root)
            free_gb = free / (1024**3)
            if free_gb < 20: continue

            is_system = (d_letter == "C:")
            is_ssd = is_drive_ssd(root)
            is_usb = is_bus_usb(root)
            is_source = (source_drive_letter and d_letter == source_drive_letter.upper())

            level = 0
            if is_ssd and not is_system and not is_usb: level = 5
            elif is_ssd and is_system: level = 4
            elif not is_ssd and not is_source and not is_system: level = 3
            elif not is_ssd and is_source: level = 2
            elif is_system: level = 1

            candidates.append({
                "path": root,
                "level": level,
                "free": free_gb
            })
        except: pass

    candidates.sort(key=lambda x: (x["level"], x["free"]), reverse=True)
    if candidates: return candidates[0]["path"]
    else: return "C:\\"

# === 组件定义 ===
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = []
        self.display_max = 10.0  
        self.target_max = 10.0   
        self.bind("<Configure>", lambda e: self.draw())
        self.running = True
        self.animate_loop()

    def add_point(self, val):
        self.points.append(val)
        if len(self.points) > 100: self.points.pop(0)
        current_data_max = max(self.points) if self.points else 10
        self.target_max = max(current_data_max, 10) * 1.2

    def animate_loop(self):
        if self.winfo_exists() and self.running:
            diff = self.target_max - self.display_max
            if abs(diff) > 0.1:
                self.display_max += diff * 0.1 
                self.draw() 
            self.after(30, self.animate_loop) 

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10 or not self.points: return
        scale_y = (h - 20) / self.display_max
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4, 4))
        n = len(self.points)
        if n < 2: return
        step_x = w / (n - 1)
        coords = []
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
        if len(coords) >= 4:
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

    def clear(self):
        self.points = []
        self.target_max = 10.0
        self.display_max = 10.0 
        self.delete("all")

class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333", **kwargs)
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=15, pady=(10,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"通道 {ch_id} · 空闲", font=("微软雅黑", 12, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="等待任务...", font=("Arial", 11), text_color="#444")
        self.lbl_info.pack(side="right")
        self.scope = InfinityScope(self)
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=15, pady=(0,10))
        self.lbl_fps = ctk.CTkLabel(btm, text="0", font=("Impact", 20), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10, "bold"), text_color="#444").pack(side="left", padx=(5,0), pady=(8,0))
        self.lbl_eta = ctk.CTkLabel(btm, text="ETA: --:--", font=("Consolas", 12), text_color="#666")
        self.lbl_eta.pack(side="right", padx=(10, 0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        if not self.winfo_exists(): return
        self.lbl_title.configure(text=f"运行中: {filename[:15]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        self.scope.clear()

    def update_data(self, fps, prog, eta):
        if not self.winfo_exists(): return
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{fps}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        self.lbl_eta.configure(text=f"ETA: {eta}")

    def reset(self):
        if not self.winfo_exists(): return
        self.lbl_title.configure(text="通道 · 空闲", text_color="#555")
        self.lbl_info.configure(text="等待任务...", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.lbl_eta.configure(text="ETA: --:--", text_color="#333")
        self.scope.clear()

class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.status_code = STATUS_WAIT 
        self.ram_data = None 
        self.ssd_cache_path = None
        self.source_mode = "PENDING"
        self.filepath = filepath
        
        self.lbl_index = ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 20), text_color="#555")
        self.lbl_index.grid(row=0, column=0, rowspan=2, padx=(10, 5))
        
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=1, sticky="w", padx=5, pady=(8,0))
        
        ctk.CTkLabel(name_frame, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), text_color="#EEE", anchor="w").pack(side="left")
        
        self.btn_open = ctk.CTkButton(self, text="📂", width=30, height=24, fg_color="#444", hover_color="#555", 
                                      font=("Segoe UI Emoji", 12), command=self.open_location)
        self.btn_open.grid(row=0, column=2, padx=10, pady=(8,0), sticky="e")
        
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,8))
        
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def open_location(self):
        try:
            subprocess.run(['explorer', '/select,', os.path.normpath(self.filepath)])
        except: pass

    def update_index(self, new_index):
        try:
            if self.winfo_exists():
                self.lbl_index.configure(text=f"{new_index:02d}")
        except: pass

    def set_status(self, text, color="#888", code=None):
        try:
            if self.winfo_exists():
                self.lbl_status.configure(text=text, text_color=color)
                if code is not None: self.status_code = code
        except: pass
    
    def set_progress(self, val, color=COLOR_ACCENT):
        try:
            if self.winfo_exists():
                self.progress.set(val)
                self.progress.configure(progress_color=color)
        except: pass
        
    def clean_memory(self):
        self.ram_data = None
        self.source_mode = "PENDING"
        self.ssd_cache_path = None

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def scroll_to_card(self, widget):
        try:
            self.scroll.update_idletasks()
            widget_y = widget.winfo_y()
            parent_height = self.scroll.winfo_children()[0].winfo_height()
            view_height = self.scroll.winfo_height()
            if parent_height > view_height:
                target = (widget_y - (view_height * 0.2)) / parent_height
                self.scroll._parent_canvas.yview_moveto(max(0, min(1, target)))
        except: pass
    
    # [v68 Fix]: 修复闭包陷阱和状态检查，确保清理逻辑能更新 UI
    def safe_update(self, func, *args, **kwargs):
        if self.winfo_exists():
            self.after(5, partial(self._guarded_call, func, *args, **kwargs))

    def _guarded_call(self, func, *args, **kwargs):
        try:
            if self.winfo_exists(): func(*args, **kwargs)
        except: pass

    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v68 (Stable & Protected)")
        self.geometry("1300x900")
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(1200, 850) 
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.running = False
        self.stop_flag = False
        
        self.queue_lock = threading.Lock() 
        self.slot_lock = threading.Lock()
        self.read_lock = threading.Lock()
        
        self.monitor_slots = []
        self.available_indices = [] 
        self.current_workers = 2
        
        self.executor = ThreadPoolExecutor(max_workers=16) 
        self.submitted_tasks = set() 
        self.temp_dir = ""
        self.manual_cache_path = None
        self.temp_files = set()
        
        self.total_tasks_run = 0
        self.finished_tasks_count = 0

        self.setup_ui()
        disable_power_throttling() 
        set_execution_state(True)  
        
        self.after(200, self.sys_check)
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def animate_text_change(self, button, new_text, new_fg_color=None):
        def hex_to_rgb(hex_col):
            if not hex_col or not isinstance(hex_col, str) or len(hex_col) != 7: return (255, 255, 255)
            return tuple(int(hex_col[i:i+2], 16) for i in (1, 3, 5))
        def rgb_to_hex(rgb): return '#%02x%02x%02x' % rgb

        try: start_hex = button._text_color if isinstance(button._text_color, str) else button._text_color[1]
        except: start_hex = "#FFFFFF"
        
        bg_hex = COLOR_ACCENT 
        steps, delay = 10, 15
        c1, c2 = hex_to_rgb(start_hex), hex_to_rgb(bg_hex)
        
        def fade_out(step):
            if step <= steps:
                r = int(c1[0] + (c2[0] - c1[0]) * (step / steps))
                g = int(c1[1] + (c2[1] - c1[1]) * (step / steps))
                b = int(c1[2] + (c2[2] - c1[2]) * (step / steps))
                try: button.configure(text_color=rgb_to_hex((r,g,b)))
                except: pass
                self.after(delay, lambda: fade_out(step + 1))
            else:
                button.configure(text=new_text)
                if new_fg_color: button.configure(fg_color=new_fg_color)
                fade_in(0)
        
        target_text_rgb = (0, 0, 0)
        def fade_in(step):
            if step <= steps:
                r = int(c2[0] + (target_text_rgb[0] - c2[0]) * (step / steps))
                g = int(c2[1] + (target_text_rgb[1] - c2[1]) * (step / steps))
                b = int(c2[2] + (target_text_rgb[2] - c2[2]) * (step / steps))
                try: button.configure(text_color=rgb_to_hex((r,g,b)))
                except: pass
                self.after(delay, lambda: fade_in(step + 1))
        fade_out(0)

    def drop_file(self, event):
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    def add_list(self, files):
        with self.queue_lock:
            existing_paths = set(os.path.normpath(os.path.abspath(f)) for f in self.file_queue)
            new_added = False
            for f in files:
                f_norm = os.path.normpath(os.path.abspath(f))
                if f_norm in existing_paths: continue
                if f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts', '.flv')):
                    self.file_queue.append(f)
                    existing_paths.add(f_norm) 
                    if f not in self.task_widgets:
                        card = TaskCard(self.scroll, 0, f) 
                        self.task_widgets[f] = card
                    new_added = True
            
            if not new_added: return
            def get_file_size(path):
                try: return os.path.getsize(path)
                except: return float('inf') 
            self.file_queue.sort(key=get_file_size)
            for i, f in enumerate(self.file_queue):
                if f in self.task_widgets:
                    card = self.task_widgets[f]
                    card.pack_forget()
                    card.pack(fill="x", pady=4)
                    card.update_index(i + 1)
            
            if self.running:
                self.update_run_status()

    def update_run_status(self):
        if not self.running: return
        total = len(self.file_queue)
        current = min(self.finished_tasks_count + 1, total)
        if current > total and total > 0: current = total
        
        txt = f"压制中 ({current}/{total})"
        try: self.btn_run.configure(text=txt)
        except: pass

    def apply_system_priority(self, level):
        mapping = {"常规": PRIORITY_NORMAL, "优先": PRIORITY_ABOVE, "极速": PRIORITY_HIGH}
        p_val = mapping.get(level, PRIORITY_ABOVE)
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, p_val)
            ctypes.windll.kernel32.CloseHandle(handle)
        except: pass
    
    def on_closing(self):
        if self.running:
            if not messagebox.askokcancel("退出", "任务正在进行中，确定要退出？"): return
        self.stop_flag = True
        self.running = False
        self.executor.shutdown(wait=False)
        self.kill_all_procs()
        self.clean_junk()
        self.destroy()
        set_execution_state(False)
        os._exit(0)
        
    def kill_all_procs(self):
        for p in list(self.active_procs): 
            try: p.terminate(); p.kill()
            except: pass
        try: subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], creationflags=subprocess.CREATE_NO_WINDOW)
        except: pass

    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("错误", "找不到 FFmpeg！")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.smart_preload_worker, daemon=True).start()
        threading.Thread(target=self.gpu_monitor_loop, daemon=True).start()
        self.update_monitor_layout()

    # [v68.1]: 动态显存预算检测
    def should_use_gpu(self, codec_sel):
        if not self.gpu_var.get():
            return False
        
        free_vram = get_free_vram_gb()
        
        # 估算单任务显存需求 (4K分辨率下估算)
        # AV1 编码器通常比 HEVC/AVC 占用更多显存
        task_cost = 3.0 # H.264
        if "AV1" in codec_sel: task_cost = 4.5
        elif "H.265" in codec_sel: task_cost = 3.8
        
        # 安全缓冲 (GB)
        safety_buffer = 2.0
        
        needed = task_cost + safety_buffer
        
        if free_vram < needed:
            print(f"[VRAM Protection] Free: {free_vram:.1f}GB < Needed: {needed:.1f}GB. Fallback to CPU.")
            return False
        
        return True

    def gpu_monitor_loop(self):
        while not self.stop_flag:
            try:
                # [v68.1]: 增加 memory.used 和 memory.total 监控
                cmd = ["nvidia-smi", "--query-gpu=power.draw,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                output = subprocess.check_output(cmd, encoding="utf-8", startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW).strip()
                if output:
                    p_str, t_str, m_used, m_total = output.split(",")
                    power = float(p_str)
                    temp = int(t_str)
                    mem_used = float(m_used) / 1024
                    mem_total = float(m_total) / 1024
                    
                    color = "#555555"
                    if temp > 75 or mem_used > (mem_total * 0.9): color = COLOR_ERROR      
                    elif temp > 60 or mem_used > (mem_total * 0.7): color = COLOR_SSD_CACHE 
                    elif power > 50: color = COLOR_SUCCESS  
                    
                    # 更新 UI 显示 VRAM
                    status_text = f"GPU: {power:.0f}W | {temp}°C | VRAM: {mem_used:.1f}/{mem_total:.1f}G"
                    self.safe_update(self.lbl_gpu.configure, text=status_text, text_color=color)
            except: pass
            time.sleep(1)

    def scan_disk(self):
        path = find_best_cache_drive(manual_override=self.manual_cache_path)
        cache_dir = os.path.join(path, "_Ultra_Smart_Cache_")
        os.makedirs(cache_dir, exist_ok=True)
        self.temp_dir = cache_dir
        self.safe_update(self.btn_cache.configure, text=f"缓存池: {path} (点击修改)")

    def select_cache_folder(self):
        d = filedialog.askdirectory(title="选择缓存盘 (SSD 优先)")
        if d:
            self.manual_cache_path = d
            self.scan_disk() 

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=320) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=320)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=20, pady=(25, 10))
        ctk.CTkLabel(l_head, text="ULTRA ENCODER", font=("Impact", 26), text_color="#FFF").pack(anchor="w")
        
        self.btn_cache = ctk.CTkButton(left, text="正在检测磁盘...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, 
                                     command=self.select_cache_folder) 
        self.btn_cache.pack(fill="x", padx=20, pady=(5, 5))
        self.btn_ram = ctk.CTkButton(left, text="内存监控中...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, state="disabled")
        self.btn_ram.pack(fill="x", padx=20, pady=(5, 5))
        
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(tools, text="+ 导入视频", width=120, height=36, corner_radius=18, 
                     fg_color="#333", hover_color="#444", command=self.add_file).pack(side="left", padx=5)
        self.btn_clear = ctk.CTkButton(tools, text="清空", width=60, height=36, corner_radius=18, 
                     fg_color="transparent", border_width=1, border_color="#444", hover_color="#331111", text_color="#CCC", command=self.clear_all)
        self.btn_clear.pack(side="left", padx=5)

        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=15, pady=20, ipadx=5, ipady=10)
        
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=(10, 5), padx=10)
        ctk.CTkLabel(rowP, text="系统优先级", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.priority_var = ctk.StringVar(value="优先")
        self.seg_priority = ctk.CTkSegmentedButton(rowP, values=["常规", "优先", "极速"], 
                                                  variable=self.priority_var, command=lambda v: self.apply_system_priority(v),
                                                  selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_priority.pack(fill="x", pady=(5, 0))

        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=(10, 5), padx=10)
        ctk.CTkLabel(row3, text="并发任务数量", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        w_box = ctk.CTkFrame(row3, fg_color="transparent")
        w_box.pack(fill="x")
        self.worker_var = ctk.StringVar(value="2")
        self.seg_worker = ctk.CTkSegmentedButton(w_box, values=["1", "2", "3", "4"], variable=self.worker_var, 
                                               corner_radius=10, command=self.update_monitor_layout)
        self.seg_worker.pack(side="left", fill="x", expand=True)
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(w_box, text="GPU", width=60, variable=self.gpu_var, progress_color=COLOR_ACCENT).pack(side="right", padx=(10,0))
        
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(row2, text="画质 (CRF/QP)", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkSlider(c_box, from_=0, to=51, variable=self.crf_var, progress_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(c_box, textvariable=self.crf_var, width=25, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="right")
        
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=(5, 5), padx=10)
        ctk.CTkLabel(row1, text="编码格式", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.codec_var = ctk.StringVar(value="H.264")
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265", "AV1"], variable=self.codec_var, selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_codec.pack(fill="x", pady=(5, 0))

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        self.btn_run = ctk.CTkButton(btn_row, text="启动引擎", height=45, corner_radius=22, 
                                   font=("微软雅黑", 15, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                                   text_color="#000", command=self.run)
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 10)) 
        self.btn_stop = ctk.CTkButton(btn_row, text="停止", height=45, corner_radius=22, width=80,
                                    fg_color="transparent", border_width=2, border_color=COLOR_ERROR, 
                                    text_color=COLOR_ERROR, hover_color="#221111", 
                                    state="disabled", command=self.stop)
        self.btn_stop.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)

        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Impact", 20), text_color="#333").pack(side="left")
        
        self.lbl_gpu = ctk.CTkLabel(r_head, text="GPU: --W | --°C", font=("Consolas", 14, "bold"), text_color="#444")
        self.lbl_gpu.pack(side="right")
        
        self.monitor_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 25))

    def update_monitor_layout(self, val=None, force_reset=False):
        if self.running and not force_reset:
            self.seg_worker.set(str(self.current_workers))
            return
        try: n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        for ch in self.monitor_slots: ch.destroy()
        self.monitor_slots.clear()
        with self.slot_lock:
            self.available_indices = [i for i in range(n)] 
        for i in range(n):
            ch = MonitorChannel(self.monitor_frame, i+1)
            ch.pack(fill="both", expand=True, pady=5)
            self.monitor_slots.append(ch)

    def process_caching(self, src_path, widget):
        file_size = os.path.getsize(src_path)
        file_size_gb = file_size / (1024**3)
        
        is_ssd = is_drive_ssd(src_path)
        is_external = is_bus_usb(src_path)
        
        if is_ssd and not is_external:
            self.safe_update(widget.set_status, "就绪 (SSD直读)", COLOR_DIRECT, STATUS_READY)
            widget.source_mode = "DIRECT"
            return True
        elif is_ssd and is_external:
            pass 

        free_ram = get_free_ram_gb()
        available_for_cache = free_ram - SAFE_RAM_RESERVE

        if available_for_cache > file_size_gb and file_size_gb < MAX_RAM_LOAD_GB:
            self.safe_update(widget.set_status, "📥 载入内存中...", COLOR_RAM, STATUS_CACHING)
            self.safe_update(widget.set_progress, 0, COLOR_RAM)
            try:
                chunk_size = 64 * 1024 * 1024 
                data_buffer = bytearray()
                read_len = 0
                
                with open(src_path, 'rb') as f:
                    while True:
                        if self.stop_flag: return False
                        chunk = f.read(chunk_size)
                        if not chunk: break
                        data_buffer.extend(chunk)
                        read_len += len(chunk)
                        if file_size > 0:
                            prog = read_len / file_size
                            self.safe_update(widget.set_progress, prog, COLOR_READING)
                
                widget.ram_data = bytes(data_buffer) 
                self.safe_update(widget.set_status, "就绪 (内存加速)", COLOR_READY_RAM, STATUS_READY)
                self.safe_update(widget.set_progress, 1, COLOR_READY_RAM)
                widget.source_mode = "RAM"
                return True
            except Exception: 
                widget.clean_memory()

        self.safe_update(widget.set_status, "📥 写入缓存...", COLOR_SSD_CACHE, STATUS_CACHING)
        self.safe_update(widget.set_progress, 0, COLOR_SSD_CACHE)
        try:
            fname = os.path.basename(src_path)
            cache_path = os.path.join(self.temp_dir, f"CACHE_{int(time.time())}_{fname}")
            copied = 0
            with open(src_path, 'rb') as fsrc:
                with open(cache_path, 'wb') as fdst:
                    while True:
                        if self.stop_flag: 
                            fdst.close(); os.remove(cache_path); return False
                        chunk = fsrc.read(32*1024*1024) 
                        if not chunk: break
                        fdst.write(chunk)
                        copied += len(chunk)
                        if file_size > 0:
                            self.safe_update(widget.set_progress, copied/file_size, COLOR_SSD_CACHE)
            self.temp_files.add(cache_path)
            widget.ssd_cache_path = cache_path
            widget.source_mode = "SSD_CACHE"
            self.safe_update(widget.set_status, "就绪 (缓存加速)", COLOR_SSD_CACHE, STATUS_READY)
            self.safe_update(widget.set_progress, 1, COLOR_SSD_CACHE)
            return True
        except:
            self.safe_update(widget.set_status, "缓存失败", COLOR_ERROR, STATUS_ERR)
            return False

    def smart_preload_worker(self):
        while True:
            free = get_free_ram_gb()
            self.safe_update(self.btn_ram.configure, text=f"空闲内存: {free:.1f} GB")
            
            if self.running and not self.stop_flag:
                if not self.read_lock.acquire(blocking=False):
                    time.sleep(0.5); continue
                
                target_file, target_widget = None, None
                with self.queue_lock: 
                    for f in self.file_queue:
                        w = self.task_widgets.get(f)
                        if w and w.status_code == STATUS_WAIT and w.source_mode == "PENDING":
                            target_file, target_widget = f, w
                            break 
                
                if target_file and target_widget:
                    self.process_caching(target_file, target_widget)
                
                self.read_lock.release()
                time.sleep(0.5) 
            else:
                time.sleep(1)

    def engine(self):
        while not self.stop_flag:
            tasks_to_run = []
            active_count = len(self.submitted_tasks)
            slots_free = self.current_workers - active_count
            
            if slots_free > 0:
                with self.queue_lock:
                    for f in self.file_queue:
                        if slots_free <= 0: break
                        if f in self.submitted_tasks: continue 
                        card = self.task_widgets[f]
                        if card.status_code in [STATUS_WAIT, STATUS_CACHING, STATUS_READY]:
                            tasks_to_run.append(f)
                            self.submitted_tasks.add(f)
                            slots_free -= 1
            
            if not tasks_to_run and active_count == 0 and self.file_queue:
                all_done = True
                with self.queue_lock:
                    for f in self.file_queue:
                        if self.task_widgets[f].status_code not in [STATUS_DONE, STATUS_ERR]:
                            all_done = False; break
                if all_done: break
            
            if not tasks_to_run: time.sleep(0.2); continue
            
            for f in tasks_to_run:
                self.executor.submit(self.process, f)
            time.sleep(0.1) 

        if not self.stop_flag:
            self.safe_update(messagebox.showinfo, "完成", "所有任务已处理完毕！")
        self.running = False
        self.safe_update(self.reset_ui_state)

    def process(self, input_file):
        my_slot_idx = None
        try:
            if self.stop_flag: return
            
            # [v68 Fix]: 槽位死锁超时保护
            wait_start = time.time()
            while my_slot_idx is None and not self.stop_flag:
                with self.slot_lock:
                    if self.available_indices: my_slot_idx = self.available_indices.pop(0)
                if my_slot_idx is None: 
                    if time.time() - wait_start > 30: # 30s timeout
                         print("[System] Slot Deadlock detected, forced reset.")
                         with self.slot_lock:
                             self.available_indices = list(range(self.current_workers))
                         continue
                    time.sleep(0.1)
            if self.stop_flag: return

            card = self.task_widgets[input_file]
            ch_ui = self.monitor_slots[my_slot_idx]
            
            self.safe_update(self.scroll_to_card, card)
            self.safe_update(self.update_run_status)
            
            while card.status_code == STATUS_CACHING and not self.stop_flag: 
                time.sleep(0.5)

            if card.source_mode == "PENDING":
                self.read_lock.acquire()
                try:
                    if card.source_mode == "PENDING" and not self.stop_flag:
                       self.process_caching(input_file, card)
                finally:
                    self.read_lock.release()
            
            if self.stop_flag: return 

            max_retries = 1 
            current_try = 0
            success = False
            output_log = []
            ram_server = None 
            
            fname = os.path.basename(input_file)
            name, ext = os.path.splitext(fname)
            codec_sel = self.codec_var.get()
            
            suffix = "_H264"
            if "H.265" in codec_sel: suffix = "_H265"
            elif "AV1" in codec_sel: suffix = "_AV1"
            
            final_target_file = os.path.join(os.path.dirname(input_file), f"{name}{suffix}{ext}")
            
            best_cache_root = find_best_cache_drive(source_drive_letter=os.path.splitdrive(input_file)[0], manual_override=self.manual_cache_path)
            best_cache_dir = os.path.join(best_cache_root, "_Ultra_Smart_Cache_")
            os.makedirs(best_cache_dir, exist_ok=True)
            self.temp_dir = best_cache_dir 
            
            temp_name = f"TEMP_{int(time.time())}_{name}{suffix}{ext}"
            working_output_file = os.path.join(best_cache_dir, temp_name)
            need_move_back = True

            while current_try <= max_retries and not self.stop_flag:
                output_log.clear()
                
                # [v68.1]: 使用更智能的动态显存检测
                using_gpu = self.gpu_var.get()
                if using_gpu:
                    if not self.should_use_gpu(codec_sel):
                        using_gpu = False
                        self.safe_update(card.set_status, "⚠️ 显存不足，转CPU", COLOR_MOVING, STATUS_RUN)
                
                if using_gpu:
                    decode_flags, strategy_log = self.get_smart_decode_args(input_file)
                else:
                    decode_flags = []
                    strategy_log = "CPU (Manual/OOM Fallback)"

                self.safe_update(card.set_status, f"▶️ {strategy_log}", COLOR_ACCENT, STATUS_RUN)

                input_arg_final = input_file
                if card.source_mode == "RAM":
                    try:
                        if not ram_server:
                            ram_server, port, _ = start_ram_server(card.ram_data)
                        # [v68]: 使用 .mp4 后缀帮助 FFmpeg 识别
                        input_arg_final = f"http://127.0.0.1:{port}/stream.mp4"
                    except:
                        input_arg_final = input_file
                elif card.source_mode == "SSD_CACHE": 
                    input_arg_final = card.ssd_cache_path

                if using_gpu:
                    if "H.265" in codec_sel: v_codec = "hevc_nvenc"
                    elif "AV1" in codec_sel: v_codec = "av1_nvenc"
                    else: v_codec = "h264_nvenc"
                else:
                    if "H.265" in codec_sel: v_codec = "libx265"
                    elif "AV1" in codec_sel: v_codec = "libaom-av1"
                    else: v_codec = "libx264"

                cmd = ["ffmpeg", "-y"]
                cmd.extend(decode_flags)
                cmd.extend(["-i", input_arg_final])
                cmd.extend(["-c:v", v_codec])
                
                is_hw_decode = "-hwaccel" in decode_flags
                
                if using_gpu:
                    if is_hw_decode:
                        cmd.extend(["-vf", "scale_cuda=format=yuv420p"])
                    else:
                        cmd.extend(["-pix_fmt", "yuv420p"])
                    
                    # [v68]: AV1 参数修正 (-qp + P6)
                    if "AV1" in codec_sel:
                         cmd.extend(["-rc", "vbr", "-qp", str(self.crf_var.get()), 
                                "-preset", "p6", "-b:v", "0"]) 
                    else:
                        cmd.extend(["-rc", "vbr", "-cq", str(self.crf_var.get()), 
                                    "-preset", "p6", "-b:v", "0"])
                else:
                    cmd.extend(["-pix_fmt", "yuv420p"])
                    cmd.extend(["-crf", str(self.crf_var.get()), "-preset", "medium"])
                
                cmd.extend(["-c:a", "copy", "-progress", "pipe:1", "-nostats", working_output_file])
                
                dur_file = input_file 
                duration = self.get_dur(dur_file)
                
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, startupinfo=si)
                self.active_procs.append(proc)
                
                try:
                    p_val = {"常规": PRIORITY_NORMAL, "优先": PRIORITY_ABOVE, "极速": PRIORITY_HIGH}.get(self.priority_var.get(), PRIORITY_ABOVE)
                    h_sub = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, proc.pid)
                    if h_sub:
                        ctypes.windll.kernel32.SetPriorityClass(h_sub, p_val)
                        disable_power_throttling(h_sub)
                        ctypes.windll.kernel32.CloseHandle(h_sub)
                except: pass

                start_t = time.time()
                last_ui_update_time = 0 
                
                current_fps = 0
                for line in proc.stdout:
                    if self.stop_flag: break
                    try: 
                        line_str = line.decode('utf-8', errors='ignore').strip()
                        if line_str: output_log.append(line_str)
                        
                        if "=" in line_str:
                            key, value = line_str.split("=", 1)
                            key = key.strip(); value = value.strip()
                            
                            if key == "fps":
                                try: current_fps = int(float(value))
                                except: pass
                            elif key == "out_time_us":
                                try:
                                    now = time.time()
                                    if now - last_ui_update_time > 0.25: 
                                        us = int(value)
                                        current_sec = us / 1000000.0
                                        if duration > 0:
                                            prog = current_sec / duration
                                            elap = now - start_t
                                            eta_sec = (elap / prog - elap) if prog > 0.01 else 0
                                            eta = f"{int(eta_sec//60):02d}:{int(eta_sec%60):02d}"
                                            self.safe_update(card.set_progress, prog, COLOR_ACCENT)
                                            self.safe_update(ch_ui.update_data, current_fps, prog, eta)
                                        last_ui_update_time = now
                                except: pass
                    except: continue
                
                proc.wait()
                if proc in self.active_procs: self.active_procs.remove(proc)
                
                if self.stop_flag: 
                    if ram_server: ram_server.shutdown(); ram_server.server_close()
                    card.clean_memory()
                    if need_move_back and os.path.exists(working_output_file):
                        try: os.remove(working_output_file)
                        except: pass
                    return 

                if proc.returncode == 0:
                    if os.path.exists(working_output_file) and os.path.getsize(working_output_file) > 500*1024:
                        success = True
                        break 
                    else:
                        output_log.append(f"[System Error] File too small: {working_output_file}")
                
                if not success and using_gpu and current_try < max_retries:
                    self.gpu_var.set(False) 
                    current_try += 1
                    time.sleep(1)
                    if os.path.exists(working_output_file):
                        try: os.remove(working_output_file)
                        except: pass
                    continue
                else:
                    break 

            if ram_server: ram_server.shutdown(); ram_server.server_close()

            if success and need_move_back:
                try:
                    self.safe_update(card.set_status, "📦 回写硬盘中...", COLOR_MOVING, STATUS_RUN)
                    shutil.move(working_output_file, final_target_file)
                except Exception as e:
                    success = False
                    output_log.append(f"[Move Error] Failed to move file back: {e}")

            card.clean_memory()
            if card.ssd_cache_path:
                try: 
                    os.remove(card.ssd_cache_path)
                    self.temp_files.remove(card.ssd_cache_path)
                except: pass
            
            self.safe_update(ch_ui.reset)
            
            if success:
                 self.finished_tasks_count += 1 
                 orig_sz = os.path.getsize(input_file)
                 if os.path.exists(final_target_file):
                     new_sz = os.path.getsize(final_target_file)
                     sv = 100 - (new_sz/orig_sz*100) if orig_sz > 0 else 0
                     self.safe_update(card.set_status, f"完成 | 压缩率: {sv:.1f}%", COLOR_SUCCESS, STATUS_DONE)
                     self.safe_update(card.set_progress, 1, COLOR_SUCCESS)
                 else:
                     self.safe_update(card.set_status, "文件丢失", COLOR_ERROR, STATUS_ERR)
            else:
                 if not self.stop_flag:
                     self.safe_update(card.set_status, "失败 (点击看日志)", COLOR_ERROR, STATUS_ERR)
                     err_msg = "\n".join(output_log[-30:]) 
                     def show_err():
                         messagebox.showerror(f"任务失败: {fname}", f"FFmpeg 报错日志 (最后30行):\n\n{err_msg}")
                     self.safe_update(show_err)

            self.safe_update(self.update_run_status) 
            with self.queue_lock:
                if input_file in self.submitted_tasks: self.submitted_tasks.remove(input_file)
        
        finally:
            if my_slot_idx is not None:
                with self.slot_lock: 
                    self.available_indices.append(my_slot_idx)
                    self.available_indices.sort()

    def run(self):
        if not self.file_queue: return
        
        self.btn_run.configure(state="disabled") 
        self.animate_text_change(self.btn_run, f"压制中 (1/{len(self.file_queue)})") 
        self.btn_stop.configure(state="normal")
        
        self.stop_flag = False
        self.update_monitor_layout(force_reset=True)
        self.running = True
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.kill_all_procs()
        self.active_procs = []
        with self.queue_lock:
            for f, card in self.task_widgets.items():
                card.clean_memory()
                if card.status_code in [STATUS_RUN, STATUS_CACHING, STATUS_READY]:
                    card.set_status("已停止", COLOR_TEXT_GRAY, STATUS_WAIT)
                    card.set_progress(0)
        self.submitted_tasks.clear()
        self.running = False
        self.reset_ui_state()

    def reset_ui_state(self):
        self.btn_run.configure(state="normal", text="启动引擎")
        self.btn_stop.configure(state="disabled")

    def add_file(self):
        f_list = filedialog.askopenfilenames()
        self.add_list(f_list)

    def clear_all(self):
        if self.running:
            if not messagebox.askyesno("警告", "队列正在运行，确定要停止并清空吗？"):
                return
            self.stop()
        self.after(100, self._do_clear)

    def _do_clear(self):
        for w in list(self.task_widgets.values()): 
            w.clean_memory()
            w.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()
        self.submitted_tasks.clear()
        self.temp_files.clear() 
        self.total_tasks_run = 0
        self.finished_tasks_count = 0
        self.running = False
        self.stop_flag = False
        self.btn_run.configure(text="启动引擎", state="normal", fg_color=COLOR_ACCENT, text_color="#000")
        self.btn_stop.configure(state="disabled")
        for ch in self.monitor_slots:
            ch.reset()
        print("[System] All states reset.")

    def analyze_source_attributes(self, filepath):
        try:
            cmd = [
                "ffprobe", "-v", "error", 
                "-select_streams", "v:0", 
                "-show_entries", "stream=codec_name,pix_fmt", 
                "-of", "csv=p=0", 
                filepath
            ]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            output = subprocess.check_output(cmd, startupinfo=si, encoding="utf-8").strip()
            if not output: return "unknown", "unknown"
            
            parts = output.split(',')
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
            return parts[0].strip(), "unknown"
        except Exception as e:
            print(f"Probe Error: {e}")
            return "error", "error"

    def get_smart_decode_args(self, filepath):
        codec, pix_fmt = self.analyze_source_attributes(filepath)
        filename = os.path.basename(filepath)
        
        decode_args = []
        strategy = "CPU (Soft)"

        if "hevc" in codec or "av1" in codec:
            decode_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            strategy = f"GPU (CUDA/{codec.upper()})"

        elif "h264" in codec:
            if "422" in pix_fmt:
                decode_args = [] 
                strategy = f"CPU (H.264 4:2:2 UNSUPPORTED by GPU)"
            else:
                decode_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
                strategy = "GPU (CUDA/AVC)"
        
        else:
            strategy = f"CPU ({codec})"

        print(f"[Smart Engine] File: {filename} | Codec: {codec} | Pix: {pix_fmt} -> Strategy: {strategy}")
        return decode_args, strategy

    def get_dur(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

    def clean_junk(self):
        for f in list(self.temp_files):
            try: os.remove(f)
            except: pass
        self.temp_files.clear()

if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()