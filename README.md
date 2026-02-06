# DataStream Encoder

<div align="left">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

**A Modern, High-Performance Automated Video Encoding Tool** **一款现代化的、高性能自动化视频压制工具**

[English](#-english) | [简体中文](#-简体中文)

</div>

---

## 📖 Introduction / 简介

**DataStream Encoder** is a minimalist automation tool designed for digital media creators. Unlike traditional command-line tools, it offers a seamless **drag-and-drop** experience while harnessing the full power of FFmpeg.

It features an intelligent **System Resource Governor**, ensuring that video encoding utilizes maximum performance without freezing your PC or interrupting your creative workflow.

**DataStream Encoder** 是专为数字媒体创作者设计的自动化工具。它在保留 FFmpeg 强大压制能力的同时，提供了极简的**拖拽交互**体验。内置智能**系统资源调度器**，确保在后台压制高画质视频时，既能跑满性能，又不会导致电脑卡顿。

---

## ✨ Key Features / 核心功能

### 🚀 Smart Automation (智能自动化)
- **Auto-Dependency Check**: Automatically detects and installs missing Python libraries (`tkinterdnd2`, `Pillow`, etc.) upon launch.
- **FFmpeg Integration**: Checks for FFmpeg presence and guides configuration if missing.
- **自动依赖管理**：启动时自动检测并安装缺失的第三方库，无需手动配置环境。

### 🛡️ Hardware Safeguards (硬件保护)
- **Dynamic RAM Management**: Calculates available physical memory in real-time (`GlobalMemoryStatusEx`) and limits buffer usage to prevent system OOM (Out of Memory) crashes.
- **Power Throttling Control**: Uses Windows APIs (`SetThreadExecutionState`) to prevent the system from sleeping during long encoding tasks.
- **动态内存调度**：实时计算物理内存余量，智能限制缓存大小，防止爆内存。
- **功耗管理**：调用 Windows 底层 API 保持唤醒状态，防止长任务压制时电脑休眠。

### 🖱️ Seamless Interaction (流畅交互)
- **Drag & Drop Support**: Native file dragging support powered by `tkinterdnd2`.
- **Modern UI**: Clean and minimalist interface tailored for efficiency.
- **拖拽支持**：原生级的文件拖拽支持，无需繁琐的路径选择。

---

## 🛠️ Quick Start / 快速开始

### Prerequisites (前置要求)
- Windows 10 / 11
- Python 3.10 or higher
- FFmpeg (The script will guide you if it's missing)

### Installation (安装与运行)

1. **Clone the repository**
   ```bash
   git clone [https://github.com/shaiyueliang9klh/DataStream_Encoder.git](https://github.com/shaiyueliang9klh/DataStream_Encoder.git)
   cd DataStream_Encoder
2. **Run the script**
   ```bash
   python ultra_encoder.py

---

## 📂 Project Structure / 项目结构
   ```Plaintext
      DataStream_Encoder/
      ├── ultra_encoder.py    # Main Application Logic (主程序)
      ├── .gitignore          # Git Configuration
      ├── LICENSE.txt         # MIT License
      └── README.md           # Documentation

---
   
## 📜 License / 许可证
This project is licensed under the MIT License.

本项目采用 MIT License 开源协议，您可以自由地使用、修改和分发。

<div align="center"> Created with ❤️ by shaiyueliang9klh </div>
