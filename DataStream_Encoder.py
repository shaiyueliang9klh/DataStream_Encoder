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
import http.server
import socketserver
from http import HTTPStatus

# === 全局视觉配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 针对 64GB 内存环境的配置
MAX_RAM_LOAD_GB = 12.0  # 单个文件最大允许载入内存的大小 (GB)
SAFE_RAM_RESERVE = 8.0  # 保留给系统的最小内存 (GB)

COLOR_BG_MAIN = "#121212"
COLOR_PANEL_LEFT = "#1a1a1a"
COLOR_PANEL_RIGHT = "#0f0f0f"
COLOR_CARD = "#2d2d2d"
COLOR_ACCENT = "#3B8ED0"
COLOR_ACCENT_HOVER = "#36719f"
COLOR_CHART_LINE = "#00E676"
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_GRAY = "#888888"
COLOR_READY_RAM = "#00B894" # 薄荷绿 (内存就绪专用色)
COLOR_SUCCESS = "#2ECC71" # 绿色 (就绪/完成)
COLOR_MOVING = "#F1C40F"  # 金色 (移动/IO)
COLOR_READING = "#9B59B6" # 紫色 (预读)
COLOR_RAM     = "#3498DB" # 蓝色 (驻留内存)
COLOR_SSD_CACHE = "#E67E22" # 橙色 (SSD缓存)
COLOR_DIRECT  = "#1ABC9C" # 青色 (直读)
COLOR_PAUSED = "#7f8c8d"  # 灰色
COLOR_ERROR = "#FF4757"   # 红色

# 状态码
STATUS_WAIT = 0
STATUS_CACHING = 1   # 正在载入
STATUS_READY = 2     # 就绪
STATUS_RUN = 3       # 压制中
STATUS_DONE = 5
STATUS_ERR = -1

# 优先级常量
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

# === Windows 电源节流解除 (防最小化降速) ===
# === Windows 电源节流解除 (增强版：支持指定句柄) ===
class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong)]

# 防止系统休眠/息屏常量
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def set_execution_state(enable=True):
    """防止系统在压制过程中休眠或降频"""
    try:
        if enable:
            # 阻止系统休眠 + 保持运行状态
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        else:
            # 恢复正常
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except: pass

def disable_power_throttling(process_handle=None):
    """
    禁止 Windows 将进程判定为后台低功耗任务 (EcoQoS/效率模式)
    如果不传 handle，则默认处理当前主进程。
    """
    try:
        PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
        PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
        ProcessPowerThrottling = 0x22
        
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION
        # ControlMask: 我们要接管哪些位的控制权
        state.ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION
        # StateMask: 设为 0 表示关闭这些节流机制 (即全速运行)
        state.StateMask = 0 
        
        if process_handle is None:
            process_handle = ctypes.windll.kernel32.GetCurrentProcess()
            
        ret = ctypes.windll.kernel32.SetProcessInformation(
            process_handle, 
            ProcessPowerThrottling, 
            ctypes.byref(state), 
            ctypes.sizeof(state)
        )
        # 调试打印 (仅在调试时有用，实际运行可注释)
        # print(f"Throttling Disabled for Handle {process_handle}: {ret}")
    except Exception as e:
        print(f"Failed to disable throttling: {e}")

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

# === 内存流媒体服务器 (核心黑科技) ===
class RamHttpHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass # 静默模式，不打印日志

    def do_GET(self):
        # 获取全局存储的二进制数据
        data = self.server.ram_data
        if not data:
            self.send_error(HTTPStatus.NOT_FOUND, "No data loaded")
            return

        file_size = len(data)
        start, end = 0, file_size - 1

        # 解析 Range 头 (实现 Seek 的关键)
        if "Range" in self.headers:
            range_header = self.headers["Range"]
            try:
                # 格式通常为 bytes=0-1023
                range_val = range_header.split("=")[1]
                start_str, end_str = range_val.split("-")
                if start_str: start = int(start_str)
                if end_str: end = int(end_str)
            except: pass
        
        # 计算长度
        chunk_len = (end - start) + 1
        
        # 发送响应头
        self.send_response(HTTPStatus.PARTIAL_CONTENT if "Range" in self.headers else HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(chunk_len))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        # 发送内存切片
        try:
            self.wfile.write(data[start : end + 1])
        except (ConnectionResetError, BrokenPipeError):
            pass # 客户端断开是正常的

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True # 确保主程序退出时子线程也退出

