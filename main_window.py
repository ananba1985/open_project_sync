from PyQt5.QtWidgets import (QMainWindow, QSplitter, QAction, QMessageBox,
                            QStatusBar, QMenu, QVBoxLayout, QWidget, QLabel, QTabWidget)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon

from config import config
from api_client import api_client
from ui_config import ConfigDialog
from ui_projects import ProjectListWidget
from ui_workpackage import WorkPackageWidget
from ui_export_import import ExportImportWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenProject 数据同步工具")
        self.setMinimumSize(1000, 600)
        
        self.setup_ui()
        self.setup_menu()
        
        # 初始加载
        QTimer.singleShot(100, self.initial_load)
        
    def setup_ui(self):
        # 创建状态栏
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        # 创建加载状态标签
        self.status_label = QLabel("就绪")
        self.statusbar.addPermanentWidget(self.status_label)
        
        # 创建主窗口部件
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # 创建标签页控件
        self.tab_widget = QTabWidget()
        
        # 创建工作任务标签页
        self.task_tab = QWidget()
        task_layout = QVBoxLayout()
        self.task_tab.setLayout(task_layout)
        
        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        
        # 创建项目列表部件
        self.project_list = ProjectListWidget()
        
        # 创建工作包部件
        self.work_package_widget = WorkPackageWidget()
        
        # 添加部件到分割器
        splitter.addWidget(self.project_list)
        splitter.addWidget(self.work_package_widget)
        
        # 设置分割器大小比例（左侧项目列表占30%，右侧工作包区域占70%）
        splitter.setSizes([300, 700])
        
        # 添加分割器到任务布局
        task_layout.addWidget(splitter)
        
        # 添加标签页到标签页控件
        self.tab_widget.addTab(self.task_tab, "任务管理")
        
        # 创建项目导出导入标签页
        self.export_import_widget = ExportImportWidget()
        self.tab_widget.addTab(self.export_import_widget, "项目导出导入")
        
        # 添加标签页控件到主布局
        main_layout.addWidget(self.tab_widget)
        
        # 连接信号
        self.project_list.project_selected.connect(self.on_project_selected)
        
        # 连接加载状态信号
        self.connect_loading_signals()
        
    def connect_loading_signals(self):
        """连接加载状态信号"""
        # 项目列表加载状态
        if hasattr(self.project_list, 'load_thread'):
            self.project_list.load_thread.started.connect(lambda: self.update_status("正在加载项目列表..."))
            self.project_list.load_thread.finished.connect(lambda: self.update_status("项目列表加载完成"))
            self.project_list.load_thread.error_occurred.connect(lambda msg: self.update_status(f"加载失败: {msg}"))
        
        # 工作包加载状态
        if hasattr(self.work_package_widget, 'load_thread'):
            self.work_package_widget.load_thread.started.connect(lambda: self.update_status("正在加载工作包..."))
            self.work_package_widget.load_thread.finished.connect(lambda: self.update_status("工作包加载完成"))
            self.work_package_widget.load_thread.error_occurred.connect(lambda msg: self.update_status(f"加载失败: {msg}"))
            
    def update_status(self, message):
        """更新状态栏消息"""
        self.status_label.setText(message)
        # 同时显示临时消息
        self.statusbar.showMessage(message, 3000)
        
    def initial_load(self):
        """初始加载数据"""
        if config.is_configured():
            # 显示主窗口后在后台刷新数据
            self.update_status("准备加载数据...")
            QTimer.singleShot(100, self.refresh_data)
        else:
            self.update_status("请先配置API设置")
            self.show_config_dialog()
        
    def setup_menu(self):
        """设置菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        # 配置操作
        config_action = QAction("设置", self)
        config_action.triggered.connect(self.show_config_dialog)
        file_menu.addAction(config_action)
        
        # 刷新操作
        refresh_action = QAction("刷新", self)
        refresh_action.triggered.connect(self.refresh_data)
        file_menu.addAction(refresh_action)
        
        # 导出导入菜单
        export_import_menu = file_menu.addMenu("导出导入")
        
        # 导出操作
        export_action = QAction("导出项目", self)
        export_action.triggered.connect(lambda: self.switch_to_export_tab())
        export_import_menu.addAction(export_action)
        
        # 导入操作
        import_action = QAction("导入项目", self)
        import_action.triggered.connect(lambda: self.switch_to_export_tab())
        export_import_menu.addAction(import_action)
        
        # 退出操作
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图")
        
        # 任务管理视图
        tasks_action = QAction("任务管理", self)
        tasks_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(0))
        view_menu.addAction(tasks_action)
        
        # 导出导入视图
        export_import_action = QAction("项目导出导入", self)
        export_import_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(1))
        view_menu.addAction(export_import_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        # 关于操作
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def switch_to_export_tab(self):
        """切换到导出导入标签页"""
        self.tab_widget.setCurrentIndex(1)
    
    def show_config_dialog(self):
        """显示配置对话框"""
        dialog = ConfigDialog(self)
        result = dialog.exec_()
        
        # 如果配置已更新，则刷新数据
        if result and config.is_configured():
            self.statusbar.showMessage("配置已更新", 3000)
            self.refresh_data()
    
    def refresh_data(self):
        """刷新数据"""
        if not config.is_configured():
            self.show_config_dialog()
            return
        
        self.update_status("开始加载数据...")
        
        # 异步加载项目列表，不阻塞界面
        self.project_list.load_projects(force_refresh=True)
        
        # 更新导出导入标签页的项目列表 - 这里使用延迟加载，等项目列表加载完后再更新
        def update_export_import_projects():
            projects = api_client.get_projects(force_refresh=False)  # 使用缓存的项目列表
            self.export_import_widget.update_project_list(projects)
            
        # 延迟更新导出导入标签页
        QTimer.singleShot(500, update_export_import_projects)
        
        # 重新连接信号（因为每次load_projects都会创建新的线程）
        QTimer.singleShot(100, self.connect_loading_signals)
    
    def on_project_selected(self, project):
        """当项目被选中时"""
        self.update_status(f"已选择项目: {project.get('name', '')}")
        
        # 更新工作包视图
        self.work_package_widget.set_project(project)
        
        # 更新导出导入标签页的当前项目
        self.export_import_widget.set_current_project(project)
        
        # 重新连接信号
        QTimer.singleShot(100, self.connect_loading_signals)
    
    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于", 
                         "OpenProject 数据同步工具\n\n"
                         "这是一个用于管理OpenProject项目和工作包的工具。\n"
                         "版本: 1.0.0")
    
    def closeEvent(self, event):
        """关闭窗口事件"""
        reply = QMessageBox.question(self, '确认退出', 
                                     "确定要退出程序吗?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore() 