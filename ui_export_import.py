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
            
            # 获取自定义字段选项
            self.progress_update.emit(17, "正在获取自定义字段选项...")
            custom_field_options = {}
            for field in custom_fields:
                field_id = field.get("id")
                if field_id:
                    options = api_client.get_custom_field_options(field_id)
                    if options:
                        custom_field_options[field_id] = options
            
            export_data["custom_field_options"] = custom_field_options
            
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
                
                # 使用与LoadWorkPackagesThread相同的流程获取全量工作包
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
                    
                    # 保存工作包ID以便后续查找
                    work_package_ids = {wp.get("id") for wp in work_packages if "id" in wp}
                    
                    # 检查是否有子任务引用
                    self.progress_update.emit(50, "正在检查子任务引用...")
                    referenced_ids = set()
                    
                    # 收集所有子任务和父任务ID
                    for wp in work_packages:
                        # 检查子任务
                        if "_links" in wp and "children" in wp["_links"]:
                            children = wp["_links"]["children"]
                            if isinstance(children, list):
                                for child in children:
                                    if isinstance(child, dict) and "href" in child:
                                        # 从href提取ID
                                        try:
                                            href = child["href"]
                                            child_id = int(href.split("/")[-1])
                                            referenced_ids.add(child_id)
                                        except (ValueError, IndexError):
                                            pass
                                            
                        # 检查父任务
                        if "_links" in wp and "parent" in wp["_links"]:
                            parent = wp["_links"]["parent"]
                            if isinstance(parent, dict) and "href" in parent:
                                href = parent["href"]
                                if href:  # 确保href不是None
                                    try:
                                        parent_id = int(href.split("/")[-1])
                                        referenced_ids.add(parent_id)
                                    except (ValueError, IndexError):
                                        pass
                    
                    # 找出缺失的引用任务
                    missing_referenced_ids = [id for id in referenced_ids if id not in work_package_ids]
                    if missing_referenced_ids:
                        missing_count = len(missing_referenced_ids)
                        self.progress_update.emit(55, f"正在获取 {missing_count} 个引用任务...")
                        
                        # 并行获取被引用的工作包详情
                        referenced_details = self.get_work_packages_details_parallel(missing_referenced_ids)
                        
                        # 添加获取到的工作包
                        added_count = 0
                        for wp_id, wp_data in referenced_details.items():
                            if wp_data:
                                work_packages.append(wp_data)
                                work_package_ids.add(wp_id)
                                added_count += 1
                        
                        self.progress_update.emit(60, f"已添加 {added_count} 个引用任务")
                    
                    # 检查工作包状态完整性
                    self.progress_update.emit(65, "正在验证工作包状态...")
                    packages_without_status = []
                    
                    for wp in work_packages:
                        wp_id = wp.get("id", "未知")
                        has_complete_status = False
                        
                        if "_links" in wp and "status" in wp["_links"]:
                            status_link = wp["_links"]["status"]
                            if isinstance(status_link, dict) and "title" in status_link and "href" in status_link:
                                has_complete_status = True
                        
                        if not has_complete_status:
                            packages_without_status.append(wp_id)
                    
                    # 获取缺少状态的工作包详细信息
                    if packages_without_status:
                        missing_count = len(packages_without_status)
                        self.progress_update.emit(70, f"正在获取 {missing_count} 个缺少状态的工作包...")
                        
                        # 并行获取缺少状态的工作包详情
                        detailed_packages = self.get_work_packages_details_parallel(packages_without_status)
                        
                        # 更新工作包信息
                        updated_count = 0
                        for wp_id, detailed_wp in detailed_packages.items():
                            if detailed_wp:
                                # 找到原来的工作包并更新，如果不存在则添加
                                updated = False
                                for i, wp in enumerate(work_packages):
                                    if wp.get("id") == wp_id:
                                        work_packages[i] = detailed_wp
                                        updated = True
                                        updated_count += 1
                                        break
                                
                                if not updated:
                                    # 如果未找到现有的工作包，则添加新的
                                    work_packages.append(detailed_wp)
                                    updated_count += 1
                        
                        self.progress_update.emit(75, f"已更新 {updated_count} 个工作包状态")
                    
                    # 确保没有重复的工作包
                    unique_wps = {}
                    for wp in work_packages:
                        wp_id = wp.get("id")
                        if wp_id is not None:
                            unique_wps[wp_id] = wp
                    
                    # 转换回列表
                    work_packages_final = list(unique_wps.values())
                    self.progress_update.emit(80, f"整理完成，共 {len(work_packages_final)} 个工作包")
                    
                    # 添加到导出数据
                    export_data["work_packages"] = work_packages_final
                else:
                    self.progress_update.emit(80, "没有找到工作包")
            
            # 将数据写入文件
            self.progress_update.emit(90, "正在写入文件...")
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            self.progress_update.emit(100, "导出完成")
            self.export_completed.emit(self.file_path)
            
        except Exception as e:
            error_msg = f"导出失败: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            self.error_occurred.emit(error_msg)
    
    def get_work_packages_details_parallel(self, work_package_ids, max_workers=10):
        """并行获取多个工作包的详细信息
        
        Args:
            work_package_ids: 工作包ID列表
            max_workers: 最大并行线程数
            
        Returns:
            dict: 以工作包ID为键，工作包详情为值的字典
        """
        if not work_package_ids:
            return {}
            
        results = {}
        
        # 使用线程池并行获取
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_id = {
                executor.submit(api_client.get_work_package, wp_id): wp_id 
                for wp_id in work_package_ids
            }
            
            # 处理完成的任务
            completed = 0
            total_count = len(work_package_ids)
            for future in concurrent.futures.as_completed(future_to_id):
                wp_id = future_to_id[future]
                completed += 1
                
                try:
                    data = future.result()
                    results[wp_id] = data
                except Exception as e:
                    results[wp_id] = None
                
                # 更新进度
                if completed % 5 == 0 or completed == total_count:
                    self.progress_update.emit(55 + int(15 * completed / total_count), f"已处理 {completed}/{total_count} 个工作包")
        
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
            self.progress_update.emit(10, f"正在读取文件 {self.file_path}")
            
            # 读取文件
            with open(self.file_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            self.progress_update.emit(20, "文件已加载，准备导入项目")
            
            # 创建参数字典
            params = {
                'project_data': project_data,
                'new_name': self.project_name,
                'force_relations': self.force_relations
            }
            
            # 导入项目
            new_project_id = self.import_project_with_data(params)
            
            if new_project_id:
                self.import_completed.emit(new_project_id)
                self.progress_update.emit(100, f"项目导入成功，ID: {new_project_id}")
            else:
                error_msg = "导入失败，未能获取新项目ID"
                self.progress_update.emit(0, error_msg)
                self.error_occurred.emit(error_msg)
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            error_msg = f"导入过程出错: {str(e)}"
            self.progress_update.emit(0, error_msg)
            self.error_occurred.emit(f"{error_msg}\n\n详细错误:\n{error_details}")

    def import_project_with_data(self, params):
        """
        执行项目导入
        
        Args:
            params: 导入参数
                - project_data: 项目数据
                - new_name: 新项目名称
                - force_relations: 是否强制处理关系
        
        Returns:
            创建的项目ID
        """
        project_data = params.get('project_data')
        new_name = params.get('new_name')
        force_relations = params.get('force_relations', False)
        
        if not project_data:
            self.error_occurred.emit("无效的项目数据")
            return None
        
        # 收集类型映射
        type_mapping = {}
        
        # 收集状态映射
        status_mapping = {}
        
        # 获取现有类型和状态
        try:
            # 获取类型
            types = api_client.get_types()
            if types:
                for t in types:
                    type_name = t.get("name", "")
                    type_id = t.get("id")
                    if type_name and type_id:
                        type_mapping[type_name] = type_id
            
            # 获取状态
            statuses = api_client.get_statuses()
            if statuses:
                for s in statuses:
                    status_name = s.get("name", "")
                    status_id = s.get("id")
                    if status_name and status_id:
                        status_mapping[status_name] = status_id
                        
        except Exception as e:
            self.progress_update.emit(20, f"获取类型和状态出错: {str(e)}")
        
        # 进度回调函数
        def progress_callback(stage, current, total, message):
            # 根据阶段计算进度百分比
            # 30-70% 用于创建工作包
            # 70-100% 用于处理关系
            
            if stage == "创建项目":
                progress = 30 * (current / total)
            elif stage == "创建工作包":
                progress = 30 + 40 * (current / total)
            elif stage == "处理关系":
                progress = 70 + 30 * (current / total)
            else:
                progress = 20  # 默认20%的进度
            
            # 发送进度更新
            self.progress_update.emit(int(progress), message)
        
        # 创建导入选项
        import_options = {
            "progress_callback": progress_callback,
            "type_mapping": type_mapping,
            "status_mapping": status_mapping,
            "force_relations": force_relations  # 添加强制处理关系选项
        }
        
        # 执行导入
        new_project_id = api_client.import_project(project_data, new_name, import_options)
        
        # 确保返回的是字符串类型
        return str(new_project_id) if new_project_id else None


class ExportImportWidget(QWidget):
    """项目导出/导入界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_project = None
        self.setup_ui()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("项目导出与导入")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title_label)
        
        # 创建导出组
        export_group = QGroupBox("导出项目")
        export_layout = QVBoxLayout()
        
        # 导出选项
        export_options_form = QFormLayout()
        
        # 选择项目下拉框
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(300)
        export_options_form.addRow("选择项目:", self.project_combo)
        
        # 导出选项复选框
        self.include_wp_checkbox = QCheckBox("包含工作包")
        self.include_wp_checkbox.setChecked(True)
        self.include_relations_checkbox = QCheckBox("包含关系")
        self.include_relations_checkbox.setChecked(True)
        self.include_comments_checkbox = QCheckBox("包含评论")
        self.include_comments_checkbox.setChecked(True)
        self.include_statuses_checkbox = QCheckBox("包含状态")
        self.include_statuses_checkbox.setChecked(True)
        
        export_options_layout = QHBoxLayout()
        export_options_layout.addWidget(self.include_wp_checkbox)
        export_options_layout.addWidget(self.include_relations_checkbox)
        export_options_layout.addWidget(self.include_comments_checkbox)
        export_options_layout.addWidget(self.include_statuses_checkbox)
        export_options_form.addRow("导出选项:", export_options_layout)
        
        export_layout.addLayout(export_options_form)
        
        # 导出按钮
        self.export_btn = QPushButton("导出项目")
        self.export_btn.setMinimumWidth(120)
        export_btn_layout = QHBoxLayout()
        export_btn_layout.addStretch()
        export_btn_layout.addWidget(self.export_btn)
        export_layout.addLayout(export_btn_layout)
        
        export_group.setLayout(export_layout)
        main_layout.addWidget(export_group)
        
        # 创建导入组
        import_group = QGroupBox("导入项目")
        import_layout = QVBoxLayout()
        
        # 导入选项
        import_options_form = QFormLayout()
        
        # 项目名称
        self.import_name_edit = QLineEdit()
        self.import_name_edit.setPlaceholderText("留空将使用原项目名称并添加'(导入)'后缀")
        self.import_name_edit.setMinimumWidth(300)
        import_options_form.addRow("新项目名称:", self.import_name_edit)
        
        # 强制处理关系选项
        force_relations_layout = QHBoxLayout()
        self.force_relations_checkbox = QCheckBox("强制处理关系 (解决冲突和循环依赖)")
        self.force_relations_checkbox.setToolTip("启用此选项可以尝试强制创建关系，处理冲突和循环依赖问题")
        force_relations_layout.addWidget(self.force_relations_checkbox)
        import_options_form.addRow("强制处理关系:", force_relations_layout)
        
        import_layout.addLayout(import_options_form)
        
        # 导入按钮
        self.import_btn = QPushButton("导入项目")
        self.import_btn.setMinimumWidth(120)
        import_btn_layout = QHBoxLayout()
        import_btn_layout.addStretch()
        import_btn_layout.addWidget(self.import_btn)
        import_layout.addLayout(import_btn_layout)
        
        import_group.setLayout(import_layout)
        main_layout.addWidget(import_group)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # 状态标签
        self.status_label = QLabel("")
        main_layout.addWidget(self.status_label)
        
        main_layout.addStretch()
        self.setLayout(main_layout)
        
        # 连接信号
        self.export_btn.clicked.connect(self.export_project)
        self.import_btn.clicked.connect(self.import_project)
        
    def load_projects(self):
        """加载项目列表到下拉框"""
        self.project_combo.clear()
        
        try:
            projects = api_client.get_projects()
            if projects:
                for project in projects:
                    self.project_combo.addItem(project.get("name", "Unknown"), project)
                
                self.status_label.setText(f"已加载 {len(projects)} 个项目")
            else:
                self.status_label.setText("未找到项目")
        except Exception as e:
            self.status_label.setText(f"加载项目失败: {str(e)}")
            
    def set_current_project(self, project):
        """设置当前项目"""
        self.current_project = project
        
        # 如果项目有效，则在下拉框中选择它
        if project:
            # 查找项目在下拉框中的索引
            project_id = project.get("id")
            if project_id:
                for i in range(self.project_combo.count()):
                    item_data = self.project_combo.itemData(i)
                    if item_data and item_data.get("id") == project_id:
                        self.project_combo.setCurrentIndex(i)
                        break
    
    def update_project_list(self, projects):
        """直接更新项目列表
        
        Args:
            projects: 项目列表数据
        """
        if not projects:
            return
            
        self.project_combo.clear()
        
        for project in projects:
            self.project_combo.addItem(project.get("name", "Unknown"), project)
        
        self.status_label.setText(f"已加载 {len(projects)} 个项目")
                
    def export_project(self):
        """导出项目"""
        # 获取选择的项目
        current_index = self.project_combo.currentIndex()
        if current_index < 0:
            QMessageBox.warning(self, "导出失败", "请选择要导出的项目")
            return
        
        selected_project = self.project_combo.itemData(current_index)
        if not selected_project:
            QMessageBox.warning(self, "导出失败", "无效的项目选择")
            return
        
        project_id = selected_project.get("id")
        project_name = selected_project.get("name", "Unknown")
        
        # 选择保存文件
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "导出项目", 
            f"{project_name}.openproj", 
            "OpenProject文件 (*.openproj);;所有文件 (*.*)"
        )
        
        if not file_path:
            return  # 用户取消
        
        # 获取导出选项
        include_wp = self.include_wp_checkbox.isChecked()
        include_relations = self.include_relations_checkbox.isChecked()
        include_comments = self.include_comments_checkbox.isChecked()
        include_statuses = self.include_statuses_checkbox.isChecked()
        
        # 显示进度条
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        # 创建导出线程
        self.export_thread = ExportThread(
            project_id, 
            file_path,
            include_work_packages=include_wp,
            include_relations=include_relations,
            include_comments=include_comments,
            include_statuses=include_statuses
        )
        
        # 连接信号
        self.export_thread.progress_update.connect(self.update_progress)
        self.export_thread.export_completed.connect(self.on_export_completed)
        self.export_thread.error_occurred.connect(self.on_export_error)
        
        # 启动线程
        self.export_thread.start()
    
    def import_project(self):
        """导入项目"""
        # 选择导入文件
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "导入项目", 
            "", 
            "OpenProject文件 (*.openproj);;所有文件 (*.*)"
        )
        
        if not file_path:
            return  # 用户取消
        
        # 获取新项目名称
        project_name = self.import_name_edit.text().strip()
        
        # 显示进度条
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        # 创建导入线程
        self.import_thread = ImportThread(file_path, project_name, self.force_relations_checkbox.isChecked())
        
        # 连接信号
        self.import_thread.progress_update.connect(self.update_progress)
        self.import_thread.import_completed.connect(self.on_import_completed)
        self.import_thread.error_occurred.connect(self.on_import_error)
        
        # 启动线程
        self.import_thread.start()
    
    def update_progress(self, value, message):
        """更新进度信息"""
        self.status_label.setText(message)
        self.progress_bar.setValue(value)
    
    def on_export_completed(self, file_path):
        """导出完成"""
        self.progress_bar.setVisible(False)
        QMessageBox.information(self, "导出成功", f"项目已成功导出到:\n{file_path}")
    
    def on_export_error(self, error_msg):
        """导出错误"""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "导出失败", error_msg)
    
    def on_import_completed(self, project_id):
        """导入完成"""
        self.progress_bar.setVisible(False)
        QMessageBox.information(self, "导入成功", "项目已成功导入")
    
    def on_import_error(self, error_msg):
        """导入错误"""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "导入失败", error_msg) 