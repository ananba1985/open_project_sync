from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QLineEdit, QPushButton, QMessageBox, QFormLayout)
from PyQt5.QtCore import Qt
from config import config
from api_client import api_client

class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenProject 设置")
        self.setMinimumWidth(500)
        self.setup_ui()
        self.load_config()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 提示标签
        info_label = QLabel("请输入OpenProject的API访问信息")
        info_label.setStyleSheet("font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        # API URL
        url_layout = QHBoxLayout()
        url_label = QLabel("API URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("例如: http://localhost:8080")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)
        
        # URL提示
        url_tip = QLabel("注意: 不要在URL末尾添加斜杠")
        url_tip.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(url_tip)
        
        # API Token
        token_layout = QHBoxLayout()
        token_label = QLabel("API Token:")
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.Password)
        self.token_input.setPlaceholderText("输入您的API访问令牌")
        token_layout.addWidget(token_label)
        token_layout.addWidget(self.token_input)
        layout.addLayout(token_layout)
        
        # Token提示
        token_tip = QLabel("个人访问令牌获取方法：\n"
                          "1. 登录OpenProject系统\n"
                          "2. 点击右上角个人头像 -> 我的账户\n"
                          "3. 点击左侧菜单中的'访问令牌'\n"
                          "4. 点击'创建'，输入名称，选择范围（至少需要api_v3权限）\n"
                          "5. 点击'创建'生成令牌，务必保存令牌，因为它只会显示一次\n\n"
                          "令牌格式示例：984614b4506a53c5768b2518d7082a87a6657bf07a075dff6f4f1ce8f4cadd32")
        token_tip.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(token_tip)
        
        # 认证方式说明（只是显示，不可选择）
        auth_info = QLabel("认证方式：使用apikey:token的Basic认证")
        auth_info.setStyleSheet("color: #0078d4; font-size: 12px; margin-top: 10px;")
        layout.addWidget(auth_info)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.save_btn = QPushButton("保存")
        self.cancel_btn = QPushButton("取消")
        
        btn_layout.addWidget(self.test_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
        # 连接信号
        self.test_btn.clicked.connect(self.test_connection)
        self.save_btn.clicked.connect(self.save_config)
        self.cancel_btn.clicked.connect(self.reject)
        
    def load_config(self):
        """加载现有配置"""
        self.url_input.setText(config.api_url)
        self.token_input.setText(config.api_token)
        
    def test_connection(self):
        """测试连接"""
        url = self.url_input.text().strip()
        token = self.token_input.text().strip()
        
        if not url or not token:
            QMessageBox.warning(self, "输入错误", "请输入API URL和令牌")
            return
            
        # 临时更新客户端的凭证
        api_client.update_credentials(url, token)
        
        if api_client.test_connection():
            QMessageBox.information(self, "连接成功", "成功连接到OpenProject服务器!")
        else:
            auth_tips = (
                "请检查以下几点：\n"
                "1. 确认URL格式正确且能访问（例如：http://localhost:8080）\n"
                "2. 确认API令牌正确且未过期\n"
                "3. 确认API令牌具有足够权限（api_v3权限）\n"
                "4. 检查OpenProject版本，可能需要适配特定版本的认证方式"
            )
            QMessageBox.critical(self, "连接失败", f"无法连接到OpenProject服务器。\n\n{auth_tips}")
    
    def save_config(self):
        """保存配置"""
        url = self.url_input.text().strip()
        token = self.token_input.text().strip()
        
        if not url or not token:
            QMessageBox.warning(self, "输入错误", "请输入API URL和令牌")
            return
        
        config.api_url = url
        config.api_token = token
        
        if config.save_config():
            # 更新API客户端
            api_client.update_credentials(url, token)
            QMessageBox.information(self, "保存成功", "配置已保存")
            self.accept()
        else:
            QMessageBox.critical(self, "保存失败", "配置保存失败，请检查文件权限") 