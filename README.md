# Cinetico Encoder

<div align="left">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![AI](https://img.shields.io/badge/Co--Pilot-Gemini-8E75B2?style=flat-square)
![Downloads](https://img.shields.io/github/downloads/shaiyueliang9klh/Cinetico_Encoder/total?style=flat-square&color=orange)

**Queue-based Video Encoding Tool with GPU Acceleration / 支持GPU加速的队列化视频压制工具**

</div>

---

## 📖 Introduction / 简介

A queue-based video encoding tool **supporting GPU acceleration**. Powered by the FFmpeg kernel, it optimizes system stability and resource management strategies tailored to the host device's performance.

队列化视频压制工具，**支持GPU加速**。以 **FFmpeg** 为内核，针对运行设备的性能差异，优化系统稳定性与资源管理策略。

---

## ⚡ Key Optimizations / 主要优化点

### - Optimized I/O Handling / I/O 读写
- **Local Loopback Mechanism**: Reduces mechanical disk latency by establishing a local loopback link, mapping video data directly to memory buffers for faster encoder feeding.
- **本地环回机制**：通过建立本地环回链路，将视频数据映射至内存缓冲，减少机械硬盘的 I/O 延迟，提高编码器吞吐效率。

### - Tiered Buffering Strategy / 分层缓存
- **Smart Pre-read**: Automatically detects system resources to determine pre-read strategies, utilizing RAM or SSD as cache to balance speed with disk lifespan.
- **智能预读**：自动检测系统资源以判定预读策略，使用 RAM 或 SSD 作为缓存，平衡速度与SSD寿命。

### - System Stability / 系统稳定性
- **Power Management**: Invokes Windows APIs to prevent the system from sleeping during active encoding tasks.
- **Thread Priority**: Optimizes thread locking mechanisms to prevent UI freezing during high-load CPU operations.
- **功耗管理**：调用 Windows 底层 API 防止系统在压制任务进行时自动休眠。
- **防卡顿优化**：通过优化线程锁机制，防止高负载压制时导致软件界面假死。

### - VRAM Monitoring / 显存监控
- **OOM Prevention**: Real-time monitoring of GPU video memory. The queue is automatically suspended if VRAM is critically low, preventing crashes.
- **防崩溃机制**：实时监控 GPU 显存状态。当显存不足时自动挂起任务队列，防止因显存溢出导致程序崩溃。

---

## 🎞️ Supported Codecs / 支持编码格式
**H.264 / H.265 / AV1**


---

 
## 🛠️ Quick Start / 快速开始

### Prerequisites / 前置要求
- Windows 10 / 11
- Python 3.10 or higher
- FFmpeg (The script will guide you if it's missing)

### Installation / 安装与运行

1. **Clone the repository**
   ```bash
   git clone [https://github.com/shaiyueliang9klh/Cinetico_Encoder.git](https://github.com/shaiyueliang9klh/Cinetico_Encoder.git)
   cd Cinetico_Encoder
2. **Run the script**
   ```bash
   python ultra_encoder.py
 

---

 
## 📂 Project Structure / 项目结构
   ```Plaintext
      Cinetico_Encoder/
      ├── ultra_encoder.py    # Main Application Logic (主程序)
      ├── .gitignore          # Git Configuration
      ├── LICENSE.txt         # MIT License
      └── README.md           # Documentation
   ```
 

---

 
## 🙏 Acknowledgements / 致谢

This project was developed with the assistance of **Google Gemini**, which provided support in code optimization and documentation.

本项目在开发过程中得到了 **Google Gemini** 的协助，特别是在代码优化与文档构建方面。
 

---

 
## 📜 License / 许可证

This project is licensed under the MIT License.

本项目采用 MIT License 开源协议，您可以自由地使用、修改和分发。

<div align="center">
    Created with ❤️ by shaiyueliang9klh
    <br>
    <i>Co-developed with the assistance of Google Gemini</i>
</div>
