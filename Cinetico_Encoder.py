import os
import sys
import shutil
import platform
import zipfile
import urllib.request
import subprocess
import importlib.util
import threading
import time
import ctypes
import uuid
import random
import http.server
import socketserver
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from collections import deque
from http import HTTPStatus

# =========================================================================
# === [模块 1] 全自动环境配置与 FFmpeg 部署 (Win/Mac 通用) ===
# =========================================================================

# 定义全局变量，后面所有代码都用这个
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

def check_and_install_dependencies():
    global FFMPEG_PATH, FFPROBE_PATH
    
    # --- 1. Python 库依赖检查 ---
    required_packages = [
        ("customtkinter", "customtkinter"),
        ("tkinterdnd2", "tkinterdnd2"),
        ("PIL", "pillow"),
        ("packaging", "packaging"),
        ("uuid", "uuid")
    ]
    
    print("--------------------------------------------------")
    print("正在检查运行环境...")

    installed_any = False
    for import_name, package_name in required_packages:
        if importlib.util.find_spec(import_name) is None:
            print(f"⚠️ 发现缺失组件: {package_name}，正在自动安装...")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", package_name, 
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"
                ])
                print(f"✅ {package_name} 安装成功！")
                installed_any = True
            except subprocess.CalledProcessError:
                if platform.system() == "Windows":
                    ctypes.windll.user32.MessageBoxW(0, f"自动安装失败: {package_name}\n请手动运行: pip install {package_name}", "环境错误", 0x10)
                sys.exit(1)
        else:
            print(f"✔ {package_name} 已安装")

    # --- 2. FFmpeg 自动部署逻辑 ---
    print("正在检查核心组件 FFmpeg...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(base_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)

    system_name = platform.system() # "Windows" or "Darwin" (Mac)
    
    # 设定下载目标
    if system_name == "Windows":
        target_ffmpeg = os.path.join(bin_dir, "ffmpeg.exe")
        target_ffprobe = os.path.join(bin_dir, "ffprobe.exe")
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    elif system_name == "Darwin":
        target_ffmpeg = os.path.join(bin_dir, "ffmpeg")
        target_ffprobe = os.path.join(bin_dir, "ffprobe")
        # 使用 Evermeet 源 (Mac)
        url = "https://evermeet.cx/ffmpeg/ffmpeg-6.0.zip" 
    else:
        print("❌ 不支持的操作系统，请手动安装 FFmpeg")
        return

    # 检测是否存在
    if os.path.exists(target_ffmpeg):
        print(f"✔ FFmpeg 已就绪: {target_ffmpeg}")
        FFMPEG_PATH = target_ffmpeg
        FFPROBE_PATH = target_ffprobe
    else:
        # 再次检查系统环境变量
        if shutil.which("ffmpeg"):
            print("✔ 检测到系统环境变量中的 FFmpeg")
            FFMPEG_PATH = "ffmpeg"
            FFPROBE_PATH = "ffprobe"
        else:
            print(f"⚠️ 未检测到 FFmpeg，正在为 {system_name} 自动下载 (约 80MB)...")
            print("⏳ 下载中，请勿关闭窗口 (Download in progress)...")
            
            try:
                zip_path = os.path.join(bin_dir, "ffmpeg_temp.zip")
                
                # 下载进度条
                def progress_hook(count, block_size, total_size):
                    percent = int(count * block_size * 100 / total_size)
                    print(f"\r下载进度: {percent}%", end='')
                
                urllib.request.urlretrieve(url, zip_path, reporthook=progress_hook)
                print("\n✅ 下载完成，正在解压...")

                # 解压逻辑
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    for file in zip_ref.namelist():
                        # Windows 版通常在 bin 子文件夹里，Mac 版直接是文件
                        filename = os.path.basename(file)
                        if "ffmpeg" in filename and not filename.endswith(".html"):
                             source = zip_ref.open(file)
                             target_file = target_ffmpeg if "ffmpeg" in filename else target_ffprobe
                             # 简单粗暴：如果是 ffmpeg.exe 就解压到 target_ffmpeg
                             if filename.lower() == "ffmpeg.exe" or filename == "ffmpeg":
                                 with open(target_ffmpeg, "wb") as f_out: shutil.copyfileobj(source, f_out)
                             elif filename.lower() == "ffprobe.exe" or filename == "ffprobe":
                                 with open(target_ffprobe, "wb") as f_out: shutil.copyfileobj(source, f_out)

                # 清理
                try: os.remove(zip_path)
                except: pass
                
                # Mac 需要赋予执行权限
                if system_name == "Darwin":
                    os.chmod(target_ffmpeg, 0o755)
                    if os.path.exists(target_ffprobe): os.chmod(target_ffprobe, 0o755)

                print("🎉 FFmpeg 部署完成！")
                FFMPEG_PATH = target_ffmpeg
                FFPROBE_PATH = target_ffprobe
                
            except Exception as e:
                print(f"\n❌ 自动下载失败: {e}")
                print("请手动下载 FFmpeg 并放到 bin 目录。")

    if installed_any:
        print("\n🎉 环境配置完毕！正在启动...")

# 执行检查
check_and_install_dependencies()

# =========================================================================
# === [模块 2] 主程序逻辑 ===
# =========================================================================

import customtkinter as ctk  
import tkinter as tk         
from tkinter import filedialog, messagebox

# 全局视觉配置
ctk.set_appearance_mode("Dark") 
ctk.set_default_color_theme("dark-blue")

# 颜色变量
COLOR_TEXT_GRAY = "#888888" 
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
COLOR_WAITING = "#555555"    

# 状态码
STATUS_WAIT = 0      
STATUS_CACHING = 1   
STATUS_READY = 2     
STATUS_RUN = 3       
STATUS_DONE = 5      
STATUS_ERR = -1      
STATE_PENDING = 0        
STATE_QUEUED_IO = 1      
STATE_CACHING = 2        
STATE_READY = 3          
STATE_ENCODING = 4       
STATE_DONE = 5           
STATE_ERROR = -1         

# Windows 优先级常量
PRIORITY_NORMAL = 0x00000020 
PRIORITY_ABOVE = 0x00008000  
PRIORITY_HIGH = 0x00000080   

# --- 辅助函数：跨平台 Subprocess 参数 ---
# 这是一个关键修复，防止 Mac 上报错
def get_subprocess_args():
    if platform.system() == "Windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}

# --- 硬件检测 ---
def get_total_ram_gb():
    try:
        if platform.system() == "Windows":
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
        else:
            return 16.0 # Mac 简化处理
    except:
        return 16.0 

def get_free_ram_gb():
    try:
        if platform.system() == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys / (1024**3)
        else:
            return 4.0
    except:
        return 4.0

TOTAL_RAM = get_total_ram_gb()
MAX_RAM_LOAD_GB = max(4.0, TOTAL_RAM - 4.0) 
SAFE_RAM_RESERVE = 3.0  

print(f"[System] RAM: {TOTAL_RAM:.1f}GB | Cache Limit: {MAX_RAM_LOAD_GB:.1f}GB")

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

# Windows 电源管理 (Mac 跳过)
def set_execution_state(enable=True):
    if platform.system() != "Windows": return
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    try:
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except: pass

def disable_power_throttling(process_handle=None):
    if platform.system() != "Windows": return
    try:
        # 省略具体代码，保持原样即可
        pass
    except: pass

# 检查 FFmpeg (使用全局路径)
def check_ffmpeg():
    try:
        # 使用 FFMPEG_PATH
        subprocess.run([FFMPEG_PATH, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except: return False

# 磁盘检测
drive_type_cache = {} 
def is_drive_ssd(path):
    if platform.system() != "Windows": return True # Mac 默认当 SSD 处理
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
    if platform.system() != "Windows": return False
    try:
        root = os.path.splitdrive(os.path.abspath(path))[0].upper()
        if ctypes.windll.kernel32.GetDriveTypeW(root + "\\") == 2: return True 
        return False
    except: return False

def find_best_cache_drive(source_drive_letter=None, manual_override=None):
    if manual_override and os.path.exists(manual_override):
        return manual_override
    
    # Mac/Linux 默认使用临时目录
    if platform.system() != "Windows":
        return os.path.expanduser("~/")

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
            candidates.append({"path": root, "level": level, "free": free_gb})
        except: pass
    candidates.sort(key=lambda x: (x["level"], x["free"]), reverse=True)
    if candidates: return candidates[0]["path"]
    else: return "C:\\"

# 全局内存仓库与单例服务器
GLOBAL_RAM_STORAGE = {} 
PATH_TO_TOKEN_MAP = {}

class GlobalRamHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass  
    def do_GET(self):
        try:
            token = self.path.lstrip('/')
            video_data = GLOBAL_RAM_STORAGE.get(token)
            if not video_data:
                self.send_error(404, "Invalid Token")
                return
            file_size = len(video_data)
            start, end = 0, file_size - 1
            if "Range" in self.headers:
                try:
                    range_val = self.headers["Range"].split("=")[1]
                    start_str, end_str = range_val.split("-")
                    if start_str: start = int(start_str)
                    if end_str: end = int(end_str)
                    elif end_str: 
                        start = file_size - int(end_str)
                        end = file_size - 1
                except: pass
            if start >= file_size:
                 self.send_error(416, "Range Not Satisfiable")
                 return
            chunk_len = (end - start) + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT if "Range" in self.headers else HTTPStatus.OK)
            self.send_header("Content-Type", "video/mp4") 
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(chunk_len))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            try: 
                self.wfile.write(memoryview(video_data)[start : end + 1])
            except (ConnectionResetError, BrokenPipeError): pass
        except Exception as e:
            print(f"Global Server Error: {e}")

def start_global_server():
    server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), GlobalRamHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[Core] Global Memory Server started on port {port}")
    return server, port

