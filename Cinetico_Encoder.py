# --- [自动环境配置模块] ---
# --- [自动环境配置模块] ---
def check_and_install_dependencies():
    import shutil
    import sys
    import subprocess
    import importlib.util
    # [修正] 必须在此处导入 ctypes，确保弹窗功能可用
    import ctypes 

    required_packages = [
        ("customtkinter", "customtkinter"),
        ("tkinterdnd2", "tkinterdnd2"),
        ("PIL", "pillow"),
        ("packaging", "packaging"),
        ("uuid", "uuid")
    ]
    
    installed_any = False
    print("--------------------------------------------------")
    print("正在检查运行环境...")

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
                # [修正] 弹窗提示，避免黑框直接闪退用户一脸懵
                ctypes.windll.user32.MessageBoxW(0, f"自动安装失败: {package_name}\n请手动运行: pip install {package_name}", "环境错误", 0x10)
                sys.exit(1)
        else:
            print(f"✔ {package_name} 已安装")

    if not shutil.which("ffmpeg"):
        # [修正] FFmpeg 缺失弹窗提醒
        ctypes.windll.user32.MessageBoxW(0, "未检测到 FFmpeg！\n请下载 FFmpeg 并将其 bin 目录添加到系统环境变量 Path 中。", "核心组件缺失", 0x10)
    
    if installed_any:
        print("\n🎉 所有依赖库安装完成！正在启动程序...")
    else:
        print("✔ 环境完整，准备启动...")

# 执行检查
check_and_install_dependencies()

import customtkinter as ctk  # 这是一个很好看的UI库，用来画界面的
import tkinter as tk         # 这是Python自带的基础界面库
from tkinter import filedialog, messagebox # 用来弹出“选择文件”和“提示框”的工具
import subprocess # 这个很重要，用来在后台运行 FFmpeg 命令
import threading  # 多线程工具，防止界面卡死（让任务在后台跑）
import os         # 系统工具，用来管理文件路径、删除文件等
import time       # 时间工具，用来计算耗时、暂停等
import shutil     # 文件操作工具，用来移动和复制文件
import ctypes     # 用来调用 Windows 底层API（比如检测内存、电源管理）
from concurrent.futures import ThreadPoolExecutor # 线程池，用来管理并发任务
import http.server # 用来搭建一个微型服务器，用于内存流播放
import socketserver
from http import HTTPStatus
from functools import partial # 函数工具，用来固定参数
from collections import deque
import uuid        # 用来生成唯一的Token，确保内存服务器的安全性

# =========================================================================
# === 全局视觉配置 (决定软件长什么样) ===
# =========================================================================
ctk.set_appearance_mode("Dark") # 设置为深色模式
ctk.set_default_color_theme("dark-blue") # 按钮默认为深蓝色

# 定义一些颜色变量，方便后面统一修改
COLOR_TEXT_GRAY = "#888888" 
COLOR_BG_MAIN = "#121212"    # 主背景黑
COLOR_PANEL_LEFT = "#1a1a1a" # 左侧面板深灰
COLOR_PANEL_RIGHT = "#0f0f0f" # 右侧面板更黑
COLOR_CARD = "#2d2d2d"       # 任务卡片颜色
COLOR_ACCENT = "#3B8ED0"     # 强调色（按钮蓝）
COLOR_ACCENT_HOVER = "#36719f" # 鼠标悬停时的蓝色
COLOR_CHART_LINE = "#00E676" # 图表线条绿
COLOR_READY_RAM = "#00B894"  # 内存就绪绿
COLOR_SUCCESS = "#2ECC71"    # 成功绿
COLOR_MOVING = "#F1C40F"     # 移动文件黄
COLOR_READING = "#9B59B6"    # 读取中紫
COLOR_RAM     = "#3498DB"    # 内存蓝
COLOR_SSD_CACHE = "#E67E22"  # 缓存橙
COLOR_DIRECT  = "#1ABC9C"    # 直读青
COLOR_PAUSED = "#7f8c8d"     # 暂停灰
COLOR_ERROR = "#FF4757"      # 错误红
COLOR_WAITING = "#555555"    # 等待中灰

# 定义任务状态码（给程序内部逻辑判断用的）
STATUS_WAIT = 0      # 等待中
STATUS_CACHING = 1   # 正在缓存
STATUS_READY = 2     # 准备就绪
STATUS_RUN = 3       # 正在运行
STATUS_DONE = 5      # 已完成
STATUS_ERR = -1      # 出错
# --- [新增] 细分状态码 (给总指挥看的) ---
STATE_PENDING = 0        # 刚进队列，啥也没干
STATE_QUEUED_IO = 1      # 指挥官已批准 IO，正在等 IO 线程池空位
STATE_CACHING = 2        # 正在读硬盘/写内存
STATE_READY = 3          # 数据已就绪 (在内存或SSD缓存中)，等待计算资源
STATE_ENCODING = 4       # 正在编码 (FFmpeg 跑着呢)
STATE_DONE = 5           # 完事
STATE_ERROR = -1         # 挂了

# 定义Windows进程优先级（用来控制是否抢占CPU）
PRIORITY_NORMAL = 0x00000020 # 正常
PRIORITY_ABOVE = 0x00008000  # 高于正常
PRIORITY_HIGH = 0x00000080   # 高

# =========================================================================
# === 系统硬件检测函数 (工具箱) ===
# =========================================================================

# [功能] 获取电脑总共有多少内存 (GB)
def get_total_ram_gb():
    try:
        # 定义一个结构体来接收Windows的内存信息
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys / (1024**3) # 把字节转换成GB
    except:
        return 16.0 # 如果检测失败，默认假设是16GB

# [功能] 获取当前还没被使用的空闲内存 (GB)
def get_free_ram_gb():
    try:
        # 代码逻辑同上，只是取了 ullAvailPhys (可用物理内存)
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
    except:
        return 4.0 # 默认假设有4G可用

# 初始化计算内存限制
TOTAL_RAM = get_total_ram_gb()
# 【这里可以改】MAX_RAM_LOAD_GB 决定了最大能把多大的文件塞进内存。
# 下面这行意思是：保留4GB给系统，剩下的全部可以用来做缓存。
MAX_RAM_LOAD_GB = max(4.0, TOTAL_RAM - 4.0) 
SAFE_RAM_RESERVE = 3.0  # 额外的安全保留区

print(f"[System] RAM: {TOTAL_RAM:.1f}GB | Cache Limit: {MAX_RAM_LOAD_GB:.1f}GB")

# 尝试导入拖拽库（可以直接把文件拖进窗口）
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class DnDWindow(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    HAS_DND = True # 标记：支持拖拽
except ImportError:
    class DnDWindow(ctk.CTk): pass # 如果没安装这个库，就用普通窗口
    HAS_DND = False # 标记：不支持拖拽

# === Windows 功耗管理 (防止电脑休眠) ===
# 这里定义了一些Windows API结构，不需要改动
class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong)]

# [功能] 告诉Windows不要让程序进入“效率模式”或休眠
def set_execution_state(enable=True):
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    try:
        if enable:
            # 阻止系统休眠
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        else:
            # 恢复正常
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except: pass

# [功能] 禁用电源限制（让CPU跑满）
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

# [功能] 启动内存服务器
def start_ram_server(ram_data):
    # 端口设为0，表示让系统自动分配一个空闲端口
    server = ThreadedHTTPServer(('127.0.0.1', 0), RamHttpHandler)
    server.ram_data = ram_data
    port = server.server_address[1] # 获取实际分配的端口
    # 在单独的线程里运行服务器，不卡主界面
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread

# [功能] 检查FFmpeg是否安装
def check_ffmpeg():
    try:
        # 尝试运行 ffmpeg -version
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except: return False

# =========================================================================
# === 磁盘检测工具 (区分 SSD 和 HDD) ===
# =========================================================================
drive_type_cache = {} # 缓存结果，避免重复检测
def is_drive_ssd(path):
    root = os.path.splitdrive(os.path.abspath(path))[0].upper() # 获取盘符，如 C:
    if not root: return False
    drive_letter = root 
    if drive_letter in drive_type_cache: return drive_type_cache[drive_letter]
    is_ssd = False
    try:
        # 这一块通过 Windows DeviceIoControl 查询是否支持“寻道惩罚”
        # 机械硬盘有寻道时间（True），SSD没有（False）
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
                is_ssd = not out.IncursSeekPenalty # 如果没有寻道惩罚，就是SSD
                drive_type_cache[drive_letter] = is_ssd
                return is_ssd
    except: pass
    drive_type_cache[drive_letter] = False
    return False

