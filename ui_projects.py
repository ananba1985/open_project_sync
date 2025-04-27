from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QListWidget, QListWidgetItem, QMessageBox, 
                            QProgressBar, QSplitter, QComboBox, QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from api_client import api_client

class LoadProjectsThread(QThread):
    """加载项目列表的线程"""
    projects_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, force_refresh=False, page=1, page_size=100):
        super().__init__()
        self.force_refresh = force_refresh
        self.page = page
        self.page_size = page_size
    
    def run(self):
        try:
            projects = api_client.get_projects(force_refresh=self.force_refresh, page=self.page, page_size=self.page_size)
            self.projects_loaded.emit(projects)
        except Exception as e:
            self.error_occurred.emit(str(e))

class ProjectListWidget(QWidget):
    """项目列表界面"""
    project_selected = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.projects = []
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 标题和刷新按钮
        header_layout = QHBoxLayout()
        title_label = QLabel("项目列表")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.refresh_btn = QPushButton("刷新")
        self.force_refresh_chk = QCheckBox("强制刷新")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.force_refresh_chk)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)
        
        # 项目列表
        self.project_list = QListWidget()
        self.project_list.setAlternatingRowColors(True)
        self.project_list.setMaximumWidth(350)  # 限制最大宽度
        
        # 分页控制
        page_layout = QHBoxLayout()
        page_layout.addWidget(QLabel("每页显示:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["50", "100", "200", "全部"])
        self.page_size_combo.setCurrentIndex(1)  # 默认100
        page_layout.addWidget(self.page_size_combo)
        
        self.prev_page_btn = QPushButton("上一页")
        self.next_page_btn = QPushButton("下一页")
        self.page_label = QLabel("第1页")
        
        page_layout.addStretch()
        page_layout.addWidget(self.prev_page_btn)
        page_layout.addWidget(self.page_label)
        page_layout.addWidget(self.next_page_btn)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        layout.addWidget(self.project_list)
        layout.addLayout(page_layout)
        layout.addWidget(self.progress_bar)
        
        self.setLayout(layout)
        self.setMaximumWidth(350)  # 限制整个控件的最大宽度
        
        # 初始状态
        self.current_page = 1
        self.prev_page_btn.setEnabled(False)
        
        # 连接信号
        self.refresh_btn.clicked.connect(lambda: self.load_projects(force_refresh=self.force_refresh_chk.isChecked()))
        self.project_list.itemClicked.connect(self.on_project_clicked)
        self.prev_page_btn.clicked.connect(self.load_prev_page)
        self.next_page_btn.clicked.connect(self.load_next_page)
        self.page_size_combo.currentIndexChanged.connect(self.on_page_size_changed)
        
    def load_projects(self, force_refresh=False):
        """加载项目列表"""
        self.project_list.clear()
        self.progress_bar.setVisible(True)
        
        # 获取当前选择的页面大小
        page_size = self.get_current_page_size()
        
        # 创建线程加载项目
        self.load_thread = LoadProjectsThread(force_refresh=force_refresh, page=self.current_page, page_size=page_size)
        self.load_thread.projects_loaded.connect(self.update_project_list)
        self.load_thread.error_occurred.connect(self.handle_error)
        self.load_thread.finished.connect(lambda: self.progress_bar.setVisible(False))
        self.load_thread.start()
    
    def get_current_page_size(self):
        """获取当前选择的页面大小"""
        page_size_text = self.page_size_combo.currentText()
        if page_size_text == "全部":
            return 1000  # 一个较大的数，实际上会返回所有项目
        return int(page_size_text)
    
    def load_prev_page(self):
        """加载上一页"""
        if self.current_page > 1:
            self.current_page -= 1
            self.page_label.setText(f"第{self.current_page}页")
            self.load_projects()
            
        # 更新按钮状态
        self.prev_page_btn.setEnabled(self.current_page > 1)
    
    def load_next_page(self):
        """加载下一页"""
        self.current_page += 1
        self.page_label.setText(f"第{self.current_page}页")
        self.load_projects()
        
        # 更新按钮状态
        self.prev_page_btn.setEnabled(True)
    
    def on_page_size_changed(self):
        """页面大小改变时重新加载"""
        self.current_page = 1
        self.page_label.setText(f"第{self.current_page}页")
        self.prev_page_btn.setEnabled(False)
        self.load_projects()
    
    def update_project_list(self, projects):
        """更新项目列表"""
        self.projects = projects
        
        for project in projects:
            item = QListWidgetItem(project.get("name", "未命名项目"))
            item.setData(Qt.UserRole, project)
            self.project_list.addItem(item)
            
        # 如果没有加载到项目，禁用下一页按钮
        self.next_page_btn.setEnabled(len(projects) > 0)
    
    def handle_error(self, error_msg):
        """处理错误"""
        QMessageBox.critical(self, "加载失败", f"加载项目列表失败: {error_msg}")
        self.progress_bar.setVisible(False)
    
    def on_project_clicked(self, item):
        """项目被点击时"""
        project_data = item.data(Qt.UserRole)
        if project_data:
            self.project_selected.emit(project_data) 