# UI 组件 (InfinityScope, MonitorChannel, TaskCard, HelpWindow)
# -----------------------------------------------------------
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = []
        self.display_max = 10.0  
        self.target_max = 10.0   
        self.running = True
        self.bind("<Configure>", lambda e: self.draw()) 
        self.animate_loop()

    def add_point(self, val):
        self.points.append(val)
        if len(self.points) > 100: self.points.pop(0)
        current_data_max = max(self.points) if self.points else 10
        self.target_max = max(current_data_max, 10) * 1.2

    def clear(self):
        self.points = []
        self.draw()

    def animate_loop(self):
        if self.winfo_exists() and self.running:
            diff = self.target_max - self.display_max
            if abs(diff) > 0.01: self.display_max += diff * 0.1
            self.draw()
            self.after(33, self.animate_loop) 

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10: return
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4, 4))
        if not self.points: return
        scale_y = (h - 20) / self.display_max
        n = len(self.points)
        if n < 2: return
        step_x = w / (n - 1) if n > 1 else w
        coords = []
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
        if len(coords) >= 4:
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

# 自定义控件：监控通道 (MonitorChannel) - [V2.3 修复波形跳动版]
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333", **kwargs)
        
        # --- 布局部分 (保持不变) ---
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
        self.lbl_ratio = ctk.CTkLabel(btm, text="RATIO: --%", font=("Consolas", 12), text_color="#666")
        self.lbl_ratio.pack(side="right", padx=(10, 0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")
        # -------------------------

        self.is_active = False
        self.last_update_time = time.time()
        self.idle_start_time = 0 
        self.after(500, self._heartbeat) # 启动心跳

    # [核心修复] 智能心跳：放宽超时判断，防止锯齿波形
    def _heartbeat(self):
        if not self.winfo_exists(): return
        
        now = time.time()
        should_push_zero = False
        
        # 情况 A: 正在运行任务 (Active)
        if self.is_active:
            # [修复点在这里]：把 0.8 改成了 3.0
            # 只有超过 3秒 没有收到 FFmpeg 的数据，才认为是卡死了，才归零。
            # 这样就不会因为 10-bit 压制刷新慢而导致波形乱跳了。
            if now - self.last_update_time > 3.0:
                should_push_zero = True
                
        # 情况 B: 任务刚结束 (Idle)
        else:
            if now - self.idle_start_time < 1.0:
                should_push_zero = True
        
        if should_push_zero:
            self.scope.add_point(0)
            if not self.is_active:
                self.lbl_fps.configure(text="0.00", text_color="#555")

        self.after(500, self._heartbeat)

    def activate(self, filename, tag):
        if not self.winfo_exists(): return
        self.is_active = True
        self.lbl_title.configure(text=f"运行中: {filename[:15]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        self.last_update_time = time.time()

    def update_data(self, fps, prog, eta, ratio):
        if not self.winfo_exists(): return
        self.last_update_time = time.time() 
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{float(fps):.2f}", text_color="#FFF") 
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        self.lbl_eta.configure(text=f"ETA: {eta}")
        self.lbl_ratio.configure(text=f"Ratio: {ratio:.1f}%", text_color="#888")

    def reset(self):
        if not self.winfo_exists(): return
        self.is_active = False
        self.idle_start_time = time.time() 
        self.lbl_title.configure(text="通道 · 空闲", text_color="#555")
        self.lbl_info.configure(text="等待任务...", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.lbl_eta.configure(text="ETA: --:--", text_color="#333")
        self.lbl_ratio.configure(text="Ratio: --%", text_color="#333")

class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.filepath = filepath
        self.status_code = STATE_PENDING 
        self.ram_data = None 
        self.ssd_cache_path = None
        self.source_mode = "PENDING"
        try: self.file_size_gb = os.path.getsize(filepath) / (1024**3)
        except: self.file_size_gb = 0.0
        self.lbl_index = ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 22), 
                                      text_color="#555", width=50, anchor="center")
        self.lbl_index.grid(row=0, column=0, rowspan=2, padx=(5, 5), pady=0) 
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=1, sticky="sw", padx=0, pady=(8, 0)) 
        ctk.CTkLabel(name_frame, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), 
                     text_color="#EEE", anchor="w").pack(side="left")
        self.btn_open = ctk.CTkButton(self, text="📂", width=28, height=22, fg_color="#444", hover_color="#555", 
                                      font=("Segoe UI Emoji", 11), command=self.open_location)
        self.btn_open.grid(row=0, column=2, padx=10, pady=(8,0), sticky="e")
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="nw")
        self.lbl_status.grid(row=1, column=1, sticky="nw", padx=0, pady=(0, 0)) 
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="new", padx=12, pady=(0, 10))

    def open_location(self):
        try: 
            if platform.system() == "Windows":
                subprocess.run(['explorer', '/select,', os.path.normpath(self.filepath)])
            elif platform.system() == "Darwin":
                subprocess.run(['open', '-R', self.filepath])
        except: pass

    def update_index(self, new_index):
        try:
            if self.winfo_exists(): self.lbl_index.configure(text=f"{new_index:02d}")
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
        self.source_mode = "PENDING"
        self.ssd_cache_path = None