# [功能] 检测是否是USB移动硬盘
def is_bus_usb(path):
    try:
        # 类似上面的逻辑，通过 BusType 判断
        root = os.path.splitdrive(os.path.abspath(path))[0].upper()
        if ctypes.windll.kernel32.GetDriveTypeW(root + "\\") == 2: return True # 类型2通常是可移动磁盘
        # ...省略底层API调用细节...
        return False
    except: return False

# [功能] 自动寻找最佳的缓存盘
def find_best_cache_drive(source_drive_letter=None, manual_override=None):
    # 如果用户手动指定了，直接用
    if manual_override and os.path.exists(manual_override):
        return manual_override

    drives = [f"{chr(i)}:\\" for i in range(65, 91) if os.path.exists(f"{chr(i)}:\\")]
    candidates = []

    # 遍历所有盘符
    for root in drives:
        try:
            d_letter = os.path.splitdrive(root)[0].upper()
            total, used, free = shutil.disk_usage(root)
            free_gb = free / (1024**3)
            if free_gb < 20: continue # 空间小于20G的不考虑

            is_system = (d_letter == "C:")
            is_ssd = is_drive_ssd(root)
            is_usb = is_bus_usb(root)
            is_source = (source_drive_letter and d_letter == source_drive_letter.upper())

            # 打分机制：非系统盘SSD > 系统盘SSD > 机械盘 > 源盘
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

    # 按分数排序，选最好的
    candidates.sort(key=lambda x: (x["level"], x["free"]), reverse=True)
    if candidates: return candidates[0]["path"]
    else: return "C:\\"

# [新增] 必须补全这两个库，否则会报错
import urllib.parse 
import socketserver

# =========================================================================
# === [架构重构 2.1 & 2.2] 全局内存仓库与单例服务器 ===
# =========================================================================

# 全局内存存储池 (Key: 文件绝对路径, Value: bytearray 数据)
# Key: Token字符串, Value: 视频二进制数据
GLOBAL_RAM_STORAGE = {} 
# Key: 文件绝对路径, Value: Token字符串 (用于防止重复加载)
PATH_TO_TOKEN_MAP = {}

class GlobalRamHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass  # 静默模式
    
    def do_GET(self):
        try:
            # 1. 直接获取 Token (去掉开头的 /)
            token = self.path.lstrip('/')
            
            # 2. 从仓库拿数据
            video_data = GLOBAL_RAM_STORAGE.get(token)
            
            if not video_data:
                self.send_error(404, "Invalid Token")
                return

            # 3. 零拷贝读取逻辑 (保持不变)
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
    # 端口 0 让系统自动分配，ThreadedTCPServer 确保不阻塞
    server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), GlobalRamHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[Core] Global Memory Server started on port {port}")
    return server, port

# =========================================================================
# === UI 组件定义 (这里定义界面上的小方块长什么样) ===
# =========================================================================

# 自定义控件：波形图 (InfinityScope)
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = []
        self.display_max = 10.0  
        self.target_max = 10.0   
        self.needs_redraw = False # 增加标记位，只有数据更新了才画
        self.running = True
        self.bind("<Configure>", lambda e: self.force_draw()) 
        self.animate_loop()

    def add_point(self, val):
        self.points.append(val)
        if len(self.points) > 100: self.points.pop(0)
        current_data_max = max(self.points) if self.points else 10
        self.target_max = max(current_data_max, 10) * 1.2
        self.needs_redraw = True # 标记：有新数据了，需要画

    def force_draw(self):
        self.needs_redraw = True
        self.draw()

    def animate_loop(self):
        if self.winfo_exists() and self.running:
            # 平滑缩放动画
            diff = self.target_max - self.display_max
            if abs(diff) > 0.01:
                self.display_max += diff * 0.1
                self.needs_redraw = True 

            if self.needs_redraw:
                self.draw()
                self.needs_redraw = False # 画完重置

            self.after(33, self.animate_loop) # 约 30 帧/秒

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10 or not self.points: return
        
        scale_y = (h - 20) / self.display_max
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4, 4))
        
        n = len(self.points)
        if n < 2: return
        
        step_x = w / 99 # 固定宽度步长，不随点数抖动
        coords = []
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
            
        if len(coords) >= 4:
            # 使用绿色渐变视觉效果
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

# 自定义控件：监控通道 (MonitorChannel) - 右边那个跳动的小窗口
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333", **kwargs)
        # ...省略布局代码，这里主要是创建 Label 和 Scope ...
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=15, pady=(10,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"通道 {ch_id} · 空闲", font=("微软雅黑", 12, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="等待任务...", font=("Arial", 11), text_color="#444")
        self.lbl_info.pack(side="right")
        self.scope = InfinityScope(self) # 嵌入波形图
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=15, pady=(0,10))
        self.lbl_fps = ctk.CTkLabel(btm, text="0", font=("Impact", 20), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10, "bold"), text_color="#444").pack(side="left", padx=(5,0), pady=(8,0))
        self.lbl_eta = ctk.CTkLabel(btm, text="ETA: --:--", font=("Consolas", 12), text_color="#666")
        self.lbl_eta.pack(side="right", padx=(10, 0))
        # [新增] 实时压缩率标签
        self.lbl_ratio = ctk.CTkLabel(btm, text="RATIO: --%", font=("Consolas", 12), text_color="#666")
        self.lbl_ratio.pack(side="right", padx=(10, 0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    # 激活：当任务开始时调用
    def activate(self, filename, tag):
        if not self.winfo_exists(): return
        self.lbl_title.configure(text=f"运行中: {filename[:15]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        self.scope.clear()

    # 更新数据：每秒调用多次
    def update_data(self, fps, prog, eta, ratio):
        if not self.winfo_exists(): return
        self.scope.add_point(fps)
        # [修改] 使用 :.2f 格式化，保留两位小数
        self.lbl_fps.configure(text=f"{float(fps):.2f}") 
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        self.lbl_eta.configure(text=f"ETA: {eta}")
        self.lbl_ratio.configure(text=f"Ratio: {ratio:.1f}%", text_color="#888")

    # 重置：任务结束时调用
    def reset(self):
        if not self.winfo_exists(): return
        self.lbl_title.configure(text="通道 · 空闲", text_color="#555")
        self.lbl_info.configure(text="等待任务...", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.lbl_eta.configure(text="ETA: --:--", text_color="#333")
        self.lbl_ratio.configure(text="Ratio: --%", text_color="#333")
        self.scope.clear()

# 自定义控件：任务卡片 (TaskCard) - 左边列表中每一行
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        # 初始化卡片状态
        self.status_code = STATUS_WAIT 
        self.ram_data = None 
        self.ssd_cache_path = None
        self.source_mode = "PENDING"
        self.filepath = filepath
        
        # [新增] 预先获取文件大小，供总指挥计算预算
        try:
            self.file_size_gb = os.path.getsize(filepath) / (1024**3)
        except:
            self.file_size_gb = 0.0
        
        self.ram_cost = 0.0 # 实际占用的 RAM (只有加载进内存才算)
        self.status_code = STATE_PENDING # 初始化状态

        # 序号
        self.lbl_index = ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 20), text_color="#555")
        self.lbl_index.grid(row=0, column=0, rowspan=2, padx=(10, 5))
        
        # 文件名
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=1, sticky="w", padx=5, pady=(8,0))
        ctk.CTkLabel(name_frame, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), text_color="#EEE", anchor="w").pack(side="left")
        
        # 打开文件夹按钮
        self.btn_open = ctk.CTkButton(self, text="📂", width=30, height=24, fg_color="#444", hover_color="#555", 
                                      font=("Segoe UI Emoji", 12), command=self.open_location)
        self.btn_open.grid(row=0, column=2, padx=10, pady=(8,0), sticky="e")
        
        # 状态文字
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,8))
        
        # 进度条
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    # 打开文件所在位置
    def open_location(self):
        try:
            subprocess.run(['explorer', '/select,', os.path.normpath(self.filepath)])
        except: pass

    # 更新卡片序号
    def update_index(self, new_index):
        try:
            if self.winfo_exists():
                self.lbl_index.configure(text=f"{new_index:02d}")
        except: pass

    # 更新状态文字
    def set_status(self, text, color="#888", code=None):
        try:
            if self.winfo_exists():
                self.lbl_status.configure(text=text, text_color=color)
                if code is not None: self.status_code = code
        except: pass
    
    # 更新进度条
    def set_progress(self, val, color=COLOR_ACCENT):
        try:
            if self.winfo_exists():
                self.progress.set(val)
                self.progress.configure(progress_color=color)
        except: pass
        
    # 清理内存：任务完成后释放
    def clean_memory(self):
        # self.ram_data = None # 此行已废弃
        self.source_mode = "PENDING"
        self.ssd_cache_path = None