def start_ram_server(ram_data):
    # 自动分配一个空闲端口 (端口为0时)
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
        # 增加 creationflags 防止弹出黑框
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except: return False

# === 磁盘类型检测 (修复版：API权威优先，防止缓存欺骗) ===
import struct

# 缓存检测结果
drive_type_cache = {}

def is_drive_ssd(path):
    """
    逻辑调整：
    1. Windows API (DeviceIoControl) 是最高权威。
       - 如果系统底层说 "有寻道惩罚" (IncursSeekPenalty=True)，那就是 HDD。
       - 此时直接返回 False，不再进行物理测速（防止被 HDD 的 DRAM 缓存欺骗）。
    2. 只有当 API 调用失败或无法判断时，才启用 PowerShell 或 Benchmark 兜底。
    """
    root = os.path.splitdrive(os.path.abspath(path))[0].upper()
    if not root: return False
    drive_letter = root # 例如 "C:"
    
    # 查缓存
    if drive_letter in drive_type_cache: 
        return drive_type_cache[drive_letter]

    print(f"[*]正在深度检测磁盘: {drive_letter}")
    is_ssd = False
    api_success = False # 标记 API 是否成功执行
    
    # --- 方法 1: Windows API 底层查询 (寻道惩罚) ---
    try:
        FILE_READ_ATTRIBUTES = 0x80
        OPEN_EXISTING = 3
        h_vol = ctypes.windll.kernel32.CreateFileW(
            f"\\\\.\\{drive_letter}",
            FILE_READ_ATTRIBUTES,
            0x00000001 | 0x00000002, 
            None,
            OPEN_EXISTING,
            0,
            None
        )
        
        if h_vol != -1:
            PropertyStandardQuery = 0
            StorageDeviceSeekPenaltyProperty = 7
            
            class STORAGE_PROPERTY_QUERY(ctypes.Structure):
                _fields_ = [("PropertyId", ctypes.c_uint),
                            ("QueryType", ctypes.c_uint),
                            ("AdditionalParameters", ctypes.c_byte * 1)]
            
            query = STORAGE_PROPERTY_QUERY()
            query.PropertyId = StorageDeviceSeekPenaltyProperty
            query.QueryType = PropertyStandardQuery
            
            class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
                _fields_ = [("Version", ctypes.c_ulong),
                            ("Size", ctypes.c_ulong),
                            ("IncursSeekPenalty", ctypes.c_bool)]
            
            out = DEVICE_SEEK_PENALTY_DESCRIPTOR()
            bytes_returned = ctypes.c_ulong()
            
            ret = ctypes.windll.kernel32.DeviceIoControl(
                h_vol,
                0x002D1400, # IOCTL_STORAGE_QUERY_PROPERTY
                ctypes.byref(query), ctypes.sizeof(query),
                ctypes.byref(out), ctypes.sizeof(out),
                ctypes.byref(bytes_returned), None
            )
            ctypes.windll.kernel32.CloseHandle(h_vol)
            
            if ret:
                api_success = True
                if not out.IncursSeekPenalty:
                    print(f"   [API] 无寻道惩罚 -> 判定为 SSD")
                    drive_type_cache[drive_letter] = True
                    return True
                else:
                    # [核心修复] API 明确说是 HDD，直接采信，防止被缓存欺骗
                    print(f"   [API] 存在寻道惩罚 -> 确认为 HDD")
                    drive_type_cache[drive_letter] = False
                    return False
    except Exception as e:
        print(f"   [API] 检测失败: {e}")

    # 如果 API 成功执行并返回了结果，上面就已经 return 了。
    # 能走到这里说明 API 失败了（比如特殊外接盒），必须启用兜底检测。

    # --- 方法 2 & 3: PowerShell 组合拳 ---
    if not is_ssd:
        try:
            cmd = f'Get-Partition -DriveLetter {drive_letter[0]} | Get-Disk | Select-Object MediaType, SpindleSpeed | ConvertTo-Json'
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            res = subprocess.check_output(["powershell", "-Command", cmd], startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, timeout=3).decode().strip().upper()
            
            if '"MEDIATYPE": "SSD"' in res or '"MEDIATYPE": 4' in res:
                print("   [PS] MediaType 确认为 SSD")
                is_ssd = True
            elif not is_ssd:
                import re
                speed_match = re.search(r'"SPINDLESPEED":\s*(\d+)', res)
                if speed_match and int(speed_match.group(1)) == 0:
                    print("   [PS] 转速为 0 -> 判定为 SSD")
                    is_ssd = True
        except: pass

    # --- 方法 4: 物理基准测试 (仅在 API 和 PS 都失效时才运行) ---
    if not is_ssd:
        try:
            # 只有不知道是不是 SSD 的时候才测，避免 HDD 缓存干扰
            print(f"   [Benchmark] 启动物理测速 (API失效兜底)...")
            test_dir = os.path.join(drive_letter + "\\", "_SpeedTest_Temp")
            os.makedirs(test_dir, exist_ok=True)
            test_file = os.path.join(test_dir, ".probe")
            
            # 增大写入量到 64MB 以尝试击穿 HDD 缓存 (虽然不一定管用，但比 4KB 好)
            # 但最好的办法还是前面 API 没报错
            with open(test_file, 'wb') as f:
                f.write(os.urandom(4096)) # 保持小文件以快速检测，但只作为最后手段
            
            t_start = time.perf_counter()
            with open(test_file, 'rb') as f:
                f.seek(2048); _ = f.read(1)
            t_end = time.perf_counter()
            
            latency = (t_end - t_start) * 1000
            print(f"   [Benchmark] 延迟: {latency:.4f} ms")
            
            if latency < 3.0: is_ssd = True
            try: os.remove(test_file); os.rmdir(test_dir)
            except: pass
        except: pass

    drive_type_cache[drive_letter] = is_ssd
    print(f"[*] 最终判定 {drive_letter} 为: {'SSD' if is_ssd else 'HDD'}")
    return is_ssd

