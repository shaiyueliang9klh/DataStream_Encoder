import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import subprocess
import threading
import os

class VideoCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FFmpeg 简易压制工具 (视觉无损)")
        self.root.geometry("500x450")
        
        # 变量存储
        self.input_path = tk.StringVar()
        self.crf_value = tk.IntVar(value=23)
        self.preset_value = tk.StringVar(value="medium")
        self.codec_value = tk.StringVar(value="libx264")
        self.status_var = tk.StringVar(value="准备就绪")

        self.create_widgets()

    def create_widgets(self):
        # 1. 文件选择区域
        file_frame = ttk.LabelFrame(self.root, text="输入文件", padding=10)
        file_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Entry(file_frame, textvariable=self.input_path, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(file_frame, text="浏览...", command=self.browse_file).pack(side="right", padx=5)

        # 2. 参数设置区域
        settings_frame = ttk.LabelFrame(self.root, text="压制参数", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)

        # 编码器选择
        ttk.Label(settings_frame, text="编码器 (Codec):").grid(row=0, column=0, sticky="w", pady=5)
        codec_combo = ttk.Combobox(settings_frame, textvariable=self.codec_value, state="readonly")
        codec_combo['values'] = ('libx264 (H.264 - 兼容性好)', 'libx265 (H.265 - 体积更小)')
        codec_combo.current(0)
        codec_combo.grid(row=0, column=1, sticky="ew", pady=5)

        # CRF 滑块
        ttk.Label(settings_frame, text="CRF (画质):").grid(row=1, column=0, sticky="w", pady=5)
        crf_frame = ttk.Frame(settings_frame)
        crf_frame.grid(row=1, column=1, sticky="ew")
        
        self.crf_scale = ttk.Scale(crf_frame, from_=0, to=51, orient="horizontal", variable=self.crf_value, command=self.update_crf_label)
        self.crf_scale.pack(side="left", fill="x", expand=True)
        self.crf_label = ttk.Label(crf_frame, text="23")
        self.crf_label.pack(side="right", padx=5)
        
        ttk.Label(settings_frame, text="(0=纯无损, 18=极高, 23=标准, 28=较低)", font=("Arial", 8), foreground="gray").grid(row=2, column=1, sticky="w")

        # Preset 选择
        ttk.Label(settings_frame, text="预设速度 (Preset):").grid(row=3, column=0, sticky="w", pady=5)
        preset_combo = ttk.Combobox(settings_frame, textvariable=self.preset_value, state="readonly")
        preset_combo['values'] = ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow')
        preset_combo.grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Label(settings_frame, text="(越慢压缩率越高，画质不变)", font=("Arial", 8), foreground="gray").grid(row=4, column=1, sticky="w")

        # 3. 状态与操作区域
        action_frame = ttk.Frame(self.root, padding=10)
        action_frame.pack(fill="both", expand=True)

        self.status_label = ttk.Label(action_frame, textvariable=self.status_var, relief="sunken", anchor="w")
        self.status_label.pack(fill="x", pady=10)

        self.run_btn = ttk.Button(action_frame, text="开始压制", command=self.start_encoding_thread)
        self.run_btn.pack(fill="x", pady=5)

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mkv *.mov *.avi *.flv")])
        if filename:
            self.input_path.set(filename)

    def update_crf_label(self, value):
        self.crf_label.config(text=str(int(float(value))))

    def get_output_filename(self, input_file):
        # 自动生成文件名：input.mp4 -> input_compressed.mp4
        dir_name = os.path.dirname(input_file)
        base_name = os.path.basename(input_file)
        name, ext = os.path.splitext(base_name)
        return os.path.join(dir_name, f"{name}_compressed{ext}")

    def start_encoding_thread(self):
        if not self.input_path.get():
            messagebox.showerror("错误", "请先选择视频文件")
            return
        
        # 禁用按钮防止重复点击
        self.run_btn.config(state="disabled")
        self.status_var.set("正在处理中，请勿关闭...")
        
        # 在新线程运行，防止界面卡死
        threading.Thread(target=self.run_ffmpeg, daemon=True).start()

    def run_ffmpeg(self):
        input_file = self.input_path.get()
        output_file = self.get_output_filename(input_file)
        
        # 解析编码器名称 (去除括号里的说明)
        codec_raw = self.codec_value.get()
        codec = "libx264" if "libx264" in codec_raw else "libx265"
        
        crf = int(self.crf_value.get())
        preset = self.preset_value.get()

        # 构建 FFmpeg 命令
        # -c:v 视频编码器
        # -crf 质量参数
        # -preset 编码速度
        # -c:a copy 音频直接复制（不重编码，保证音频无损）
        cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-c:v", codec,
            "-crf", str(crf),
            "-preset", preset,
            "-c:a", "copy", 
            output_file
        ]

        try:
            # hide_banner 和 loglevel panic 让输出更干净，或者你可以重定向输出
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            if process.returncode == 0:
                self.root.after(0, lambda: self.finish_process("成功", f"文件已保存至:\n{output_file}"))
            else:
                self.root.after(0, lambda: self.finish_process("失败", f"FFmpeg 报错:\n{process.stderr}"))
        except FileNotFoundError:
             self.root.after(0, lambda: self.finish_process("错误", "未找到 ffmpeg。请确保已安装并配置环境变量。"))
        except Exception as e:
            self.root.after(0, lambda: self.finish_process("错误", str(e)))

    def finish_process(self, title, message):
        self.run_btn.config(state="normal")
        self.status_var.set("就绪")
        if title == "成功":
            messagebox.showinfo(title, message)
        else:
            messagebox.showerror(title, message)

if __name__ == "__main__":
    root = tk.Tk()
    # 设置一下主题，让界面稍微好看点
    try:
        style = ttk.Style()
        style.theme_use('clam') 
    except:
        pass
    app = VideoCompressorApp(root)
    root.mainloop()