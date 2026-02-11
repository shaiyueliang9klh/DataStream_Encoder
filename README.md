# Cinético Encoder

<div align="left">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![AI](https://img.shields.io/badge/Co--Pilot-Gemini-8E75B2?style=flat-square)
![Downloads](https://img.shields.io/github/downloads/shaiyueliang9klh/Cinetico_Encoder/total?style=flat-square&color=orange)


<div align="left">

**A queue-based video encoding automation tool with intelligent resource scheduling.**  
**基于队列的自动化视频转码工具，具备智能资源调度能力。**

</div>

---

## 📖 Overview / 概述

Cinético Encoder is a batch video processing tool built on the FFmpeg kernel. It is designed to solve the stability issues often encountered in multi-tasking environments.

Unlike simple GUI wrappers, Cinético implements a logic layer that manages memory, VRAM, and I/O priority. It automatically adjusts encoding parameters based on the hardware status to balance processing speed and output quality.

Cinético Encoder 是一个基于 FFmpeg 内核的批量视频处理工具，旨在解决多任务环境下的稳定性问题。

不同于简单的图形界面套壳，Cinético 引入了一个逻辑层来管理内存、显存和 I/O 优先级。根据硬件状态自动调整编码参数，平衡处理速度与输出质量。

---

## ⚙️ Core Logic / 核心逻辑

### 1. Smart Rate Control / 智能码率控制

The program distinguishes between the evaluation standards of CPU and GPU encoders.
程序能够区分 CPU 和 GPU 编码器的评价标准。

* **CPU Mode**: Uses `CRF` (Constant Rate Factor) by default for optimal file size.
* **CPU 模式**：默认使用 `CRF` (恒定速率因子) 以获得最佳体积控制。
   
* **GPU Mode**: Uses `CQ` (Constant Quantization) with an automatic offset. When switching to GPU acceleration, the tool automatically calculates the equivalent value to maintain consistent visual quality and size.
* **GPU 模式**：使用 `CQ` (固定量化) 并配合自动偏移。切换至 GPU 加速时，工具会自动计算等效数值，以维持一致的视觉质量与文件体积。

### 2. Zero-Copy I/O / 零拷贝 I/O

To reduce mechanical disk latency, the tool maps video streams directly to a Global RAM Singleton. The encoder reads data via a local loopback interface at memory bus speeds, bypassing the file system bottleneck.   
为了减少机械硬盘延迟，工具将视频流直接映射至全局内存单例。编码器通过本地环回接口以内存总线速度读取数据，绕过文件系统瓶颈。

### 3. Safety Fallback / 安全降级

The engine automatically detects the specifications of the input video. If a file format is not supported by the hardware (e.g., 10-bit 4:2:2 on consumer GPUs), it automatically falls back to CPU decoding to prevent the process from crashing.   
引擎会自动检测输入视频的规格。如果文件格式不被硬件支持 (例如消费级显卡上的 10-bit 4:2:2)，它会自动降级至 CPU 解码，防止进程崩溃。

### 4. VRAM Guard / 显存保护

Real-time monitoring of GPU memory usage. If VRAM usage approaches the safety threshold during multi-tasking, the queue is temporarily suspended until resources are released.  
实时监控 GPU 显存使用情况。在多任务处理中，如果显存接近安全阈值，队列将暂时挂起，直到资源被释放。

---

## 🎞️ Supported Formats / 支持格式

 **H.264 (AVC)**  
 Maximum compatibility. Default for general distribution. <br>
 兼容性最好，通用分发的默认选择。
 
 **H.265 (HEVC)**  
 High compression efficiency. Suitable for 4K/HDR archiving. <br>
 高压缩效率，适合 4K/HDR 归档。
 
 **AV1**  
 Next-gen open standard. Best size-to-quality ratio, requires hardware support. <br>
 下一代开放标准，拥有最佳的体积画质比，需要硬件支持。

---

## 🛠️ Usage / 使用说明

### Prerequisites / 环境要求

* **System**: Windows 10 / 11 (64-bit)
* **Runtime**: [Python 3.10](https://www.python.org/downloads/) or newer.
* **Core**: [FFmpeg](https://ffmpeg.org/download.html) (Must be added to the system `PATH`).
* *Note: The script will check for FFmpeg upon startup.*
* *注：脚本启动时会自动检查 FFmpeg。*



### Running the Tool / 运行工具

1. **Clone or Download**
下载源码或克隆仓库：
```bash
git clone https://github.com/shaiyueliang9klh/Cinetico_Encoder.git
cd Cinetico_Encoder

```


2. Ensure you have a [**Python 3.10+** environment](https://www.python.org/downloads/).
   确保已[安装 **Python 3.10+** 环境](https://www.python.org/downloads/)。

3. Run the script or just double click to run / 运行脚本或直接双击运行


---

## 📄 License / 许可证

This project is open-source under the **MIT License**.
本项目基于 **MIT License** 开源。
 

<div align="center">
    Created with ❤️ by shaiyueliang9klh
    <br>
    <i>Co-developed with the assistance of Google Gemini</i>
</div>
