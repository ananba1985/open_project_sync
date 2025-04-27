from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, 
                            QProgressBar, QFileDialog, QComboBox, QGroupBox,
                            QFormLayout, QLineEdit, QCheckBox, QProgressDialog,
                            QTabWidget, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
import json
import os
from api_client import api_client
import traceback
import concurrent.futures

class ExportThread(QThread):
    """项目导出线程"""
    progress_update = pyqtSignal(int, str)  # 进度信息 - 修正为与ImportThread一致的顺序：(进度值, 消息)
    export_completed = pyqtSignal(str)  # 导出完成，参数是文件路径
    error_occurred = pyqtSignal(str)  # 错误信息
    
    def __init__(self, project_id, file_path, include_work_packages=True, include_relations=True, include_comments=True, include_statuses=True):
        super().__init__()
        self.project_id = project_id
        self.file_path = file_path
        self.include_work_packages = include_work_packages
        self.include_relations = include_relations
        self.include_comments = include_comments
        self.include_statuses = include_statuses
    
    def run(self):
        try:
            # 导出项目基本信息
            self.progress_update.emit(5, "正在获取项目基本信息...")
            project_details = api_client.get_project_details(self.project_id)
            
            if not project_details:
                self.error_occurred.emit("无法获取项目详情")
                return
                
            self.progress_update.emit(10, f"正在导出项目: {project_details.get('name', 'Unknown')}...")
            
            # 获取项目表单配置（包含更详细的自定义字段信息）
            self.progress_update.emit(12, "正在获取项目表单配置...")
            project_form_config = api_client.get_project_form_configuration(self.project_id)
            
            # 准备导出数据结构
            export_data = {
                "project": project_details,
                "project_form_config": project_form_config,
                "work_packages": [],
                "custom_fields": [],
                "statuses": [],
                "types": [],
                "export_version": "1.0"
            }
            
            # 获取自定义字段
            self.progress_update.emit(15, "正在获取自定义字段...")
            custom_fields = api_client.get_custom_fields()
            if custom_fields:
                export_data["custom_fields"] = custom_fields
            
            # 获取状态和类型
            self.progress_update.emit(20, "正在获取状态和类型数据...")
            statuses = api_client.get_statuses()
            if statuses:
                export_data["statuses"] = statuses
                
            types = api_client.get_types()
            if types:
                export_data["types"] = types
            
            # 如果需要包含工作包
            if self.include_work_packages:
                self.progress_update.emit(30, "正在获取工作包数据...")
                
                # 首先获取项目测试工作包以确定总数
                self.progress_update.emit(32, "正在确定工作包总数...")
                page_size = 50  # 初始较小的页面大小
                test_packages = api_client.get_work_packages(self.project_id, page=1, page_size=page_size)
                
                if test_packages is not None:
                    # 通过第一次请求获取总数信息
                    total_count = api_client.get_last_work_packages_total()
                    if total_count > 0:
                        # 设置合适的页面大小，确保一次能获取所有，并添加一些余量
                        page_size = total_count + 50
                        self.progress_update.emit(35, f"项目包含 {total_count} 个工作包，调整页面大小为 {page_size}")
                    else:
                        # 如果无法获取总数，使用较大的默认值
                        page_size = 500
                else:
                    # 如果测试请求失败，使用默认值
                    page_size = 500
                
                # 使用动态计算的页面大小，一次性获取所有工作包
                self.progress_update.emit(38, f"正在获取所有工作包，页面大小: {page_size}...")
                work_packages = api_client.get_work_packages(self.project_id, page=1, page_size=page_size)
                
                if work_packages:
                    self.progress_update.emit(45, f"成功获取 {len(work_packages)} 个工作包")
                    export_data["work_packages"] = work_packages
            
            # 写入导出文件
            self.progress_update.emit(90, "正在写入导出文件...")
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            self.progress_update.emit(100, "导出完成!")
            self.export_completed.emit(self.file_path)
            
        except Exception as e:
            error_msg = f"导出过程中出错: {str(e)}\n{traceback.format_exc()}"
            self.error_occurred.emit(error_msg)

    def get_work_packages_details_parallel(self, work_package_ids, max_workers=10):
        """并行获取多个工作包的详细信息"""
        results = {}
        
        def fetch_wp_details(wp_id):
            try:
                wp_details = api_client.get_work_package(wp_id)
                return wp_id, wp_details
            except Exception as e:
                print(f"获取工作包 {wp_id} 详情出错: {str(e)}")
                return wp_id, None
        
        # 使用线程池并行获取
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_id = {executor.submit(fetch_wp_details, wp_id): wp_id for wp_id in work_package_ids}
            
            # 处理完成的任务
            for i, future in enumerate(concurrent.futures.as_completed(future_to_id)):
                wp_id = future_to_id[future]
                try:
                    result_id, wp_details = future.result()
                    results[result_id] = wp_details
                    
                    # 更新进度
                    progress = int(55 + (i / len(work_package_ids)) * 5)  # 55-60% 的进度区间
                    self.progress_update.emit(progress, f"已获取 {i+1}/{len(work_package_ids)} 个工作包详情")
                except Exception as e:
                    print(f"处理工作包 {wp_id} 结果时出错: {str(e)}")
        
        return results

