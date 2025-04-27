from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, 
                            QProgressBar, QSplitter, QTabWidget, QFormLayout, 
                            QLineEdit, QTextEdit, QComboBox, QDialog, QDialogButtonBox,
                            QDateEdit, QCheckBox, QGroupBox, QSpinBox, QProgressDialog,
                            QScrollArea)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate, QTimer
from PyQt5.QtGui import QColor, QIcon
import json
from api_client import api_client
import concurrent.futures
import requests

class LoadWorkPackagesThread(QThread):
    """加载工作包列表的线程"""
    wp_loaded = pyqtSignal(list)
    metadata_loaded = pyqtSignal(list, list, list)  # 类型、状态、自定义字段
    error_occurred = pyqtSignal(str)
    progress_update = pyqtSignal(str, int)  # 新增进度更新信号(消息, 百分比)
    
    def __init__(self, project_id, load_metadata=False):
        super().__init__()
        self.project_id = project_id
        self.load_metadata = load_metadata
    
    def run(self):
        try:
            # 发送进度更新
            self.progress_update.emit("开始加载工作包...", 20)
            
            # 首先获取项目详情，了解工作包总数
            self.progress_update.emit("正在获取项目信息...", 25)
            project_details = api_client.get_project_details(self.project_id)
            
            # 设置合适的页面大小，确保能一次性获取所有工作包
            if project_details:
                # 尝试从项目详情中获取工作包总数，如果无法获取，则先请求一个小的页面来获取总数
                page_size = 50  # 初始较小的页面大小
                test_packages = api_client.get_work_packages(self.project_id, page=1, page_size=page_size)
                
                if test_packages is not None:
                    # 通过第一次请求获取总数信息
                    total_count = api_client.get_last_work_packages_total()
                    if total_count > 0:
                        # 设置合适的页面大小，确保一次能获取所有，并添加一些余量
                        page_size = total_count + 50
                        self.progress_update.emit(f"项目包含 {total_count} 个工作包，调整页面大小为 {page_size}", 28)
                    else:
                        # 如果无法获取总数，使用较大的默认值
                        page_size = 500
                else:
                    # 如果测试请求失败，使用默认值
                    page_size = 500
            else:
                # 如果无法获取项目详情，使用默认值
                page_size = 500
            
            # 一次性加载工作包，使用动态计算的页面大小
            print(f"开始一次性加载所有工作包，页面大小：{page_size}...")
            self.progress_update.emit("正在从服务器获取工作包数据...", 30)
            work_packages = api_client.get_work_packages(self.project_id, page=1, page_size=page_size)
            
            if work_packages is None or len(work_packages) == 0:
                error_msg = "无法获取工作包数据，服务器返回空列表"
                print(error_msg)
                self.error_occurred.emit(error_msg)
                return
            
            success_msg = f"成功获取 {len(work_packages)} 个工作包"
            print(success_msg)
            self.progress_update.emit(success_msg, 50)
            
            # 保存工作包ID以便后续查找
            work_package_ids = {wp.get("id") for wp in work_packages if "id" in wp}
            print(f"主列表中有 {len(work_package_ids)} 个唯一工作包ID")
            
            # 检查是否有子任务引用
            self.progress_update.emit("正在检查子任务引用...", 55)
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
                missing_ids_str = ", ".join([str(id) for id in missing_referenced_ids[:20]])
                if missing_count > 20:
                    missing_ids_str += f"... (共{missing_count}个)"
                
                self.progress_update.emit(f"正在获取 {missing_count} 个引用任务...", 60)
                print(f"发现 {missing_count} 个被引用但不在主列表中的工作包: {missing_ids_str}")
                
                # 并行获取被引用的工作包详情
                referenced_details = self.get_work_packages_details_parallel(missing_referenced_ids)
                
                # 添加获取到的工作包
                added_count = 0
                for wp_id, wp_data in referenced_details.items():
                    if wp_data:
                        print(f"成功获取被引用的工作包 {wp_id} 详情，添加到列表")
                        work_packages.append(wp_data)
                        work_package_ids.add(wp_id)
                        added_count += 1
                
                self.progress_update.emit(f"已添加 {added_count} 个引用任务", 65)
                print(f"添加引用任务后，总共有 {len(work_packages)} 个工作包")
            
            # 检查工作包状态完整性
            self.progress_update.emit("正在验证工作包状态...", 70)
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
                missing_ids = ", ".join([str(id) for id in packages_without_status[:20]])
                if len(packages_without_status) > 20:
                    missing_ids += f"... (共{missing_count}个)"
                
                self.progress_update.emit(f"正在获取 {missing_count} 个缺少状态的工作包...", 75)
                print(f"发现 {missing_count} 个工作包缺少状态信息: {missing_ids}")
                
                # 并行获取缺少状态的工作包详情
                detailed_packages = self.get_work_packages_details_parallel(packages_without_status)
                
                # 更新工作包信息
                updated_count = 0
                for wp_id, detailed_wp in detailed_packages.items():
                    if detailed_wp:
                        # 验证获取的详细信息是否包含状态
                        status_link = detailed_wp.get("_links", {}).get("status", {})
                        has_status = isinstance(status_link, dict) and "title" in status_link and "href" in status_link
                        status_info = status_link.get("title", "未知") if has_status else "未知"
                        
                        print(f"工作包 {wp_id} 详细信息获取成功，状态: {status_info}")
                        
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
                            print(f"新增工作包 {wp_id}")
                
                self.progress_update.emit(f"已更新 {updated_count} 个工作包状态", 80)
                print(f"更新状态后，总共有 {len(work_packages)} 个工作包")
            else:
                self.progress_update.emit("所有工作包都包含状态信息", 80)
            
            # 确保没有重复的工作包
            unique_wps = {}
            for wp in work_packages:
                wp_id = wp.get("id")
                if wp_id is not None:
                    unique_wps[wp_id] = wp
            
            # 转换回列表
            work_packages_final = list(unique_wps.values())
            print(f"去重后，最终有 {len(work_packages_final)} 个唯一工作包")
            
            # 发送所有工作包数据
            self.progress_update.emit(f"准备更新 UI，共 {len(work_packages_final)} 个工作包", 85)
            self.wp_loaded.emit(work_packages_final)
            
            # 如果需要，同时加载元数据
            if self.load_metadata:
                self.progress_update.emit("正在加载元数据...", 90)
                
                # 加载类型
                self.progress_update.emit("正在加载工作包类型...", 92)
                types = api_client.get_types()
                
                # 加载状态
                self.progress_update.emit("正在加载工作包状态...", 94)
                statuses = api_client.get_statuses()
                
                # 加载自定义字段
                self.progress_update.emit("正在加载自定义字段...", 96)
                custom_fields = api_client.get_custom_fields()
                
                # 发送元数据
                self.progress_update.emit("元数据加载完成", 98)
                self.metadata_loaded.emit(types, statuses, custom_fields)
                
        except Exception as e:
            import traceback
            error_details = f"加载工作包出错: {str(e)}\n{traceback.format_exc()}"
            print(error_details)
            self.error_occurred.emit(str(e))
    
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
        total_count = len(work_package_ids)
        print(f"开始并行获取 {total_count} 个工作包详情，使用 {max_workers} 个并行线程")
        
        # 使用线程池并行获取
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_id = {
                executor.submit(api_client.get_work_package, wp_id): wp_id 
                for wp_id in work_package_ids
            }
            
            # 处理完成的任务
            completed = 0
            for future in concurrent.futures.as_completed(future_to_id):
                wp_id = future_to_id[future]
                completed += 1
                
                try:
                    data = future.result()
                    results[wp_id] = data
                    print(f"并行获取进度: {completed}/{total_count}, 工作包 {wp_id} 获取{'成功' if data else '失败'}")
                except Exception as e:
                    print(f"并行获取进度: {completed}/{total_count}, 工作包 {wp_id} 请求异常: {str(e)}")
                    results[wp_id] = None
        
        success_count = sum(1 for data in results.values() if data is not None)
        print(f"并行获取完成: 总计 {total_count} 个工作包, 成功 {success_count} 个, 失败 {total_count - success_count} 个")
        return results
    
    def get_work_package_details(self, work_package_id):
        """获取单个工作包的详细信息"""
        try:
            # 确保链接格式正确
            url = f"/api/v3/work_packages/{work_package_id}"
            if not url.startswith("/"):
                url = f"/{url}"
                
            full_url = f"{api_client.api_url}{url}"
            print(f"获取工作包详细信息，URL: {full_url}")
            
            response = requests.get(
                full_url, 
                auth=api_client.auth, 
                headers=api_client.headers,
                timeout=(5, 15)  # 5秒连接超时，15秒读取超时
            )
            
            # 处理响应
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # 检查状态信息是否完整
                    status_link = data.get("_links", {}).get("status", {})
                    has_complete_status = isinstance(status_link, dict) and "title" in status_link and "href" in status_link
                    status_info = status_link.get("title", "未设置") if has_complete_status else "状态信息不完整"
                    
                    print(f"获取到工作包 {work_package_id} 详细信息，状态: {status_info}")
                    return data
                except Exception as json_err:
                    print(f"解析工作包 {work_package_id} 响应JSON时出错: {str(json_err)}")
            else:
                print(f"获取工作包 {work_package_id} 详细信息失败，HTTP状态: {response.status_code}")
            
            return None
        except Exception as e:
            print(f"获取工作包 {work_package_id} 详情请求异常: {str(e)}")
            return None