class HelpWindow(ctk.CTkToplevel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometry("1150x900") 
        self.title("Cinético - Technical Guide")
        self.lift()
        self.focus_force()
        self.FONT_H1 = ("Segoe UI", 34, "bold")      
        self.FONT_H2 = ("微软雅黑", 18)              
        self.FONT_SEC = ("Segoe UI", 22, "bold")     
        self.FONT_SEC_CN = ("微软雅黑", 16, "bold")  
        self.FONT_ITEM = ("Segoe UI", 16, "bold")    
        self.FONT_BODY_EN = ("Segoe UI", 13)         
        self.FONT_BODY_CN = ("微软雅黑", 13)         
        self.COL_BG = "#121212"        
        self.COL_CARD = "#1E1E1E"      
        self.COL_TEXT_HI = "#FFFFFF"   
        self.COL_TEXT_MED = "#CCCCCC"  
        self.COL_TEXT_LOW = "#888888"  
        self.COL_ACCENT = "#3B8ED0"    
        self.configure(fg_color=self.COL_BG)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=50, pady=(45, 25))
        ctk.CTkLabel(header, text="Cinético Technical Overview", font=self.FONT_H1, text_color=self.COL_TEXT_HI, anchor="w").pack(fill="x")
        ctk.CTkLabel(header, text="Cinético 技术概览与操作指南", font=self.FONT_H2, text_color=self.COL_TEXT_LOW, anchor="w").pack(fill="x", pady=(8, 0))
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=30, pady=(0, 30))
        self.add_section_title("0. Smart Optimization Guide", "智能并发设置建议")
        self.add_desc_text("Based on your current hardware configuration / 根据您当前的硬件配置")
        cpu_advice, gpu_advice = self.get_hardware_advice()
        self.add_item_block("CPU Encoding Mode", "CPU 纯软解", cpu_advice['en'], cpu_advice['cn'])
        self.add_item_block("GPU Acceleration Mode", "GPU 硬件加速", gpu_advice['en'], gpu_advice['cn'])
        ctk.CTkFrame(self.scroll, height=60, fg_color="transparent").pack()

    def get_hardware_advice(self):
        try: cpu_count = os.cpu_count() or 4
        except: cpu_count = 4
        if cpu_count >= 16:
            rec_cpu = 3 
            cpu_desc = "High-Performance CPU."
            cpu_en = "Your CPU is powerful. [3] is the sweet spot."
            cpu_cn = "您的 CPU 性能强劲，[3] 是最佳甜点值。"
        elif cpu_count >= 8:
            rec_cpu = 2
            cpu_desc = "Standard 8+ Thread CPU."
            cpu_en = "Use [2] tasks to balance speed."
            cpu_cn = "建议使用 [2] 个并发。"
        else:
            rec_cpu = 1
            cpu_desc = "Basic CPU."
            cpu_en = "Focus on [1] task."
            cpu_cn = "集中算力处理 [1] 个任务。"
        gpu_name = "Unknown"
        is_dual_nvenc = False
        try:
            cmd = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            if platform.system() == "Windows":
                gpu_name = subprocess.check_output(cmd, startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8").strip()
            else:
                gpu_name = subprocess.check_output(cmd, encoding="utf-8").strip()
        except: pass
        if "4090" in gpu_name or "4080" in gpu_name: is_dual_nvenc = True
        if is_dual_nvenc:
            gpu_en = "Dual-NVENC detected. Set to [3] or [4]."
            gpu_cn = "检测到双编码芯片，推荐 [3] 或 [4]。"
        else:
            gpu_en = "Standard GPU. Set to [2]."
            gpu_cn = "标准显卡，推荐 [2]。"
        return {"en": f"{cpu_desc}\n{cpu_en}", "cn": f"{cpu_cn}"}, {"en": f"{gpu_name}\n{gpu_en}", "cn": f"{gpu_cn}"}

    def add_section_title(self, text_en, text_cn):
        f = ctk.CTkFrame(self.scroll, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(35, 15))
        bar = ctk.CTkFrame(f, width=5, height=28, fg_color=self.COL_ACCENT)
        bar.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(f, text=text_en, font=self.FONT_SEC, text_color=self.COL_TEXT_HI).pack(side="left", anchor="sw")
        ctk.CTkLabel(f, text=f"  {text_cn}", font=self.FONT_SEC_CN, text_color=self.COL_TEXT_LOW).pack(side="left", anchor="sw", pady=(3,0))
    def add_desc_text(self, text):
        ctk.CTkLabel(self.scroll, text=text, font=self.FONT_BODY_EN, text_color=self.COL_TEXT_MED, 
                     justify="left", anchor="w").pack(fill="x", padx=40, pady=(0, 20))
    def add_item_block(self, title_en, title_cn, body_en, body_cn):
        card = ctk.CTkFrame(self.scroll, fg_color=self.COL_CARD, corner_radius=8)
        card.pack(fill="x", padx=20, pady=10)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=25, pady=20)
        title_box = ctk.CTkFrame(inner, fg_color="transparent")
        title_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(title_box, text=title_en, font=self.FONT_ITEM, text_color=self.COL_TEXT_HI).pack(side="left")
        if title_cn: ctk.CTkLabel(title_box, text=f"  {title_cn}", font=self.FONT_ITEM, text_color=self.COL_ACCENT).pack(side="left")
        ctk.CTkLabel(inner, text=body_en, font=self.FONT_BODY_EN, text_color=self.COL_TEXT_MED, justify="left", anchor="w", wraplength=950).pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(inner, text=body_cn, font=self.FONT_BODY_CN, text_color=self.COL_TEXT_LOW, justify="left", anchor="w", wraplength=950).pack(fill="x")