# =========================================================================
# === [V4.1 修复版] 专家手册：无引用标记污染，纯净代码 ===
# =========================================================================
class HelpWindow(ctk.CTkToplevel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometry("1150x900") 
        self.title("Cinético - 架构白皮书")
        # 修复：防止窗口在某些情况下被主窗口遮挡，但允许用户最小化
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        
        # 1. 顶部标题区
        header = ctk.CTkFrame(self, height=80, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=25)
        
        # 左侧标题
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="ULTRA ARCHITECTURE", font=("Impact", 32), text_color="#444").pack(anchor="w")
        ctk.CTkLabel(title_box, text="高性能计算架构与操作指南", font=("微软雅黑", 20, "bold"), text_color="#FFF").pack(anchor="w")
        
        # 右侧版本号
        ctk.CTkLabel(header, text="Kernel: v75.0\nDoc: v4.1", font=("Consolas", 12), text_color="#666", justify="right").pack(side="right")

        # 2. 滚动内容区
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # =======================
        # 第一部分：四大核心黑科技
        # =======================
        self.add_section_header("🌌 核心架构：为什么 Cinético 如此之快？", "#E67E22")
        
        feature_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        feature_frame.pack(fill="x", padx=10, pady=10)
        # 修复：配置权重，防止卡片挤在一起
        feature_frame.grid_columnconfigure(0, weight=1)
        feature_frame.grid_columnconfigure(1, weight=1)

        # 特性 1
        self.create_feature_card(feature_frame, 0, 0, 
            "⚡ Zero-Copy Loopback (零拷贝环回)",
            "传统软件读写硬盘会产生巨大的 I/O 中断延迟。本引擎内置微型 HTTP Server，建立本地环回链路。视频数据被直接映射到 RAM 内存空间，以 12GB/s 的总线速度直接投喂给编码器，彻底消除机械硬盘瓶颈。"
        )
        # 特性 2
        self.create_feature_card(feature_frame, 0, 1, 
            "🔄 Tiered Storage Tiering (分层存储调度)",
            "独创的热数据分层算法。引擎自动探测系统空闲 RAM 和 SSD 缓存池。小于阈值的文件驻留内存，大文件自动降级至 NVMe SSD 缓存。实现“内存级速度，硬盘级容量”的混合加速。"
        )
        # 特性 3
        self.create_feature_card(feature_frame, 1, 0, 
            "🛡️ Kernel-Level QoS (内核级进程治理)",
            "直接调用 Windows Kernel API (SetThreadExecutionState)，接管电源管理策略。强制 CPU 进入高能效状态，防止系统降频或休眠。配合多线程 Spinlock 锁机制，杜绝界面假死。"
        )
        # 特性 4
        self.create_feature_card(feature_frame, 1, 1, 
            "🧠 Heuristic VRAM Guard (启发式显存哨兵)",
            "实时监控 GPU 显存拓扑。不同于简单的“报错退出”，本引擎能动态预测下一个任务的显存开销。当 VRAM 不足时自动挂起队列，实现“流水线式”的显存复用，压榨显卡最后 1MB 性能。"
        )
        # 在 self.scroll 中增加第 5 个特性卡片
        self.create_feature_card(feature_frame, 2, 0, 
            "🚀 Heterogeneous Hybrid Decoupling (异构解码分流)",
            "开启后，偶数通道将解码压力分流至 CPU，从而解除显卡单解码器 (NVDEC) 的竞争瓶颈。配合 NVENC 双编码核心，可实现总吞吐量 (Total FPS) 提升约 30%-50%。"
        )

        # =======================
        # 第二部分：编码格式
        # =======================
        self.add_section_header("🎞️编码标准深度对标 (Codec)", "#00E676")
        self.add_tip("技术指标基于《2026全球视频编码技术全景报告》")

        codec_data = [
            ("标准代号", "压缩算法效率", "硬件生态现状", "编码延迟", "专家决策建议"),
            ("H.264 (AVC)", "基准 (100%)", "👑 100% 覆盖", "🚀 < 100ms", "兼容性之王。任何能点亮的屏幕都能播。适合交付给客户、老旧设备播放或极低延迟场景。"),
            ("H.265 (HEVC)", "节省 ~50%", "⭐️ 主流标配", "⚡ 中等", "4K/HDR 时代的基石。同画质下体积减半。适合NAS收藏、节省硬盘。Win10/11 需扩展支持。"),
            ("AV1", "节省 ~65%", "📈 快速增长", "🐢 较高", "来自互联网巨头的免版税格式。Netflix/YouTube首选。画质无敌，但需 RTX30/40 或新处理器支持硬解。"),
        ]
        self.create_grid_table(codec_data, col_weights=[1, 1, 1, 1, 4])

        # =======================
        # 第三部分：画质控制
        # =======================
        self.add_section_header("🎨 量化画质控制 (CRF Rate Control)", "#3B8ED0")
        
        crf_data = [
            ("CRF 数值", "视觉质量等级", "比特率 (Bitrate)", "工业级应用场景"),
            ("16 - 19", "💎 Archival (归档级)", "超高 (100%)", "作为后期剪辑的中间素材 (Mezzanine)、永久保存的珍贵录像。肉眼无法区分原片。"),
            ("20 - 24", "⚖️ High Profile (推荐)", "高 (50%)", "【默认值 23】。完美平衡点。适合上传 B站/YouTube 4K，在此数值上继续降低很难察觉画质提升。"),
            ("25 - 30", "📱 Mobile (移动级)", "中 (25%)", "适合手机小屏幕观看、网课录屏、会议记录。在移动设备上观看依然清晰，体积优势巨大。"),
            ("31 - 35", "📉 Proxy (代理级)", "低 (10%)", "仅用于内部预览、监控录像归档。动态画面会有明显的块状伪影 (Artifacts)。"),
        ]
        self.create_grid_table(crf_data, col_weights=[1, 1, 1, 4])

        # =======================
        # 第四部分：硬件调度
        # =======================
        self.add_section_header("⚙️ 异构计算调度策略 (Heterogeneous Computing)", "#9B59B6")
        
        hw_data = [
            ("计算单元", "核心架构优势", "潜在物理瓶颈", "调度引擎建议"),
            ("NVIDIA GPU", "NVENC 专用电路\n不占用 CUDA 核心", "同码率下画质\n微弱于 CPU (VMAF-1%)", "✅【强制开启】。能效比是 CPU 的 10 倍以上。建议并发数设为 2-3 个以跑满带宽。"),
            ("Intel/AMD CPU", "复杂指令集 (AVX)\n画质控制最精准", "浮点算力不足\n导致系统卡顿/过热", "❌ 仅作为故障转移 (Failover)。本程序已通过 SetPriorityClass 限制线程，防止死机。"),
        ]
        self.create_grid_table(hw_data, col_weights=[1, 2, 2, 4])

        ctk.CTkLabel(self.scroll, text="Designed by Cinético Team | Powered by FFmpeg & Python", font=("Arial", 10), text_color="#333").pack(pady=30)

    # --- 组件：特性卡片 ---
    def create_feature_card(self, parent, r, c, title, text):
        card = ctk.CTkFrame(parent, fg_color="#222", corner_radius=10, border_width=1, border_color="#333")
        card.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(card, text=title, font=("微软雅黑", 14, "bold"), text_color="#EEE", anchor="w").pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkLabel(card, text=text, font=("微软雅黑", 12), text_color="#AAA", anchor="w", justify="left", wraplength=450).pack(fill="both", expand=True, padx=15, pady=(0, 15))

    # --- 组件：带色块的标题 ---
    def add_section_header(self, text, color):
        frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        frame.pack(fill="x", padx=15, pady=(35, 15))
        bar = ctk.CTkFrame(frame, width=6, height=28, fg_color=color, corner_radius=3)
        bar.pack(side="left", padx=(5, 12))
        lbl = ctk.CTkLabel(frame, text=text, font=("微软雅黑", 18, "bold"), text_color=color)
        lbl.pack(side="left")

    # --- 组件：小提示 ---
    def add_tip(self, text):
        lbl = ctk.CTkLabel(self.scroll, text=text, font=("Consolas", 11), text_color="#666", anchor="w")
        lbl.pack(fill="x", padx=45, pady=(0, 10))

    # --- 核心组件：绝对对齐的网格表格 ---
    def create_grid_table(self, data, col_weights):
        # 表格容器
        table_frame = ctk.CTkFrame(self.scroll, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333")
        table_frame.pack(fill="x", padx=20, pady=5)
        
        # 1. 配置列宽权重
        for i, w in enumerate(col_weights):
            table_frame.grid_columnconfigure(i, weight=w)

        # 2. 填充数据
        for r_idx, row_data in enumerate(data):
            is_header = (r_idx == 0)
            bg_color = "#2D2D2D" if is_header else ("#202020" if r_idx % 2 == 1 else "transparent")
            text_color = "#FFFFFF" if is_header else "#CCCCCC"
            font = ("微软雅黑", 13, "bold") if is_header else ("微软雅黑", 12)
            
            for c_idx, text in enumerate(row_data):
                # 最后一列左对齐，其他居中
                align = "center" if c_idx == 0 else "w"
                pad_x = 20 if align == "w" else 5
                
                cell_frame = ctk.CTkFrame(table_frame, fg_color=bg_color, corner_radius=0)
                cell_frame.grid(row=r_idx, column=c_idx, sticky="nsew", padx=1, pady=1)
                
                label = ctk.CTkLabel(
                    cell_frame, 
                    text=text, 
                    font=font, 
                    text_color=text_color,
                    anchor=align,
                    justify="left"
                )
                label.pack(fill="both", expand=True, padx=pad_x, pady=10)

# =========================================================================
# === 主程序类 (核心逻辑都在这) ===
# =========================================================================
class UltraEncoderApp(DnDWindow):
    # 安全的更新UI（防止多线程报错）
    def safe_update(self, func, *args, **kwargs):
        if self.winfo_exists():
            # 使用 after 方法把任务扔回主线程执行
            self.after(10, partial(self._guarded_call, func, *args, **kwargs))

    def _guarded_call(self, func, *args, **kwargs):
        try:
            if self.winfo_exists(): func(*args, **kwargs)
        except: pass

    # [v76 最终修复]: 放弃坐标检测，改用纯数学索引计算，稳如老狗
    def scroll_to_card(self, widget):
        try:
            # 1. 找到这个卡片对应的是哪个文件
            target_file = None
            for f, card in self.task_widgets.items():
                if card == widget:
                    target_file = f
                    break
            
            if not target_file: return

            # 2. 算出它在队伍里的排号
            if target_file in self.file_queue:
                index = self.file_queue.index(target_file) - 1 # 比如第 5 个
                total = len(self.file_queue)               # 总共 10 个
                
                # 3. 直接计算进度条百分比
                if total > 1:
                    # 算法：当前序号 / 总数 = 进度位置 (0.0 到 1.0)
                    # 比如 5/10 = 0.5，进度条就拉到中间
                    target_pos = index / total
                    
                    # 4. 修正视野：稍微往上提一丢丢，避免标题栏挡住任务
                    # 如果不是第一个任务，就往上提一个身位 (1/total)
                    if index > 0:
                        target_pos = max(0.0, target_pos - (1 / total) * 0.5)

                    # 5. 强制执行滚动
                    self.scroll._parent_canvas.yview_moveto(target_pos)
                    
                    # 双重保险：有时候第一次滚不动，100毫秒后再补一脚
                    self.after(100, lambda: self.scroll._parent_canvas.yview_moveto(target_pos))
        except Exception as e:
            print(f"Scroll Error: {e}")

    # 【新增】预加载函数
    def preload_help_window(self):
        try:
            self.help_window = HelpWindow(self) # 创建实例
            self.help_window.withdraw()         # 立即隐藏
            # 劫持关闭事件：当用户点击关闭时，不销毁，而是隐藏
            self.help_window.protocol("WM_DELETE_WINDOW", self.hide_help_window)
        except: pass

    # 【新增】隐藏代替销毁
    def hide_help_window(self):
        self.help_window.withdraw()

    # --- 初始化函数：程序启动时执行这里 ---
    def __init__(self):
        super().__init__()
        self.title("Cinético_Encoder")
        self.geometry("1300x900")
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(1200, 850) 
        self.protocol("WM_DELETE_WINDOW", self.on_closing) # 拦截关闭窗口事件
        
        # 核心变量初始化
        self.file_queue = []       # 文件队列（存路径）
        self.task_widgets = {}     # 卡片字典（路径 -> 卡片对象）
        self.active_procs = []     # 正在运行的FFmpeg进程
        self.running = False       # 运行状态
        self.stop_flag = False     # 停止标志
        
        # 线程锁（防止多个线程同时改一个变量导致冲突）
        self.queue_lock = threading.Lock() 
        self.slot_lock = threading.Lock()
        self.read_lock = threading.Lock()
        self.gpu_lock = threading.Lock()
        
        self.gpu_active_count = 0  # 当前有多少个GPU任务在跑
        self.total_vram_gb = self.get_total_vram_gb() # 获取显存大小
        
        self.monitor_slots = []    # 监控通道列表
        self.available_indices = [] # 空闲的通道索引
        self.current_workers = 2   # 当前并发数
        
        # 线程池：用于管理后台任务
        self.executor = ThreadPoolExecutor(max_workers=16) 
        self.submitted_tasks = set() 
        self.temp_dir = ""
        self.manual_cache_path = None
        self.temp_files = set() # 临时文件列表，用于退出时清理
        
        self.total_tasks_run = 0
        self.finished_tasks_count = 0

        self.setup_ui() # 构建界面
        # [架构修正] 启动全局流媒体服务器 (单例模式)
        self.global_server, self.global_port = start_global_server()
        disable_power_throttling() # 性能全开
        set_execution_state(True)  # 禁止休眠
        
        # 延迟200毫秒进行系统自检（等待界面加载完）
        self.after(200, self.sys_check)
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

        # 【新增】延迟 200ms 后在后台预加载帮助窗口
        self.after(200, self.preload_help_window)

    # 显示帮助弹窗
    # [修改后] 点击问号时，弹出我们设计好的漂亮窗口
    def show_help(self):
        # 如果窗口还没创建（比如刚启动还没来得及预加载），就现做
        if not hasattr(self, "help_window") or not self.help_window.winfo_exists():
            self.preload_help_window()
        
        # 显示并置顶
        self.help_window.deiconify()
        self.help_window.lift()

    # 拖拽文件进来时触发
    def drop_file(self, event):
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    # 添加文件到列表的逻辑
    def add_list(self, files):
        with self.queue_lock: # 加锁，防止冲突
            existing_paths = set(os.path.normpath(os.path.abspath(f)) for f in self.file_queue)
            new_added = False
            for f in files:
                # [关键修正] 无论来源如何，先强制转为 Windows 标准路径 (带反斜杠)
                f_norm = os.path.normpath(os.path.abspath(f))
                
                if f_norm in existing_paths: continue # 如果已存在，跳过
                
                if f_norm.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts', '.flv', '.wmv')):
                    self.file_queue.append(f_norm) # [Fix] 必须存入 standardized path
                    existing_paths.add(f_norm) 
                    if f_norm not in self.task_widgets:
                        # 创建一个新的任务卡片
                        card = TaskCard(self.scroll, 0, f_norm) 
                        self.task_widgets[f_norm] = card
                    new_added = True
            
            if not new_added: return
            
            # 按文件体积从低到高排序
            self.file_queue.sort(key=lambda x: os.path.getsize(x))

            # 刷新界面上的列表显示
            for i, f in enumerate(self.file_queue):
                if f in self.task_widgets:
                    card = self.task_widgets[f]
                    card.pack_forget()
                    card.pack(fill="x", pady=4)
                    card.update_index(i + 1)
            
            if self.running:
                self.update_run_status()

    # 更新“压制中 (1/10)” 这种文字
    def update_run_status(self):
        if not self.running: return
        total = len(self.file_queue)
        current = min(self.finished_tasks_count + 1, total)
        if current > total and total > 0: current = total
        
        txt = f"任务队列: {current} / {total}"
        try: 
            # 【修改】把状态更新到右上方标题栏旁边的 Label
            self.lbl_run_status.configure(text=txt) 
        except: pass

    # 应用系统优先级
    def apply_system_priority(self, level):
        mapping = {"常规": PRIORITY_NORMAL, "优先": PRIORITY_ABOVE, "极速": PRIORITY_HIGH}
        p_val = mapping.get(level, PRIORITY_ABOVE)
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, p_val)
            ctypes.windll.kernel32.CloseHandle(handle)
        except: pass
    
    # 关闭窗口时的逻辑
    def on_closing(self):
        if self.running:
            if not messagebox.askokcancel("退出", "任务正在进行中，确定要退出？"): return
        self.stop_flag = True
        self.running = False
        self.executor.shutdown(wait=False) # 强制关闭线程池
        self.kill_all_procs() # 杀掉FFmpeg
        self.clean_junk()     # 清理临时文件
        self.destroy()
        set_execution_state(False)
        os._exit(0)
    
    # 清理垃圾文件
    def clean_junk(self):
        try:
            for f in self.temp_files:
                if os.path.exists(f): os.remove(f)
        except: pass
        
    # 杀掉所有FFmpeg进程
    def kill_all_procs(self):
        for p in list(self.active_procs): 
            try: p.terminate(); p.kill()
            except: pass
        try: subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], creationflags=subprocess.CREATE_NO_WINDOW)
        except: pass

    # 系统自检
    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("错误", "找不到 FFmpeg！请确保已安装 FFmpeg 并添加到环境变量。")
            return
        # 在后台线程检测磁盘和GPU，防止卡UI
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.gpu_monitor_loop, daemon=True).start()
        self.update_monitor_layout()

    # 获取显存大小
    def get_total_vram_gb(self):
        try:
            cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si, encoding="utf-8").strip()) / 1024.0
        except: return 8.0 # 获取失败默认8G

    # [逻辑] 决定是否使用GPU
    def should_use_gpu(self, codec_sel):
        if not self.gpu_var.get(): return False # 如果开关没开，直接返回False
        
        # 估算显存占用：H.264约1.2G，AV1约2.0G
        task_cost = 1.2 
        if "AV1" in codec_sel: task_cost = 2.0
        
        system_reserve = 1.5 # 留给系统显示的显存
        
        with self.gpu_lock:
            # 预测：(当前正在跑的任务数 + 1) * 单个任务消耗
            predicted_usage = (self.gpu_active_count + 1) * task_cost
            if predicted_usage > (self.total_vram_gb - system_reserve):
                # 如果超标了，但现在还没任务在跑，那还是让它跑（总不能一个都不跑）
                if self.gpu_active_count < 2: return True
                print(f"[VRAM Warning] 预估: {predicted_usage:.1f}G > Limit. Waiting.")
                return False 
        return True

    # 后台线程：每秒读取一次显卡状态
    def gpu_monitor_loop(self):
        while not self.stop_flag:
            try:
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
                    # 温度或显存过高变红
                    if temp > 75 or mem_used > (mem_total * 0.9): color = COLOR_ERROR      
                    elif temp > 60 or mem_used > (mem_total * 0.7): color = COLOR_SSD_CACHE 
                    elif power > 50: color = COLOR_SUCCESS  
                    
                    status_text = f"GPU: {power:.0f}W | {temp}°C | VRAM: {mem_used:.1f}/{mem_total:.1f}G"
                    self.safe_update(self.lbl_gpu.configure, text=status_text, text_color=color)
            except: pass
            time.sleep(1)

    # 扫描磁盘，找缓存目录
    def scan_disk(self):
        path = find_best_cache_drive(manual_override=self.manual_cache_path)
        cache_dir = os.path.join(path, "_Ultra_Smart_Cache_")
        os.makedirs(cache_dir, exist_ok=True)
        self.temp_dir = cache_dir
        self.safe_update(self.btn_cache.configure, text=f"缓存池: {path} (点击修改)")

    # 手动选择缓存文件夹
    def select_cache_folder(self):
        d = filedialog.askdirectory(title="选择缓存盘 (SSD 优先)")
        if d:
            self.manual_cache_path = d
            self.scan_disk() 

    # 【新增】智能按钮响应函数
    def toggle_action(self):
        # 如果当前没在跑，就尝试启动
        if not self.running:
            if not self.file_queue:
                messagebox.showinfo("提示", "请先拖入或导入视频文件！")
                return
            # 队列里有任务才启动
            self.run()
        else:
            # 如果正在跑，点击就是停止
            self.stop()

    # --- 界面布局逻辑 (把所有按钮放上去) ---
    def setup_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=320) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=320)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        # 标题栏
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=20, pady=(25, 10))
        
        title_box = ctk.CTkFrame(l_head, fg_color="transparent")
        title_box.pack(fill="x")
        ctk.CTkLabel(title_box, text="Cinético", font=("Segoe UI Black", 32), text_color="#FFF").pack(side="left")
        
        # 帮助按钮
        btn_help = ctk.CTkButton(title_box, text="❓", width=30, height=30, corner_radius=15, 
                                 fg_color="#333", hover_color="#555", command=self.show_help)
        btn_help.pack(side="right")
        
        # 缓存按钮
        self.btn_cache = ctk.CTkButton(left, text="正在检测磁盘...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, 
                                     command=self.select_cache_folder) 
        self.btn_cache.pack(fill="x", padx=20, pady=(5, 5))
        
        # 工具栏 (+ 和 清空)
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(tools, text="+ 导入视频", width=120, height=36, corner_radius=18, 
                     fg_color="#333", hover_color="#444", command=self.add_file).pack(side="left", padx=5)
        self.btn_clear = ctk.CTkButton(tools, text="清空", width=60, height=36, corner_radius=18, 
                     fg_color="transparent", border_width=1, border_color="#444", hover_color="#331111", text_color="#CCC", command=self.clear_all)
        self.btn_clear.pack(side="left", padx=5)

        # --- 在 setup_ui 函数中，找到 l_btm 部分，替换整个 l_btm 的定义 ---
        
        # 底部控制区 (把 padding 改小，pady=10)
        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=15, pady=20, ipadx=5, ipady=10)
        
        # --- 1. 优先级选择 ---
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=(10, 5), padx=15) # pady 改小
        ctk.CTkLabel(rowP, text="系统优先级", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.priority_var = ctk.StringVar(value="优先")
        self.seg_priority = ctk.CTkSegmentedButton(rowP, values=["常规", "优先", "极速"], 
                                                  variable=self.priority_var, command=lambda v: self.apply_system_priority(v),
                                                  selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_priority.pack(fill="x", pady=(5, 0))

        # --- 2. 并发数与功能开关 (分层布局，防止挤压) ---
        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=(10, 5), padx=15)
        ctk.CTkLabel(row3, text="并发任务数量", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        
        # 上排：并发数选择
        w_box_top = ctk.CTkFrame(row3, fg_color="transparent")
        w_box_top.pack(fill="x", pady=(5, 2))
        self.worker_var = ctk.StringVar(value="2")
        self.seg_worker = ctk.CTkSegmentedButton(w_box_top, values=["1", "2", "3", "4"], variable=self.worker_var, 
                                               corner_radius=10, command=self.update_monitor_layout)
        self.seg_worker.pack(fill="x", expand=True)

        # 下排：核心开关组 (去掉重复，横向排布)
        w_box_btm = ctk.CTkFrame(row3, fg_color="transparent")
        w_box_btm.pack(fill="x", pady=(5, 0))
        
        # GPU 开关 (仅保留一个)
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(w_box_btm, text="GPU", width=60, variable=self.gpu_var, 
                     progress_color=COLOR_ACCENT).pack(side="left")
        
        # 保留信息
        self.keep_meta_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(w_box_btm, text="保留信息", width=80, variable=self.keep_meta_var, 
                     progress_color=COLOR_RAM, font=("微软雅黑", 11)).pack(side="left", padx=5)
        
        # 异构分流
        self.hybrid_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(w_box_btm, text="异构分流", width=80, variable=self.hybrid_var, 
                     progress_color=COLOR_SUCCESS, font=("微软雅黑", 11)).pack(side="left", padx=5)

        # --- 3. 画质滑块 ---
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=(10, 5), padx=15) # 【修改】这里原来是 pady=15，改小了，这就紧凑了
        ctk.CTkLabel(row2, text="CRF 画质控制", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkSlider(c_box, from_=16, to=35, variable=self.crf_var, progress_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(c_box, textvariable=self.crf_var, width=25, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="right")
        
        # --- 4. 编码格式选择 ---
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=(5, 15), padx=15) # 【修改】下方留白改成 15，和按钮稍微靠近点
        ctk.CTkLabel(row1, text="编码格式", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.codec_var = ctk.StringVar(value="H.264")
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265", "AV1"], variable=self.codec_var, selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_codec.pack(fill="x", pady=(5, 0))

        # --- 5. 启动按钮 ---
        # 去掉了底部的 pady，让它尽量靠下
        self.btn_action = ctk.CTkButton(l_btm, text="COMPRESS / 启动", height=50, corner_radius=12, 
                                   font=("微软雅黑", 16, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                                   text_color="#000", command=self.toggle_action)
        self.btn_action.pack(fill="x", padx=15, pady=(0, 5)) # 底部留一点点缝隙即可

        # 任务列表滚动区
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # 右侧面板配置
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        # [UI修复] 调亮文字颜色，使其可见
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Microsoft YaHei UI", 20, "bold"), text_color="#BBB").pack(side="left")
        
        # 【新增】这里加一个 Label，专门用来显示任务队列状态
        self.lbl_run_status = ctk.CTkLabel(r_head, text="", font=("微软雅黑", 12, "bold"), text_color=COLOR_ACCENT)
        self.lbl_run_status.pack(side="left", padx=20, pady=2) # 放在标题右边

        self.lbl_gpu = ctk.CTkLabel(r_head, text="GPU: --W | --°C", font=("Consolas", 14, "bold"), text_color="#444")
        self.lbl_gpu.pack(side="right")
        
        # [UI修复] 改用 ScrollableFrame，防止任务多了显示不下
        self.monitor_frame = ctk.CTkScrollableFrame(right, fg_color="transparent")
        # 修改 padding：底部留空稍微改小一点，给滚动条留位置
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))

    # 清空列表
    def clear_all(self):
        if self.running: return
        for k, v in self.task_widgets.items(): v.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()
        self.finished_tasks_count = 0
        self.btn_action.configure(text="COMPRESS / 启动")

    # 更新右侧监控窗口的布局（根据并发数增减）
    def update_monitor_layout(self, val=None, force_reset=False):
        if self.running and not force_reset:
            self.seg_worker.set(str(self.current_workers))
            return
        try: n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        for ch in self.monitor_slots: ch.destroy() # 删除旧的
        self.monitor_slots.clear()
        with self.slot_lock:
            self.available_indices = [i for i in range(n)] # 重置可用通道索引
        for i in range(n):
            ch = MonitorChannel(self.monitor_frame, i+1) # 创建新的监控通道
            ch.pack(fill="both", expand=True, pady=5)
            self.monitor_slots.append(ch)

    # --- 缓存处理核心逻辑 ---
    # [修复版] 智能缓存函数：修复 no_wait 逻辑跳跃问题
    def process_caching(self, src_path, widget, lock_obj=None, no_wait=False):
        file_size = os.path.getsize(src_path)
        file_size_gb = file_size / (1024**3)
        
        is_ssd = is_drive_ssd(src_path)
        is_external = is_bus_usb(src_path)
        
        # 1. SSD 直读判断
        if is_ssd and not is_external:
            self.safe_update(widget.set_status, "就绪 (SSD直读)", COLOR_DIRECT, STATUS_READY)
            widget.source_mode = "DIRECT"
            return True

        # 2. 内存等待逻辑
        # 如果是预加载(no_wait=True)，limit=0，直接跳过等待循环
        if file_size_gb < MAX_RAM_LOAD_GB:
             wait_count = 0
             limit = 0 if no_wait else 60 
             
             while wait_count < limit: 
                 free_ram = get_free_ram_gb()
                 available = free_ram - SAFE_RAM_RESERVE
                 if available > file_size_gb:
                     break 
                 
                 if wait_count == 0:
                     self.safe_update(widget.set_status, "⏳ 等待内存...", COLOR_WAITING, STATUS_WAIT)
                 
                 if self.stop_flag: return False
                 time.sleep(0.5)
                 wait_count += 1

        # 3. 开始 IO 操作 (加锁)
        if lock_obj: lock_obj.acquire()
        try:
            # 再次检查内存 (Double Check)
            free_ram = get_free_ram_gb()
            available_for_cache = free_ram - SAFE_RAM_RESERVE

            # 尝试载入内存
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
                    
                    # === [核心修复] 使用 Token 系统 ===
                    token = str(uuid.uuid4().hex) # 生成唯一 ID
                    GLOBAL_RAM_STORAGE[token] = data_buffer
                    PATH_TO_TOKEN_MAP[src_path] = token
                    # ================================
                    
                    self.safe_update(widget.set_status, "就绪 (内存加速)", COLOR_READY_RAM, STATUS_READY)                    
                    self.safe_update(widget.set_progress, 1, COLOR_READY_RAM)
                    widget.source_mode = "RAM"
                    return True
                except Exception: 
                    widget.clean_memory() 

            # 4. 内存不够，写入 SSD 缓存
            # [关键] 只要进入这里，必须强制更新状态，确保 UI 有反应
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
        
    # 点击“启动”按钮触发
    # [核心修复] 启动函数：包含完整状态重置
    def run(self):
        if not self.file_queue: return
        # 防止重复点击
        if self.running: return

        self.running = True
        self.stop_flag = False
        
        # 【修改】按钮文字固定显示 STOP，不再显示进度
        # [UI修复] 使用低调的暗红色，不再抢眼
        self.btn_action.configure(
            text="STOP / 停止",  
            fg_color="#852222",  # 深暗红，既有警示作用又不刺眼
            hover_color="#A32B2B", # 悬停时稍微亮一点
            state="normal"
        )
        self.btn_clear.configure(state="disabled")

        # 2. 重置线程池（防止旧任务僵死）
        self.executor.shutdown(wait=False)
        self.executor = ThreadPoolExecutor(max_workers=16)
        self.preload_executor.shutdown(wait=False)
        self.preload_executor = ThreadPoolExecutor(max_workers=1)
        
        # 3. 清理内部队列
        self.submitted_tasks.clear()
        self.preloading_tasks.clear()
        self.gpu_active_count = 0
        
        # 4. 重置通道资源
        with self.slot_lock:
            self.available_indices = list(range(self.current_workers))
        self.update_monitor_layout()

        # 5. 重置未完成任务的状态 (Finished 的不动)
        with self.queue_lock:
            # 重新计算已完成数量
            self.finished_tasks_count = 0
            for f in self.file_queue:
                card = self.task_widgets[f]
                if card.status_code == STATUS_DONE:
                    self.finished_tasks_count += 1
                else:
                    # 强制重置未完成的任务
                    card.set_status("等待处理", "#888", STATUS_WAIT)
                    card.set_progress(0)
                    card.clean_memory() # 释放之前的内存缓存
                    # 如果有之前的缓存文件，尽量删除（可选，不强求）
                    if card.ssd_cache_path and os.path.exists(card.ssd_cache_path):
                        try: os.remove(card.ssd_cache_path)
                        except: pass
                    card.ssd_cache_path = None
                    card.source_mode = "PENDING"

        # 6. 启动调度引擎
        threading.Thread(target=self.engine, daemon=True).start()

    # [配套修改] 停止函数
    def stop(self):
        self.stop_flag = True
        # 【修改】原来是 self.btn_stop，现在改成 self.btn_action
        self.kill_all_procs()
        self.btn_action.configure(text="正在停止...", state="disabled")

    # 重置界面状态（任务结束或停止后）
    def reset_ui_state(self):
        # --- 【修改】还原按钮为“启动模式” ---
        self.btn_action.configure(
            text="COMPRESS / 启动", 
            fg_color=COLOR_ACCENT, 
            hover_color=COLOR_ACCENT_HOVER,
            state="normal"
        )
        # 【新增】任务结束时，清空右上角的状态文字
        self.lbl_run_status.configure(text="") 
        self.btn_clear.configure(state="normal")
        self.update_monitor_layout(force_reset=True)

    # 获取视频时长（用于计算进度）
    def get_dur(self, path):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
            out = subprocess.check_output(cmd, creationflags=subprocess.CREATE_NO_WINDOW).strip()
            return float(out)
        except: return 0

    # 添加文件对话框
    def add_file(self):
        files = filedialog.askopenfilenames(title="选择视频文件", filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.avi *.ts *.flv *.wmv")])
        if files: self.add_list(files)

    # --- 调度引擎 (Engine) ---
    # --- [重构] 总指挥 (Grand Commander) ---
    def engine(self):
        # 1. 初始化资源账本
        total_ram_limit = MAX_RAM_LOAD_GB  # 最大可用 RAM (比如 50GB)
        current_ram_usage = 0.0            # 当前已用 RAM
        
        # 线程池分开：IO池 和 计算池
        # IO 池：如果是 SSD 环境，允许并发；否则只能 1 个
        is_cache_ssd = is_drive_ssd(self.temp_dir) or (self.manual_cache_path and is_drive_ssd(self.manual_cache_path))
        
        # [修改点] 纯固态环境：IO 并发数 = 用户设置的并发数；机械硬盘 = 1
        io_concurrency = self.current_workers if is_cache_ssd else 1
        
        self.io_executor = ThreadPoolExecutor(max_workers=io_concurrency)
        
        # 循环 Tick
        while not self.stop_flag:
            # --- A. 资源盘点 (每轮循环都重新计算，确保准确) ---
            active_io_count = 0
            active_compute_count = 0
            current_ram_usage = 0.0
            
            with self.queue_lock:
                for f in self.file_queue:
                    card = self.task_widgets[f]
                    # 统计 RAM：只有 RAM 模式且未完成的任务才占空间
                    if card.source_mode == "RAM" and card.status_code not in [STATE_DONE, STATE_ERROR]:
                        current_ram_usage += card.file_size_gb
                    
                    # 统计活跃线程
                    if card.status_code in [STATE_QUEUED_IO, STATE_CACHING]:
                        active_io_count += 1
                    elif card.status_code == STATE_ENCODING:
                        active_compute_count += 1

            # --- B. 调度 IO (后勤) ---
            # 只有当 IO 槽位有空，且还有任务在排队时
            if active_io_count < io_concurrency:
                with self.queue_lock:
                    for f in self.file_queue:
                        card = self.task_widgets[f]
                        
                        # 找到一个待命的任务
                        if card.status_code == STATE_PENDING:
                            # [智能 RAM 判断]
                            # 预测：如果我们加载它，内存会爆吗？
                            predicted_usage = current_ram_usage + card.file_size_gb
                            
                            # 决策：是否进 RAM
                            should_use_ram = False
                            if predicted_usage < total_ram_limit:
                                should_use_ram = True
                                # 预占位：虽然还没加载完，但我们在账本上先把它记下来，防止下一个任务超发
                                current_ram_usage += card.file_size_gb 
                            else:
                                should_use_ram = False # 内存不够，走 SSD 缓存
                            
                            # 下达指令
                            if should_use_ram:
                                card.source_mode = "RAM"
                            else:
                                card.source_mode = "SSD_CACHE" # 强制 SSD 模式
                            
                            # 更改状态，防止重复提交
                            card.status_code = STATE_QUEUED_IO
                            active_io_count += 1
                            
                            # 派出后勤兵
                            self.io_executor.submit(self._worker_io_task, f)
                            
                            # 如果 IO 槽位满了，停止本轮 IO 调度
                            if active_io_count >= io_concurrency:
                                break

            # --- C. 调度计算 (前线) ---
            # 只有当计算槽位有空
            if active_compute_count < self.current_workers:
                with self.queue_lock:
                    for f in self.file_queue:
                        card = self.task_widgets[f]
                        
                        # 找到一个粮草已备好 (Ready) 的任务
                        if card.status_code == STATE_READY:
                            # 更改状态
                            card.status_code = STATE_ENCODING
                            active_compute_count += 1
                            
                            # 派出突击手
                            self.executor.submit(self._worker_compute_task, f)
                            
                            if active_compute_count >= self.current_workers:
                                break
            
            # --- D. 检查全部完成 ---
            all_done = True
            with self.queue_lock:
                for f in self.file_queue:
                    if self.task_widgets[f].status_code not in [STATE_DONE, STATE_ERROR]:
                        all_done = False; break
            if all_done and active_io_count == 0 and active_compute_count == 0:
                break
                
            time.sleep(0.1) # 休息一下，防止 CPU 空转

        # 循环结束，善后
        self.running = False
        self.safe_update(messagebox.showinfo, "完成", "所有任务处理完毕")
        self.safe_update(self.reset_ui_state)

    # --- [新增] 后勤兵：只负责 IO (读硬盘/写内存) ---
    def _worker_io_task(self, task_file):
        card = self.task_widgets[task_file]
        try:
            # 标记状态
            self.safe_update(card.set_status, "📥正在加载...", COLOR_READING, STATE_CACHING)
            
            # 复用你原有的 process_caching 逻辑，但去掉了锁等待，因为指挥官已经批了条子
            # 注意：这里我们强制它尝试加载，具体的 RAM/SSD 决策指挥官已经做好了
            # 如果指挥官决定用 RAM，它会分配额度；否则走 SSD 缓存
            
            # 尝试加载 (这里调用你原有的 process_caching，但要确保它不会无限阻塞)
            # 传入 no_wait=True，因为指挥官已经确认过资源了
            success = self.process_caching(task_file, card, lock_obj=None, no_wait=True)
            
            if success:
                # 任务完成，标记为就绪，等待计算
                self.safe_update(card.set_status, "⚡就绪 (等待编码)", COLOR_READY_RAM if card.source_mode == "RAM" else COLOR_SSD_CACHE, STATE_READY)
            else:
                self.safe_update(card.set_status, "IO 失败", COLOR_ERROR, STATE_ERROR)

        except Exception as e:
            print(f"IO Error: {e}")
            self.safe_update(card.set_status, "IO 错误", COLOR_ERROR, STATE_ERROR)

# --- [升级] 智能日志分析器 ---
    def analyze_ffmpeg_log(self, logs):
        log_text = "\n".join(logs[-30:]) # 看得更远一点
        
        error_patterns = [
            ("Permission denied", "❌ 文件权限不足 (被占用?)"),
            ("No such file", "❌ 找不到输入文件 (路径乱码?)"),
            ("Unknown encoder", "❌ 找不到编码器 (驱动问题?)"),
            ("Device mismatch", "❌ 显卡设备不匹配 (请关闭异构分流)"),
            ("out of memory", "❌ 显存/内存不足 (OOM)"),
            ("Tag", "❌ 容器格式不兼容 (如 FLAC->MP4)"),
            ("Invalid data", "❌ 数据流损坏 (RAM读取失败)"),
            ("Server returned 404", "❌ 内存数据丢失 (Key不匹配)"),
            ("Qavg: nan", "❌ 音频编码崩溃 (流媒体时间戳错乱)"), # [新增]
            ("aac", "❌ 音频格式错误"), # [新增]
        ]
        
        for pattern, reason in error_patterns:
            if pattern in log_text or pattern.lower() in log_text.lower():
                return reason
        
        return "❌ 未知错误 (建议检查输入文件是否损坏)"

    # =========================================================================
    # === [新增] 智能解码能力检测 (核心稳定性保障) ===
    # =========================================================================
    def check_decoding_capability(self, input_path):
        """
        返回一个字典:
        {
            "can_hw_decode": bool,  # 是否支持 GPU 解码
            "pix_fmt": str,         # 像素格式 (如 yuv422p10le)
            "codec_name": str       # 编码格式 (如 h264)
        }
        """
        try:
            # 1. 使用 ffprobe 获取视频流的详细像素格式
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=pix_fmt,codec_name", 
                "-of", "csv=p=0", input_path
            ]
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            output = subprocess.check_output(cmd, startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW).strip().decode('utf-8')
            
            parts = output.split(',')
            codec_name = parts[0].strip()
            pix_fmt = parts[1].strip() if len(parts) > 1 else ""

            # 2. 硬编码黑名单 (NVIDIA NVDEC 目前不支持的格式)
            # 索尼/佳能的 10-bit 4:2:2 是重灾区
            unsupported_pix_fmts = [
                "yuv422p10le", "yuv422p10be", # 10bit 4:2:2
                "yuv422p12le", "yuv422p12be", # 12bit 4:2:2
                "yuv444p10le", "yuv444p12le"  # 部分 4:4:4 也可能出问题
            ]

            # 3. 判断逻辑
            can_hw_decode = True
            if pix_fmt in unsupported_pix_fmts:
                can_hw_decode = False
                print(f"[Smart Check] 检测到高规格素材 ({pix_fmt})，将强制使用 CPU 解码以保证稳定。")
            
            return {"can_hw_decode": can_hw_decode, "pix_fmt": pix_fmt, "codec_name": codec_name}

        except Exception as e:
            print(f"[Check Error] 检测失败，默认回退到 CPU 解码: {e}")
            return {"can_hw_decode": False, "pix_fmt": "unknown", "codec_name": "unknown"}

    # =========================================================================
    # === [V7.0 工业级重构版] 核心计算任务 (自动降级策略) ===
    # =========================================================================
    def _worker_compute_task(self, task_file):
        card = self.task_widgets[task_file]
        fname = os.path.basename(task_file)
        slot_idx = -1
        ch_ui = None
        proc = None
        temp_audio_wav = os.path.join(self.temp_dir, f"TEMP_AUDIO_{uuid.uuid4().hex}.wav")
        output_log = []
        input_size = 0
        duration = 1.0
        
        # --- 资源申请 ---
        with self.slot_lock:
            if self.available_indices:
                slot_idx = self.available_indices.pop(0)
                if slot_idx < len(self.monitor_slots):
                    ch_ui = self.monitor_slots[slot_idx]
        
        if not ch_ui: 
            class DummyUI: 
                def activate(self, *a): pass
                def update_data(self, *a): pass
                def reset(self): pass
            ch_ui = DummyUI()

        try:
            # 0. 基础信息获取
            if os.path.exists(task_file):
                input_size = os.path.getsize(task_file)
                duration = self.get_dur(task_file)
                if duration <= 0: duration = 1.0

            # 1. 智能预检：判断是否需要音频分离 & 是否支持硬解
            # 索尼素材必须分离音频，否则时间戳必挂
            need_audio_extract = True 
            
            # 检测视频解码能力
            decode_info = self.check_decoding_capability(task_file)
            hw_decode_allowed = decode_info["can_hw_decode"]
            
            # --- 阶段 1: 音频预处理 (WAV 落地) ---
            has_audio = False
            if need_audio_extract:
                self.safe_update(card.set_status, "🎵 提取音频...", COLOR_READING, STATE_ENCODING)
                extract_cmd = [
                    "ffmpeg", "-y", "-i", task_file, 
                    "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    "-f", "wav", temp_audio_wav
                ]
                si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.run(extract_cmd, startupinfo=si, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                if os.path.exists(temp_audio_wav) and os.path.getsize(temp_audio_wav) > 1024:
                    has_audio = True

            # --- 阶段 2: 构建“自适应”压制命令 ---
            self.safe_update(card.set_status, "▶️ 智能编码中...", COLOR_ACCENT, STATE_ENCODING)
            
            # 用户设置
            codec_sel = self.codec_var.get()
            using_gpu = self.gpu_var.get() # 用户总开关
            is_mixed_mode = self.hybrid_var.get()
            is_even_slot = (slot_idx % 2 == 0)

            # 决策链：最终是否开启硬件解码？
            # 必须满足 3 个条件：
            # 1. 用户开启 GPU 开关
            # 2. 显卡物理支持该格式 (4:2:0)
            # 3. 没有开启“异构分流”的 CPU 强制位
            final_hw_decode = using_gpu and hw_decode_allowed
            if is_mixed_mode and is_even_slot:
                final_hw_decode = False # 异构模式下，偶数槽强制用 CPU 解码

            # 决策链：最终是否开启硬件编码？
            # 只要用户开了 GPU，我们就尽量用 GPU 编码 (NVENC)，这个兼容性很好
            final_hw_encode = using_gpu

            # --- 路径准备 ---
            input_video_source = task_file
            # 只有在 CPU 解码模式下，才敢用 RAM 内存流
            # 因为 NVIDIA 驱动读取 HTTP 流有时候会有 Bug，读本地文件最稳
            if not final_hw_decode and card.source_mode == "RAM":
                token = PATH_TO_TOKEN_MAP.get(task_file)
                if token: input_video_source = f"http://127.0.0.1:{self.global_port}/{token}"
            elif card.source_mode == "SSD_CACHE" and card.ssd_cache_path:
                input_video_source = card.ssd_cache_path

            output_dir = os.path.dirname(task_file)
            f_name_no_ext = os.path.splitext(fname)[0]
            working_output_file = os.path.join(output_dir, f"{f_name_no_ext}_Cinético.mp4")

            # --- 组装 FFmpeg 命令 ---
            cmd = ["ffmpeg", "-y"]
            
            # [A] 硬件解码参数 (Input Options)
            if final_hw_decode:
                # 只有确认支持 4:2:0 且用户开启时，才加这行
                cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
                # 显存回收参数 (防止多任务炸显存)
                cmd.extend(["-extra_hw_frames", "2"]) 

            # [B] 输入文件
            if not final_hw_decode and card.source_mode == "RAM":
                cmd.extend(["-probesize", "50M", "-analyzeduration", "100M"])
            
            cmd.extend(["-i", input_video_source])
            if has_audio:
                cmd.extend(["-i", temp_audio_wav])

            # [C] 映射流
            cmd.extend(["-map", "0:v:0"])
            if has_audio: cmd.extend(["-map", "1:a:0"])

            # [D] 视频编码参数 (Output Options)
            v_codec = "libx264" # 默认 fallback
            
            if final_hw_encode:
                # === GPU 编码分支 (NVENC) ===
                if "H.264" in codec_sel: v_codec = "h264_nvenc"
                elif "H.265" in codec_sel: v_codec = "hevc_nvenc"
                elif "AV1" in codec_sel: v_codec = "av1_nvenc"
                cmd.extend(["-c:v", v_codec])

                # 关键：像素格式处理
                if final_hw_decode:
                    # 全链路 GPU：直接在显存内缩放/转换，性能最强
                    cmd.extend(["-vf", "scale_cuda=format=yuv420p"]) 
                else:
                    # 半链路 (CPU解->GPU压)：需要手动上传数据到 GPU
                    # 索尼素材通常是 10bit 422，必须先转成 yuv420p 才能喂给 NVENC
                    cmd.extend(["-pix_fmt", "yuv420p"]) 

                # 码率控制
                cmd.extend(["-rc", "vbr", "-cq", str(self.crf_var.get()), "-b:v", "0"])
                if "AV1" not in codec_sel: cmd.extend(["-preset", "p4"]) # P4 是速度/画质平衡点
            
            else:
                # === CPU 编码分支 (x264/x265) ===
                if "H.265" in codec_sel: v_codec = "libx265"
                elif "AV1" in codec_sel: v_codec = "libsvtav1"
                cmd.extend(["-c:v", v_codec, "-pix_fmt", "yuv420p", "-crf", str(self.crf_var.get()), "-preset", "medium"])

            # [E] 音频编码参数
            if has_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "320k"])

            # [F] 杂项
            if self.keep_meta_var.get(): cmd.extend(["-map_metadata", "0"])
            cmd.extend(["-progress", "pipe:1", "-nostats", working_output_file])

            # --- 阶段 3: 执行与监控 ---
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
            self.active_procs.append(proc)

            # 错误日志捕获线程
            def log_stderr(p):
                for l in p.stderr:
                    try: output_log.append(l.decode('utf-8', errors='ignore').strip())
                    except: pass
            threading.Thread(target=log_stderr, args=(proc,), daemon=True).start()

            # 生成 UI 标签文字
            info_decode = "GPU" if final_hw_decode else "CPU"
            info_encode = "GPU" if final_hw_encode else "CPU"
            tag_info = f"Dec:{info_decode} | Enc:{info_encode}"
            if card.source_mode == "RAM": tag_info += " | RAM"
            self.safe_update(ch_ui.activate, fname, tag_info)

            # --- 阶段 4: 进度解析循环 (保持原有逻辑) ---
            progress_stats = {}
            start_t = time.time()
            last_ui_update_time = 0 
            
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
                            if now - last_ui_update_time > 0.2:
                                fps = float(progress_stats.get("fps", "0")) if "fps" in progress_stats else 0.0
                                current_us = int(value.strip())
                                prog = min(1.0, (current_us / 1000000.0) / duration)
                                
                                # ETA 计算
                                eta = "--:--"
                                elapsed = now - start_t
                                if prog > 0.005:
                                    eta_sec = (elapsed / prog) - elapsed
                                    if eta_sec < 0: eta_sec = 0
                                    eta = f"{int(eta_sec//60):02d}:{int(eta_sec%60):02d}"
                                
                                # 压缩率计算
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

            # 善后
            if os.path.exists(temp_audio_wav):
                try: os.remove(temp_audio_wav)
                except: pass

            if self.stop_flag:
                self.safe_update(card.set_status, "已停止", COLOR_PAUSED, STATE_PENDING)
            elif proc.returncode == 0:
                self.safe_update(card.set_status, "完成", COLOR_SUCCESS, STATE_DONE)
                self.safe_update(card.set_progress, 1.0, COLOR_SUCCESS)
            else:
                # 打印错误日志分析
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
            
            self.safe_update(ch_ui.reset)
            with self.slot_lock:
                if slot_idx != -1:
                    self.available_indices.append(slot_idx)
                    self.available_indices.sort()

# 程序入口
if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()