class LoadProjectsThread(QThread):
    """异步加载项目列表线程"""
    projects_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, force_refresh=False):
        super().__init__()
        self.force_refresh = force_refresh
    
    def run(self):
        try:
            # 加载项目列表
            projects = api_client.get_projects(force_refresh=self.force_refresh)
            self.projects_loaded.emit(projects)
        except Exception as e:
            self.error_occurred.emit(str(e))

class LoadProjectFormConfigThread(QThread):
    """异步加载项目表单配置线程"""
    config_loaded = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, project_id):
        super().__init__()
        self.project_id = project_id
    
    def run(self):
        try:
            # 加载项目表单配置
            config = api_client.get_project_form_configuration(self.project_id)
            self.config_loaded.emit(config)
        except Exception as e:
            self.error_occurred.emit(str(e))

class WorkPackageWidget(QWidget):
    """工作包列表和详情界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_project = None
        self.work_packages = []
        self.project_form_config = {"attributeGroups": [], "fields": {}}
        self.setup_ui()
        self.custom_fields = []
        self.wp_types = []
        self.wp_statuses = []
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        
        # 标题和按钮区域
        header_layout = QHBoxLayout()
        self.project_label = QLabel("未选择项目")
        self.project_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.refresh_btn = QPushButton("刷新")
        self.new_btn = QPushButton("新建工作包")
        self.edit_btn = QPushButton("编辑")
        self.delete_btn = QPushButton("删除")
        
        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        
        header_layout.addWidget(self.project_label)
        header_layout.addStretch()
        header_layout.addWidget(self.refresh_btn)
        header_layout.addWidget(self.new_btn)
        header_layout.addWidget(self.edit_btn)
        header_layout.addWidget(self.delete_btn)
        
        main_layout.addLayout(header_layout)
        
        # 工作包表格
        self.wp_table = QTableWidget()
        self.wp_table.setColumnCount(5)  # 先创建基本列，后面会动态更新
        self.wp_table.setHorizontalHeaderLabels(["ID", "主题", "类型", "状态", "优先级"])
        self.wp_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.wp_table.setSelectionMode(QTableWidget.SingleSelection)
        self.wp_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.wp_table.setAlternatingRowColors(True)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        # 详情区域
        self.detail_widget = QTabWidget()
        
        # 基本信息标签页
        self.basic_tab = QWidget()
        self.basic_layout = QFormLayout()
        self.basic_tab.setLayout(self.basic_layout)
        
        # 详细信息标签页
        self.detail_tab = QWidget()
        self.detail_layout = QFormLayout()
        self.detail_tab.setLayout(self.detail_layout)
        
        # 人员标签页
        self.people_tab = QWidget()
        self.people_layout = QFormLayout()
        self.people_tab.setLayout(self.people_layout)
        
        # 预估和进度标签页
        self.estimate_tab = QWidget()
        self.estimate_layout = QFormLayout()
        self.estimate_tab.setLayout(self.estimate_layout)
        
        # 成本标签页
        self.cost_tab = QWidget()
        self.cost_layout = QFormLayout()
        self.cost_tab.setLayout(self.cost_layout)
        
        # 其他标签页
        self.other_tab = QWidget()
        self.other_layout = QFormLayout()
        self.other_tab.setLayout(self.other_layout)
        
        # 添加标签页，但不立即显示
        self.detail_widget.addTab(self.basic_tab, "基本信息")
        
        # 创建分割控件
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.wp_table)
        splitter.addWidget(self.detail_widget)
        splitter.setSizes([300, 300])  # 设置初始大小
        
        main_layout.addWidget(splitter)
        main_layout.addWidget(self.progress_bar)
        
        self.setLayout(main_layout)
        
        # 连接信号
        self.refresh_btn.clicked.connect(self.load_work_packages)
        self.wp_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.new_btn.clicked.connect(self.create_work_package)
        self.edit_btn.clicked.connect(self.edit_work_package)
        self.delete_btn.clicked.connect(self.delete_work_package)
    
    def set_project(self, project):
        """设置当前项目"""
        self.current_project = project
        self.project_label.setText(f"项目: {project.get('name', '')}")
        
        # 获取项目工作包表单配置
        project_id = project.get("id")
        if project_id:
            # 显示进度条
            self.progress_bar.setVisible(True)
            
            # 异步加载项目表单配置
            self.config_thread = LoadProjectFormConfigThread(project_id)
            self.config_thread.config_loaded.connect(self.on_project_form_config_loaded)
            self.config_thread.error_occurred.connect(self.handle_error)
            self.config_thread.finished.connect(lambda: self.progress_bar.setVisible(False))
            self.config_thread.start()
            
    def on_project_form_config_loaded(self, config):
        """项目表单配置加载完成的回调"""
        self.project_form_config = config
        self.setup_detail_tabs()
        
        # 加载工作包列表和元数据
        self.load_work_packages(load_metadata=True)
    
    def setup_detail_tabs(self):
        """根据项目表单配置设置详情标签页"""
        # 清空所有标签页
        while self.detail_widget.count() > 0:
            self.detail_widget.removeTab(0)
        
        # 清空所有布局
        self.clear_layout(self.basic_layout)
        self.clear_layout(self.detail_layout)
        self.clear_layout(self.people_layout)
        self.clear_layout(self.estimate_layout)
        self.clear_layout(self.cost_layout)
        self.clear_layout(self.other_layout)
        
        # 映射属性组到标签页
        group_to_tab = {
            "基本信息": (self.basic_tab, self.basic_layout, "基本信息"),
            "详细信息": (self.detail_tab, self.detail_layout, "详细信息"),
            "人员": (self.people_tab, self.people_layout, "人员"),
            "预估和进度": (self.estimate_tab, self.estimate_layout, "预估和进度"),
            "成本": (self.cost_tab, self.cost_layout, "成本")
        }
        
        # 跟踪已添加的标签页和字段
        added_tabs = set()
        attribute_to_group = {}
        
        # 从表单配置提取属性组信息
        for group in self.project_form_config.get("attributeGroups", []):
            group_name = group.get("name", "")
            attributes = group.get("attributes", [])
            
            # 记录属性所属的组
            for attr in attributes:
                attribute_to_group[attr] = group_name
            
            # 如果组名在映射中，添加标签页
            if group_name in group_to_tab:
                tab, layout, title = group_to_tab[group_name]
                if title not in added_tabs:
                    self.detail_widget.addTab(tab, title)
                    added_tabs.add(title)
        
        # 添加"其他"标签页用于未分组的字段
        self.detail_widget.addTab(self.other_tab, "其他")
        
        # 配置工作包表格列
        self.configure_wp_table_columns()
    
    def clear_layout(self, layout):
        """清空布局中的所有控件"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
    
    def configure_wp_table_columns(self):
        """配置工作包表格列，根据项目表单配置"""
        # 基本列： ID, 主题, 类型, 状态, 优先级
        basic_columns = ["id", "subject", "type", "status", "priority"]
        
        # 查找表单中定义的自定义字段
        custom_columns = []
        fields = self.project_form_config.get("fields", {})
        for key, field in fields.items():
            if key.startswith("customField"):
                custom_columns.append((key, field.get("name", key)))
        
        # 特殊处理：确保城市字段(customField1)总是在列表中，即使它不在表单配置中
        city_field_key = "customField1"
        has_city_column = any(key == city_field_key for key, _ in custom_columns)
        if not has_city_column:
            print("表格列配置中未找到城市字段，手动添加")
            custom_columns.append((city_field_key, "城市"))
        
        # 设置列数
        total_columns = len(basic_columns) + len(custom_columns)
        self.wp_table.setColumnCount(total_columns)
        
        # 设置表头
        headers = ["ID", "主题", "类型", "状态", "优先级"]
        for _, name in custom_columns:
            headers.append(name)
        self.wp_table.setHorizontalHeaderLabels(headers)
    
    def load_work_packages(self, load_metadata=False):
        """加载工作包列表"""
        if not self.current_project:
            return
            
        # 清空表格和详情
        self.wp_table.setRowCount(0)
        self.clear_details()
        
        # 创建进度对话框，确保显示在主窗口前面
        progress = QProgressDialog("正在加载工作包数据...", "取消", 0, 100, self)
        progress.setWindowTitle("请稍等")
        progress.setWindowModality(Qt.WindowModal)  # 使对话框模态，阻止主窗口操作
        progress.setMinimumDuration(0)  # 立即显示
        progress.show()  # 显示对话框
        
        # 设置初始进度信息
        progress.setValue(5)
        progress.setLabelText("准备加载工作包数据...")
        
        # 获取项目ID
        project_id = self.current_project.get("id")
        if not project_id:
            QMessageBox.warning(self, "项目ID错误", "无法获取项目ID")
            progress.close()
            return
        
        # 更新进度条
        progress.setValue(10)
        progress.setLabelText(f"开始加载项目 {project_id} 的工作包...")
        
        # 创建线程加载工作包
        self.load_thread = LoadWorkPackagesThread(project_id, load_metadata)
        
        # 连接信号以更新进度
        def update_progress(message, value):
            progress.setValue(value)
            progress.setLabelText(message)
        
        # 定义工作包加载完成回调
        def on_wp_loaded(work_packages):
            update_progress(f"已加载 {len(work_packages)} 个工作包，正在更新UI...", 90)
            self.update_work_packages(work_packages)
            progress.setValue(100)
            
        # 定义元数据加载完成回调
        def on_metadata_loaded(types, statuses, custom_fields):
            update_progress("正在更新元数据...", 95)
            self.update_metadata(types, statuses, custom_fields)
            
        # 定义错误处理回调
        def on_error(error_msg):
            progress.close()
            self.handle_error(error_msg)
            
        # 连接线程信号
        self.load_thread.started.connect(lambda: update_progress("正在连接服务器...", 20))
        self.load_thread.wp_loaded.connect(on_wp_loaded)
        self.load_thread.progress_update.connect(update_progress)  # 连接进度更新信号
        
        if load_metadata:
            update_progress("正在准备加载元数据...", 30)
            self.load_thread.metadata_loaded.connect(on_metadata_loaded)
            
        self.load_thread.error_occurred.connect(on_error)
        self.load_thread.finished.connect(progress.close)
        
        # 启动线程
        self.load_thread.start()
        
        # 隐藏原进度条
        self.progress_bar.setVisible(False)
    
    def update_metadata(self, types, statuses, custom_fields):
        """更新元数据"""
        self.wp_types = types
        self.wp_statuses = statuses
        self.custom_fields = custom_fields
    
    def update_work_packages(self, work_packages):
        """更新工作包列表"""
        print(f"开始更新UI，显示 {len(work_packages)} 个工作包")
        self.work_packages = work_packages
        
        # 先禁用表格更新以提高性能
        self.wp_table.setUpdatesEnabled(False)
        self.wp_table.setSortingEnabled(False)
        
        # 基本列： ID, 主题, 类型, 状态, 优先级
        basic_columns = ["id", "subject", "type", "status", "priority"]
        
        # 自定义字段列
        custom_columns = []
        fields = self.project_form_config.get("fields", {})
        for key, field in fields.items():
            if key.startswith("customField"):
                custom_columns.append(key)
        
        # 特殊处理：确保城市字段(customField1)总是在列表中，即使它不在表单配置中
        city_field_key = "customField1"
        if city_field_key not in custom_columns:
            print("工作包列表中未找到城市字段，手动添加")
            custom_columns.append(city_field_key)
            # 为表单字段添加一个城市字段的模拟定义，方便后续处理
            if city_field_key not in fields:
                fields[city_field_key] = {"name": "城市", "type": "CustomOption"}
        
        # 一次性设置表格行数
        total_columns = len(basic_columns) + len(custom_columns)
        self.wp_table.setColumnCount(total_columns)
        self.wp_table.setRowCount(len(work_packages))
        
        # 设置表头
        headers = ["ID", "主题", "类型", "状态", "优先级"]
        for key in custom_columns:
            headers.append(fields.get(key, {}).get("name", key.replace("customField", "自定义字段")))
        self.wp_table.setHorizontalHeaderLabels(headers)
        
        # 批量准备状态颜色映射
        status_colors = {
            "完成": QColor(144, 238, 144),
            "已完成": QColor(144, 238, 144),
            "Closed": QColor(144, 238, 144),
            "进行中": QColor(255, 255, 0),
            "In progress": QColor(255, 255, 0),
            "拒绝": QColor(255, 200, 200),
            "Rejected": QColor(255, 200, 200),
            "挂起": QColor(255, 165, 0),
            "On hold": QColor(255, 165, 0)
        }
        
        # 预处理状态ID到名称的映射，减少循环中的查找操作
        status_id_to_name = {}
        for status in self.wp_statuses:
            status_id = status.get("id")
            if status_id:
                status_id_to_name[f"/api/v3/statuses/{status_id}"] = status.get("name", "")
        
        # 批量填充表格，减少行遍历次数
        for row, wp in enumerate(work_packages):
            wp_id = wp.get("id", "未知")
            
            # 创建所有单元格项
            items = []
            
            # ID列
            id_item = QTableWidgetItem(str(wp_id))
            id_item.setData(Qt.UserRole, wp)  # 将完整数据保存到item中
            items.append(id_item)
            
            # 主题列
            subject = wp.get("subject", "")
            items.append(QTableWidgetItem(subject))
            
            # 类型列
            type_link = wp.get("_links", {}).get("type", {})
            type_title = type_link.get("title", "")
            items.append(QTableWidgetItem(type_title))
            
            # 状态列
            status_link = wp.get("_links", {}).get("status", {})
            status_title = status_link.get("title", "")
            if not status_title and "_links" in wp and "status" in wp["_links"]:
                # 尝试从status链接中提取状态名称
                status_href = wp["_links"]["status"].get("href", "")
                if status_href:
                    status_title = status_id_to_name.get(status_href, "")
            
            status_item = QTableWidgetItem(status_title)
            
            # 设置状态颜色
            if status_title in status_colors:
                status_item.setBackground(status_colors[status_title])
            
            items.append(status_item)
            
            # 优先级列
            priority_link = wp.get("_links", {}).get("priority", {})
            priority_title = priority_link.get("title", "")
            items.append(QTableWidgetItem(priority_title))
            
            # 自定义字段列 - 直接从links中获取标题
            links = wp.get("_links", {})
            for field_key in custom_columns:
                field_value = ""
                if field_key in links:
                    field_link = links[field_key]
                    if isinstance(field_link, dict) and "title" in field_link:
                        field_value = field_link["title"]
                items.append(QTableWidgetItem(field_value))
            
            # 一次性设置整行
            for col, item in enumerate(items):
                self.wp_table.setItem(row, col, item)
        
        # 重新启用表格更新和排序
        self.wp_table.setSortingEnabled(True)
        
        # 优化调整列宽的方式 - 只计算一次而不是每列每行都计算
        for col in range(self.wp_table.columnCount()):
            self.wp_table.resizeColumnToContents(col)
        
        # 批量调整行高
        for row in range(self.wp_table.rowCount()):
            self.wp_table.resizeRowToContents(row)
        
        # 重新启用表格更新
        self.wp_table.setUpdatesEnabled(True)
        
        # 按照ID排序
        self.wp_table.sortItems(0, Qt.AscendingOrder)
        
        print(f"UI更新完成，显示 {self.wp_table.rowCount()} 行工作包数据")
    
    def handle_error(self, error_msg):
        """处理错误"""
        QMessageBox.critical(self, "加载失败", f"加载失败: {error_msg}")
        self.progress_bar.setVisible(False)
    
    def on_selection_changed(self):
        """当表格选择改变时"""
        selected_items = self.wp_table.selectedItems()
        if not selected_items:
            self.clear_details()
            self.edit_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
            
        # 获取第一列（ID列）的数据
        row = selected_items[0].row()
        item = self.wp_table.item(row, 0)
        if item:
            wp_data = item.data(Qt.UserRole)
            if wp_data:
                self.show_work_package_details(wp_data)
                self.edit_btn.setEnabled(True)
                self.delete_btn.setEnabled(True)
    
    def show_work_package_details(self, wp_data):
        """显示工作包详情，根据项目表单配置动态创建UI"""
        # 清空所有标签页中的控件
        self.clear_layout(self.basic_layout)
        self.clear_layout(self.detail_layout)
        self.clear_layout(self.people_layout)
        self.clear_layout(self.estimate_layout)
        self.clear_layout(self.cost_layout)
        self.clear_layout(self.other_layout)
        
        # 映射属性组到标签页和布局
        group_to_layout = {
            "基本信息": self.basic_layout,
            "详细信息": self.detail_layout,
            "人员": self.people_layout,
            "预估和进度": self.estimate_layout,
            "成本": self.cost_layout
        }
        
        # 从表单配置中获取字段到属性组的映射
        attribute_to_group = {}
        fields_info = {}
        
        # 提取字段信息和字段所属组
        for group in self.project_form_config.get("attributeGroups", []):
            group_name = group.get("name", "")
            attributes = group.get("attributes", [])
            
            for attr in attributes:
                attribute_to_group[attr] = group_name
        
        # 获取表单中的字段信息
        for key, field in self.project_form_config.get("fields", {}).items():
            fields_info[key] = field
        
        # 处理工作包数据中的各个字段
        for key, value in wp_data.items():
            if key.startswith("_"):  # 跳过内部字段
                continue
                
            # 获取字段名称和值
            field_name = key
            field_value = value
            
            # 如果字段有定义，使用定义中的名称
            if key in fields_info:
                field_name = fields_info[key].get("name", key)
            
            # 获取字段所属组
            group = attribute_to_group.get(key, "其他")
            
            # 选择布局
            layout = group_to_layout.get(group, self.other_layout)
            
            # 创建标签显示值
            value_label = QLabel()
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            
            # 根据字段类型设置值
            if isinstance(field_value, dict):
                if "raw" in field_value:  # 富文本
                    value_label.setText(field_value.get("raw", ""))
                else:
                    value_label.setText(json.dumps(field_value, ensure_ascii=False))
            else:
                value_label.setText(str(field_value))
                
            # 添加到布局
            layout.addRow(f"{field_name}:", value_label)
        
        # 处理_links中的字段
        if "_links" in wp_data:
            links = wp_data["_links"]
            for key, value in links.items():
                if key in ["self", "delete", "update", "schema"]:  # 跳过API链接
                    continue
                    
                # 获取字段名称
                field_name = key
                if key in fields_info:
                    field_name = fields_info[key].get("name", key)
                elif key.startswith("customField") and key in fields_info:
                    field_name = fields_info[key].get("name", key)
                
                # 获取字段所属组
                group = attribute_to_group.get(key, "其他")
                
                # 选择布局
                layout = group_to_layout.get(group, self.other_layout)
                
                # 创建标签显示值
                value_label = QLabel()
                value_label.setWordWrap(True)
                value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                
                # 设置值
                if isinstance(value, dict) and "title" in value:
                    value_label.setText(value["title"])
                elif isinstance(value, list):
                    titles = []
                    for item in value:
                        if isinstance(item, dict) and "title" in item:
                            titles.append(item["title"])
                    value_label.setText(", ".join(titles))
                else:
                    value_label.setText(str(value))
                
                # 添加到布局
                layout.addRow(f"{field_name}:", value_label)
    
    def clear_details(self):
        """清空详情区域"""
        self.clear_layout(self.basic_layout)
        self.clear_layout(self.detail_layout)
        self.clear_layout(self.people_layout)
        self.clear_layout(self.estimate_layout)
        self.clear_layout(self.cost_layout)
        self.clear_layout(self.other_layout)
    
    def create_work_package(self):
        """创建工作包"""
        if not self.current_project:
            QMessageBox.warning(self, "错误", "请先选择项目")
            return
            
        dialog = WorkPackageDialog(self.wp_types, self.wp_statuses, self.custom_fields, self.project_form_config, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            # 获取对话框数据
            data = dialog.get_work_package_data()
            
            # 添加项目链接
            project_id = self.current_project.get("id")
            data["_links"]["project"] = {
                "href": f"/api/v3/projects/{project_id}"
            }
            
            # 创建工作包
            result = api_client.create_work_package(project_id, data)
            if result:
                QMessageBox.information(self, "创建成功", "工作包创建成功")
                self.load_work_packages()  # 刷新列表
            else:
                QMessageBox.critical(self, "创建失败", "工作包创建失败")
    
    def edit_work_package(self):
        """编辑工作包"""
        selected_items = self.wp_table.selectedItems()
        if not selected_items:
            return
            
        row = selected_items[0].row()
        item = self.wp_table.item(row, 0)
        if not item:
            return
            
        wp_data = item.data(Qt.UserRole)
        if not wp_data:
            return
            
        # 获取工作包ID
        wp_id = wp_data.get("id")
        if not wp_id:
            QMessageBox.warning(self, "错误", "无法获取工作包ID")
            return
            
        # 获取最新的工作包数据（包括锁定版本）
        latest_wp_data = api_client.get_work_package(wp_id)
        if not latest_wp_data:
            QMessageBox.warning(self, "获取失败", "无法获取最新的工作包数据")
            return
            
        # 记录当前的锁定版本
        lock_version = latest_wp_data.get("lockVersion")
        print(f"获取到最新的工作包数据，锁定版本: {lock_version}")
        
        dialog = WorkPackageDialog(
            self.wp_types, 
            self.wp_statuses, 
            self.custom_fields,
            self.project_form_config,
            work_package=latest_wp_data,
            parent=self
        )
        
        if dialog.exec_() == QDialog.Accepted:
            # 获取对话框数据
            data = dialog.get_work_package_data()
            
            # 确保数据中包含锁定版本
            if "lockVersion" not in data and lock_version is not None:
                data["lockVersion"] = lock_version
                print(f"添加锁定版本到更新数据: {lock_version}")
            
            # 更新工作包
            result = api_client.update_work_package(wp_id, data)
            if result:
                QMessageBox.information(self, "更新成功", "工作包更新成功")
                self.load_work_packages()  # 刷新列表
            else:
                QMessageBox.critical(self, "更新失败", "工作包更新失败")
                # 显示错误详情
                edit_again = QMessageBox.question(
                    self,
                    "是否重试?",
                    "工作包更新失败，是否重新尝试编辑?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if edit_again == QMessageBox.Yes:
                    self.edit_work_package()  # 递归调用，重新尝试
    
    def delete_work_package(self):
        """删除工作包"""
        selected_items = self.wp_table.selectedItems()
        if not selected_items:
            return
            
        row = selected_items[0].row()
        item = self.wp_table.item(row, 0)
        if not item:
            return
            
        wp_data = item.data(Qt.UserRole)
        if not wp_data:
            return
            
        wp_id = wp_data.get("id")
        subject = wp_data.get("subject", "")
        
        # 确认删除
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除工作包 #{wp_id} {subject} 吗？\n此操作不可恢复!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success = api_client.delete_work_package(wp_id)
            if success:
                QMessageBox.information(self, "删除成功", "工作包已删除")
                self.load_work_packages()  # 刷新列表
            else:
                QMessageBox.critical(self, "删除失败", "工作包删除失败")

class WorkPackageDialog(QDialog):
    """工作包编辑对话框"""
    
    def __init__(self, types, statuses, custom_fields, project_form_config, work_package=None, parent=None):
        """初始化工作包对话框
        
        Args:
            types: 可用类型列表
            statuses: 可用状态列表
            custom_fields: 自定义字段列表
            project_form_config: 项目表单配置
            work_package: 要编辑的工作包数据（如果不是新建）
            parent: 父窗口
        """
        super().__init__(parent)
        self.types = types
        self.statuses = statuses
        self.custom_fields = custom_fields
        self.project_form_config = project_form_config
        self.work_package = work_package  # 如果是编辑模式，则传入工作包数据
        self.custom_inputs = {}
        self.field_inputs = {}  # 存储所有字段的输入控件
        self.lock_version = None  # 保存锁定版本
        self.group_layouts = {}  # 用于存储分组布局
        
        # 导入所需的QTimer进行线程安全UI更新
        from PyQt5.QtCore import QTimer
        self.timer = QTimer
        
        self.setWindowTitle("工作包" + ("编辑" if work_package else "创建"))
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.resize(800, 600)
        
        self.setup_ui()
        
        if work_package:
            self.load_work_package_data(work_package)
            # 保存锁定版本
            self.lock_version = work_package.get("lockVersion")
            print(f"工作包锁定版本: {self.lock_version}")
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 设置窗口标题
        if self.mode == "create":
            self.setWindowTitle("创建工作包")
            self.save_button = QPushButton("创建")
        else:
            self.setWindowTitle("编辑工作包")
            self.save_button = QPushButton("保存")
        
        # 设置窗口图标
        self.setWindowIcon(QIcon(":/icons/package.png"))
        
        # 创建滚动区域以处理大量字段
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # 创建分组
        self.group_boxes = {}
        self.group_layouts = {}
        
        # 定义分组
        groups = ["基本信息", "详细信息", "日期时间", "人员", "关联", "其他"]
        for group in groups:
            group_box = QGroupBox(group)
            group_layout = QFormLayout()
            group_box.setLayout(group_layout)
            
            self.group_boxes[group] = group_box
            self.group_layouts[group] = group_layout
            
            scroll_layout.addWidget(group_box)
        
        # 添加一个拉伸项，让分组控件靠上
        scroll_layout.addStretch()
        
        # 设置滚动区域的内容控件
        scroll_area.setWidget(scroll_content)
        
        # 为表单控件创建一个字典
        self.field_inputs = {}
        
        # 获取工作包类型信息
        self.load_types()
        
        # 获取状态信息
        self.load_statuses()
        
        # 获取项目表单配置
        if self.project_id:
            form_config = api_client.get_project_form_configuration(self.project_id)
            self.project_form_config = form_config
        else:
            form_config = {}
            self.project_form_config = {}
        
        # 获取字段定义
        fields = form_config.get("fields", {})
        
        # 定义字段分组
        attribute_to_group = {
            "subject": "基本信息",
            "type": "基本信息",
            "status": "基本信息",
            "description": "详细信息",
            "startDate": "日期时间",
            "dueDate": "日期时间",
            "estimatedTime": "详细信息",
            "percentageDone": "详细信息",
            "assignee": "人员",
            "responsible": "人员",
            "priority": "详细信息",
            "version": "关联",
            "parent": "关联"
        }
        
        # 获取城市字段ID和字段键
        city_field_id = api_client.get_city_field_id()
        city_field_key = f"customField{city_field_id}"
        
        # 将城市字段添加到基本信息分组
        attribute_to_group[city_field_key] = "基本信息"
        
        # 创建字段输入控件
        for key, field_info in fields.items():
            field_type = field_info.get("type", "")
            field_name = field_info.get("name", key)
            
            # 基本字段
            if key == "subject":
                self.create_subject_field(field_info, attribute_to_group)
            elif key == "type":
                self.create_type_field(field_info, attribute_to_group)
            elif key == "status":
                self.create_status_field(field_info, attribute_to_group)
            elif key == "description":
                self.create_description_field(field_info, attribute_to_group)
            # 自定义字段
            elif key.startswith("customField"):
                self.create_custom_field(key, field_info, attribute_to_group)
        
        # 特殊处理：确保城市字段总是被创建，即使它不在表单配置中
        if city_field_key not in self.field_inputs:
            print(f"表单配置中未找到城市字段({city_field_key})，手动创建")
            # 创建一个模拟的字段信息
            city_field_info = {
                "name": "城市",
                "type": "CustomOption",
                "required": False
            }
            self.create_custom_field(city_field_key, city_field_info, {city_field_key: "基本信息"})
    
    def create_subject_field(self, field_info, attribute_to_group):
        """创建主题输入控件"""
        field_name = field_info.get("name", "主题")
        
        # 创建输入控件
        input_widget = QLineEdit()
        self.field_inputs["subject"] = input_widget
        
        # 添加到布局
        group = attribute_to_group.get("subject", "基本信息")
        layout = self.group_layouts.get(group, self.group_layouts.get("其他"))
        layout.addRow(f"{field_name}:", input_widget)
    
    def create_type_field(self, field_info, attribute_to_group):
        """创建类型下拉框"""
        field_name = field_info.get("name", "类型")
        
        # 创建下拉框
        input_widget = QComboBox()
        for wp_type in self.types:
            input_widget.addItem(wp_type.get("name", ""), wp_type.get("id"))
        self.field_inputs["type"] = input_widget
        
        # 添加到布局
        group = attribute_to_group.get("type", "基本信息")
        layout = self.group_layouts.get(group, self.group_layouts.get("其他"))
        layout.addRow(f"{field_name}:", input_widget)
    
    def create_status_field(self, field_info, attribute_to_group):
        """创建状态下拉框"""
        field_name = field_info.get("name", "状态")
        
        # 创建下拉框
        input_widget = QComboBox()
        for status in self.statuses:
            input_widget.addItem(status.get("name", ""), status.get("id"))
        self.field_inputs["status"] = input_widget
        
        # 添加到布局
        group = attribute_to_group.get("status", "基本信息")
        layout = self.group_layouts.get(group, self.group_layouts.get("其他"))
        layout.addRow(f"{field_name}:", input_widget)
    
    def create_description_field(self, field_info, attribute_to_group):
        """创建描述文本框"""
        field_name = field_info.get("name", "描述")
        
        # 创建文本框
        input_widget = QTextEdit()
        self.field_inputs["description"] = input_widget
        
        # 添加到布局
        group = attribute_to_group.get("description", "基本信息")
        layout = self.group_layouts.get(group, self.group_layouts.get("其他"))
        layout.addRow(f"{field_name}:", input_widget)
    
    def create_custom_field(self, field_key, field_info, attribute_to_group):
        """创建自定义字段输入控件"""
        field_name = field_info.get("name", field_key)
        field_type = field_info.get("type", "")
        is_required = field_info.get("required", False)
        
        # 创建输入控件
        input_widget = None
        
        # 获取城市字段ID和字段键
        city_field_id = api_client.get_city_field_id()
        city_field_key = f"customField{city_field_id}"
        
        # 根据字段类型创建适当的控件
        if field_type in ["String", "Text"]:
            input_widget = QLineEdit()
        elif field_type in ["Integer", "Float"]:
            input_widget = QLineEdit()
            # 可以添加验证器
        elif field_type in ["Date", "DateTime"]:
            input_widget = QDateEdit()
            input_widget.setCalendarPopup(True)
            input_widget.setDate(QDate.currentDate())
        elif field_type in ["Boolean"]:
            input_widget = QCheckBox()
        elif field_type in ["CustomOption", "List"]:
            # 创建下拉框
            input_widget = QComboBox()
            
            # 添加一个占位项，表示正在加载
            input_widget.addItem("正在加载选项...", None)
            
            # 特殊处理城市字段
            if "城市" in field_name or "city" in field_name.lower() or field_key == city_field_key:
                print(f"检测到城市字段: {field_name} (字段键: {field_key})")
                # 设置特殊样式以便识别
                input_widget.setStyleSheet("QComboBox { background-color: #e6f7ff; border: 1px solid #1890ff; }")
                
                field_id = field_key.replace("customField", "")
                
                # 使用单独的线程加载选项，避免阻塞UI
                def load_options():
                    try:
                        options = api_client.get_custom_field_options(field_id)
                        if options:
                            # 使用Qt的信号槽机制安全地更新UI控件
                            from PyQt5.QtCore import QTimer
                            
                            def update_ui():
                                input_widget.blockSignals(True)
                                input_widget.clear()
                                for option in options:
                                    value = option.get("value", "")
                                    option_id = option.get("id", "")
                                    input_widget.addItem(value, option_id)
                                input_widget.blockSignals(False)
                                print(f"城市字段 {field_name} 加载了 {len(options)} 个选项")
                            
                            # 使用QTimer在主线程中执行UI更新
                            QTimer.singleShot(0, update_ui)
                    except Exception as e:
                        print(f"加载城市选项时出错: {str(e)}")
                
                # 启动线程加载选项
                import threading
                threading.Thread(target=load_options).start()
            else:
                # 延迟加载选项，避免UI卡顿
                def delayed_load():
                    field_id = field_key.replace("customField", "")
                    options = api_client.get_custom_field_options(field_id)
                    
                    # 在主线程中更新UI
                    from PyQt5.QtCore import QTimer
                    
                    def update_ui():
                        input_widget.blockSignals(True)
                        input_widget.clear()
                        if options:
                            for option in options:
                                value = option.get("value", "")
                                option_id = option.get("id", "")
                                input_widget.addItem(value, option_id)
                            print(f"为字段 {field_name} 加载了 {len(options)} 个选项")
                        else:
                            input_widget.addItem("无可用选项", None)
                        input_widget.blockSignals(False)
                    
                    # 使用QTimer在主线程中执行UI更新
                    QTimer.singleShot(0, update_ui)
                
                # 启动线程加载选项
                import threading
                threading.Thread(target=delayed_load).start()
        else:
            input_widget = QLineEdit()  # 默认使用文本框
        
        if input_widget:
            # 设置工具提示，显示字段ID和类型
            input_widget.setToolTip(f"字段ID: {field_key}\n类型: {field_type}")
            
            self.field_inputs[field_key] = input_widget
            
            # 添加到布局
            group = attribute_to_group.get(field_key, "其他")
            layout = self.group_layouts.get(group, self.group_layouts.get("其他"))
            
            # 如果是必填项，添加标记
            field_label = field_name
            if is_required:
                field_label += " *"
                
            layout.addRow(f"{field_label}:", input_widget)
    
    def load_work_package_data(self, wp_data):
        """加载工作包数据到表单"""
        # 保存锁定版本
        self.lock_version = wp_data.get("lockVersion")
        print(f"从工作包数据加载锁定版本: {self.lock_version}")
        
        # 基本字段
        # 主题
        if "subject" in self.field_inputs and "subject" in wp_data:
            self.field_inputs["subject"].setText(wp_data.get("subject", ""))
        
        # 描述
        if "description" in self.field_inputs:
            description = wp_data.get("description", {})
            if isinstance(description, dict):
                description_text = description.get("raw", "")
            else:
                description_text = str(description)
            self.field_inputs["description"].setPlainText(description_text)
        
        # 从_links中加载值
        if "_links" in wp_data:
            links = wp_data["_links"]
            
            # 类型
            if "type" in self.field_inputs and "type" in links:
                type_link = links["type"]
                if isinstance(type_link, dict) and "href" in type_link:
                    type_id = type_link["href"].split("/")[-1]
                    index = self.field_inputs["type"].findData(type_id)
                    if index >= 0:
                        self.field_inputs["type"].setCurrentIndex(index)
            
            # 状态
            if "status" in self.field_inputs and "status" in links:
                status_link = links["status"]
                if isinstance(status_link, dict) and "href" in status_link:
                    status_id = status_link["href"].split("/")[-1]
                    index = self.field_inputs["status"].findData(status_id)
                    if index >= 0:
                        self.field_inputs["status"].setCurrentIndex(index)
            
            # 自定义字段
            for field_key, input_widget in self.field_inputs.items():
                if field_key.startswith("customField") and field_key in links:
                    value = links[field_key]
                    
                    if isinstance(input_widget, QComboBox):
                        # 对于下拉框，先获取可选值
                        self.load_custom_field_options(field_key, input_widget, value)
                    elif isinstance(input_widget, QLineEdit):
                        if isinstance(value, dict) and "title" in value:
                            input_widget.setText(value["title"])
                    elif isinstance(input_widget, QDateEdit):
                        if isinstance(value, str):
                            try:
                                date = QDate.fromString(value, Qt.ISODate)
                                input_widget.setDate(date)
                            except:
                                pass
                    elif isinstance(input_widget, QCheckBox):
                        if isinstance(value, bool):
                            input_widget.setChecked(value)
                        elif isinstance(value, str):
                            input_widget.setChecked(value.lower() in ('true', 'yes', '1'))
    
    def load_custom_field_options(self, field_key, combo_box, current_value):
        """加载自定义字段的选项值"""
        # 清空下拉框
        combo_box.clear()
        
        # 获取字段定义
        field_info = self.project_form_config.get("fields", {}).get(field_key, {})
        field_name = field_info.get("name", field_key)
        
        # 获取字段ID
        field_id = field_key.replace("customField", "")
        
        print(f"为字段 {field_name} (ID: {field_id}) 加载选项...")
        
        # 获取选项
        options = api_client.get_custom_field_options(field_id)
        
        # 如果成功获取到选项，则添加到下拉框
        if options:
            for option in options:
                value = option.get("value", "")
                option_id = option.get("id", "")
                combo_box.addItem(value, option_id)
            print(f"已加载 {len(options)} 个选项")
        
        # 如果没有选项，但有当前值，则添加当前值
        if combo_box.count() == 0 and isinstance(current_value, dict) and "title" in current_value:
            title = current_value["title"]
            id_value = None
            if "href" in current_value:
                id_value = current_value["href"].split("/")[-1]
            combo_box.addItem(title, id_value)
            print(f"已添加当前值: {title}")
        
        # 设置当前值
        if isinstance(current_value, dict):
            value_id = None
            if "href" in current_value:
                value_id = current_value["href"].split("/")[-1]
            
            if value_id:
                index = combo_box.findData(value_id)
                if index >= 0:
                    combo_box.setCurrentIndex(index)
                    print(f"已选中值: {combo_box.itemText(index)}")
                else:
                    print(f"未找到匹配的选项 ID: {value_id}")
            elif "title" in current_value:
                # 尝试通过标题匹配
                title = current_value["title"]
                for i in range(combo_box.count()):
                    if combo_box.itemText(i) == title:
                        combo_box.setCurrentIndex(i)
                        print(f"通过标题匹配选中值: {title}")
                        break
    
    def get_work_package_data(self):
        """获取表单数据，只包含有变更的字段"""
        data = {
            "_links": {}
        }
        
        # 添加锁定版本
        if self.lock_version is not None:
            data["lockVersion"] = self.lock_version
        
        # 基本字段
        # 主题
        if "subject" in self.field_inputs:
            data["subject"] = self.field_inputs["subject"].text()
        
        # 描述
        if "description" in self.field_inputs and self.field_inputs["description"].toPlainText():
            data["description"] = {
                "raw": self.field_inputs["description"].toPlainText()
            }
        
        # 类型
        if "type" in self.field_inputs and self.field_inputs["type"].currentData():
            data["_links"]["type"] = {
                "href": f"/api/v3/types/{self.field_inputs['type'].currentData()}"
            }
        
        # 状态
        if "status" in self.field_inputs and self.field_inputs["status"].currentData():
            data["_links"]["status"] = {
                "href": f"/api/v3/statuses/{self.field_inputs['status'].currentData()}"
            }
        
        # 自定义字段
        for field_key, input_widget in self.field_inputs.items():
            if field_key.startswith("customField"):
                if isinstance(input_widget, QLineEdit) and input_widget.text():
                    data["_links"][field_key] = {
                        "title": input_widget.text()
                    }
                elif isinstance(input_widget, QComboBox) and input_widget.currentData():
                    field_id = field_key.replace("customField", "")
                    data["_links"][field_key] = {
                        "href": f"/api/v3/custom_options/{input_widget.currentData()}"
                    }
                elif isinstance(input_widget, QCheckBox):
                    data[field_key] = input_widget.isChecked()
                elif isinstance(input_widget, QDateEdit):
                    data[field_key] = input_widget.date().toString(Qt.ISODate)
        
        # 简化请求，如果我们只是更新一个自定义字段
        if self.work_package and len(data["_links"]) == 1 and next(iter(data["_links"])).startswith("customField"):
            # 只有一个自定义字段被更新
            field_key = next(iter(data["_links"]))
            simplified_data = {
                "_links": {
                    field_key: data["_links"][field_key]
                }
            }
            # 保留锁定版本
            if "lockVersion" in data:
                simplified_data["lockVersion"] = data["lockVersion"]
            print("使用简化的更新数据，只包含修改的自定义字段")
            return simplified_data
            
        return data 