# 主程序
class UltraEncoderApp(DnDWindow):
    def safe_update(self, func, *args, **kwargs):
        if self.winfo_exists():
            self.after(10, partial(self._guarded_call, func, *args, **kwargs))
    def _guarded_call(self, func, *args, **kwargs):
        try:
            if self.winfo_exists(): func(*args, **kwargs)
        except: pass
    def scroll_to_card(self, widget):
        try:
            target_file = None
            for f, card in self.task_widgets.items():
                if card == widget: target_file = f; break
            if not target_file: return
            if target_file in self.file_queue:
                index = self.file_queue.index(target_file) - 1 
                total = len(self.file_queue)               
                if total > 1:
                    target_pos = index / total
                    if index > 0: target_pos = max(0.0, target_pos - (1 / total) * 0.5)
                    self.scroll._parent_canvas.yview_moveto(target_pos)
                    self.after(100, lambda: self.scroll._parent_canvas.yview_moveto(target_pos))
        except: pass
    def preload_help_window(self):
        try:
            self.help_window = HelpWindow(self) 
            self.help_window.withdraw()         
            self.help_window.protocol("WM_DELETE_WINDOW", self.hide_help_window)
        except: pass
    def hide_help_window(self):
        self.help_window.withdraw()
    def __init__(self):
        super().__init__()
        self.title("Cinético_Encoder")
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
        self.gpu_lock = threading.Lock()
        self.gpu_active_count = 0  
        self.total_vram_gb = self.get_total_vram_gb() 
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
        self.global_server, self.global_port = start_global_server()
        disable_power_throttling() 
        set_execution_state(True)  
        self.after(200, self.sys_check)
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)
        self.after(200, self.preload_help_window)

    def show_help(self):
        if not hasattr(self, "help_window") or not self.help_window.winfo_exists():
            self.preload_help_window()
        self.help_window.deiconify()
        self.help_window.lift()

    def drop_file(self, event):
        self.auto_clear_completed()
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    def auto_clear_completed(self):
        if self.running: return
        if not self.file_queue: return
        all_finished = True
        for f in self.file_queue:
            code = self.task_widgets[f].status_code
            if code != 5 and code != -1: 
                all_finished = False; break
        if all_finished: self.clear_all()

    def check_placeholder(self):
        if not self.file_queue:
            self.scroll.pack_forget()
            self.lbl_placeholder.pack(fill="both", expand=True, padx=10, pady=5)
        else:
            self.lbl_placeholder.pack_forget()
            self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

    def add_list(self, files):
        with self.queue_lock: 
            existing_paths = set(os.path.normpath(os.path.abspath(f)) for f in self.file_queue)
            new_added = False
            for f in files:
                f_norm = os.path.normpath(os.path.abspath(f))
                if f_norm in existing_paths: continue 
                if f_norm.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts', '.flv', '.wmv')):
                    self.file_queue.append(f_norm) 
                    existing_paths.add(f_norm) 
                    if f_norm not in self.task_widgets:
                        card = TaskCard(self.scroll, 0, f_norm) 
                        self.task_widgets[f_norm] = card
                    new_added = True
            if not new_added: return
            self.file_queue.sort(key=lambda x: os.path.getsize(x))
            for i, f in enumerate(self.file_queue):
                if f in self.task_widgets:
                    card = self.task_widgets[f]
                    card.pack_forget()
                    card.pack(fill="x", pady=4)
                    card.update_index(i + 1)
            if self.running: self.update_run_status()
            self.safe_update(self.check_placeholder)

    def update_run_status(self):
        if not self.running: return
        total = len(self.file_queue)
        current = min(self.finished_tasks_count + 1, total)
        if current > total and total > 0: current = total
        try: self.lbl_run_status.configure(text=f"任务队列: {current} / {total}") 
        except: pass

    def apply_system_priority(self, level_text):
        if platform.system() != "Windows": return
        p_val = PRIORITY_NORMAL 
        if "ABOVE" in level_text: p_val = PRIORITY_ABOVE
        elif "HIGH" in level_text: p_val = PRIORITY_HIGH
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
    
    def clean_junk(self):
        try:
            for f in self.temp_files:
                if os.path.exists(f): os.remove(f)
        except: pass
        
    def kill_all_procs(self):
        for p in list(self.active_procs): 
            try: p.terminate(); p.kill()
            except: pass
        try: 
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.run(["pkill", "-f", "ffmpeg"])
        except: pass

    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("错误", "找不到 FFmpeg！自动下载失败，请手动安装。")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.gpu_monitor_loop, daemon=True).start()
        self.update_monitor_layout()

    def get_total_vram_gb(self):
        try:
            cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
            kwargs = get_subprocess_args()
            return float(subprocess.check_output(cmd, encoding="utf-8", **kwargs).strip()) / 1024.0
        except: return 8.0 

    def should_use_gpu(self, codec_sel):
        if not self.gpu_var.get(): return False 
        task_cost = 1.2 
        if "AV1" in codec_sel: task_cost = 2.0
        system_reserve = 1.5 
        with self.gpu_lock:
            predicted_usage = (self.gpu_active_count + 1) * task_cost
            if predicted_usage > (self.total_vram_gb - system_reserve):
                if self.gpu_active_count < 2: return True
                return False 
        return True

    def gpu_monitor_loop(self):
        while not self.stop_flag:
            try:
                cmd = ["nvidia-smi", "--query-gpu=power.draw,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
                kwargs = get_subprocess_args()
                output = subprocess.check_output(cmd, encoding="utf-8", **kwargs).strip()
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

    def toggle_action(self):
        if not self.running:
            if not self.file_queue:
                messagebox.showinfo("提示", "请先拖入或导入视频文件！")
                return
            self.run()
        else:
            self.stop()

    def detect_optimal_concurrency(self):
        optimal_n = 2
        try:
            gpu_name = "Unknown"
            is_dual_nvenc = False
            try:
                cmd = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
                kwargs = get_subprocess_args()
                gpu_name = subprocess.check_output(cmd, encoding="utf-8", **kwargs).strip().upper()
                dual_nvenc_triggers = ["RTX 4090", "RTX 4080", "RTX 4070 TI", "TITAN", "L40", "A40", "A100"]
                for trigger in dual_nvenc_triggers:
                    if trigger in gpu_name: is_dual_nvenc = True; break
            except: pass
            cpu_count = os.cpu_count() or 4
            is_high_core_cpu = (cpu_count >= 16)
            if is_dual_nvenc: optimal_n = 3
            elif is_high_core_cpu: optimal_n = 3
            elif cpu_count < 8: optimal_n = 1
            else: optimal_n = 2
        except: optimal_n = 2
        return str(optimal_n)

    def setup_ui(self):
        SIDEBAR_WIDTH = 420 
        self.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=SIDEBAR_WIDTH)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        UNIFIED_PAD_X = 20  
        ROW_SPACING = 6     
        LABEL_PAD = (0, 3)
        FONT_TITLE_MINI = ("微软雅黑", 11, "bold") 
        FONT_BTN_BIG    = ("微软雅黑", 11, "bold")
        COL_TEXT_ACTIVE = "#FFFFFF"   
        COL_TEXT_INACTIVE = "#999999" 
        COL_BTN_BG_OFF = "#333333"    
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=UNIFIED_PAD_X, pady=(20, 5))
        title_box = ctk.CTkFrame(l_head, fg_color="transparent")
        title_box.pack(fill="x")
        ctk.CTkLabel(title_box, text="Cinético", font=("Segoe UI Black", 36), text_color="#FFF").pack(side="left")
        btn_help = ctk.CTkButton(title_box, text="❓", width=30, height=30, corner_radius=15, 
                                 fg_color="#333", hover_color="#555", command=self.show_help)
        btn_help.pack(side="right")
        self.btn_cache = ctk.CTkButton(left, text="Checking Disk...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, 
                                     command=self.select_cache_folder) 
        self.btn_cache.pack(fill="x", padx=UNIFIED_PAD_X, pady=(5, 5))
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(tools, text="IMPORT / 导入视频", width=190, height=38, corner_radius=19, 
                     fg_color="#333", hover_color="#444", text_color="#DDD", font=("微软雅黑", 12, "bold"),
                     command=self.add_file).pack(side="left", padx=5)
        self.btn_clear = ctk.CTkButton(tools, text="RESET / 重置", width=190, height=38, corner_radius=19, 
                     fg_color="transparent", border_width=1, border_color="#444", 
                     hover_color="#331111", text_color="#CCC", font=("微软雅黑", 12),
                     command=self.clear_all)
        self.btn_clear.pack(side="left", padx=5)
        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=UNIFIED_PAD_X, pady=10)
        self.gpu_var = ctk.BooleanVar(value=False) 
        self.keep_meta_var = ctk.BooleanVar(value=True)
        self.hybrid_var = ctk.BooleanVar(value=False) 
        self.depth_10bit_var = ctk.BooleanVar(value=False)
        self.priority_var = ctk.StringVar(value="HIGH / 高优先") 
        self.worker_var = ctk.StringVar(value="2")
        self.crf_var = ctk.IntVar(value=23)
        self.codec_var = ctk.StringVar(value="H.264")
        def update_btn_visuals():
            is_gpu = self.gpu_var.get()
            self.btn_gpu.configure(fg_color=COLOR_ACCENT if is_gpu else COL_BTN_BG_OFF, text_color=COL_TEXT_ACTIVE if is_gpu else COL_TEXT_INACTIVE)
            is_meta = self.keep_meta_var.get()
            self.btn_meta.configure(fg_color=COLOR_ACCENT if is_meta else COL_BTN_BG_OFF, text_color=COL_TEXT_ACTIVE if is_meta else COL_TEXT_INACTIVE)
            is_hybrid = self.hybrid_var.get()
            if not is_gpu: self.btn_hybrid.configure(state="disabled", fg_color="#222222", text_color="#555")
            else: self.btn_hybrid.configure(state="normal", fg_color=COLOR_ACCENT if is_hybrid else COL_BTN_BG_OFF, text_color=COL_TEXT_ACTIVE if is_hybrid else COL_TEXT_INACTIVE)
            is_10bit = self.depth_10bit_var.get()
            self.btn_10bit.configure(fg_color=COLOR_ACCENT if is_10bit else COL_BTN_BG_OFF, text_color=COL_TEXT_ACTIVE if is_10bit else COL_TEXT_INACTIVE)
        def on_toggle_gpu():
            target = not self.gpu_var.get()
            if target and "H.264" in self.codec_var.get() and self.depth_10bit_var.get(): self.depth_10bit_var.set(False)
            self.gpu_var.set(target)
            if not target: self.hybrid_var.set(False) 
            if target: self.crf_var.set(min(40, self.crf_var.get() + 5))
            else: self.crf_var.set(max(16, self.crf_var.get() - 5))
            update_btn_visuals()
            update_labels()
        def on_toggle_10bit():
            target = not self.depth_10bit_var.get()
            if target and "H.264" in self.codec_var.get():
                if self.gpu_var.get():
                    self.gpu_var.set(False)
                    self.hybrid_var.set(False) 
                    self.crf_var.set(max(16, self.crf_var.get() - 5))
            self.depth_10bit_var.set(target)
            update_btn_visuals()
            update_labels()
        def on_codec_change(value):
            if "H.264" in value:
                if self.gpu_var.get() and self.depth_10bit_var.get():
                    self.gpu_var.set(False)
                    self.hybrid_var.set(False)
                    self.crf_var.set(max(16, self.crf_var.get() - 5))
            update_btn_visuals()
            update_labels() 
        def on_toggle_simple(var):
            var.set(not var.get())
            update_btn_visuals()
        def update_labels():
            if self.gpu_var.get(): self.lbl_quality_title.configure(text="QUALITY (CQ) / 固定量化")
            else: self.lbl_quality_title.configure(text="QUALITY (CRF) / 恒定速率")
        f_toggles = ctk.CTkFrame(l_btm, fg_color="transparent")
        f_toggles.pack(fill="x", padx=UNIFIED_PAD_X, pady=(15, 5))
        for i in range(4): f_toggles.grid_columnconfigure(i, weight=1)
        self.btn_gpu = ctk.CTkButton(f_toggles, text="GPU ACCEL\n硬件加速", font=FONT_BTN_BIG, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=on_toggle_gpu)
        self.btn_gpu.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        self.btn_meta = ctk.CTkButton(f_toggles, text="KEEP DATA\n保留信息", font=FONT_BTN_BIG, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=lambda: on_toggle_simple(self.keep_meta_var))
        self.btn_meta.grid(row=0, column=1, padx=3, sticky="ew")
        self.btn_hybrid = ctk.CTkButton(f_toggles, text="HYBRID\n异构分流", font=FONT_BTN_BIG, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=lambda: on_toggle_simple(self.hybrid_var))
        self.btn_hybrid.grid(row=0, column=2, padx=3, sticky="ew")
        self.btn_10bit = ctk.CTkButton(f_toggles, text="10-BIT\n高色深", font=FONT_BTN_BIG, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=on_toggle_10bit)
        self.btn_10bit.grid(row=0, column=3, padx=(3, 0), sticky="ew")
        update_btn_visuals()
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(rowP, text="PRIORITY / 系统优先级", font=FONT_TITLE_MINI, text_color="#DDD").pack(anchor="w", pady=LABEL_PAD)
        self.seg_priority = ctk.CTkSegmentedButton(rowP, values=["NORMAL / 常规", "ABOVE / 较高", "HIGH / 高优先"], variable=self.priority_var, command=lambda v: self.apply_system_priority(v), selected_color=COLOR_ACCENT, corner_radius=8, height=30, text_color="#DDDDDD", selected_hover_color="#36719f", unselected_hover_color="#444")
        self.seg_priority.pack(fill="x")
        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(row3, text="CONCURRENCY / 并发任务", font=FONT_TITLE_MINI, text_color="#DDD").pack(anchor="w", pady=LABEL_PAD)
        self.worker_var = ctk.StringVar(value=self.detect_optimal_concurrency()) 
        self.seg_worker = ctk.CTkSegmentedButton(row3, values=["1", "2", "3", "4"], variable=self.worker_var, corner_radius=8, height=30, selected_color=COLOR_ACCENT, command=self.update_monitor_layout, text_color="#DDDDDD", selected_hover_color="#36719f", unselected_hover_color="#444")
        self.seg_worker.pack(fill="x")
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        self.lbl_quality_title = ctk.CTkLabel(row2, text="QUALITY (CRF) / 恒定速率", font=FONT_TITLE_MINI, text_color="#DDD")
        self.lbl_quality_title.pack(anchor="w", pady=LABEL_PAD)
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        slider = ctk.CTkSlider(c_box, from_=16, to=40, variable=self.crf_var, progress_color=COLOR_ACCENT, height=20)
        slider.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkLabel(c_box, textvariable=self.crf_var, width=35, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="right")
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(row1, text="CODEC / 编码格式", font=FONT_TITLE_MINI, text_color="#DDD").pack(anchor="w", pady=LABEL_PAD)
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265", "AV1"], variable=self.codec_var, selected_color=COLOR_ACCENT, corner_radius=8, height=30, command=on_codec_change, text_color="#DDDDDD", selected_hover_color="#36719f", unselected_hover_color="#444")
        self.seg_codec.pack(fill="x")
        self.btn_action = ctk.CTkButton(l_btm, text="COMPRESS / 压制", height=55, corner_radius=12, font=("微软雅黑", 18, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#000", command=self.toggle_action)
        self.btn_action.pack(fill="x", padx=UNIFIED_PAD_X, pady=20)
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.lbl_placeholder = ctk.CTkLabel(left, text="📂\n\nDrag & Drop Video Files Here\n拖入视频文件开启任务", font=("微软雅黑", 16, "bold"), text_color="#444444", justify="center")
        self.check_placeholder()
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Microsoft YaHei UI", 20, "bold"), text_color="#BBB").pack(side="left")
        self.lbl_run_status = ctk.CTkLabel(r_head, text="", font=("微软雅黑", 12, "bold"), text_color=COLOR_ACCENT)
        self.lbl_run_status.pack(side="left", padx=20, pady=2) 
        self.lbl_gpu = ctk.CTkLabel(r_head, text="GPU: --W | --°C", font=("Consolas", 14, "bold"), text_color="#444")
        self.lbl_gpu.pack(side="right")
        self.monitor_frame = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))

    def clear_all(self):
        if self.running: return 
        for k, v in self.task_widgets.items(): v.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()
        self.check_placeholder()
        self.finished_tasks_count = 0
        try: self.scroll._parent_canvas.yview_moveto(0.0)
        except: pass
        self.reset_ui_state()
        self.lbl_run_status.configure(text="")
        self.update_monitor_layout(force_reset=True)

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

    def process_caching(self, src_path, widget, lock_obj=None, no_wait=False):
        file_size = os.path.getsize(src_path)
        file_size_gb = file_size / (1024**3)
        is_ssd = is_drive_ssd(src_path)
        is_external = is_bus_usb(src_path)
        if is_ssd and not is_external:
            self.safe_update(widget.set_status, "就绪 (SSD直读)", COLOR_DIRECT, STATUS_READY)
            widget.source_mode = "DIRECT"
            return True
        if file_size_gb < MAX_RAM_LOAD_GB:
             wait_count = 0
             limit = 0 if no_wait else 60 
             while wait_count < limit: 
                 free_ram = get_free_ram_gb()
                 available = free_ram - SAFE_RAM_RESERVE
                 if available > file_size_gb: break 
                 if wait_count == 0: self.safe_update(widget.set_status, "⏳ 等待内存...", COLOR_WAITING, STATUS_WAIT)
                 if self.stop_flag: return False
                 time.sleep(0.5)
                 wait_count += 1
        if lock_obj: lock_obj.acquire()
        try:
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
                    token = str(uuid.uuid4().hex) 
                    GLOBAL_RAM_STORAGE[token] = data_buffer
                    PATH_TO_TOKEN_MAP[src_path] = token
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
        finally:
            if lock_obj: lock_obj.release()
        
    def run(self):
        if not self.file_queue: return
        if self.running: return
        self.running = True
        self.stop_flag = False
        self.btn_action.configure(text="STOP / 停止", fg_color="#852222", hover_color="#A32B2B", state="normal")
        self.btn_clear.configure(state="disabled")
        self.executor.shutdown(wait=False)
        self.executor = ThreadPoolExecutor(max_workers=16)
        self.submitted_tasks.clear()
        self.gpu_active_count = 0
        with self.slot_lock: self.available_indices = list(range(self.current_workers))
        self.update_monitor_layout()
        with self.queue_lock:
            self.finished_tasks_count = 0
            for f in self.file_queue:
                card = self.task_widgets[f]
                if card.status_code == STATUS_DONE: self.finished_tasks_count += 1
                else:
                    card.set_status("等待处理", "#888", STATUS_WAIT)
                    card.set_progress(0)
                    card.clean_memory() 
                    if card.ssd_cache_path and os.path.exists(card.ssd_cache_path):
                        try: os.remove(card.ssd_cache_path)
                        except: pass
                    card.ssd_cache_path = None
                    card.source_mode = "PENDING"
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.kill_all_procs()
        self.btn_action.configure(text="正在停止...", state="disabled")

    def reset_ui_state(self):
        self.btn_action.configure(text="COMPRESS / 压制", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, state="normal")
        self.lbl_run_status.configure(text="") 
        self.btn_clear.configure(state="normal")
        self.update_monitor_layout(force_reset=True)

    def get_dur(self, path):
        try:
            # 使用 FFMPEG_PATH 衍生出的 FFPROBE_PATH
            cmd = [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
            kwargs = get_subprocess_args()
            out = subprocess.check_output(cmd, **kwargs).strip()
            return float(out)
        except: return 0

    def add_file(self):
        files = filedialog.askopenfilenames(title="选择视频文件", filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.avi *.ts *.flv *.wmv")])
        if files: 
            self.auto_clear_completed()
            self.add_list(files)

    def show_custom_popup(self, title, message):
        if not self.winfo_exists(): return
        top = ctk.CTkToplevel(self)
        top.geometry("320x160")
        top.title("")
        top.overrideredirect(True) 
        top.attributes("-topmost", True) 
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 160
            y = self.winfo_y() + (self.winfo_height() // 2) - 80
            top.geometry(f"+{x}+{y}")
        except: pass
        bg = ctk.CTkFrame(top, fg_color="#2B2B2B", border_width=2, border_color=COLOR_ACCENT, corner_radius=15)
        bg.pack(fill="both", expand=True)
        ctk.CTkLabel(bg, text=title, font=("微软雅黑", 18, "bold"), text_color=COLOR_ACCENT).pack(pady=(25, 5))
        ctk.CTkLabel(bg, text=message, font=("微软雅黑", 13), text_color="#DDD").pack(pady=(0, 20))
        def close_win(): top.destroy()
        ctk.CTkButton(bg, text="OK / 知道了", width=100, height=32, corner_radius=16, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, command=close_win).pack(pady=10)
        top.grab_set()

    def launch_fireworks(self):
        if not self.winfo_exists(): return
        top = ctk.CTkToplevel(self)
        top.title("")
        w, h = self.winfo_width(), self.winfo_height()
        x, y = self.winfo_x(), self.winfo_y()
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.overrideredirect(True)
        top.transient(self)
        top.attributes("-transparentcolor", "black") 
        canvas = ctk.CTkCanvas(top, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        particles = []
        colors = [COLOR_ACCENT, "#F1C40F", "#E74C3C", "#2ECC71", "#9B59B6", "#00FFFF", "#FF00FF", "#FFFFFF"] 
        particle_count = 150 
        for _ in range(particle_count):
            particles.append({"x": random.uniform(-50, 100), "y": h + random.uniform(0, 30), "vx": random.gauss(15, 10), "vy": random.gauss(-40, 12), "grav": 2.0, "size": random.uniform(3, 8), "color": random.choice(colors), "life": 1.0, "decay": random.uniform(0.012, 0.025)})
        for _ in range(particle_count):
            particles.append({"x": random.uniform(w-100, w+50), "y": h + random.uniform(0, 30), "vx": random.gauss(-15, 10), "vy": random.gauss(-40, 12), "grav": 1.6, "size": random.uniform(3, 8), "color": random.choice(colors), "life": 1.0, "decay": random.uniform(0.012, 0.025)})
        def animate():
            if not top.winfo_exists(): return
            canvas.delete("all")
            alive_count = 0
            for p in particles:
                if p["life"] > 0:
                    alive_count += 1
                    tail_x, tail_y = p["x"], p["y"]
                    p["x"] += p["vx"]
                    p["y"] += p["vy"]
                    p["vy"] += p["grav"] 
                    p["vx"] *= 0.97      
                    p["life"] -= p["decay"]
                    if p["life"] > 0.05:
                        canvas.create_line(tail_x, tail_y, p["x"], p["y"], fill=p["color"], width=p["size"] * p["life"], capstyle="round")
            if alive_count > 0: top.after(15, animate)
            else: top.destroy()
        animate()

    def engine(self):
        total_ram_limit = MAX_RAM_LOAD_GB 
        current_ram_usage = 0.0            
        is_cache_ssd = is_drive_ssd(self.temp_dir) or (self.manual_cache_path and is_drive_ssd(self.manual_cache_path))
        io_concurrency = self.current_workers if is_cache_ssd else 1
        self.io_executor = ThreadPoolExecutor(max_workers=io_concurrency)
        while not self.stop_flag:
            active_io_count = 0
            active_compute_count = 0
            current_ram_usage = 0.0
            with self.queue_lock:
                for f in self.file_queue:
                    card = self.task_widgets[f]
                    if card.source_mode == "RAM" and card.status_code not in [STATE_DONE, STATE_ERROR]:
                        current_ram_usage += card.file_size_gb
                    if card.status_code in [STATE_QUEUED_IO, STATE_CACHING]: active_io_count += 1
                    elif card.status_code == STATE_ENCODING: active_compute_count += 1
            with self.queue_lock:
                for f in self.file_queue:
                    card = self.task_widgets[f]
                    if card.status_code == STATE_PENDING:
                        source_is_ssd = is_drive_ssd(f)
                        if source_is_ssd:
                            card.source_mode = "DIRECT"
                            card.status_code = STATE_READY 
                            self.safe_update(card.set_status, "就绪 (SSD直读)", COLOR_DIRECT, STATE_READY)
                            self.safe_update(card.set_progress, 1.0, COLOR_DIRECT)
                            continue 
                        else:
                            if active_io_count >= 1: break 
                            predicted_usage = current_ram_usage + card.file_size_gb
                            if predicted_usage < total_ram_limit:
                                should_use_ram = True
                                current_ram_usage += card.file_size_gb 
                            else: should_use_ram = False 
                            card.source_mode = "RAM" if should_use_ram else "SSD_CACHE"
                            card.status_code = STATE_QUEUED_IO
                            active_io_count += 1
                            self.io_executor.submit(self._worker_io_task, f)
                            break
            if active_compute_count < self.current_workers:
                with self.queue_lock:
                    for f in self.file_queue:
                        card = self.task_widgets[f]
                        if card.status_code == STATE_READY:
                            card.status_code = STATE_ENCODING
                            active_compute_count += 1
                            self.executor.submit(self._worker_compute_task, f)
                            self.safe_update(self.scroll_to_card, card)
                            if active_compute_count >= self.current_workers: break
            all_done = True
            with self.queue_lock:
                for f in self.file_queue:
                    if self.task_widgets[f].status_code not in [STATE_DONE, STATE_ERROR]: all_done = False; break
            if all_done and active_io_count == 0 and active_compute_count == 0: break
            time.sleep(0.1) 
        self.running = False
        if not self.stop_flag:
            self.safe_update(self.launch_fireworks)
            def set_complete_state():
                self.btn_action.configure(text="COMPLETED / 已完成", fg_color=COLOR_SUCCESS, hover_color="#27AE60", state="disabled")
                self.lbl_run_status.configure(text="✨ All Tasks Finished")
                self.btn_clear.configure(state="normal") 
            self.safe_update(set_complete_state)
        else: self.safe_update(self.reset_ui_state)

    def _worker_io_task(self, task_file):
        card = self.task_widgets[task_file]
        try:
            self.safe_update(card.set_status, "📥正在加载...", COLOR_READING, STATE_CACHING)
            success = self.process_caching(task_file, card, lock_obj=None, no_wait=True)
            if success:
                self.safe_update(card.set_status, "⚡就绪 (等待编码)", COLOR_READY_RAM if card.source_mode == "RAM" else COLOR_SSD_CACHE, STATE_READY)
            else: self.safe_update(card.set_status, "IO 失败", COLOR_ERROR, STATE_ERROR)
        except Exception as e:
            print(f"IO Error: {e}")
            self.safe_update(card.set_status, "IO 错误", COLOR_ERROR, STATE_ERROR)

    def analyze_ffmpeg_log(self, logs):
        log_text = "\n".join(logs[-30:]) 
        error_patterns = [("Permission denied", "❌ 文件权限不足"), ("No such file", "❌ 找不到输入文件"), ("Unknown encoder", "❌ 找不到编码器"), ("Device mismatch", "❌ 显卡设备不匹配"), ("out of memory", "❌ 显存/内存不足"), ("Tag", "❌ 容器格式不兼容"), ("Invalid data", "❌ 数据流损坏"), ("Server returned 404", "❌ 内存数据丢失"), ("Qavg: nan", "❌ 音频编码崩溃"), ("aac", "❌ 音频格式错误")]
        for pattern, reason in error_patterns:
            if pattern in log_text or pattern.lower() in log_text.lower(): return reason
        return "❌ 未知错误"

    def check_decoding_capability(self, input_path):
        try:
            # 使用全局 FFPROBE_PATH
            cmd = [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt,codec_name", "-of", "csv=p=0", input_path]
            kwargs = get_subprocess_args()
            output = subprocess.check_output(cmd, encoding='utf-8', **kwargs).strip()
            parts = output.split(',')
            codec_name = parts[0].strip()
            pix_fmt = parts[1].strip() if len(parts) > 1 else ""
            unsupported_pix_fmts = ["yuv422p10le", "yuv422p10be", "yuv422p12le", "yuv422p12be", "yuv444p10le", "yuv444p12le"]
            can_hw_decode = True
            if pix_fmt in unsupported_pix_fmts:
                can_hw_decode = False
                print(f"[Smart Check] 检测到高规格素材 ({pix_fmt})，将强制使用 CPU 解码以保证稳定。")
            return {"can_hw_decode": can_hw_decode, "pix_fmt": pix_fmt, "codec_name": codec_name}
        except Exception as e:
            print(f"[Check Error] 检测失败，默认回退到 CPU 解码: {e}")
            return {"can_hw_decode": False, "pix_fmt": "unknown", "codec_name": "unknown"}

    def _worker_compute_task(self, task_file):
        card = self.task_widgets[task_file]
        fname = os.path.basename(task_file)
        slot_idx = -1
        ch_ui = None
        proc = None
        working_output_file = None 
        temp_audio_wav = os.path.join(self.temp_dir, f"TEMP_AUDIO_{uuid.uuid4().hex}.wav")
        output_log = []
        input_size = 0
        duration = 1.0
        with self.slot_lock:
            if self.available_indices:
                slot_idx = self.available_indices.pop(0)
                if slot_idx < len(self.monitor_slots): ch_ui = self.monitor_slots[slot_idx]
        if not ch_ui: 
            class DummyUI: 
                def activate(self, *a): pass
                def update_data(self, *a): pass
                def reset(self): pass
            ch_ui = DummyUI()
        try:
            self.safe_update(ch_ui.activate, fname, "⏳ 正在预处理 / Pre-processing...")
            if os.path.exists(task_file):
                input_size = os.path.getsize(task_file)
                duration = self.get_dur(task_file)
                if duration <= 0: duration = 1.0
            need_audio_extract = True 
            decode_info = self.check_decoding_capability(task_file)
            hw_decode_allowed = decode_info["can_hw_decode"]
            has_audio = False
            if need_audio_extract:
                self.safe_update(ch_ui.activate, fname, "🎵 正在分离音频流 / Extracting Audio...")
                self.safe_update(card.set_status, "🎵 提取音频...", COLOR_READING, STATE_ENCODING)
                # 使用全局 FFMPEG_PATH
                extract_cmd = [FFMPEG_PATH, "-y", "-i", task_file, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", "-f", "wav", temp_audio_wav]
                kwargs = get_subprocess_args()
                subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
                if os.path.exists(temp_audio_wav) and os.path.getsize(temp_audio_wav) > 1024: has_audio = True
            self.safe_update(card.set_status, "▶️ 智能编码中...", COLOR_ACCENT, STATE_ENCODING)
            codec_sel = self.codec_var.get()
            using_gpu = self.gpu_var.get()
            is_mixed_mode = self.hybrid_var.get()
            is_even_slot = (slot_idx % 2 == 0)
            final_hw_decode = using_gpu and hw_decode_allowed
            if is_mixed_mode and is_even_slot: final_hw_decode = False 
            final_hw_encode = using_gpu
            input_video_source = task_file
            if not final_hw_decode and card.source_mode == "RAM":
                token = PATH_TO_TOKEN_MAP.get(task_file)
                if token: input_video_source = f"http://127.0.0.1:{self.global_port}/{token}"
            elif card.source_mode == "SSD_CACHE" and card.ssd_cache_path:
                input_video_source = card.ssd_cache_path
            output_dir = os.path.dirname(task_file)
            f_name_no_ext = os.path.splitext(fname)[0]
            date_str = time.strftime("%Y%m%d")
            final_filename = f"{f_name_no_ext}_Compressed_{date_str}.mp4"
            final_output_path = os.path.join(output_dir, final_filename)
            temp_output_filename = f"TEMP_ENC_{uuid.uuid4().hex}.mp4"
            working_output_file = os.path.join(self.temp_dir, temp_output_filename)
            
            # 使用全局 FFMPEG_PATH
            cmd = [FFMPEG_PATH, "-y"]
            if final_hw_decode:
                cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
                cmd.extend(["-extra_hw_frames", "2"]) 
            if not final_hw_decode and card.source_mode == "RAM":
                cmd.extend(["-probesize", "50M", "-analyzeduration", "100M"])
            cmd.extend(["-i", input_video_source])
            if has_audio: cmd.extend(["-i", temp_audio_wav])
            cmd.extend(["-map", "0:v:0"])
            if has_audio: cmd.extend(["-map", "1:a:0"])
            v_codec = "libx264" 
            if final_hw_encode:
                if "H.264" in codec_sel: v_codec = "h264_nvenc"
                elif "H.265" in codec_sel: v_codec = "hevc_nvenc"
                elif "AV1" in codec_sel: v_codec = "av1_nvenc"
                cmd.extend(["-c:v", v_codec])
            use_10bit = self.depth_10bit_var.get()
            if final_hw_encode and "H.264" in codec_sel and use_10bit: use_10bit = False
            if final_hw_encode:
                if use_10bit:
                    if final_hw_decode: cmd.extend(["-vf", "scale_cuda=format=p010le"]) 
                    else: cmd.extend(["-pix_fmt", "p010le"])
                else:
                    if final_hw_decode: cmd.extend(["-vf", "scale_cuda=format=yuv420p"]) 
                    else: cmd.extend(["-pix_fmt", "yuv420p"]) 
                cmd.extend(["-rc", "vbr", "-cq", str(self.crf_var.get()), "-b:v", "0"])
                if "AV1" not in codec_sel: cmd.extend(["-preset", "p4"])
            else:
                if use_10bit: cmd.extend(["-pix_fmt", "yuv420p10le"])
                else: cmd.extend(["-pix_fmt", "yuv420p"])
                cmd.extend(["-crf", str(self.crf_var.get()), "-preset", "medium"])
            if has_audio: cmd.extend(["-c:a", "aac", "-b:a", "320k"])
            if self.keep_meta_var.get(): cmd.extend(["-map_metadata", "0"])
            cmd.extend(["-progress", "pipe:1", "-nostats", working_output_file])

            # 使用 subprocess 跨平台参数
            kwargs = get_subprocess_args()
            if platform.system() == "Windows":
                 proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=kwargs['startupinfo'], creationflags=kwargs['creationflags'])
            else:
                 proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            self.active_procs.append(proc)
            def log_stderr(p):
                for l in p.stderr:
                    try: output_log.append(l.decode('utf-8', errors='ignore').strip())
                    except: pass
            threading.Thread(target=log_stderr, args=(proc,), daemon=True).start()
            info_decode = "GPU" if final_hw_decode else "CPU"
            info_encode = "GPU" if final_hw_encode else "CPU"
            tag_info = f"Dec:{info_decode} | Enc:{info_encode}"
            if card.source_mode == "RAM": tag_info += " | RAM"
            self.safe_update(ch_ui.activate, fname, tag_info)
            progress_stats = {}
            start_t = time.time()
            last_ui_update_time = 0 
            ui_update_interval = 0.3
            for line in proc.stdout:
                if self.stop_flag: break
                try: 
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if not line_str: continue
                    if "=" in line_str:
                        key, value = line_str.split("=", 1)
                        progress_stats[key.strip()] = value.strip()
                        if key.strip() == "out_time_us":
                            now = time.time()
                            if now - last_ui_update_time > ui_update_interval:
                                fps = float(progress_stats.get("fps", "0")) if "fps" in progress_stats else 0.0
                                current_us = int(value.strip())
                                prog = min(1.0, (current_us / 1000000.0) / duration)
                                eta = "--:--"
                                elapsed = now - start_t
                                if prog > 0.005:
                                    eta_sec = (elapsed / prog) - elapsed
                                    if eta_sec < 0: eta_sec = 0
                                    eta = f"{int(eta_sec//60):02d}:{int(eta_sec%60):02d}"
                                ratio = 0.0
                                if os.path.exists(working_output_file) and prog > 0.01:
                                    curr_size = os.path.getsize(working_output_file)
                                    in_proc = input_size * prog
                                    if in_proc > 0: ratio = (curr_size / in_proc) * 100
                                self.safe_update(ch_ui.update_data, fps, prog, eta, ratio)
                                self.safe_update(card.set_progress, prog, COLOR_ACCENT)
                                last_ui_update_time = now
                except: pass
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)
            if os.path.exists(temp_audio_wav):
                try: os.remove(temp_audio_wav)
                except: pass
            if self.stop_flag:
                self.safe_update(card.set_status, "已停止", COLOR_PAUSED, STATE_PENDING)
            elif proc.returncode == 0:
                try:
                    self.safe_update(card.set_status, "📦 正在回写...", COLOR_MOVING, STATE_DONE)
                    if os.path.exists(working_output_file): shutil.move(working_output_file, final_output_path)
                    if self.keep_meta_var.get() and os.path.exists(final_output_path): shutil.copystat(task_file, final_output_path)
                    final_size_mb = 0
                    ratio_str = ""
                    try:
                        final_size_mb = os.path.getsize(final_output_path)
                        saved_percent = (1.0 - (final_size_mb / input_size)) * 100
                        if saved_percent < 0: ratio_str = f"(+{abs(saved_percent):.1f}%)"
                        else: ratio_str = f"(-{saved_percent:.1f}%)"
                    except: pass
                    status_text = f"完成 {ratio_str}"
                    self.safe_update(card.set_status, status_text, COLOR_SUCCESS, STATE_DONE)
                    self.safe_update(card.set_progress, 1.0, COLOR_SUCCESS)
                except Exception as move_err:
                    print(f"Move Error: {move_err}")
                    self.safe_update(card.set_status, "回写失败", COLOR_ERROR, STATE_ERROR)
                    saved_path = working_output_file
                    working_output_file = None 
                    self.show_custom_popup("回写错误", f"无法移回原目录，已保留在缓存池：\n{saved_path}")
            else:
                err_msg = self.analyze_ffmpeg_log(output_log)
                print(f"Task Failed: {fname}\nReason: {err_msg}")
                self.safe_update(card.set_status, "转码失败", COLOR_ERROR, STATE_ERROR)
                self.safe_update(messagebox.showerror, "错误", f"处理 {fname} 时发生错误：\n{err_msg}")
        except Exception as e:
            print(f"Critical System Error: {e}")
            self.safe_update(card.set_status, "系统错误", COLOR_ERROR, STATE_ERROR)
        finally:
            token = PATH_TO_TOKEN_MAP.get(task_file)
            if token and token in GLOBAL_RAM_STORAGE:
                 del GLOBAL_RAM_STORAGE[token]
                 del PATH_TO_TOKEN_MAP[task_file]
            if working_output_file and os.path.exists(working_output_file):
                try: os.remove(working_output_file)
                except: pass
            self.safe_update(ch_ui.reset)
            with self.slot_lock:
                if slot_idx != -1:
                    self.available_indices.append(slot_idx)
                    self.available_indices.sort()

if __name__ == "__main__":
    try:
        if platform.system() == "Windows":
            whnd = ctypes.windll.kernel32.GetConsoleWindow()
            if whnd != 0: ctypes.windll.user32.ShowWindow(whnd, 0)
    except Exception: pass
    app = UltraEncoderApp()
    app.mainloop()