# === 核心：统一智能选盘算法 (修复版：源盘扣分策略) ===
def find_best_cache_drive(source_drive_letter=None):
    # 获取所有可用盘符 (A-Z)
    drives = [f"{chr(i)}:\\" for i in range(65, 91) if os.path.exists(f"{chr(i)}:\\")]
    
    candidates = [] # 格式: (分数, 剩余空间, 路径)
    
    for root in drives:
        d_letter = os.path.splitdrive(root)[0].upper()
        
        try:
            # 2. 空间检查 (至少预留 15GB)
            usage = shutil.disk_usage(root)
            free_gb = usage.free / (1024**3)
            if free_gb < 15: continue
            
            # 3. 评分系统
            score = 0
            is_system = (d_letter == "C:")
            is_ssd_detected = is_drive_ssd(root)
            
            # 规则A: 只要不是系统盘，基础分 +100 (保护C盘)
            if not is_system: 
                score += 100
            
            # 规则B: 如果检测到是SSD，额外 +50 (尽管现在检测不到，但这行留着无害)
            if is_ssd_detected:
                score += 50
            
            # 规则C: 系统盘如果是SSD，也给点分 (作为最后的保底)
            if is_system and is_ssd_detected:
                score += 10
            
            # [新功能] 规则D: 如果是源素材所在的盘，扣 50 分
            # 这样既不会完全禁用它（防止没盘可用），又能让脚本优先选别的盘
            if source_drive_letter and d_letter == source_drive_letter.upper():
                score -= 50
                
            candidates.append((score, usage.free, root))
        except: pass
    
    # 4. 竞价排名: 先比分数(高优先)，分数相同比剩余空间(大优先)
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    
    if candidates:
        # 返回冠军盘符
        return candidates[0][2]
    else:
        # 实在没得选，只能回退到 C 盘
        return "C:\\"

def get_force_ssd_dir():
    # 启动时还不知道源文件在哪，所以不扣分，直接找最好的盘显示给用户看
    best_root = find_best_cache_drive(source_drive_letter=None)
    path = os.path.join(best_root, "_Ultra_Smart_Cache_")
    os.makedirs(path, exist_ok=True)
    return path

