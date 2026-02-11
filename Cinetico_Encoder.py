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
import random      # 用来生成随机数，辅助测试和模拟数据

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

# 自定义控件：波形图 (InfinityScope) - [V2.0 强制刷新版]
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
        # 保持数据池不要太大，100个点足够铺满屏幕了
        if len(self.points) > 100: self.points.pop(0)
        
        current_data_max = max(self.points) if self.points else 10
        # 动态调整Y轴刻度，让波形图看起来会有“呼吸感”
        self.target_max = max(current_data_max, 10) * 1.2

    def clear(self):
        self.points = []
        self.draw()

    def animate_loop(self):
        if self.winfo_exists() and self.running:
            # 1. 每一帧都平滑缩放 Y 轴
            diff = self.target_max - self.display_max
            if abs(diff) > 0.01:
                self.display_max += diff * 0.1
            
            # 2. [核心修改] 每一帧都强制重绘，不再等待数据
            # 这样即使数据没更新，Y轴的缩放动画也能继续，不会卡住
            self.draw()

            self.after(33, self.animate_loop) # 30 FPS 刷新率

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10: return
        
        # 绘制中心虚线
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4, 4))
        
        if not self.points: return

        scale_y = (h - 20) / self.display_max
        n = len(self.points)
        if n < 2: return
        
        # 自动拉伸 X 轴，让波形永远填满宽度
        step_x = w / (n - 1) if n > 1 else w
        
        coords = []
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
            
        if len(coords) >= 4:
            # 使用平滑曲线
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

# 自定义控件：监控通道 (MonitorChannel) - [V2.2 智能连续波形版]
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

        # [智能起搏器配置]
        self.is_active = False
        self.last_update_time = time.time()
        self.idle_start_time = 0 # 记录何时开始空闲的
        self.after(500, self._heartbeat) # 启动心跳

    # 智能心跳：负责连接波形，也负责在闲置时休眠
    def _heartbeat(self):
        if not self.winfo_exists(): return
        
        now = time.time()
        should_push_zero = False
        
        # 情况 A: 正在运行任务 (Active)
        if self.is_active:
            # 如果超过 0.8 秒没有收到 FFmpeg 的数据 (可能在提取音频/回写硬盘)
            if now - self.last_update_time > 0.8:
                should_push_zero = True
                
        # 情况 B: 任务刚结束 (Idle)
        else:
            # [关键逻辑] 只有在空闲的前 3 秒内，我们才继续推 0
            # 作用：让波形平滑回落，并连接到下一个紧接着的任务
            # 如果超过 3 秒没新任务，就停止刷新，让图表“定格”保留历史记录
            if now - self.idle_start_time < 3.0:
                should_push_zero = True
        
        if should_push_zero:
            self.scope.add_point(0)
            # 只有在确实没有任务跑的时候，才把文字归零
            if not self.is_active:
                self.lbl_fps.configure(text="0.00", text_color="#555")

        # 继续循环 (500ms 一次)
        self.after(500, self._heartbeat)

    def activate(self, filename, tag):
        if not self.winfo_exists(): return
        self.is_active = True
        self.lbl_title.configure(text=f"运行中: {filename[:15]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        
        # [关键修改] 删掉了 self.scope.clear()
        # 这样新任务的波形会接着旧任务画，形成连续的示波器效果
        
        self.last_update_time = time.time()

    def update_data(self, fps, prog, eta, ratio):
        if not self.winfo_exists(): return
        self.last_update_time = time.time() # 只要有数据，就更新活跃时间
        
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{float(fps):.2f}", text_color="#FFF") 
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        self.lbl_eta.configure(text=f"ETA: {eta}")
        self.lbl_ratio.configure(text=f"Ratio: {ratio:.1f}%", text_color="#888")

    def reset(self):
        if not self.winfo_exists(): return
        self.is_active = False
        self.idle_start_time = time.time() # [关键] 记录空闲开始的时间
        
        self.lbl_title.configure(text="通道 · 空闲", text_color="#555")
        self.lbl_info.configure(text="等待任务...", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.lbl_eta.configure(text="ETA: --:--", text_color="#333")
        self.lbl_ratio.configure(text="Ratio: --%", text_color="#333")
        # 同样不 clear，交给 heartbeat 处理过渡

# 自定义控件：任务卡片 (TaskCard) - [V3.1 对齐修复版]
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        
        # 配置列权重
        self.grid_columnconfigure(1, weight=1)
        
        self.filepath = filepath
        self.status_code = STATE_PENDING 
        self.ram_data = None 
        self.ssd_cache_path = None
        self.source_mode = "PENDING"
        
        try: self.file_size_gb = os.path.getsize(filepath) / (1024**3)
        except: self.file_size_gb = 0.0
        
        # --- 1. 序号 (左侧) ---
        # [修改点 1] width=50: 强制给它 50px 的固定宽度，不再随文字变宽变窄
        # [修改点 2] anchor="e": 让数字靠右对齐 (或者用 "center" 居中)，这样 "9" 和 "10" 的个位数能对齐
        self.lbl_index = ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 22), 
                                      text_color="#555", width=50, anchor="center")
        # padx=(5, 5): 因为有了固定宽度，外边距可以稍微改小一点，保持视觉平衡
        self.lbl_index.grid(row=0, column=0, rowspan=2, padx=(5, 5), pady=0) 
        
        # --- 2. 文件名区域 (中间上部) ---
        # 现在的 column 1 绝对是从左边第 60px (50px宽+10px间距) 的位置开始，绝对对齐！
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=1, sticky="sw", padx=0, pady=(8, 0)) 
        
        ctk.CTkLabel(name_frame, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), 
                     text_color="#EEE", anchor="w").pack(side="left")
        
        # --- 3. 文件夹按钮 (右侧) ---
        self.btn_open = ctk.CTkButton(self, text="📂", width=28, height=22, fg_color="#444", hover_color="#555", 
                                      font=("Segoe UI Emoji", 11), command=self.open_location)
        self.btn_open.grid(row=0, column=2, padx=10, pady=(8,0), sticky="e")
        
        # --- 4. 状态文字 (中间下部) ---
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="nw")
        self.lbl_status.grid(row=1, column=1, sticky="nw", padx=0, pady=(0, 0)) 
        
        # --- 5. 进度条 (最底部) ---
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="new", padx=12, pady=(0, 10))

    # (以下方法不用变)
    def open_location(self):
        try: subprocess.run(['explorer', '/select,', os.path.normpath(self.filepath)])
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

