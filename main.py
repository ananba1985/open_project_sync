#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import argparse
import requests
import base64

# 首先检查是否支持GUI模式
try:
    from api_client import _HAS_PYQT
except ImportError:
    _HAS_PYQT = False

# 只在GUI模式下导入PyQt5相关模块
if _HAS_PYQT:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from main_window import MainWindow

from config import config
from api_client import api_client

def test_api_connection():
    """测试API连接，用于调试"""
    print("\n正在测试OpenProject API连接...")
    url = "http://localhost:8080"
    token = "984614b4506a53c5768b2518d7082a87a6657bf07a075dff6f4f1ce8f4cadd32"
    
    print(f"测试URL: {url}")
    print(f"测试Token: {token[:5]}...")
    
    # 测试1: 基本网络连接
    try:
        response = requests.get(url)
        print(f"基本连接测试: 状态码 {response.status_code}")
    except Exception as e:
        print(f"基本连接测试失败: {e}")
    
    # 测试2: API Bearer认证
    api_url = f"{url}/api/v3/projects"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    try:
        print(f"\nBearer认证测试URL: {api_url}")
        print(f"请求头: {headers}")
        response = requests.get(api_url, headers=headers)
        print(f"Bearer认证测试: 状态码 {response.status_code}")
        print(f"响应内容: {response.text[:200]}...")
    except Exception as e:
        print(f"Bearer认证测试失败: {e}")
    
    # 测试3: 令牌直接作为Basic认证
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}"
        }
        print(f"\n令牌直接作为Basic认证测试URL: {api_url}")
        print(f"请求头: {headers}")
        response = requests.get(api_url, headers=headers)
        print(f"令牌直接作为Basic认证测试: 状态码 {response.status_code}")
        print(f"响应内容: {response.text[:200]}...")
    except Exception as e:
        print(f"令牌直接作为Basic认证测试失败: {e}")
    
    # 测试4: apikey:token格式的Basic认证
    try:
        auth_str = base64.b64encode(f"apikey:{token}".encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_str}"
        }
        print(f"\napikey:token格式的Basic认证测试URL: {api_url}")
        print(f"请求头: {headers}")
        response = requests.get(api_url, headers=headers)
        print(f"apikey:token格式的Basic认证测试: 状态码 {response.status_code}")
        print(f"响应内容: {response.text[:200]}...")
    except Exception as e:
        print(f"apikey:token格式的Basic认证测试失败: {e}")
    
    # 测试5: requests的auth参数
    try:
        print(f"\nrequests的auth参数认证测试URL: {api_url}")
        print(f"auth参数: ('apikey', token)")
        response = requests.get(api_url, auth=('apikey', token), headers={"Content-Type": "application/json"})
        print(f"requests的auth参数认证测试: 状态码 {response.status_code}")
        print(f"响应内容: {response.text[:200]}...")
    except Exception as e:
        print(f"requests的auth参数认证测试失败: {e}")
    
    # 测试6: 尝试使用令牌:X格式的Basic认证
    try:
        auth_str = base64.b64encode(f"{token}:X".encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_str}"
        }
        print(f"\n令牌:X格式的Basic认证测试URL: {api_url}")
        print(f"请求头: Authorization=Basic {auth_str[:20]}...")
        response = requests.get(api_url, headers=headers)
        print(f"令牌:X格式的Basic认证测试: 状态码 {response.status_code}")
        print(f"响应内容: {response.text[:200]}...")
    except Exception as e:
        print(f"令牌:X格式的Basic认证测试失败: {e}")
    
    print("\n测试完成\n")

def print_usage():
    """打印使用方法"""
    print("OpenProject同步工具")
    print("用法:")
    print("  - GUI模式: python main.py")
    print("  - 命令行模式: python main.py [选项]")
    print("\n选项:")
    print("  --report         启动报表服务器")
    print("  --help           显示此帮助信息")
    print("\n如需完整GUI功能，请安装PyQt5:")
    print("  - Ubuntu/Debian: sudo apt-get install python3-pyqt5 libgl1-mesa-glx")
    print("  - CentOS/RHEL: sudo yum install python3-qt5 mesa-libGL")
    print("  - 或使用pip: pip install PyQt5")

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='OpenProject同步工具')
    parser.add_argument('--report', action='store_true', help='启动报表服务器')
    parser.add_argument('--gui', action='store_true', help='启动GUI界面')
    
    args = parser.parse_args()
    
    # 如果没有指定参数且支持GUI，则默认启动GUI
    if not any(vars(args).values()) and _HAS_PYQT:
        args.gui = True
    
    # 如果没有指定参数且不支持GUI，则打印帮助
    if not any(vars(args).values()) and not _HAS_PYQT:
        print("错误: 无法导入PyQt5，不能启动GUI模式。")
        print("请安装PyQt5或使用命令行模式。")
        print_usage()
        return
    
    # 根据参数执行相应功能
    if args.report:
        # 启动报表服务器
        import report_server
        report_server.start_server()
    elif args.gui:
        if not _HAS_PYQT:
            print("错误: 无法导入PyQt5，不能启动GUI模式。")
            print_usage()
            return
        
        # 启动GUI界面
        app = QApplication(sys.argv)
        app.setApplicationName("OpenProject 数据同步工具")
        
        # 设置样式表
        app.setStyleSheet("""
            QMainWindow, QDialog {
                background-color: #f5f5f5;
            }
            QTableWidget {
                gridline-color: #d0d0d0;
            }
            QTableWidget::item:selected {
                background-color: #d0e7ff;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        
        # 创建主窗口
        main_window = MainWindow()
        main_window.show()
        
        # 检查配置
        if not config.is_configured():
            # 显示配置对话框
            main_window.show_config_dialog()
        
        # 执行应用程序
        sys.exit(app.exec_())
    else:
        print_usage()

if __name__ == "__main__":
    main()