# === 组件定义 ===
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = []
        self.display_max = 10.0  # 当前显示的Y轴上限 (用于动画)
        self.target_max = 10.0   # 目标的Y轴上限
        self.bind("<Configure>", lambda e: self.draw())
        # 启动独立渲染循环 (60FPS)
        self.animate_loop()

    def add_point(self, val):
        self.points.append(val)
        if len(self.points) > 100: self.points.pop(0)
        # 不再直接调用 draw，而是更新目标值，让 animate_loop 去追赶
        current_data_max = max(self.points) if self.points else 10
        self.target_max = max(current_data_max, 10) * 1.2  # 留出20%顶部余量

    def animate_loop(self):
        if self.winfo_exists():
            # === 核心算法：缓动插值 (Lerp) ===
            # 让显示值每次只向目标值移动 10% 的距离 -> 形成丝滑的减速效果
            diff = self.target_max - self.display_max
            if abs(diff) > 0.1:
                self.display_max += diff * 0.1  # 0.1 是阻尼系数，越小越顺滑
                self.draw() # 只有数值变化时才重绘
            
            # 保持约 60FPS 的刷新率
            self.after(16, self.animate_loop)

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10 or not self.points: return

        # 使用平滑过渡后的 display_max 进行绘图
        scale_y = (h - 20) / self.display_max
        
        # 画虚线中轴
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
            # width=2, smooth=True 是关键
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True, capstyle="round", joinstyle="round")

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
        
        # [修改] 将 Label 赋值给 self.lbl_index 以便后续修改
        self.lbl_index = ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 20), text_color="#555")
        self.lbl_index.grid(row=0, column=0, rowspan=2, padx=15)
        
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), text_color="#EEE", anchor="w").grid(row=0, column=1, sticky="w", padx=5, pady=(8,0))
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,8))
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    # [新增] 用于更新序号的方法
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

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    # [新增] 自动滚动到指定任务卡片
    def scroll_to_card(self, widget):
        """修复后的自动滚动逻辑"""
        try:
            # 1. 强制刷新布局，确保坐标是最新的
            self.scroll.update_idletasks()
            
            # 2. 获取目标控件相对于滚动列表顶部的 Y 坐标
            # widget.winfo_y() 获取的是在 parent 里的位置
            item_y = widget.winfo_y()
            item_height = widget.winfo_height()
            
            # 3. 获取滚动区域的总高度
            # self.scroll.winfo_children()[0] 通常是那个被拉长的内部 Frame
            inner_frame = self.scroll.winfo_children()[0]
            total_height = inner_frame.winfo_height()
            
            # 4. 获取可视窗口的高度
            view_height = self.scroll.winfo_height()
            
            if total_height > view_height and total_height > 0:
                # 5. 计算目标位置 (将卡片置于视口约 20% - 30% 的位置，视觉上最舒适)
                # 如果 item_y 很小（刚开始），target_pos 会是 0
                target_pos = (item_y - view_height * 0.25) / (total_height - view_height)
                
                # 限制在 0.0 到 1.0 之间
                target_pos = max(0.0, min(1.0, target_pos))
                
                # 6. 执行滚动
                self.scroll._parent_canvas.yview_moveto(target_pos)
        except Exception as e: 
            print(f"Scroll Fix Error: {e}")
    
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder") # 中文标题
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
        self.temp_files = set()
        
        self.setup_ui()
        # 【新增】全局防降速
        disable_power_throttling() # 对主界面
        set_execution_state(True)  # 阻止系统休眠
        
        self.after(200, self.sys_check)
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    # === 新增：颜色插值动画函数 ===
    def animate_text_change(self, button, new_text, new_fg_color=None):
        """让按钮文字通过 淡出 -> 切换 -> 淡入 实现丝滑过渡"""
        
        # 1. 定义颜色转换工具
        def hex_to_rgb(hex_col):
            hex_col = hex_col.lstrip('#')
            return tuple(int(hex_col[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(rgb):
            return '#%02x%02x%02x' % (int(rgb[0]), int(rgb[1]), int(rgb[2]))

        # 获取当前文字颜色 (默认黑色或配置色) 和 背景色 (模拟透明)
        start_hex = button._text_color if hasattr(button, '_text_color') else "#000000"
        if isinstance(start_hex, list) or isinstance(start_hex, tuple): start_hex = start_hex[1] # 取暗色模式颜色
        
        bg_hex = COLOR_ACCENT # 按钮当前的背景色，用于融合
        target_text_hex = "#000000" # 最终文字颜色
        
        # 动画步骤
        steps = 10
        delay = 15 # ms

        # 第一阶段：淡出 (文字色 -> 背景色)
        c1 = hex_to_rgb(start_hex)
        c2 = hex_to_rgb(bg_hex)
        
        def fade_out(step):
            if step <= steps:
                r = c1[0] + (c2[0] - c1[0]) * (step / steps)
                g = c1[1] + (c2[1] - c1[1]) * (step / steps)
                b = c1[2] + (c2[2] - c1[2]) * (step / steps)
                try: button.configure(text_color=rgb_to_hex((r,g,b)))
                except: pass
                self.after(delay, lambda: fade_out(step + 1))
            else:
                # 切换文字和颜色
                button.configure(text=new_text)
                if new_fg_color: button.configure(fg_color=new_fg_color)
                # 开始淡入
                fade_in(0)

        # 第二阶段：淡入 (背景色 -> 目标文字色)
        def fade_in(step):
            if step <= steps:
                r = c2[0] + (c1[0] - c2[0]) * (step / steps)
                g = c2[1] + (c1[1] - c2[1]) * (step / steps)
                b = c2[2] + (c1[2] - c2[2]) * (step / steps)
                try: button.configure(text_color=rgb_to_hex((r,g,b)))
                except: pass
                self.after(delay, lambda: fade_in(step + 1))
        
        fade_out(0)

    def drop_file(self, event):
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    def add_list(self, files):
        with self.queue_lock:
            # 1. 先将新文件加入队列和字典
            new_added = False
            for f in files:
                if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts', '.flv')):
                    self.file_queue.append(f)
                    # 创建卡片 (序号先填0，稍后统一刷新)
                    if f not in self.task_widgets:
                        card = TaskCard(self.scroll, 0, f) 
                        self.task_widgets[f] = card
                    new_added = True
            
            if not new_added: return

            # 2. [核心功能] 按照文件大小排序 (从小到大)
            # 辅助函数：获取文件大小 (字节)
            def get_file_size(path):
                try: return os.path.getsize(path)
                except: return float('inf') # 如果读取失败，放到最后
            
            # 对 file_queue 进行原地排序
            self.file_queue.sort(key=get_file_size)

            # 3. 刷新 UI 列表顺序
            for i, f in enumerate(self.file_queue):
                if f in self.task_widgets:
                    card = self.task_widgets[f]
                    # 先解绑 (从界面移除但保留实例)，再重新 Pack (按新顺序添加)
                    card.pack_forget()
                    card.pack(fill="x", pady=4)
                    # 更新左侧序号 (i+1)
                    card.update_index(i + 1)

    def apply_system_priority(self, level):
        mapping = {"常规": PRIORITY_NORMAL, "优先": PRIORITY_ABOVE, "极速": PRIORITY_HIGH}
        p_val = mapping.get(level, PRIORITY_ABOVE)
        
        # 1. 修改主程序 (UI) 优先级
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, p_val)
            ctypes.windll.kernel32.CloseHandle(handle)
        except: pass

        # 2. 实时遍历并修改所有正在运行的 FFmpeg 子进程
        count = 0
        for proc in self.active_procs:
            if proc.poll() is None: # 确保进程还在运行
                try:
                    # 获取子进程句柄并设置优先级
                    h_sub = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, proc.pid)
                    if h_sub:
                        ctypes.windll.kernel32.SetPriorityClass(h_sub, p_val)
                        ctypes.windll.kernel32.CloseHandle(h_sub)
                        count += 1
                except: pass
        
        # 状态栏反馈
        if count > 0:
            self.set_status_bar(f"优先级: {level} (已实时应用到 {count} 个任务)")
        else:
            self.set_status_bar(f"系统优先级: {level} (将应用于新任务)")
    
    def on_closing(self):
        if self.running:
            if not messagebox.askokcancel("退出", "任务正在进行中，确定要退出？"): return
        self.stop_flag = True
        self.running = False
        self.executor.shutdown(wait=False)
        self.kill_all_procs()
        self.clean_junk()
        self.destroy()
        set_execution_state(False) # 【新增】恢复系统休眠策略
        self.stop_flag = True
        os._exit(0)
        
    def kill_all_procs(self):
        for p in self.active_procs:
            try: 
                p.terminate()
                p.kill()
            except: pass
        try:
            subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], creationflags=subprocess.CREATE_NO_WINDOW)
        except: pass

    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("错误", "找不到 FFmpeg！请确保已安装并添加到系统 PATH。")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.smart_preload_worker, daemon=True).start()
        self.update_monitor_layout()

    def scan_disk(self):
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"缓存池: {path}"))

    def set_status_bar(self, text):
        pass # [修改] 界面元素已移除，此函数不再执行任何操作

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=320) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=320)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=20, pady=(25, 10))
        # [修改] 仅保留主标题
        ctk.CTkLabel(l_head, text="ULTRA ENCODER", font=("Impact", 26), text_color="#FFF").pack(anchor="w")
        
        self.btn_cache = ctk.CTkButton(left, text="正在检测磁盘...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, command=self.open_cache)
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
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265"], variable=self.codec_var, selected_color=COLOR_ACCENT, corner_radius=10)
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
        # [修改] 删除了右侧状态栏文字
        
        self.monitor_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 25))

    def update_monitor_layout(self, val=None):
        if self.running:
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
        
        # 1. 优先 SSD 直读检测
        is_ssd = is_drive_ssd(src_path)
        if is_ssd:
            self.after(0, lambda: [widget.set_status("就绪 (SSD直读)", COLOR_DIRECT, STATUS_READY)])
            widget.source_mode = "DIRECT"
            return True

        # 2. RAM 缓存逻辑 (带进度条修复版)
        free_ram = get_free_ram_gb()
        available_for_cache = free_ram - SAFE_RAM_RESERVE

        if available_for_cache > file_size_gb and file_size_gb < MAX_RAM_LOAD_GB:
            self.after(0, lambda: [widget.set_status("📥 载入内存中...", COLOR_RAM, STATUS_CACHING), widget.set_progress(0, COLOR_RAM)])
            try:
                # 分块读取，每读 64MB 更新一次进度
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
                            self.after(0, lambda p=prog: widget.set_progress(p, COLOR_READING))
                
                widget.ram_data = bytes(data_buffer) 
                # [已应用新颜色] 薄荷绿状态
                self.after(0, lambda: [widget.set_status("就绪 (内存加速)", COLOR_READY_RAM, STATUS_READY), widget.set_progress(1, COLOR_READY_RAM)])
                widget.source_mode = "RAM"
                return True
            except Exception as e: 
                print(f"RAM Load Failed: {e}")
                widget.clean_memory()

        # 3. SSD 缓存逻辑
        self.after(0, lambda: [widget.set_status("📥 写入缓存...", COLOR_SSD_CACHE, STATUS_CACHING), widget.set_progress(0, COLOR_SSD_CACHE)])
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
                            self.after(0, lambda p=copied/file_size: widget.set_progress(p, COLOR_SSD_CACHE))
            self.temp_files.add(cache_path)
            widget.ssd_cache_path = cache_path
            widget.source_mode = "SSD_CACHE"
            self.after(0, lambda: [widget.set_status("就绪 (缓存加速)", COLOR_SSD_CACHE, STATUS_READY), widget.set_progress(1, COLOR_SSD_CACHE)])
            return True
        except:
            self.after(0, lambda: widget.set_status("缓存失败", COLOR_ERROR, STATUS_ERR))
            return False

    def smart_preload_worker(self):
        while True:
            free = get_free_ram_gb()
            self.after(0, lambda f=free: self.btn_ram.configure(text=f"空闲内存: {f:.1f} GB"))
            
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
            self.after(0, lambda: messagebox.showinfo("完成", "所有任务已处理完毕！"))
        self.running = False
        self.after(0, self.reset_ui_state)

    def process(self, input_file):
        if self.stop_flag: return
        
        # === 1. 获取线程槽位 ===
        my_slot_idx = None
        while my_slot_idx is None and not self.stop_flag:
            with self.slot_lock:
                if self.available_indices: my_slot_idx = self.available_indices.pop(0)
            if my_slot_idx is None: time.sleep(0.1)
        if self.stop_flag: return

        card = self.task_widgets[input_file]
        ch_ui = self.monitor_slots[my_slot_idx]
        
        # [功能] 自动滚动到当前任务
        self.after(0, lambda: self.scroll_to_card(card))
        
        # 等待缓存完成
        while card.status_code == STATUS_CACHING and not self.stop_flag: 
            time.sleep(0.5)

        # 确保缓存逻辑执行
        if card.source_mode == "PENDING":
            self.read_lock.acquire()
            try:
                if card.source_mode == "PENDING" and not self.stop_flag:
                   self.process_caching(input_file, card)
            finally:
                self.read_lock.release()
        
        if self.stop_flag: 
            with self.slot_lock: self.available_indices.append(my_slot_idx); self.available_indices.sort()
            return

        # === 2. 准备阶段 ===
        max_retries = 1 
        current_try = 0
        success = False
        output_log = []
        ram_server = None 
        
        # [核心] 磁盘智能选择 (应用扣分策略)
        fname = os.path.basename(input_file)
        name, ext = os.path.splitext(fname)
        codec_sel = self.codec_var.get()
        suffix = "_H265" if "H.265" in codec_sel else "_H264"
        final_target_file = os.path.join(os.path.dirname(input_file), f"{name}{suffix}{ext}")
        
        # 获取源文件所在盘符 (例如 "D:")
        src_drive = os.path.splitdrive(os.path.abspath(input_file))[0].upper()
        
        # 调用核心算法寻找最佳缓存盘 (传入源盘符以进行扣分)
        best_cache_root = find_best_cache_drive(source_drive_letter=src_drive)
        best_cache_dir = os.path.join(best_cache_root, "_Ultra_Smart_Cache_")
        os.makedirs(best_cache_dir, exist_ok=True)
        
        # [UI] 实时更新显示的缓存池位置，让您看到它选了哪个盘
        self.after(0, lambda: self.btn_cache.configure(text=f"缓存池: {best_cache_dir}"))
        
        # 确定临时文件路径 (强制走缓存，分离IO)
        temp_name = f"TEMP_{int(time.time())}_{name}{suffix}{ext}"
        working_output_file = os.path.join(best_cache_dir, temp_name)
        need_move_back = True

        # === 3. 压制循环 ===
        while current_try <= max_retries and not self.stop_flag:
            output_log.clear()
            using_gpu = self.gpu_var.get()
            mode_label = {"DIRECT": "SSD直读", "RAM": "内存加速", "SSD_CACHE": "缓存加速"}.get(card.source_mode, "未知")
            
            # [UI] 状态文案
            status_text = f"▶️ 压制中 ({mode_label})"
            if current_try > 0: status_text = f"⚠️ 重试中 (CPU)..."
            
            self.after(0, lambda: [card.set_status(status_text, COLOR_ACCENT, STATUS_RUN), card.set_progress(0, COLOR_ACCENT)])
            
            tag = "HEVC" if "H.265" in codec_sel else "AVC"
            gpu_flag = "NVENC" if using_gpu else "CPU"
            self.after(0, lambda: ch_ui.activate(fname, f"{tag} | {gpu_flag}"))
            
            # 构建输入源
            input_arg = input_file
            if card.source_mode == "RAM":
                try:
                    if not ram_server:
                        ram_server, port, _ = start_ram_server(card.ram_data)
                    input_arg = f"http://127.0.0.1:{port}/video{ext}"
                    print(f"Memory Streaming at: {input_arg}")
                except Exception as e:
                    print(f"Server Error: {e}")
                    card.source_mode = "DIRECT"
                    input_arg = input_file
            elif card.source_mode == "SSD_CACHE": 
                input_arg = card.ssd_cache_path
            
            # 构建命令
            v_codec = "hevc_nvenc" if "H.265" in codec_sel else "h264_nvenc"
            if not using_gpu: v_codec = "libx265" if "H.265" in codec_sel else "libx264"
            
            cmd = ["ffmpeg", "-y", "-i", input_arg, "-c:v", v_codec]
            
            if using_gpu:
                cmd.extend(["-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(self.crf_var.get()), 
                            "-preset", "p6", "-b:v", "0"])
            else:
                cmd.extend(["-crf", str(self.crf_var.get()), "-preset", "medium"])
            
            # 关键参数: 机器可读进度日志
            cmd.extend(["-c:a", "copy", "-progress", "pipe:1", "-nostats", working_output_file])
            
            dur_file = input_file 
            duration = self.get_dur(dur_file)
            
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, startupinfo=si)
            self.active_procs.append(proc)
            
            # 尝试应用优先级
            try:
                # 1. 设置优先级 (原代码已有，保留)
                p_val = {"常规": PRIORITY_NORMAL, "优先": PRIORITY_ABOVE, "极速": PRIORITY_HIGH}.get(self.priority_var.get(), PRIORITY_ABOVE)
                h_sub = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, proc.pid)
                if h_sub:
                    ctypes.windll.kernel32.SetPriorityClass(h_sub, p_val)
                    
                    # 2. 【新增】强制对 FFmpeg 子进程关闭电源节流/效率模式
                    disable_power_throttling(h_sub)
                    
                    ctypes.windll.kernel32.CloseHandle(h_sub)
            except: pass

            start_t = time.time()
            last_upd = 0
            
            # 日志解析
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
                                us = int(value)
                                current_sec = us / 1000000.0
                                if duration > 0:
                                    prog = current_sec / duration
                                    if time.time() - last_upd > 0.1:
                                        elap = time.time() - start_t
                                        eta_sec = (elap / prog - elap) if prog > 0.01 else 0
                                        eta = f"{int(eta_sec//60):02d}:{int(eta_sec%60):02d}"
                                        self.after(0, lambda p=prog: card.set_progress(p, COLOR_ACCENT))
                                        self.after(0, lambda f=current_fps, p=prog, e=eta: ch_ui.update_data(f, p, e))
                                        last_upd = time.time()
                            except: pass
                except: continue
            
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)
            
            # 停止检查
            if self.stop_flag: 
                if ram_server: ram_server.shutdown(); ram_server.server_close()
                card.clean_memory()
                if need_move_back and os.path.exists(working_output_file):
                    try: os.remove(working_output_file)
                    except: pass
                with self.slot_lock: self.available_indices.append(my_slot_idx); self.available_indices.sort()
                return 

            # 成功判定
            if proc.returncode == 0:
                if os.path.exists(working_output_file) and os.path.getsize(working_output_file) > 500*1024:
                    success = True
                    break 
                else:
                    output_log.append(f"[System Error] File too small: {working_output_file}")
            
            # 自动降级重试 (GPU -> CPU)
            if not success and using_gpu and current_try < max_retries:
                output_log.append("[Auto-Fix] GPU failed. Switching to CPU.")
                self.gpu_var.set(False)
                current_try += 1
                time.sleep(1)
                if os.path.exists(working_output_file):
                    try: os.remove(working_output_file)
                    except: pass
                continue
            else:
                break 

        # === 4. 收尾阶段 ===
        if ram_server: ram_server.shutdown(); ram_server.server_close()

        # 搬运回写 (Move Back)
        if success and need_move_back:
            try:
                self.after(0, lambda: card.set_status("📦 回写硬盘中...", COLOR_MOVING, STATUS_RUN))
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
        
        self.after(0, ch_ui.reset)
        with self.slot_lock: self.available_indices.append(my_slot_idx); self.available_indices.sort()
        
        # 最终状态更新
        if success:
             orig_sz = os.path.getsize(input_file)
             if os.path.exists(final_target_file):
                 new_sz = os.path.getsize(final_target_file)
                 sv = 100 - (new_sz/orig_sz*100) if orig_sz > 0 else 0
                 self.after(0, lambda: [card.set_status(f"完成 | 压缩率: {sv:.1f}%", COLOR_SUCCESS, STATUS_DONE), card.set_progress(1, COLOR_SUCCESS)])
             else:
                 self.after(0, lambda: card.set_status("文件丢失", COLOR_ERROR, STATUS_ERR))
        else:
             if not self.stop_flag:
                 self.after(0, lambda: card.set_status("失败 (点击看日志)", COLOR_ERROR, STATUS_ERR))
                 err_msg = "\n".join(output_log[-30:]) 
                 def show_err():
                     messagebox.showerror(f"任务失败: {fname}", f"FFmpeg 报错日志 (最后30行):\n\n{err_msg}")
                 self.after(0, show_err)

        with self.queue_lock:
            if input_file in self.submitted_tasks: self.submitted_tasks.remove(input_file)

    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        
        # === 修改：使用丝滑动画切换文字 ===
        # 原代码: self.btn_run.configure(state="disabled", text="引擎运行中...")
        self.btn_run.configure(state="disabled") # 先禁用防止连点
        self.animate_text_change(self.btn_run, "▶ 压制进行中...") 
        
        self.btn_stop.configure(state="normal")
        self.update_monitor_layout()
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

    def open_cache(self):
        if self.temp_dir: os.startfile(self.temp_dir)
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