class ImportThread(QThread):
    """项目导入线程"""
    progress_update = pyqtSignal(int, str)  # 进度信息 - 修正参数顺序：(进度值, 消息)
    import_completed = pyqtSignal(str)  # 导入完成，参数是项目ID
    error_occurred = pyqtSignal(str)  # 错误信息
    
    def __init__(self, file_path, project_name=None, force_relations=False):
        super().__init__()
        self.file_path = file_path
        self.project_name = project_name
        self.force_relations = force_relations
    
    def run(self):
        try:
            self.progress_update.emit(5, "正在读取导入文件...")
            
            # 读取导入文件
            with open(self.file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            # 检查数据版本
            export_version = import_data.get("export_version", "未知")
            self.progress_update.emit(10, f"文件版本: {export_version}")
            
            # 准备导入参数
            params = {
                "project_data": import_data,
                "new_name": self.project_name,
                "import_options": {
                    "force_relations": self.force_relations
                }
            }
            
            # 开始导入
            self.progress_update.emit(15, "开始导入项目...")
            self.import_project_with_data(params)
            
        except Exception as e:
            error_msg = f"导入过程中出错: {str(e)}\n{traceback.format_exc()}"
            self.error_occurred.emit(error_msg)
    
    def import_project_with_data(self, params):
        """执行项目导入"""
        project_data = params.get("project_data", {})
        new_name = params.get("new_name")
        import_options = params.get("import_options", {})
        
        if not project_data:
            self.error_occurred.emit("导入数据为空")
            return
            
        # 获取原始项目信息
        project = project_data.get("project", {})
        if not project:
            self.error_occurred.emit("项目数据为空")
            return
            
        self.progress_update.emit(20, f"正在导入项目: {new_name or project.get('name', '未命名项目')}")
        
        # 进度回调函数，用于接收导入过程中的进度更新
        def progress_callback(stage, current, total, message):
            # 根据阶段计算进度百分比
            # 30-70% 用于创建工作包
            # 70-100% 用于处理关系
            progress = 0
            if stage == "create_packages":
                if total > 0:
                    progress = 30 + (current / total) * 40
                else:
                    progress = 50
            elif stage == "create_relations":
                if total > 0:
                    progress = 70 + (current / total) * 30
                else:
                    progress = 85
            elif stage == "finalize":
                progress = 95
                
            self.progress_update.emit(int(progress), message)
            
        # 调用API客户端导入项目
        try:
            result = api_client.import_project(
                project_data, 
                new_name=new_name, 
                import_options=import_options,
                progress_callback=progress_callback
            )
            
            if result and "id" in result:
                project_id = result["id"]
                self.progress_update.emit(100, f"导入完成! 项目ID: {project_id}")
                self.import_completed.emit(project_id)
            else:
                error = result.get("error", "未知错误")
                self.error_occurred.emit(f"导入失败: {error}")
                
        except Exception as e:
            self.error_occurred.emit(f"导入出错: {str(e)}")

class ExportImportWidget(QWidget):
    """项目导出导入界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.current_project = None
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("项目导出导入")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title_label)
        
        # 创建标签页
        tabs = QTabWidget()
        
        # 导出标签页
        export_tab = QWidget()
        export_layout = QVBoxLayout()
        
        # 导出 - 项目选择
        export_project_group = QGroupBox("选择要导出的项目")
        export_project_layout = QFormLayout()
        self.export_project_combo = QComboBox()
        self.export_project_combo.setMinimumWidth(300)
        self.export_refresh_btn = QPushButton("刷新")
        
        project_layout = QHBoxLayout()
        project_layout.addWidget(self.export_project_combo)
        project_layout.addWidget(self.export_refresh_btn)
        
        export_project_layout.addRow("项目:", project_layout)
        export_project_group.setLayout(export_project_layout)
        export_layout.addWidget(export_project_group)
        
        # 导出 - 导出选项
        export_options_group = QGroupBox("导出选项")
        export_options_layout = QVBoxLayout()
        
        self.include_wp_check = QCheckBox("包含工作包")
        self.include_wp_check.setChecked(True)
        self.include_relations_check = QCheckBox("包含工作包关系")
        self.include_relations_check.setChecked(True)
        self.include_comments_check = QCheckBox("包含评论")
        self.include_comments_check.setChecked(True)
        self.include_statuses_check = QCheckBox("包含状态")
        self.include_statuses_check.setChecked(True)
        
        export_options_layout.addWidget(self.include_wp_check)
        export_options_layout.addWidget(self.include_relations_check)
        export_options_layout.addWidget(self.include_comments_check)
        export_options_layout.addWidget(self.include_statuses_check)
        
        export_options_group.setLayout(export_options_layout)
        export_layout.addWidget(export_options_group)
        
        # 导出 - 导出按钮
        self.export_btn = QPushButton("导出项目")
        self.export_btn.setMinimumHeight(40)
        export_layout.addWidget(self.export_btn)
        
        # 添加进度条
        self.export_progress = QProgressBar()
        self.export_progress.setVisible(False)
        export_layout.addWidget(self.export_progress)
        
        # 导出状态标签
        self.export_status_label = QLabel("")
        export_layout.addWidget(self.export_status_label)
        
        export_layout.addStretch()
        export_tab.setLayout(export_layout)
        
        # 导入标签页
        import_tab = QWidget()
        import_layout = QVBoxLayout()
        
        # 导入 - 文件选择
        import_file_group = QGroupBox("选择要导入的文件")
        import_file_layout = QHBoxLayout()
        self.import_file_path = QLineEdit()
        self.import_file_path.setReadOnly(True)
        self.import_browse_btn = QPushButton("浏览...")
        
        import_file_layout.addWidget(self.import_file_path)
        import_file_layout.addWidget(self.import_browse_btn)
        import_file_group.setLayout(import_file_layout)
        import_layout.addWidget(import_file_group)
        
        # 导入 - 项目名称
        import_name_group = QGroupBox("项目名称")
        import_name_layout = QFormLayout()
        self.import_project_name = QLineEdit()
        self.import_project_name.setPlaceholderText("留空使用原始项目名称")
        import_name_layout.addRow("新项目名称:", self.import_project_name)
        import_name_group.setLayout(import_name_layout)
        import_layout.addWidget(import_name_group)
        
        # 导入 - 导入选项
        import_options_group = QGroupBox("导入选项")
        import_options_layout = QVBoxLayout()
        self.force_relations_check = QCheckBox("强制创建关系（即使引用的工作包不存在）")
        import_options_layout.addWidget(self.force_relations_check)
        import_options_group.setLayout(import_options_layout)
        import_layout.addWidget(import_options_group)
        
        # 导入 - 导入按钮
        self.import_btn = QPushButton("导入项目")
        self.import_btn.setMinimumHeight(40)
        import_layout.addWidget(self.import_btn)
        
        # 添加进度条
        self.import_progress = QProgressBar()
        self.import_progress.setVisible(False)
        import_layout.addWidget(self.import_progress)
        
        # 导入状态标签
        self.import_status_label = QLabel("")
        import_layout.addWidget(self.import_status_label)
        
        import_layout.addStretch()
        import_tab.setLayout(import_layout)
        
        # 添加标签页
        tabs.addTab(export_tab, "导出项目")
        tabs.addTab(import_tab, "导入项目")
        
        layout.addWidget(tabs)
        self.setLayout(layout)
        
        # 连接信号
        self.export_refresh_btn.clicked.connect(self.load_projects)
        self.export_btn.clicked.connect(self.export_project)
        self.import_browse_btn.clicked.connect(self.browse_import_file)
        self.import_btn.clicked.connect(self.import_project)
    
    def load_projects(self):
        """加载项目列表"""
        self.export_project_combo.clear()
        self.export_status_label.setText("正在加载项目列表...")
        
        # 获取项目列表
        projects = api_client.get_projects(force_refresh=True)
        
        if projects:
            for project in projects:
                self.export_project_combo.addItem(project.get("name", "未命名项目"), project)
            
            self.export_status_label.setText(f"已加载 {len(projects)} 个项目")
        else:
            self.export_status_label.setText("未找到项目或加载失败")
    
    def set_current_project(self, project):
        """设置当前选中的项目"""
        self.current_project = project
        
        # 如果项目列表为空，加载项目
        if self.export_project_combo.count() == 0:
            self.load_projects()
            return
            
        # 如果有指定项目，选中它
        if project:
            for i in range(self.export_project_combo.count()):
                item_data = self.export_project_combo.itemData(i)
                if item_data and item_data.get("id") == project.get("id"):
                    self.export_project_combo.setCurrentIndex(i)
                    break
    
    def update_project_list(self, projects):
        """更新项目列表（由外部调用）"""
        if not projects:
            return
            
        self.export_project_combo.clear()
        
        for project in projects:
            self.export_project_combo.addItem(project.get("name", "未命名项目"), project)
            
        self.export_status_label.setText(f"已加载 {len(projects)} 个项目")
        
        # 如果有当前项目，尝试重新选中
        if self.current_project:
            self.set_current_project(self.current_project)
    
    def browse_import_file(self):
        """浏览要导入的文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件", "", "JSON文件 (*.json)"
        )
        
        if file_path:
            self.import_file_path.setText(file_path)
            
            # 尝试从文件名生成项目名称建议
            file_name = os.path.basename(file_path)
            name_suggestion = os.path.splitext(file_name)[0]
            
            # 如果文件名是合理的项目名，填入建议
            if name_suggestion and name_suggestion.lower() != "export" and len(name_suggestion) > 3:
                self.import_project_name.setText(name_suggestion)
    
    def export_project(self):
        """导出项目"""
        # 获取选中的项目
        current_index = self.export_project_combo.currentIndex()
        if current_index < 0:
            QMessageBox.warning(self, "未选择项目", "请选择要导出的项目")
            return
            
        project = self.export_project_combo.itemData(current_index)
        if not project:
            QMessageBox.warning(self, "项目数据缺失", "无法获取项目数据")
            return
            
        project_id = project.get("id")
        project_name = project.get("name", "未命名项目")
        
        if not project_id:
            QMessageBox.warning(self, "项目ID缺失", "无法获取项目ID")
            return
            
        # 获取导出选项
        include_wp = self.include_wp_check.isChecked()
        include_relations = self.include_relations_check.isChecked()
        include_comments = self.include_comments_check.isChecked()
        include_statuses = self.include_statuses_check.isChecked()
        
        # 选择保存文件
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存导出文件", f"{project_name}_export.json", "JSON文件 (*.json)"
        )
        
        if not file_path:
            return
            
        # 创建并启动导出线程
        self.export_thread = ExportThread(
            project_id, file_path,
            include_work_packages=include_wp,
            include_relations=include_relations,
            include_comments=include_comments,
            include_statuses=include_statuses
        )
        
        self.export_thread.progress_update.connect(self.update_progress)
        self.export_thread.export_completed.connect(self.on_export_completed)
        self.export_thread.error_occurred.connect(self.on_export_error)
        
        # 更新UI状态
        self.export_progress.setValue(0)
        self.export_progress.setVisible(True)
        self.export_status_label.setText("正在导出...")
        self.export_btn.setEnabled(False)
        
        # 启动线程
        self.export_thread.start()
    
    def import_project(self):
        """导入项目"""
        file_path = self.import_file_path.text()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "文件错误", "请选择有效的导入文件")
            return
            
        project_name = self.import_project_name.text().strip()
        force_relations = self.force_relations_check.isChecked()
        
        # 创建并启动导入线程
        self.import_thread = ImportThread(
            file_path, 
            project_name=project_name if project_name else None,
            force_relations=force_relations
        )
        
        self.import_thread.progress_update.connect(self.update_progress)
        self.import_thread.import_completed.connect(self.on_import_completed)
        self.import_thread.error_occurred.connect(self.on_import_error)
        
        # 更新UI状态
        self.import_progress.setValue(0)
        self.import_progress.setVisible(True)
        self.import_status_label.setText("正在导入...")
        self.import_btn.setEnabled(False)
        
        # 启动线程
        self.import_thread.start()
    
    def update_progress(self, value, message):
        """更新进度条和状态消息"""
        if hasattr(self.sender(), "objectName") and self.sender().objectName() == "ExportThread":
            self.export_progress.setValue(value)
            self.export_status_label.setText(message)
        else:
            self.import_progress.setValue(value)
            self.import_status_label.setText(message)
    
    def on_export_completed(self, file_path):
        """导出完成的处理"""
        self.export_btn.setEnabled(True)
        self.export_status_label.setText(f"导出完成! 文件已保存: {file_path}")
        QMessageBox.information(self, "导出成功", f"项目已成功导出到:\n{file_path}")
    
    def on_export_error(self, error_msg):
        """导出错误的处理"""
        self.export_btn.setEnabled(True)
        self.export_status_label.setText(f"导出失败!")
        QMessageBox.critical(self, "导出失败", f"导出过程中出错:\n{error_msg}")
    
    def on_import_completed(self, project_id):
        """导入完成的处理"""
        self.import_btn.setEnabled(True)
        self.import_status_label.setText(f"导入完成! 项目ID: {project_id}")
        QMessageBox.information(self, "导入成功", f"项目已成功导入，ID: {project_id}")
        
        # 刷新项目列表
        self.load_projects()
    
    def on_import_error(self, error_msg):
        """导入错误的处理"""
        self.import_btn.setEnabled(True)
        self.import_status_label.setText(f"导入失败!")
        QMessageBox.critical(self, "导入失败", f"导入过程中出错:\n{error_msg}")