# =========================================================================
# === [V5.2 最终版] 帮助窗口：全卡片式统一排版 ===
# =========================================================================
class HelpWindow(ctk.CTkToplevel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.geometry("1150x900") 
        self.title("Cinético - Technical Guide")
        self.lift()
        self.focus_force()
        
        # --- 字体配置 (保持大字号) ---
        self.FONT_H1 = ("Segoe UI", 34, "bold")      
        self.FONT_H2 = ("微软雅黑", 18)              
        self.FONT_SEC = ("Segoe UI", 22, "bold")     
        self.FONT_SEC_CN = ("微软雅黑", 16, "bold")  
        self.FONT_ITEM = ("Segoe UI", 16, "bold")    
        self.FONT_BODY_EN = ("Segoe UI", 13)         
        self.FONT_BODY_CN = ("微软雅黑", 13)         
        
        # 颜色配置
        self.COL_BG = "#121212"        
        self.COL_CARD = "#1E1E1E"      
        self.COL_TEXT_HI = "#FFFFFF"   
        self.COL_TEXT_MED = "#CCCCCC"  
        self.COL_TEXT_LOW = "#888888"  
        self.COL_ACCENT = "#3B8ED0"    
        self.COL_TIP    = "#F1C40F"    # 建议高亮色

        self.configure(fg_color=self.COL_BG)

        # --- 顶部标题区 ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=50, pady=(45, 25))
        
        ctk.CTkLabel(header, text="Cinético Technical Overview & Operation Guide", 
                     font=self.FONT_H1, text_color=self.COL_TEXT_HI, anchor="w").pack(fill="x")
        ctk.CTkLabel(header, text="Cinético 技术概览与操作指南", 
                     font=self.FONT_H2, text_color=self.COL_TEXT_LOW, anchor="w").pack(fill="x", pady=(8, 0))

        # --- 滚动内容区 ---
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=30, pady=(0, 30))

        # =======================
        # [NEW] Part 0: Smart Hardware Advice
        # =======================
        self.add_section_title("0. Smart Optimization Guide", "智能并发设置建议")
        self.add_desc_text("Based on your current hardware configuration, here are the recommended settings for maximum efficiency without system freeze.\n根据您当前的硬件配置，以下是防止卡顿并最大化效率的推荐设置。")
        
        # 获取建议
        cpu_advice, gpu_advice = self.get_hardware_advice()
        
        # 显示 CPU 建议
        self.add_item_block(
            "CPU Encoding Mode (x264/x265/AV1)", "CPU 纯软解压制",
            f"Your CPU has multiple cores. To prevent system lag, do not use all threads.\n{cpu_advice['en']}",
            f"您的处理器核心较多。为防止系统卡死，请勿占满所有线程。\n建议：{cpu_advice['cn']}"
        )

        # 显示 GPU 建议
        self.add_item_block(
            "GPU Acceleration Mode (NVENC)", "N卡 硬件加速压制",
            f"Depends on the number of NVENC chips on your graphics card.\n{gpu_advice['en']}",
            f"取决于您显卡上的 NVENC 编码芯片数量。\n建议：{gpu_advice['cn']}"
        )

        # =======================
        # Part I: Functional Modules
        # =======================
        self.add_section_title("I. Functional Modules Detail", "功能模块详解")
        self.add_desc_text("Cinético is designed to deliver industrial-grade video processing capabilities through minimalist interaction logic.\nCinético 旨在通过极简的交互逻辑提供工业级的视频处理能力。")

        # 1. Core Processing
        self.add_sub_header("1. Core Processing / 核心处理")
        self.add_item_block(
            "Hardware Acceleration / GPU ACCEL", "硬件加速",
            "Utilizes dedicated NVIDIA NVENC circuits for hardware encoding. Significantly improves throughput and reduces power consumption. Disable only for benchmarking or troubleshooting compatibility issues.",
            "调用 NVIDIA NVENC 专用电路进行硬件编码。显著提升吞吐量，降低能耗。仅在基准测试或排查兼容性问题时关闭。"
        )
        self.add_item_block(
            "Heterogeneous Offloading / HYBRID", "异构分流",
            "A load balancing strategy. When enabled, it forces CPU decoding while using GPU encoding. Optimizes pipeline efficiency during concurrent multi-tasking.",
            "负载均衡策略。开启后，将强制使用 CPU 解码，使用GPU 编码。可优化多任务并发流水线效率。"
        )

        # 2. Codec Standards
        self.add_sub_header("2. Codec Standards / 编码标准")
        self.add_item_block(
            "H.264 (AVC)", "",
            "Extensive device support. Suitable for cross-platform distribution, client delivery, or playback on legacy hardware. Ensures maximum compatibility.",
            "广泛的设备支持。适用于跨平台分发、交付客户或在老旧硬件上播放。确保最大的兼容性。"
        )
        self.add_item_block(
            "H.265 (HEVC)", "",
            "High compression ratio. At equivalent image quality, bitrate is reduced by approximately 50% compared to H.264. Suitable for storage and archiving of 4K high-resolution video.",
            "高压缩比。在同等画质下，比特率较 H.264 降低约 50%。适用于 4K 高分辨率视频的存储与归档。"
        )
        self.add_item_block(
            "AV1", "",
            "Next-generation open-source coding format with superior compression efficiency. Suitable for scenarios requiring extreme file size control; encoding duration is longer, and playback requires hardware support.",
            "新一代开源编码格式，具备更优异的压缩效率。适用于对体积控制有极高要求的场景，编码耗时长，播放端需硬件支持。"
        )

        # 2.5 Color Depth / 色彩深度
        self.add_separator()
        self.add_sub_header("2.5 Color Depth / 色彩深度")
        
        self.add_item_block(
            "8-BIT", "Standard / 标准色彩",
            "16.7 million colors. Standard for web streaming and compatibility. \nRecommendation: Use for social media sharing or legacy device playback.",
            "1670 万色。网络流媒体与兼容性的标准。\n建议：用于社交媒体分享或老旧设备播放。"
        )
        
        self.add_item_block(
            "10-BIT", "High Color Depth / 高色深",
            "1.07 billion colors. Eliminates color banding and improves compression efficiency for gradients. \nRecommendation: Always Enable for Archiving.",
            "10.7 亿色。彻底消除色彩断层，提升渐变色区域压缩效率。\n建议：存档或追求高画质时务必开启。"
        )

        # 3. Rate Control & Quality
        self.add_sub_header("3. Rate Control & Quality / 码率控制与画质")
        self.add_desc_text("The quantization strategy adapts automatically based on the hardware selection.\n量化策略根据硬件选择自动适配。")
        
        self.add_item_block(
            "CPU Mode: CRF (Constant Rate Factor)", "基准值: 23",
            "Based on psychovisual models. Allocates bitrate dynamically according to motion complexity. Lower values yield higher quality.\nDefault: 23 (Balanced).",
            "基于心理视觉模型的恒定速率因子。根据画面运动复杂度动态分配码率，压缩效率极高。数值越小画质越高。\n默认值：23（平衡点）。"
        )
        self.add_item_block(
            "GPU Mode: CQ (Constant Quantization)", "基准值: 28",
            "Based on fixed mathematical quantization. Requires higher values to achieve file sizes comparable to CRF. Linear degradation.\nDefault: 28 (Equivalent to CRF 23).",
            "基于固定数学算法的量化参数。由于缺乏深度运动预测，需设定比 CRF 更高的数值以控制体积。线性衰减。\n默认值：28（体积近似 CRF 23）。"
        )
        
        self.add_item_block(
            "Value Guide / 数值参考", "",
            "CPU (CRF): 18-22 (High) | 23-26 (Balanced) | 27+ (Small)\nGPU (CQ):  20-25 (High) | 26-30 (Balanced) | 31+ (Small)",
            "CPU (CRF): 18-22 (高画质) | 23-26 (平衡) | 27+ (小体积)\nGPU (CQ):  20-25 (高画质) | 26-30 (平衡) | 31+ (小体积)"
        )

        # 4. System Scheduling
        self.add_sub_header("4. System Scheduling / 系统调度")
        self.add_item_block(
            "Retain Metadata / KEEP DATA", "保留元数据",
            "Retains original shooting parameters, timestamps, and camera information during encapsulation.",
            "封装时保留原片的拍摄参数、时间戳及相机信息。"
        )
        self.add_item_block(
            "Concurrent Tasks / CONCURRENCY", "并发任务",
            "Adjusts the number of parallel processing tasks based on VRAM capacity.",
            "根据显存容量调整并行处理的任务数量。"
        )
        self.add_item_block(
            "Process Priority / PRIORITY", "进程优先级",
            "Normal: Standard scheduling.\nHigh: Aggressive scheduling. Allocates maximum CPU time slices to the encoding process to accelerate compression, but significantly occupies system resources.",
            "Normal：标准调度。\nHigh：激进调度。向编码进程分配最大化的 CPU 时间片，加速压制，但显著占用系统资源。可能影响其他应用响应速度。"
        )

        # =======================
        # Part II: Core Architecture
        # =======================
        self.add_separator()
        self.add_section_title("II. Core Architecture Analysis", "核心架构解析")
        self.add_desc_text("Cinético has reconstructed underlying data transmission and resource management to break through the performance bottlenecks of traditional transcoding tools.\nCinético 重构底层数据传输与资源管理，突破传统转码工具性能瓶颈。")

        self.add_item_block(
            "1. Zero-Copy Loopback", "零拷贝环回",
            "Maps video streams to RAM; the encoder bypasses the conventional file system to acquire data at memory bus speeds, eliminating mechanical hard drive seek latency.",
            "将视频流映射至 RAM，编码器绕过常规文件系统，以内存总线速度获取数据，消除机械硬盘的寻道延迟。"
        )

        self.add_item_block(
            "2. Adaptive Storage Tiering", "自适应分层存储",
            "Dynamically allocates caching strategies based on file size and hardware environment.\n· Small files reside in memory for instant reading.\n· Large files are scheduled to SSD to ensure read/write stability.",
            "根据文件体积与硬件环境动态分配缓存策略。\n· 小文件驻留内存即时读取。\n· 大文件调度至SSD确保读写稳定性。"
        )

        self.add_item_block(
            "3. Heuristic VRAM Guard", "显存启发式管理",
            "A protection mechanism designed for high-load scenarios. Automatically suspends operations when VRAM resources approach the threshold, ensuring stability under extreme operating conditions.",
            "针对高负载场景设计的保护机制。显存资源临近阈值自动挂起，确保极端工况稳定性。"
        )

        ctk.CTkFrame(self.scroll, height=60, fg_color="transparent").pack()

    # [NEW] 修正版：基于 UI 限制和实战体验的建议
    def get_hardware_advice(self):
        import subprocess
        import os
        
        # --- 1. CPU 智能建议 (修正版) ---
        # 核心逻辑：UI 上限只有 4。
        # 对于 10-bit 压制，内存带宽是瓶颈，并发过多会导致 L3 缓存未命中率飙升，反而变慢。
        # 即使是 32 线程的 CPU，跑 3-4 个高负载任务也已经是甜点区了。
        try:
            cpu_count = os.cpu_count() or 4
        except:
            cpu_count = 4
            
        if cpu_count >= 16:
            # 16 线程以上 (i7/i9/R9)：性能过剩。
            # 推荐 3 个是为了留有余量给系统，用起来最丝滑；推荐 4 个是极限压榨。
            # 我们这里采取"甜点"策略，推荐 3 或 4。
            rec_cpu = 3 
            cpu_desc = "High-Performance CPU."
            cpu_reason_en = "Your CPU is powerful, but encoding is memory-intensive. To avoid cache thrashing, [3] is the sweet spot."
            cpu_reason_cn = "您的 CPU 性能强劲，但视频编码非常依赖内存带宽。为避免资源争抢导致掉速，[3] 是最佳甜点值。"
        elif cpu_count >= 8:
            # 8-12 线程 (i5/R5)：标准配置
            rec_cpu = 2
            cpu_desc = "Standard 8+ Thread CPU."
            cpu_reason_en = "Use [2] tasks to balance speed and system responsiveness."
            cpu_reason_cn = "建议使用 [2] 个并发，以在速度和系统响应之间取得平衡。"
        else:
            # 低于 8 线程
            rec_cpu = 1
            cpu_desc = "Basic CPU."
            cpu_reason_en = "Focus all power on [1] task for best stability."
            cpu_reason_cn = "集中所有算力处理 [1] 个任务以确保稳定。"

        cpu_msg_en = f"{cpu_desc} ({cpu_count} Threads detected).\nRecommendation: Set to [{rec_cpu}].\n{cpu_reason_en}"
        cpu_msg_cn = f"{cpu_desc} (检测到 {cpu_count} 线程)。\n推荐：将并发数设置为 [{rec_cpu}]。\n{cpu_reason_cn}"

        # --- 2. GPU 智能建议 (保持工业级检测不变) ---
        gpu_name = "Unknown"
        is_dual_nvenc = False
        
        try:
            cmd = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            gpu_name = subprocess.check_output(cmd, startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8").strip()
        except: pass
        
        name_upper = gpu_name.upper()
        dual_nvenc_triggers = ["RTX 4090", "RTX 4080", "RTX 4070 TI", "RTX 6000", "RTX A6000", "TITAN", "L40", "L4", "A40", "A100", "A800"]
        
        for trigger in dual_nvenc_triggers:
            if trigger in name_upper:
                is_dual_nvenc = True; break
        
        if is_dual_nvenc:
            rec_gpu = 4
            gpu_msg_en = f"Detected Dual-NVENC Card ({gpu_name}).\nRecommendation: Set to [3] or [4] to utilize both chips."
            gpu_msg_cn = f"检测到双编码芯片显卡 ({gpu_name})。\n推荐：将并发数设置为 [3] 或 [4] 以利用双芯片优势。"
        else:
            rec_gpu = 2
            gpu_msg_en = f"Standard Single-NVENC Card ({gpu_name}).\nRecommendation: Set to [2] for max efficiency."
            gpu_msg_cn = f"标准单编码芯片显卡 ({gpu_name})。\n推荐：将并发数设置为 [2] (效率最高)。"

        if "4070 SUPER" in name_upper:
            gpu_msg_cn += "\n(注: 4070 Super 为单芯片，与 Ti 不同)"

        return {"en": cpu_msg_en, "cn": cpu_msg_cn}, {"en": gpu_msg_en, "cn": gpu_msg_cn}

    # --- 辅助方法：添加分隔线 ---
    def add_separator(self):
        line = ctk.CTkFrame(self.scroll, height=2, fg_color="#333333")
        line.pack(fill="x", padx=20, pady=50)

    # --- 辅助方法：添加大章节标题 ---
    def add_section_title(self, text_en, text_cn):
        f = ctk.CTkFrame(self.scroll, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(35, 15))
        
        bar = ctk.CTkFrame(f, width=5, height=28, fg_color=self.COL_ACCENT)
        bar.pack(side="left", padx=(0, 15))
        
        ctk.CTkLabel(f, text=text_en, font=self.FONT_SEC, text_color=self.COL_TEXT_HI).pack(side="left", anchor="sw")
        ctk.CTkLabel(f, text=f"  {text_cn}", font=self.FONT_SEC_CN, text_color=self.COL_TEXT_LOW).pack(side="left", anchor="sw", pady=(3,0))

    # --- 辅助方法：添加子分类标题 ---
    def add_sub_header(self, text):
        ctk.CTkLabel(self.scroll, text=text, font=self.FONT_SEC_CN, text_color=self.COL_TEXT_HI, anchor="w")\
            .pack(fill="x", padx=40, pady=(30, 12))

    # --- 辅助方法：添加纯文本描述 ---
    def add_desc_text(self, text):
        ctk.CTkLabel(self.scroll, text=text, font=self.FONT_BODY_EN, text_color=self.COL_TEXT_MED, 
                     justify="left", anchor="w").pack(fill="x", padx=40, pady=(0, 20))

    # --- 辅助方法：添加功能卡片 ---
    def add_item_block(self, title_en, title_cn, body_en, body_cn):
        card = ctk.CTkFrame(self.scroll, fg_color=self.COL_CARD, corner_radius=8)
        card.pack(fill="x", padx=20, pady=10)
        
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=25, pady=20)
        
        # 标题行
        title_box = ctk.CTkFrame(inner, fg_color="transparent")
        title_box.pack(fill="x", pady=(0, 10))
        
        t1 = ctk.CTkLabel(title_box, text=title_en, font=self.FONT_ITEM, text_color=self.COL_TEXT_HI)
        t1.pack(side="left")
        
        if title_cn:
            # 这里的文字颜色改为 Accent Color (蓝色)，让小标题更醒目，
            # 同时也区分了左边的纯英文大标题
            t2 = ctk.CTkLabel(title_box, text=f"  {title_cn}", font=self.FONT_ITEM, text_color=self.COL_ACCENT)
            t2.pack(side="left")

        # 内容行 (英文)
        ctk.CTkLabel(inner, text=body_en, font=self.FONT_BODY_EN, text_color=self.COL_TEXT_MED, 
                     justify="left", anchor="w", wraplength=950).pack(fill="x", pady=(0, 6))
        
        # 内容行 (中文)
        ctk.CTkLabel(inner, text=body_cn, font=self.FONT_BODY_CN, text_color=self.COL_TEXT_LOW, 
                     justify="left", anchor="w", wraplength=950).pack(fill="x")

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
        # [修改] 先检查一下是不是要自动清场
        self.auto_clear_completed()
        
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    # [新增] 智能清理：如果当前队列的任务全部完成了，就自动清空，为新任务腾地儿
    # [修正版] 智能清理：不再依赖不可靠的计数器，直接检查任务状态
    def auto_clear_completed(self):
        # 1. 如果正在跑，绝对不能清空 (可能用户只是想中途加一个文件)
        if self.running: return

        # 2. 如果队列是空的，没必要清空
        if not self.file_queue: return

        # 3. [核心修复] 遍历检查所有任务的实际状态
        # 只要列表里有一个任务既不是“完成”也不是“报错”，那就说明还没跑完
        all_finished = True
        for f in self.file_queue:
            # STATE_DONE = 5 (完成), STATE_ERROR = -1 (报错)
            code = self.task_widgets[f].status_code
            if code != 5 and code != -1: # 硬编码判断，防止常量未定义
                all_finished = False
                break
        
        # 4. 如果确实全部结束了，执行清场
        if all_finished:
            print("Detected all tasks finished. Auto clearing...")
            # 调用 clear_all，它内部会调用 reset_ui_state 把按钮变回“压制”并解锁
            self.clear_all()

    # [修改版] 检查是否显示占位符 (互斥切换模式)
    def check_placeholder(self):
        if not self.file_queue:
            # === 空状态 ===
            # 1. 拔掉滚动列表 (腾出空间)
            self.scroll.pack_forget()
            
            # 2. 显示占位符 (因为它现在独占中间区域，expand=True 会让它完美垂直居中)
            self.lbl_placeholder.pack(fill="both", expand=True, padx=10, pady=5)
            
        else:
            # === 有任务 ===
            # 1. 拔掉占位符
            self.lbl_placeholder.pack_forget()
            
            # 2. 恢复滚动列表
            self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

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
            
            # [新增] 检查占位符状态 (有文件了就隐藏它)
            self.safe_update(self.check_placeholder)

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

    # 应用系统优先级 [修正：严格对应 Windows API]
    def apply_system_priority(self, level_text):
        p_val = PRIORITY_NORMAL # 默认值
        
        # 1. 常规 (Normal) -> 0x20
        if "NORMAL" in level_text: 
            p_val = PRIORITY_NORMAL
            
        # 2. 较高 (Above Normal) -> 0x8000
        # 这是最推荐的档位，既快又不卡鼠标
        elif "ABOVE" in level_text: 
            p_val = PRIORITY_ABOVE
            
        # 3. 高 (High) -> 0x80
        # 这是应用程序层面的最高级，再高就是 Realtime(0x100) 作死级了
        elif "HIGH" in level_text: 
            p_val = PRIORITY_HIGH
            
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

    # [NEW] 启动时自动侦测最佳并发数
    def detect_optimal_concurrency(self):
        import subprocess
        import os
        
        # 默认保守值
        optimal_n = 2
        
        try:
            # 1. 检测显卡 (GPU)
            # 逻辑：如果是双编码器高端卡 (4080/4090/Ti/Pro)，有能力跑 4 路，但为了稳健默认设为 3
            gpu_name = "Unknown"
            is_dual_nvenc = False
            
            try:
                cmd = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
                si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                gpu_name = subprocess.check_output(cmd, startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8").strip().upper()
                
                dual_nvenc_triggers = ["RTX 4090", "RTX 4080", "RTX 4070 TI", "RTX 6000", "RTX A6000", "TITAN", "L40", "L4", "A40", "A100", "A800"]
                for trigger in dual_nvenc_triggers:
                    if trigger in gpu_name:
                        is_dual_nvenc = True; break
            except: pass

            # 2. 检测处理器 (CPU)
            # 逻辑：如果是 16 线程以上的高端 U，也具备跑 3 路的能力
            cpu_count = os.cpu_count() or 4
            is_high_core_cpu = (cpu_count >= 16)

            # 3. 综合决策
            if is_dual_nvenc:
                # 显卡很强 -> 推荐 3 (用户要求：即使推荐4也降级为3，求稳)
                optimal_n = 3
                print(f"[Auto-Config] Detected Dual-NVENC GPU ({gpu_name}). Setting concurrency to 3.")
            elif is_high_core_cpu:
                # CPU 很强 -> 推荐 3
                optimal_n = 3
                print(f"[Auto-Config] Detected High-Core CPU ({cpu_count} threads). Setting concurrency to 3.")
            elif cpu_count < 8:
                # 电脑太弱 -> 降级为 1 (保护老电脑)
                optimal_n = 1
                print(f"[Auto-Config] Detected Weak CPU. Limiting concurrency to 1.")
            else:
                # 普通配置 -> 2
                optimal_n = 2
                print(f"[Auto-Config] Standard hardware detected. Defaulting to 2.")

        except Exception as e:
            print(f"[Auto-Config] Detection failed: {e}. Fallback to 2.")
            optimal_n = 2
            
        return str(optimal_n)

    # =========================================================================
    # === [UI V5.0 终极逻辑版] 互斥锁 + 视觉统一 + 420px ===
    # =========================================================================
    def setup_ui(self):
        # [修改] 用户指定的完美宽度
        SIDEBAR_WIDTH = 420 
        
        self.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=SIDEBAR_WIDTH)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        # --- 统一参数 ---
        UNIFIED_PAD_X = 20  
        ROW_SPACING = 6     
        LABEL_PAD = (0, 3)
        
        # [修改] 统一字体与颜色常量
        FONT_TITLE_MINI = ("微软雅黑", 11, "bold") 
        FONT_BTN_BIG    = ("微软雅黑", 11, "bold")
        COL_TEXT_ACTIVE = "#FFFFFF"   # 激活状态：纯白
        COL_TEXT_INACTIVE = "#999999" # 未激活：统一浅灰
        COL_BTN_BG_OFF = "#333333"    # 按钮背景：关闭
        
        # --- 1. 顶部区域 ---
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=UNIFIED_PAD_X, pady=(20, 5))
        
        title_box = ctk.CTkFrame(l_head, fg_color="transparent")
        title_box.pack(fill="x")
        ctk.CTkLabel(title_box, text="Cinético", font=("Segoe UI Black", 36), text_color="#FFF").pack(side="left")
        
        btn_help = ctk.CTkButton(title_box, text="❓", width=30, height=30, corner_radius=15, 
                                 fg_color="#333", hover_color="#555", command=self.show_help)
        btn_help.pack(side="right")
        
        self.btn_cache = ctk.CTkButton(left, text="Checking Disk... / 正在检测磁盘", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, 
                                     command=self.select_cache_folder) 
        self.btn_cache.pack(fill="x", padx=UNIFIED_PAD_X, pady=(5, 5))
        
        # --- 2. 工具栏 ---
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

        # --- 3. 底部参数控制区 ---
        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=UNIFIED_PAD_X, pady=10)

        # 变量初始化
        self.gpu_var = ctk.BooleanVar(value=False) 
        self.keep_meta_var = ctk.BooleanVar(value=True)
        self.hybrid_var = ctk.BooleanVar(value=False) 
        self.depth_10bit_var = ctk.BooleanVar(value=False)
        
        self.priority_var = ctk.StringVar(value="HIGH / 高优先") 
        self.worker_var = ctk.StringVar(value="2")
        self.crf_var = ctk.IntVar(value=23)
        self.codec_var = ctk.StringVar(value="H.264")

        # ======================================================
        # === [核心逻辑] 状态互斥与视觉刷新函数 ===
        # ======================================================
        def update_btn_visuals():
            # 统一刷新所有按钮的颜色，确保绝对一致
            # 1. GPU
            is_gpu = self.gpu_var.get()
            self.btn_gpu.configure(
                fg_color=COLOR_ACCENT if is_gpu else COL_BTN_BG_OFF,
                text_color=COL_TEXT_ACTIVE if is_gpu else COL_TEXT_INACTIVE
            )
            # 2. Meta
            is_meta = self.keep_meta_var.get()
            self.btn_meta.configure(
                fg_color=COLOR_ACCENT if is_meta else COL_BTN_BG_OFF,
                text_color=COL_TEXT_ACTIVE if is_meta else COL_TEXT_INACTIVE
            )
            # 3. Hybrid (特殊：如果 GPU 没开，它是 Disabled 状态)
            is_hybrid = self.hybrid_var.get()
            if not is_gpu:
                self.btn_hybrid.configure(state="disabled", fg_color="#222222", text_color="#555")
            else:
                self.btn_hybrid.configure(
                    state="normal",
                    fg_color=COLOR_ACCENT if is_hybrid else COL_BTN_BG_OFF,
                    text_color=COL_TEXT_ACTIVE if is_hybrid else COL_TEXT_INACTIVE
                )
            # 4. 10-BIT
            is_10bit = self.depth_10bit_var.get()
            self.btn_10bit.configure(
                fg_color=COLOR_ACCENT if is_10bit else COL_BTN_BG_OFF,
                text_color=COL_TEXT_ACTIVE if is_10bit else COL_TEXT_INACTIVE
            )

        # --- A. 点击 GPU 时的逻辑 ---
        def on_toggle_gpu():
            current = self.gpu_var.get()
            target = not current
            
            # 互斥检查：如果开启 GPU，且当前是 H.264 + 10-bit -> 必须关掉 10-bit
            if target and "H.264" in self.codec_var.get() and self.depth_10bit_var.get():
                self.depth_10bit_var.set(False) # 牺牲 10-bit
            
            self.gpu_var.set(target)
            if not target: self.hybrid_var.set(False) # 关 GPU 必关 Hybrid
            
            # 自动调整 CRF/CQ 数值
            if target: self.crf_var.set(min(40, self.crf_var.get() + 5))
            else: self.crf_var.set(max(16, self.crf_var.get() - 5))
            
            update_btn_visuals()
            update_labels()

        # --- B. 点击 10-BIT 时的逻辑 ---
        def on_toggle_10bit():
            current = self.depth_10bit_var.get()
            target = not current
            
            # 互斥检查：如果开启 10-bit，且当前是 H.264 -> 必须关掉 GPU
            if target and "H.264" in self.codec_var.get():
                if self.gpu_var.get():
                    self.gpu_var.set(False)
                    self.hybrid_var.set(False) 
                    
                    # [新增修复] 强制关掉 GPU 时，必须把数值减回去 (-5)
                    # 否则下次再开 GPU 又加 5，数值就会无限膨胀
                    self.crf_var.set(max(16, self.crf_var.get() - 5))
            
            self.depth_10bit_var.set(target)
            update_btn_visuals()
            update_labels()

        # --- C. 切换编码格式时的逻辑 ---
        def on_codec_change(value):
            # 如果切回 H.264，且 GPU 和 10-bit 同时开着 -> 优先保留 10-bit，关掉 GPU
            if "H.264" in value:
                if self.gpu_var.get() and self.depth_10bit_var.get():
                    self.gpu_var.set(False)
                    self.hybrid_var.set(False)
                    
                    # [新增修复] 这里同样需要把数值减回去
                    self.crf_var.set(max(16, self.crf_var.get() - 5))
                    
            update_btn_visuals()
            update_labels() # [记得加上这句] 确保标题文字(CQ/CRF)也能及时刷新

        def on_toggle_simple(var):
            var.set(not var.get())
            update_btn_visuals()

        def update_labels():
            if self.gpu_var.get():
                self.lbl_quality_title.configure(text="QUALITY (CQ) / 固定量化")
            else:
                self.lbl_quality_title.configure(text="QUALITY (CRF) / 恒定速率")

        # === 布局按钮 ===
        f_toggles = ctk.CTkFrame(l_btm, fg_color="transparent")
        f_toggles.pack(fill="x", padx=UNIFIED_PAD_X, pady=(15, 5))
        for i in range(4): f_toggles.grid_columnconfigure(i, weight=1)
        
        # 1. GPU
        self.btn_gpu = ctk.CTkButton(f_toggles, text="GPU ACCEL\n硬件加速", font=FONT_BTN_BIG,
                                     corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER,
                                     command=on_toggle_gpu)
        self.btn_gpu.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        # 2. Meta
        self.btn_meta = ctk.CTkButton(f_toggles, text="KEEP DATA\n保留信息", font=FONT_BTN_BIG,
                                      corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER,
                                      command=lambda: on_toggle_simple(self.keep_meta_var))
        self.btn_meta.grid(row=0, column=1, padx=3, sticky="ew")

        # 3. Hybrid
        self.btn_hybrid = ctk.CTkButton(f_toggles, text="HYBRID\n异构分流", font=FONT_BTN_BIG,
                                        corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER,
                                        command=lambda: on_toggle_simple(self.hybrid_var))
        self.btn_hybrid.grid(row=0, column=2, padx=3, sticky="ew")

        # 4. 10-BIT
        self.btn_10bit = ctk.CTkButton(f_toggles, text="10-BIT\n高色深", font=FONT_BTN_BIG,
                                       corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER,
                                       command=on_toggle_10bit)
        self.btn_10bit.grid(row=0, column=3, padx=(3, 0), sticky="ew")

        # 初始化一次视觉状态
        update_btn_visuals()

        # --- 系统优先级 ---
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(rowP, text="PRIORITY / 系统优先级", font=FONT_TITLE_MINI, text_color="#DDD").pack(anchor="w", pady=LABEL_PAD)
        # [修改] text_color={"selected": "#FFF", "normal": "#AAA"} 显式指定颜色
        self.seg_priority = ctk.CTkSegmentedButton(rowP, values=["NORMAL / 常规", "ABOVE / 较高", "HIGH / 高优先"], 
                                                  variable=self.priority_var, 
                                                  command=lambda v: self.apply_system_priority(v),
                                                  selected_color=COLOR_ACCENT, corner_radius=8, height=30,
                                                  text_color="#DDDDDD", selected_hover_color="#36719f", unselected_hover_color="#444")
        self.seg_priority.pack(fill="x")

        # --- 并发任务 ---
        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(row3, text="CONCURRENCY / 并发任务", font=FONT_TITLE_MINI, text_color="#DDD").pack(anchor="w", pady=LABEL_PAD)
        
        # [修改] 调用智能检测函数来设置默认值 (原来是 value="2")
        # 这样程序一启动，按钮就会自动停在最适合这台电脑的位置上
        default_worker = self.detect_optimal_concurrency()
        
        self.worker_var = ctk.StringVar(value=default_worker) # <--- 这里修改了
        
        self.seg_worker = ctk.CTkSegmentedButton(row3, values=["1", "2", "3", "4"], variable=self.worker_var, 
                                               corner_radius=8, height=30, selected_color=COLOR_ACCENT, 
                                               command=self.update_monitor_layout,
                                               text_color="#DDDDDD", selected_hover_color="#36719f", unselected_hover_color="#444")
        self.seg_worker.pack(fill="x")

        # --- 画质滑块 ---
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        self.lbl_quality_title = ctk.CTkLabel(row2, text="QUALITY (CRF) / 恒定速率", font=FONT_TITLE_MINI, text_color="#DDD")
        self.lbl_quality_title.pack(anchor="w", pady=LABEL_PAD)
        
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        slider = ctk.CTkSlider(c_box, from_=16, to=40, variable=self.crf_var, progress_color=COLOR_ACCENT, height=20)
        slider.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkLabel(c_box, textvariable=self.crf_var, width=35, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="right")

        # --- 编码格式 ---
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(row1, text="CODEC / 编码格式", font=FONT_TITLE_MINI, text_color="#DDD").pack(anchor="w", pady=LABEL_PAD)
        
        # [修改] 增加 command 绑定 on_codec_change
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265", "AV1"], 
                                                variable=self.codec_var, selected_color=COLOR_ACCENT, 
                                                corner_radius=8, height=30,
                                                command=on_codec_change,
                                                text_color="#DDDDDD", selected_hover_color="#36719f", unselected_hover_color="#444")
        self.seg_codec.pack(fill="x")

        # --- 启动按钮 ---
        self.btn_action = ctk.CTkButton(l_btm, text="COMPRESS / 压制", height=55, corner_radius=12, 
                                   font=("微软雅黑", 18, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                                   text_color="#000", command=self.toggle_action)
        self.btn_action.pack(fill="x", padx=UNIFIED_PAD_X, pady=20)

        # --- 列表区 ---
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.lbl_placeholder = ctk.CTkLabel(
            left, 
            text="📂\n\nDrag & Drop Video Files Here\n拖入视频文件开启任务",
            font=("微软雅黑", 16, "bold"),
            text_color="#444444",
            justify="center"
        )
        self.check_placeholder()

        # --- 右侧面板 ---
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

    # 清空列表
    # [修改] 重置功能：清空列表 + 还原按钮状态 + 滚动条归位
    def clear_all(self):
        if self.running: return # 运行中禁止重置
        
        # 1. 清空 UI 列表
        for k, v in self.task_widgets.items(): v.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()
        
        # [新增] 列表清空了，把占位符显示回来
        self.check_placeholder()
        
        self.finished_tasks_count = 0
        
        # 2. [新增] 强制滚动条回到最顶部 (0.0)
        # 必须访问 _parent_canvas 才能控制滚动位置
        try:
            self.scroll._parent_canvas.yview_moveto(0.0)
        except: pass

        # 3. 强制把大按钮还原回“压制”状态
        self.reset_ui_state()
        
        # 4. 清空顶部状态栏文字
        self.lbl_run_status.configure(text="")
        
        # 5. 重置监控窗口
        self.update_monitor_layout(force_reset=True)

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
        
        # 3. 清理内部队列
        self.submitted_tasks.clear()
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
        # --- 【修改】还原按钮文字为 "压制" ---
        self.btn_action.configure(
            text="COMPRESS / 压制",  # 这里记得改成新的文案
            fg_color=COLOR_ACCENT, 
            hover_color=COLOR_ACCENT_HOVER,
            state="normal"
        )
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
        if files: 
            # [修改] 只有当用户真的选了文件点确定了，我们才清空旧的
            self.auto_clear_completed()
            self.add_list(files)

    # [新增] 自定义的高颜值深色弹窗
    def show_custom_popup(self, title, message):
        if not self.winfo_exists(): return
        
        # 创建顶层窗口
        top = ctk.CTkToplevel(self)
        top.geometry("320x160")
        top.title("")
        top.overrideredirect(True) # 去掉丑陋的 Windows 标题栏
        top.attributes("-topmost", True) # 强制置顶
        
        # 居中计算
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 160
            y = self.winfo_y() + (self.winfo_height() // 2) - 80
            top.geometry(f"+{x}+{y}")
        except: pass

        # 边框和背景容器
        bg = ctk.CTkFrame(top, fg_color="#2B2B2B", border_width=2, border_color=COLOR_ACCENT, corner_radius=15)
        bg.pack(fill="both", expand=True)
        
        # 标题
        ctk.CTkLabel(bg, text=title, font=("微软雅黑", 18, "bold"), text_color=COLOR_ACCENT).pack(pady=(25, 5))
        
        # 内容
        ctk.CTkLabel(bg, text=message, font=("微软雅黑", 13), text_color="#DDD").pack(pady=(0, 20))
        
        # 确认按钮
        def close_win():
            top.destroy()
            
        ctk.CTkButton(bg, text="OK / 知道了", width=100, height=32, corner_radius=16,
                      fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                      command=close_win).pack(pady=10)
        
        # 强制模态（锁住主窗口不让点）
        top.grab_set()

    # ======================================================
    # === [最终融合版] 暴力参数 + 丝滑拖尾渲染 ===
    # ======================================================
    def launch_fireworks(self):
        if not self.winfo_exists(): return

        # 1. 创建全屏透明覆盖层
        top = ctk.CTkToplevel(self)
        top.title("")
        w, h = self.winfo_width(), self.winfo_height()
        x, y = self.winfo_x(), self.winfo_y()
        top.geometry(f"{w}x{h}+{x}+{y}")
        
        top.overrideredirect(True)
        # [新增] 让特效窗口“依附”于主窗口
        # 这样它会永远盖在主程序上面，但不会盖在其他软件（如浏览器）上面
        top.transient(self)
        top.attributes("-transparentcolor", "black") 
        
        canvas = ctk.CTkCanvas(top, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        # 2. 粒子物理系统
        particles = []
        colors = [COLOR_ACCENT, "#F1C40F", "#E74C3C", "#2ECC71", "#9B59B6", "#00FFFF", "#FF00FF", "#FFFFFF"] 
        
        particle_count = 150 # 稍微增加一点数量，因为爆发很快
        
        # === [左侧发射器] (使用你提供的参数) ===
        for _ in range(particle_count):
            particles.append({
                # [发射点]: 宽 150px 的区域
                "x": random.uniform(-50, 100), 
                "y": h + random.uniform(0, 30),
                
                # [速度]: 使用高斯分布，形成扇形
                "vx": random.gauss(15, 10),   
                "vy": random.gauss(-40, 12), # 强劲向上
                
                "grav": 2.0,                  # 强重力 (下落快)
                "size": random.uniform(3, 8), # 对应线条粗细
                "color": random.choice(colors),
                "life": 1.0,
                "decay": random.uniform(0.012, 0.025) 
            })
            
        # === [右侧发射器] (使用你提供的参数) ===
        for _ in range(particle_count):
            particles.append({
                # [发射点]: 右下角区域
                "x": random.uniform(w-100, w+50), 
                "y": h + random.uniform(0, 30),
                
                # [速度]: 向左飞
                "vx": random.gauss(-15, 10),
                "vy": random.gauss(-40, 12),
                
                "grav": 1.6, # 稍微轻一点 (保留你的不对称设计)
                "size": random.uniform(3, 8),
                "color": random.choice(colors),
                "life": 1.0,
                "decay": random.uniform(0.012, 0.025)
            })

        # 3. 动画循环 (使用 Create Line 实现拖尾)
        def animate():
            if not top.winfo_exists(): return
            canvas.delete("all")
            
            alive_count = 0
            
            for p in particles:
                if p["life"] > 0:
                    alive_count += 1
                    
                    # === 物理计算 ===
                    # 1. 记录上一帧位置 (作为拖尾起点)
                    tail_x, tail_y = p["x"], p["y"]
                    
                    # 2. 更新位置
                    p["x"] += p["vx"]
                    p["y"] += p["vy"]
                    
                    # 3. 应用你的物理参数
                    p["vy"] += p["grav"] # 重力
                    p["vx"] *= 0.97      # 空气阻力 (保留你的 0.97，阻力较小，飞得远)
                    p["life"] -= p["decay"]
                    
                    # === 绘制逻辑: 动态拖尾 ===
                    # 只有当粒子还没死透时才画
                    if p["life"] > 0.05:
                        # 使用 create_line 代替 create_oval
                        # 从 [上一帧位置] 画到 [当前位置]，自然形成速度拖尾
                        canvas.create_line(
                            tail_x, tail_y, 
                            p["x"], p["y"], 
                            fill=p["color"], 
                            # 宽度随生命值衰减
                            width=p["size"] * p["life"], 
                            # 圆头线帽，保证美观
                            capstyle="round" 
                        )
            
            if alive_count > 0:
                # 15ms 约等于 66 FPS
                top.after(15, animate)
            else:
                top.destroy()

        animate()

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
            # [修改版] 策略：SSD直读跳过IO队列，HDD强制单线程排队
            with self.queue_lock:
                for f in self.file_queue:
                    card = self.task_widgets[f]
                    
                    # 找到一个待命的任务
                    if card.status_code == STATE_PENDING:
                        # 1. 检测【源文件】所在的硬盘类型
                        source_is_ssd = is_drive_ssd(f)
                        
                        # === 策略分支 A: 源文件是 SSD ===
                        if source_is_ssd:
                            # 用户要求：SSD 直接读取，不用进 RAM，也不用缓存
                            card.source_mode = "DIRECT"
                            card.status_code = STATE_READY # 直接标记为就绪
                            
                            # 更新 UI
                            self.safe_update(card.set_status, "就绪 (SSD直读)", COLOR_DIRECT, STATE_READY)
                            self.safe_update(card.set_progress, 1.0, COLOR_DIRECT)
                            
                            # 不需要提交给 io_executor，直接看下一个任务
                            continue 

                        # === 策略分支 B: 源文件是 HDD (机械硬盘) ===
                        else:
                            # 用户要求：HDD 必须依次读取 (强制串行)
                            # 如果当前已经有任何一个 IO 任务在跑 (active_io_count > 0)，就立刻停止调度，等待它完成
                            if active_io_count >= 1:
                                break 
                            
                            # 如果没有 IO 任务，则开始处理这个 HDD 任务 (进 RAM 或 SSD缓存)
                            # [智能 RAM 判断逻辑保持不变]
                            predicted_usage = current_ram_usage + card.file_size_gb
                            
                            if predicted_usage < total_ram_limit:
                                should_use_ram = True
                                current_ram_usage += card.file_size_gb 
                            else:
                                should_use_ram = False 
                            
                            # 下达指令
                            card.source_mode = "RAM" if should_use_ram else "SSD_CACHE"
                            card.status_code = STATE_QUEUED_IO
                            active_io_count += 1
                            
                            # 派出后勤兵
                            self.io_executor.submit(self._worker_io_task, f)
                            
                            # HDD 只能跑一个，提交完这一个立刻退出循环
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

                            self.safe_update(self.scroll_to_card, card)
                            
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
        
        # [逻辑修改] 任务自然完成（非手动停止）
        if not self.stop_flag:
            # 1. 发射礼花！🎆 (保留你的得意之作)
            self.safe_update(self.launch_fireworks)
            
            # 2. [新功能] 不弹窗，直接把大按钮变绿，提示完成
            def set_complete_state():
                # A. 大按钮变成“已完成”且禁止点击
                self.btn_action.configure(
                    text="COMPLETED / 已完成",
                    fg_color=COLOR_SUCCESS,    
                    hover_color="#27AE60",     
                    state="disabled"           
                )
                self.lbl_run_status.configure(text="✨ All Tasks Finished")

                # ==================================================
                # === [关键修复] 必须把重置按钮解锁，否则用户无法重置！===
                # ==================================================
                self.btn_clear.configure(state="normal") 
                
            self.safe_update(set_complete_state)
            
        else:
            # 如果是手动停止的，恢复原状
            self.safe_update(self.reset_ui_state)
            
        # 注意：这里去掉了原来的 self.safe_update(self.reset_ui_state)，
        # 因为如果是自然完成，我们要保持“绿色完成态”让用户看到，不能马上重置。
        # 只有在 stop_flag == True (手动停止) 时才立即重置。

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
    # === [V7.2 终极版] 核心计算任务 (修复假死感 + 找回压缩比显示) ===
    # =========================================================================
    def _worker_compute_task(self, task_file):
        card = self.task_widgets[task_file]
        fname = os.path.basename(task_file)
        slot_idx = -1
        ch_ui = None
        proc = None
        
        # 安全初始化变量
        working_output_file = None 
        temp_audio_wav = os.path.join(self.temp_dir, f"TEMP_AUDIO_{uuid.uuid4().hex}.wav")
        output_log = []
        input_size = 0
        duration = 1.0
        
        # --- 1. 资源申请 ---
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
            # === [改动1] 拿到槽位立刻激活 UI，防止用户觉得卡死 ===
            # 先给用户一个 "正在准备" 的信号，清空之前的波形
            self.safe_update(ch_ui.activate, fname, "⏳ 正在预处理 / Pre-processing...")

            # 0. 基础信息获取
            if os.path.exists(task_file):
                input_size = os.path.getsize(task_file)
                duration = self.get_dur(task_file)
                if duration <= 0: duration = 1.0

            # 1. 智能预检
            need_audio_extract = True 
            decode_info = self.check_decoding_capability(task_file)
            hw_decode_allowed = decode_info["can_hw_decode"]
            
            # --- 阶段 1: 音频预处理 ---
            has_audio = False
            if need_audio_extract:
                # === [改动2] 在监控屏上也提示正在提取音频 ===
                self.safe_update(ch_ui.activate, fname, "🎵 正在分离音频流 / Extracting Audio...")
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

            # --- 阶段 2: 构建命令 ---
            self.safe_update(card.set_status, "▶️ 智能编码中...", COLOR_ACCENT, STATE_ENCODING)
            
            codec_sel = self.codec_var.get()
            using_gpu = self.gpu_var.get()
            is_mixed_mode = self.hybrid_var.get()
            is_even_slot = (slot_idx % 2 == 0)

            final_hw_decode = using_gpu and hw_decode_allowed
            if is_mixed_mode and is_even_slot: final_hw_decode = False 
            final_hw_encode = using_gpu

            # --- 路径准备 ---
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

            # --- 组装 FFmpeg 命令 ---
            cmd = ["ffmpeg", "-y"]
            
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
            
            # === [核心修改] 手动位深控制 ===
            # 1. 获取用户开关状态
            use_10bit = self.depth_10bit_var.get()
            
            # [安全门] 如果是 GPU 加速且选了 H.264，强制回退到 8-bit
            # 因为消费级显卡 (GeForce) 的 NVENC 不支持 H.264 10-bit
            if final_hw_encode and "H.264" in codec_sel and use_10bit:
                print("Warning: NVENC H.264 does not support 10-bit on this device. Fallback to 8-bit.")
                use_10bit = False

            # 2. 应用像素格式参数
            if final_hw_encode:
                # === GPU 编码 (NVENC) ===
                if use_10bit:
                    # 10-bit (P010)
                    if final_hw_decode: 
                        # 显存内转换: yuv420p -> p010le
                        cmd.extend(["-vf", "scale_cuda=format=p010le"]) 
                    else: 
                        # 内存上传: 直接指定 p010le
                        cmd.extend(["-pix_fmt", "p010le"])
                else:
                    # 8-bit (YUV420P)
                    if final_hw_decode: 
                        cmd.extend(["-vf", "scale_cuda=format=yuv420p"]) 
                    else: 
                        cmd.extend(["-pix_fmt", "yuv420p"]) 

                # 码率控制 (保持不变)
                cmd.extend(["-rc", "vbr", "-cq", str(self.crf_var.get()), "-b:v", "0"])
                if "AV1" not in codec_sel: cmd.extend(["-preset", "p4"])
            
            else:
                # === CPU 编码 (x264/x265/SVT-AV1) ===
                if use_10bit:
                    # CPU 10-bit 通常使用 yuv420p10le
                    cmd.extend(["-pix_fmt", "yuv420p10le"])
                else:
                    # 8-bit
                    cmd.extend(["-pix_fmt", "yuv420p"])

                cmd.extend(["-crf", str(self.crf_var.get()), "-preset", "medium"])

            if has_audio: cmd.extend(["-c:a", "aac", "-b:a", "320k"])
            if self.keep_meta_var.get(): cmd.extend(["-map_metadata", "0"])
            cmd.extend(["-progress", "pipe:1", "-nostats", working_output_file])

            # --- 阶段 3: 执行 ---
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
            self.active_procs.append(proc)

            def log_stderr(p):
                for l in p.stderr:
                    try: output_log.append(l.decode('utf-8', errors='ignore').strip())
                    except: pass
            threading.Thread(target=log_stderr, args=(proc,), daemon=True).start()

            # 正式开始编码，更新监控屏信息
            info_decode = "GPU" if final_hw_decode else "CPU"
            info_encode = "GPU" if final_hw_encode else "CPU"
            tag_info = f"Dec:{info_decode} | Enc:{info_encode}"
            if card.source_mode == "RAM": tag_info += " | RAM"
            self.safe_update(ch_ui.activate, fname, tag_info)

            # --- 阶段 4: 进度循环 ---
            progress_stats = {}
            start_t = time.time()
            last_ui_update_time = 0 
            
            # [Fix] 动态调整 UI 刷新率
            # 10-bit 压制时，系统负载极大，强制降低 UI 刷新频率以防止界面卡死
            # 8-bit: 0.2s 刷新一次 (流畅) | 10-bit: 0.8s 刷新一次 (稳定)
            ui_update_interval = 0.8 if use_10bit else 0.25

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
                            # [Fix] 使用动态间隔
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
                    
                    if os.path.exists(working_output_file):
                        shutil.move(working_output_file, final_output_path)
                    
                    if self.keep_meta_var.get() and os.path.exists(final_output_path):
                        shutil.copystat(task_file, final_output_path)

                    # === [改动3] 找回压缩比显示逻辑 ===
                    final_size_mb = 0
                    ratio_str = ""
                    try:
                        final_size_mb = os.path.getsize(final_output_path)
                        # 计算节省了多少百分比: (1 - 新/旧) * 100
                        saved_percent = (1.0 - (final_size_mb / input_size)) * 100
                        # 如果变大了，显示 +xx%
                        if saved_percent < 0:
                            ratio_str = f"(+{abs(saved_percent):.1f}%)"
                        else:
                            ratio_str = f"(-{saved_percent:.1f}%)"
                    except: pass
                    
                    # 组合最终状态文字： "完成 (-45.2%)"
                    status_text = f"完成 {ratio_str}"
                    self.safe_update(card.set_status, status_text, COLOR_SUCCESS, STATE_DONE)
                    # ==================================

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

# 程序入口
# 程序入口
if __name__ == "__main__":
    # --- [最终修正] 窗口隐藏逻辑 ---
    try:
        import ctypes
        # 1. 获取当前黑框的句柄
        whnd = ctypes.windll.kernel32.GetConsoleWindow()
        
        # 2. 只要句柄存在，就把它“变没”
        if whnd != 0:
            # 参数 0 = SW_HIDE (完全隐藏，任务栏也不显示)
            # 相比 FreeConsole，这种方法更稳定，不会导致后续 print 报错
            ctypes.windll.user32.ShowWindow(whnd, 0)
            
    except Exception:
        pass # 就算隐藏失败，也不要影响主程序启动
    # -----------------------------

    app = UltraEncoderApp()
    app.mainloop()