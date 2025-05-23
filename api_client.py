import requests
import base64
import json
import os
import re
import time
from config import config
import concurrent.futures
import traceback
import threading

# 尝试导入PyQt5，如果失败则使用无GUI模式
try:
    from PyQt5.QtWidgets import QApplication
    _HAS_PYQT = True
except ImportError:
    print("警告：无法导入PyQt5，将使用无GUI模式运行")
    _HAS_PYQT = False

class OpenProjectClient:
    def __init__(self):
        self.api_url = config.api_url
        self.api_token = config.api_token
        self.auth = None
        self.headers = {"Content-Type": "application/json"}
        
        # 缓存数据
        self._custom_fields_cache = None
        self._types_cache = None
        self._statuses_cache = None
        self._projects_cache = None
        self._project_form_config_cache = {}
        self._field_name_to_id_cache = {}  # 字段名称到ID的映射缓存
        self._cities_cache = None  # 城市列表缓存
        self._debug_mode = False  # 调试模式开关
        
        # 添加一个变量用于存储最后一次请求的工作包总数
        self._last_work_packages_total = 0
        
        # 连接优化设置
        self._session = requests.Session()
        self._connection_pool_size = 5
        self._keep_alive = True
        self._connection_timeout = 5
        self._read_timeout = 30
        self._retry_count = 2
        
        # 设置连接池
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=self._connection_pool_size,
            pool_maxsize=self._connection_pool_size,
            max_retries=self._retry_count
        )
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)
        
        # 初始化凭证
        self.update_credentials(self.api_url, self.api_token)
    
    def update_credentials(self, api_url, api_token):
        """更新API凭证"""
        self.api_url = api_url.rstrip("/")  # 移除末尾的斜杠
        self.api_token = api_token
        
        # 设置认证
        self.auth = ('apikey', self.api_token)
        
        # 同时设置Basic认证头，以备不支持auth参数的情况
        if self.api_token:
            auth_str = base64.b64encode(f"apikey:{self.api_token}".encode()).decode()
            self.headers = {"Content-Type": "application/json", "Authorization": f"Basic {auth_str}"}
            # 更新会话的默认头信息
            self._session.headers.update(self.headers)
        
        print(f"API凭证已更新: URL={self.api_url}, Token={self.api_token[:5] if self.api_token else None}...")
        
        # 清空所有缓存
        self._projects_cache = None
        self._project_form_config_cache = {}
        self._custom_fields_cache = None
        self._types_cache = None
        self._statuses_cache = None
        self._field_name_to_id_cache = {}
        self._cities_cache = None
        
        # 删除所有特定的缓存属性，确保完全重置状态
        for cache_attr in ['_city_field_id_cache', '_loading_projects', '_loading_projects_callbacks', '_last_work_packages_total']:
            if hasattr(self, cache_attr):
                if cache_attr == '_loading_projects':
                    self._loading_projects = False
                    self._loading_projects_callbacks = []
                else:
                    delattr(self, cache_attr)
        
        print("所有缓存已清空，将在下次请求时重新获取数据")
    
    def get_projects(self, force_refresh=False, page=1, page_size=100):
        """获取所有项目列表
        
        Args:
            force_refresh: 是否强制刷新缓存
            page: 页码
            page_size: 每页数量
        """
        start_time = time.time()
        
        # 添加缓存属性
        if not hasattr(self, '_projects_cache'):
            self._projects_cache = None
            
        # 添加标志记录是否正在加载项目列表
        if not hasattr(self, '_loading_projects'):
            self._loading_projects = False
            self._loading_projects_callbacks = []
            
        # 如果正在加载，添加回调等待结果
        if self._loading_projects:
            print("项目列表正在加载中，等待结果...")
            def callback(projects):
                return projects
            self._loading_projects_callbacks.append(callback)
            # 休眠一段时间等待结果，同时处理事件以保持UI响应
            while self._loading_projects and len(self._loading_projects_callbacks) > 0:
                time.sleep(0.1)
                if _HAS_PYQT:
                    QApplication.processEvents()
            return self._projects_cache
            
        # 如果有缓存且不需要强制刷新，直接返回缓存
        if self._projects_cache is not None and not force_refresh:
            end_time = time.time()
            print(f"从缓存获取项目列表耗时: {end_time - start_time:.2f}秒")
            return self._projects_cache
        
        # 设置加载标志
        self._loading_projects = True
        
        print("开始请求项目列表...")
        url = f"{self.api_url}/api/v3/projects"
        params = {
            "pageSize": page_size,
            "offset": (page - 1) * page_size
        }
        
        if self._debug_mode:
            print(f"正在请求: {url}")
            print(f"请求参数: {params}")
            
        try:
            # 使用auth参数进行认证
            print(f"开始发送网络请求: {time.strftime('%H:%M:%S')}")
            req_start = time.time()
            
            # 在请求前允许UI更新
            if _HAS_PYQT:
                QApplication.processEvents()
            
            # 使用会话进行请求
            response = self._session.get(
                url, 
                params=params,
                auth=self.auth
            )
            
            # 请求后再次允许UI更新
            if _HAS_PYQT:
                QApplication.processEvents()
            
            req_end = time.time()
            print(f"请求耗时: {req_end - req_start:.2f}秒")
            
            # 处理响应
            if response.status_code == 200:
                result = response.json()
                projects = result.get("_embedded", {}).get("elements", [])
                self._projects_cache = projects
                end_time = time.time()
                print(f"获取项目列表完成，共 {len(projects)} 个项目，总耗时: {end_time - start_time:.2f}秒")
                
                # 处理所有等待的回调
                for callback in self._loading_projects_callbacks:
                    callback(projects)
                self._loading_projects_callbacks = []
                
                # 清除加载标志
                self._loading_projects = False
                
                return projects
            else:
                print(f"请求失败: {response.status_code} - {response.text}")
                # 清除加载标志和回调
                self._loading_projects = False
                self._loading_projects_callbacks = []
                return []
        except Exception as e:
            print(f"请求出错: {str(e)}")
            # 清除加载标志和回调
            self._loading_projects = False
            self._loading_projects_callbacks = []
            return []
            
    def get_custom_fields(self):
        """获取自定义字段列表"""
        # 使用已有的缓存属性
        if self._custom_fields_cache is not None:
            print("从缓存返回自定义字段列表")
            return self._custom_fields_cache
            
        try:
            url = f"{self.api_url}/api/v3/custom_fields"
            
            print("正在获取自定义字段列表...")
            response = self._session.get(
                url,
                auth=self.auth
            )
            
            if response.status_code == 200:
                result = response.json()
                custom_fields = result.get("_embedded", {}).get("elements", [])
                print(f"获取到 {len(custom_fields)} 个自定义字段")
                # 缓存结果
                self._custom_fields_cache = custom_fields
                return custom_fields
            else:
                print(f"获取自定义字段失败: {response.status_code} - {response.text}")
                # API不可用，尝试从工作包获取自定义字段信息
                print("尝试从工作包中获取自定义字段信息...")
                fields_from_wp = self._get_custom_fields_from_work_packages()
                # 缓存结果
                self._custom_fields_cache = fields_from_wp
                return fields_from_wp
        except Exception as e:
            print(f"获取自定义字段出错: {str(e)}")
            print("尝试从工作包中获取自定义字段信息...")
            fields_from_wp = self._get_custom_fields_from_work_packages()
            # 缓存结果
            self._custom_fields_cache = fields_from_wp
            return fields_from_wp
        
    def get_statuses(self):
        """获取状态列表"""
        # 实现获取状态的逻辑
        return []
        
    def get_types(self):
        """获取类型列表"""
        # 实现获取类型的逻辑
        return []
        
    def get_project_details(self, project_id):
        """获取项目详情
        
        Args:
            project_id: 项目ID
            
        Returns:
            项目详情数据，失败时返回None
        """
        try:
            url = f"{self.api_url}/api/v3/projects/{project_id}"
            
            print(f"正在获取项目详情: {project_id}")
            response = self._session.get(
                url,
                auth=self.auth
            )
            
            if response.status_code == 200:
                project_data = response.json()
                return project_data
            else:
                print(f"获取项目详情失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"获取项目详情出错: {str(e)}")
            return None
    
    def get_project_form_configuration(self, project_id):
        """获取项目表单配置
        
        Args:
            project_id: 项目ID
            
        Returns:
            项目表单配置数据，失败时返回空字典
        """
        # 检查缓存
        if project_id in self._project_form_config_cache:
            return self._project_form_config_cache[project_id]
            
        try:
            # 先尝试使用原API
            url = f"{self.api_url}/api/v3/projects/{project_id}/form"
            
            print(f"正在获取项目表单配置: {project_id}")
            response = self._session.get(
                url,
                auth=self.auth
            )
            
            if response.status_code == 200:
                form_data = response.json()
                # 缓存结果
                self._project_form_config_cache[project_id] = form_data
                return form_data
            else:
                print(f"获取项目表单配置失败: {response.status_code} - {response.text}")
                print("尝试获取工作包表单配置...")
                # 尝试工作包表单
                wp_form_data = self._get_work_package_form_configuration(project_id)
                if wp_form_data:
                    self._project_form_config_cache[project_id] = wp_form_data
                    return wp_form_data
                return {}
        except Exception as e:
            print(f"获取项目表单配置出错: {str(e)}")
            wp_form_data = self._get_work_package_form_configuration(project_id)
            if wp_form_data:
                self._project_form_config_cache[project_id] = wp_form_data
                return wp_form_data
            return {}
    
    def get_work_packages(self, project_id, page=1, page_size=100):
        """获取项目的工作包列表
        
        Args:
            project_id: 项目ID
            page: 页码
            page_size: 每页数量
            
        Returns:
            工作包列表，失败时返回None
        """
        try:
            url = f"{self.api_url}/api/v3/projects/{project_id}/work_packages"
            params = {
                "pageSize": page_size,
                "offset": (page - 1) * page_size,
                "filters": "[]"
            }
            
            print(f"正在获取项目工作包: {project_id}，页码: {page}，每页: {page_size}")
            response = self._session.get(
                url,
                params=params,
                auth=self.auth
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # 存储总数信息
                self._last_work_packages_total = result.get("total", 0)
                
                work_packages = result.get("_embedded", {}).get("elements", [])
                return work_packages
            else:
                print(f"获取工作包失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"获取工作包出错: {str(e)}")
            return None
    
    def get_last_work_packages_total(self):
        """获取最后一次工作包请求的总数
        
        Returns:
            工作包总数
        """
        return self._last_work_packages_total
    
    def get_work_package(self, work_package_id):
        """获取单个工作包详情
        
        Args:
            work_package_id: 工作包ID
            
        Returns:
            工作包详情数据，失败时返回None
        """
        try:
            url = f"{self.api_url}/api/v3/work_packages/{work_package_id}"
            
            response = self._session.get(
                url,
                auth=self.auth
            )
            
            if response.status_code == 200:
                work_package_data = response.json()
                return work_package_data
            else:
                print(f"获取工作包详情失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"获取工作包详情出错: {str(e)}")
            return None
    
    def get_work_package_attachments(self, work_package_id):
        """获取工作包的附件列表
        
        Args:
            work_package_id: 工作包ID
            
        Returns:
            附件列表，失败时返回空列表
        """
        try:
            url = f"{self.api_url}/api/v3/work_packages/{work_package_id}/attachments"
            
            response = self._session.get(
                url,
                auth=self.auth
            )
            
            if response.status_code == 200:
                result = response.json()
                attachments = result.get("_embedded", {}).get("elements", [])
                return attachments
            else:
                print(f"获取工作包附件失败: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"获取工作包附件出错: {str(e)}")
            return []
    
    def get_work_package_file_links(self, work_package_id):
        """获取工作包的文件链接列表
        
        Args:
            work_package_id: 工作包ID
            
        Returns:
            文件链接列表，失败时返回空列表
        """
        try:
            url = f"{self.api_url}/api/v3/work_packages/{work_package_id}/file_links"
            
            response = self._session.get(
                url,
                auth=self.auth
            )
            
            if response.status_code == 200:
                result = response.json()
                file_links = result.get("_embedded", {}).get("elements", [])
                return file_links
            else:
                print(f"获取工作包文件链接失败: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"获取工作包文件链接出错: {str(e)}")
            return []
    
    def download_attachment(self, attachment_id):
        """下载附件内容
        
        Args:
            attachment_id: 附件ID
            
        Returns:
            (附件内容二进制数据, 文件名, 内容类型)元组，失败时返回(None, None, None)
        """
        try:
            url = f"{self.api_url}/api/v3/attachments/{attachment_id}/content"
            
            response = self._session.get(
                url,
                auth=self.auth,
                stream=True  # 使用流式下载
            )
            
            if response.status_code == 200:
                # 获取文件名和内容类型
                content_disposition = response.headers.get('Content-Disposition', '')
                filename = None
                if content_disposition:
                    # 提取文件名
                    match = re.search(r'filename="?([^";]+)"?', content_disposition)
                    if match:
                        filename = match.group(1)
                
                content_type = response.headers.get('Content-Type', 'application/octet-stream')
                
                # 获取完整的二进制内容
                content = response.content
                
                return (content, filename, content_type)
            else:
                print(f"下载附件失败: {response.status_code} - {response.text}")
                return (None, None, None)
        except Exception as e:
            print(f"下载附件出错: {str(e)}")
            return (None, None, None)
    
    def get_custom_field_options(self, field_id):
        """获取自定义字段选项
        
        Args:
            field_id: 自定义字段ID
            
        Returns:
            选项列表，失败时返回空列表
        """
        try:
            # 尝试从项目表单配置获取选项
            projects = self.get_projects()
            if not projects:
                print("无法获取项目列表")
                return []
            
            project_id = projects[0].get("id")
            if not project_id:
                print("无法获取项目ID")
                return []
            
            # 获取项目表单配置
            form_config = self.get_project_form_configuration(project_id)
            if not form_config:
                print("无法获取项目表单配置")
                return []
            
            # 查找字段信息
            field_key = f"customField{field_id}"
            if field_key in form_config.get("fields", {}):
                field_info = form_config["fields"][field_key]
                
                # 从embedded中查找
                if "_embedded" in field_info and "allowedValues" in field_info["_embedded"]:
                    allowed_values = field_info["_embedded"]["allowedValues"]
                    options = []
                    for value in allowed_values:
                        if isinstance(value, dict):
                            option = {
                                "id": value.get("id"),
                                "value": value.get("value", value.get("name", "")),
                                "href": f"/api/v3/custom_options/{value.get('id')}"
                            }
                            options.append(option)
                    
                    print(f"从表单配置中获取到 {len(options)} 个选项")
                    return options
                
                # 从links中查找
                elif "_links" in field_info and "allowedValues" in field_info["_links"]:
                    values = field_info["_links"]["allowedValues"]
                    options = []
                    for value in values:
                        if "href" in value and "title" in value:
                            option_id = value["href"].split("/")[-1]
                            option = {
                                "id": option_id,
                                "value": value["title"],
                                "href": value["href"]
                            }
                            options.append(option)
                    
                    print(f"从links中获取到 {len(options)} 个选项")
                    return options
                    
            # 如果上述方法失败，尝试从工作包中提取
            print(f"尝试从工作包中提取字段ID={field_id}的选项")
            work_packages = self.get_work_packages(project_id, page=1, page_size=200)
            if not work_packages:
                print("无法获取工作包列表")
                return []
            
            options_dict = {}
            field_key = f"customField{field_id}"
            
            for wp in work_packages:
                if "_links" in wp and field_key in wp["_links"]:
                    field_value = wp["_links"][field_key]
                    
                    # 处理单个值
                    if isinstance(field_value, dict):
                        if "href" in field_value and "title" in field_value:
                            option_id = field_value["href"].split("/")[-1]
                            if option_id not in options_dict:
                                options_dict[option_id] = {
                                    "id": option_id,
                                    "value": field_value["title"],
                                    "href": field_value["href"]
                                }
                    
                    # 处理多个值
                    elif isinstance(field_value, list):
                        for value in field_value:
                            if isinstance(value, dict) and "href" in value and "title" in value:
                                option_id = value["href"].split("/")[-1]
                                if option_id not in options_dict:
                                    options_dict[option_id] = {
                                        "id": option_id,
                                        "value": value["title"],
                                        "href": value["href"]
                                    }
            
            options = list(options_dict.values())
            print(f"从工作包中提取到 {len(options)} 个选项")
            return options
            
        except Exception as e:
            print(f"获取自定义字段选项出错: {str(e)}")
            return []
    
    def import_project(self, project_data, new_name=None, import_options=None):
        """导入项目
        
        Args:
            project_data: 项目数据
            new_name: 新项目名称
            import_options: 导入选项
            
        Returns:
            新项目ID
        """
        # 计算导入开始时间
        start_time = time.time()
        
        # 获取进度回调函数（如果有）
        progress_callback = None
        force_relations = False  # 默认不强制处理关系
        
        if import_options:
            if "progress_callback" in import_options:
                progress_callback = import_options["progress_callback"]
            if "force_relations" in import_options:
                force_relations = import_options["force_relations"]
        
        # 获取映射
        custom_field_mapping = import_options.get("custom_field_mapping", {}) if import_options else {}
        status_mapping = import_options.get("status_mapping", {}) if import_options else {}
        type_mapping = import_options.get("type_mapping", {}) if import_options else {}
        
        try:
            # 提取项目信息
            print(f"开始导入项目: {new_name or project_data.get('project', {}).get('name', '未命名')}")
            
            if "project" not in project_data:
                raise ValueError("无效的项目数据: 缺少项目信息")
            
            project_info = project_data["project"]
            
            # 准备创建新项目的数据
            original_name = project_info.get("name", "未命名项目")
            original_identifier = project_info.get("identifier", "").lower()
            
            # 使用新名称或添加导入后缀
            project_name = new_name or f"{original_name} (导入)"
            
            # 为标识符添加随机后缀以避免冲突
            import_suffix = f"import_{int(time.time())}"
            project_identifier = f"{original_identifier}_{import_suffix}"
            
            # 创建项目的请求数据
            new_project_data = {
                "name": project_name,
                "identifier": project_identifier,
                "description": {
                    "raw": project_info.get("description", {}).get("raw", f"从 {original_name} 导入")
                }
            }
            
            # 发送创建项目请求
            if progress_callback:
                progress_callback("创建项目", 0, 1, f"正在创建新项目: {project_name}")
            
            url = f"{self.api_url}/api/v3/projects"
            response = self._session.post(
                url,
                json=new_project_data,
                auth=self.auth
            )
            
            if response.status_code not in [201, 200]:
                error_msg = f"创建项目失败: {response.status_code} - {response.text}"
                print(error_msg)
                raise ValueError(error_msg)
            
            # 获取新项目ID
            new_project = response.json()
            new_project_id = new_project.get("id")
            
            if not new_project_id:
                raise ValueError("创建项目成功但无法获取项目ID")
            
            print(f"新项目创建成功，ID: {new_project_id}")
            
            # 导入工作包
            if "work_packages" in project_data and project_data["work_packages"]:
                work_packages = project_data["work_packages"]
                total_wp_count = len(work_packages)
                
                if progress_callback:
                    progress_callback("创建工作包", 0, total_wp_count, f"准备导入 {total_wp_count} 个工作包")
                
                print(f"开始导入 {total_wp_count} 个工作包...")
                
                # 用于存储旧ID与新ID的映射关系
                id_mapping = {}
                completed_count = 0
                
                # 串行创建工作包
                for index, wp in enumerate(work_packages):
                    try:
                        # 获取原始工作包信息
                        original_id = wp.get("id")
                        wp_subject = wp.get("subject", "未命名工作包")
                        wp_description = wp.get("description", {}).get("raw", "")
                        
                        # 准备新工作包数据
                        new_wp_data = {
                            "subject": wp_subject,
                            "_links": {
                                "project": {
                                    "href": f"/api/v3/projects/{new_project_id}"
                                }
                            }
                        }
                        
                        # 添加描述
                        if wp_description:
                            new_wp_data["description"] = {"raw": wp_description}
                        
                        # 添加类型
                        if "_links" in wp and "type" in wp["_links"]:
                            original_type_id = None
                            type_title = wp["_links"]["type"].get("title", "")
                            type_href = wp["_links"]["type"].get("href", "")
                            
                            if type_href:
                                # 从href中提取ID
                                try:
                                    original_type_id = re.search(r"/(\d+)$", type_href).group(1)
                                except:
                                    pass
                            
                            # 使用类型映射或使用相同的类型名称
                            if original_type_id and original_type_id in type_mapping:
                                mapped_type_id = type_mapping[original_type_id]
                                new_wp_data["_links"]["type"] = {"href": f"/api/v3/types/{mapped_type_id}"}
                            elif type_title:
                                # 查找相同名称的类型
                                types = self.get_types()
                                for t in types:
                                    if t.get("name") == type_title:
                                        new_wp_data["_links"]["type"] = {"href": f"/api/v3/types/{t.get('id')}"}
                                        break
                        
                        # 添加状态
                        if "_links" in wp and "status" in wp["_links"]:
                            original_status_id = None
                            status_title = wp["_links"]["status"].get("title", "")
                            status_href = wp["_links"]["status"].get("href", "")
                            
                            if status_href:
                                # 从href中提取ID
                                try:
                                    original_status_id = re.search(r"/(\d+)$", status_href).group(1)
                                except:
                                    pass
                            
                            # 使用状态映射或使用相同的状态ID
                            if original_status_id and original_status_id in status_mapping:
                                # 如果有特定的状态映射，优先使用
                                mapped_status_id = status_mapping[original_status_id]
                                new_wp_data["_links"]["status"] = {"href": f"/api/v3/statuses/{mapped_status_id}"}
                                print(f"使用映射状态ID: {original_status_id} -> {mapped_status_id}, 标题: {status_title}")
                            elif original_status_id:
                                # 直接使用原始状态ID，保持一致性
                                new_wp_data["_links"]["status"] = {"href": f"/api/v3/statuses/{original_status_id}"}
                                print(f"使用原始状态ID: {original_status_id}, 标题: {status_title}")
                            elif status_title:
                                # 查找相同名称的状态（作为备选）
                                statuses = self.get_statuses()
                                for s in statuses:
                                    if s.get("name") == status_title:
                                        new_wp_data["_links"]["status"] = {"href": f"/api/v3/statuses/{s.get('id')}"}
                                        print(f"通过名称匹配状态: {status_title}, ID: {s.get('id')}")
                                        break
                        
                        # 添加自定义字段
                        if "_links" in wp:
                            for key, value in wp["_links"].items():
                                # 检查是否是自定义字段
                                if key.startswith("customField") and isinstance(value, dict):
                                    # 获取自定义字段ID和值
                                    field_id = key.replace("customField", "")
                                    field_href = value.get("href", "")
                                    field_title = value.get("title", "")
                                    
                                    # 检查是否有自定义字段映射
                                    mapped_field_id = None
                                    if field_id in custom_field_mapping:
                                        mapped_field_id = custom_field_mapping[field_id]
                                        mapped_key = f"customField{mapped_field_id}"
                                        print(f"应用自定义字段映射: {key} -> {mapped_key}")
                                    else:
                                        mapped_key = key
                                    
                                    if field_href and field_title:
                                        print(f"处理自定义字段: {mapped_key}, 值: {field_title}")
                                        # 添加到新工作包数据
                                        new_wp_data["_links"][mapped_key] = {
                                            "href": field_href,
                                            "title": field_title
                                        }
                                        
                                        # 特殊处理城市字段
                                        if field_id == "1" and "城市" in field_title:
                                            # 获取城市字段ID
                                            city_field_id = self.get_city_field_id()
                                            city_key = f"customField{city_field_id}"
                                            # 如果与原始键不同，则添加城市字段
                                            if city_key != mapped_key:
                                                print(f"添加城市字段映射: {city_key}, 值: {field_title}")
                                                new_wp_data["_links"][city_key] = {
                                                    "href": field_href,
                                                    "title": field_title
                                                }
                        
                        # 创建工作包
                        create_url = f"{self.api_url}/api/v3/work_packages"
                        create_response = self._session.post(
                            create_url,
                            json=new_wp_data,
                            auth=self.auth
                        )
                        
                        if create_response.status_code not in [201, 200]:
                            print(f"创建工作包失败: {create_response.status_code} - {create_response.text}")
                            continue
                        
                        # 获取新工作包ID
                        new_wp = create_response.json()
                        new_wp_id = new_wp.get("id")
                        
                        if not new_wp_id:
                            print(f"创建工作包成功但无法获取ID: {wp_subject}")
                            continue
                        
                        print(f"工作包创建成功: {wp_subject}, 新ID: {new_wp_id}, 原ID: {original_id}")
                        
                        # 存储ID映射关系
                        if original_id:
                            id_mapping[str(original_id)] = str(new_wp_id)
                            
                    except Exception as e:
                        print(f"导入工作包过程中出错: {str(e)}")
                        continue
                    finally:
                        # 更新进度
                        completed_count += 1
                        if progress_callback and (completed_count % 5 == 0 or completed_count == total_wp_count):
                            progress_callback("创建工作包", completed_count, total_wp_count, 
                                            f"已创建 {completed_count}/{total_wp_count} 个工作包")
                
                # 更新最终进度
                if progress_callback:
                    progress_callback("创建工作包", total_wp_count, total_wp_count, f"已导入 {len(id_mapping)} 个工作包")
                
                print(f"工作包导入完成，成功导入 {len(id_mapping)} 个工作包")
                
                # 等待服务器处理完所有工作包创建请求
                if progress_callback:
                    progress_callback("处理关系", 0, 1, "等待工作包创建稳定，准备处理关系...")
                
                wait_time = 15  # 增加等待时间到15秒
                print(f"等待{wait_time}秒，确保所有工作包创建完全处理完毕...")
                time.sleep(wait_time)
                
                # 导入关系
                if id_mapping and work_packages:
                    if progress_callback:
                        progress_callback("处理关系", 0, 1, "准备处理工作包关系")
                    
                    # 初始化关系处理的计数器
                    relations_created = 0
                    relations_failed = 0
                    
                    # 处理关系的函数
                    def process_relation(relation_type, from_id, to_id):
                        """处理工作包关系
                        
                        Args:
                            relation_type: 关系类型 ('parent', 'child', 'follows', 'precedes', 'relates')
                            from_id: 源工作包ID
                            to_id: 目标工作包ID
                            
                        Returns:
                            bool: 是否成功创建关系
                        """
                        max_retries = 8  # 增加最大重试次数
                        retry_count = 0
                        
                        while retry_count < max_retries:
                            try:
                                print(f"尝试创建关系 (尝试 {retry_count+1}/{max_retries}): {relation_type} {from_id} -> {to_id}")
                                
                                if relation_type == 'parent':
                                    # 设置父工作包关系
                                    update_url = f"{self.api_url}/api/v3/work_packages/{from_id}"
                                    
                                    # 获取当前工作包信息以获取lock_version
                                    get_wp_response = self._session.get(
                                        update_url,
                                        auth=self.auth
                                    )
                                    
                                    if get_wp_response.status_code != 200:
                                        print(f"获取工作包信息失败: {from_id}, 状态码: {get_wp_response.status_code}")
                                        retry_count += 1
                                        time.sleep(2)  # 增加等待时间
                                        continue
                                    
                                    wp_data = get_wp_response.json()
                                    lock_version = wp_data.get("lockVersion", 0)
                                    
                                    # 设置关系
                                    update_data = {
                                        "lockVersion": lock_version,
                                        "_links": {
                                            "parent": {
                                                "href": f"/api/v3/work_packages/{to_id}"
                                            }
                                        },
                                        "_flags": ["force_relation"]  # 添加强制关系标志
                                    }
                                    
                                    response = self._session.patch(
                                        update_url,
                                        json=update_data,
                                        auth=self.auth
                                    )
                                    
                                    if response.status_code in [200, 201]:
                                        print(f"设置父子关系成功: {from_id} -> {to_id}")
                                        return True
                                    else:
                                        print(f"设置父子关系失败: {from_id} -> {to_id}, 状态码: {response.status_code}, 返回: {response.text}")
                                        # 如果是冲突，更新锁版本后重试
                                        if response.status_code == 409:
                                            retry_count += 1
                                            time.sleep(3)  # 增加等待时间
                                            continue
                                        
                                        # 如果失败，尝试使用关系API
                                        if retry_count >= max_retries / 2:
                                            try:
                                                print(f"尝试使用关系API替代父子关系: {from_id} -> {to_id}")
                                                relation_url = f"{self.api_url}/api/v3/work_package_relations"
                                                relation_data = {
                                                    "_links": {
                                                        "from": {
                                                            "href": f"/api/v3/work_packages/{from_id}"
                                                        },
                                                        "to": {
                                                            "href": f"/api/v3/work_packages/{to_id}"
                                                        }
                                                    },
                                                    "type": "relates"  # 使用relates作为替代
                                                }
                                                
                                                alt_response = self._session.post(
                                                    relation_url,
                                                    json=relation_data,
                                                    auth=self.auth
                                                )
                                                
                                                if alt_response.status_code in [200, 201]:
                                                    print(f"使用关系API创建关联关系成功: {from_id} -> {to_id}")
                                                    return True
                                            except Exception as e:
                                                print(f"替代方法出错: {str(e)}")
                                        
                                        retry_count += 1
                                        time.sleep(3)  # 增加等待时间
                                        continue
                                
                                elif relation_type == 'child':
                                    # 子关系与父关系相反，from成为to的子
                                    update_url = f"{self.api_url}/api/v3/work_packages/{from_id}"
                                    
                                    # 获取当前工作包信息以获取lock_version
                                    get_wp_response = self._session.get(
                                        update_url,
                                        auth=self.auth
                                    )
                                    
                                    if get_wp_response.status_code != 200:
                                        print(f"获取工作包信息失败: {from_id}, 状态码: {get_wp_response.status_code}")
                                        retry_count += 1
                                        time.sleep(2)  # 增加等待时间
                                        continue
                                    
                                    wp_data = get_wp_response.json()
                                    lock_version = wp_data.get("lockVersion", 0)
                                    
                                    # 设置关系
                                    update_data = {
                                        "lockVersion": lock_version,
                                        "_links": {
                                            "parent": {
                                                "href": f"/api/v3/work_packages/{to_id}"
                                            }
                                        },
                                        "_flags": ["force_relation"]  # 添加强制关系标志
                                    }
                                    
                                    response = self._session.patch(
                                        update_url,
                                        json=update_data,
                                        auth=self.auth
                                    )
                                    
                                    if response.status_code in [200, 201]:
                                        print(f"设置子关系成功: {from_id} -> {to_id}")
                                        return True
                                    else:
                                        print(f"设置子关系失败: {from_id} -> {to_id}, 状态码: {response.status_code}, 返回: {response.text}")
                                        # 如果是冲突，更新锁版本后重试
                                        if response.status_code == 409:
                                            retry_count += 1
                                            time.sleep(3)  # 增加等待时间
                                            continue
                                        
                                        # 如果失败，尝试使用关系API
                                        if retry_count >= max_retries / 2:
                                            try:
                                                print(f"尝试使用关系API替代子关系: {from_id} -> {to_id}")
                                                relation_url = f"{self.api_url}/api/v3/work_package_relations"
                                                relation_data = {
                                                    "_links": {
                                                        "from": {
                                                            "href": f"/api/v3/work_packages/{from_id}"
                                                        },
                                                        "to": {
                                                            "href": f"/api/v3/work_packages/{to_id}"
                                                        }
                                                    },
                                                    "type": "relates"  # 使用relates作为替代
                                                }
                                                
                                                alt_response = self._session.post(
                                                    relation_url,
                                                    json=relation_data,
                                                    auth=self.auth
                                                )
                                                
                                                if alt_response.status_code in [200, 201]:
                                                    print(f"使用关系API创建关联关系成功: {from_id} -> {to_id}")
                                                    return True
                                            except Exception as e:
                                                print(f"替代方法出错: {str(e)}")
                                        
                                        retry_count += 1
                                        time.sleep(3)  # 增加等待时间
                                        continue
                                
                                else:
                                    # 处理其他类型的关系
                                    relation_url = f"{self.api_url}/api/v3/work_package_relations"
                                    relation_data = {
                                        "_links": {
                                            "from": {
                                                "href": f"/api/v3/work_packages/{from_id}"
                                            },
                                            "to": {
                                                "href": f"/api/v3/work_packages/{to_id}"
                                            }
                                        }
                                    }
                                    
                                    # 根据关系类型设置type属性
                                    if relation_type == 'follows':
                                        relation_data["type"] = "follows"
                                    elif relation_type == 'precedes':
                                        relation_data["type"] = "precedes"
                                    elif relation_type == 'relates':
                                        relation_data["type"] = "relates"
                                    else:
                                        print(f"未知的关系类型: {relation_type}")
                                        return False
                                    
                                    response = self._session.post(
                                        relation_url,
                                        json=relation_data,
                                        auth=self.auth
                                    )
                                    
                                    if response.status_code in [200, 201]:
                                        print(f"创建{relation_type}关系成功: {from_id} -> {to_id}")
                                        return True
                                    else:
                                        print(f"创建{relation_type}关系失败: {from_id} -> {to_id}, 状态码: {response.status_code}, 返回: {response.text}")
                                        retry_count += 1
                                        time.sleep(2)  # 增加等待时间
                                        continue
                                
                            except Exception as e:
                                print(f"处理关系时出错 ({relation_type}): {from_id} -> {to_id}, 错误: {str(e)}")
                                retry_count += 1
                                time.sleep(2)  # 增加等待时间
                                continue
                        
                        # 如果重试多次仍然失败
                        print(f"处理关系失败，已重试 {max_retries} 次: {relation_type} {from_id} -> {to_id}")
                        return False
                    
                    # 准备关系数据
                    parent_child_relations = []
                    predecessor_successor_relations = []
                    other_relations = []
                    
                    for wp in work_packages:
                        original_id = str(wp.get("id"))
                        if not original_id or original_id not in id_mapping:
                            continue
                        
                        new_id = id_mapping[original_id]
                        
                        # 处理父关系
                        if "_links" in wp and "parent" in wp["_links"] and wp["_links"]["parent"]:
                            parent_href = wp["_links"]["parent"].get("href", "")
                            if parent_href:
                                # 从href中提取父ID
                                try:
                                    parent_id = re.search(r"/(\d+)$", parent_href).group(1)
                                    if parent_id and parent_id in id_mapping:
                                        parent_child_relations.append(('child', new_id, id_mapping[parent_id]))
                                except:
                                    pass
                        
                        # 收集关系数据
                        if "relations" in wp:
                            for relation in wp["relations"]:
                                relation_type = relation.get("type", "")
                                to_id = relation.get("to_id", "")
                                
                                if not to_id or not relation_type or to_id not in id_mapping:
                                    continue
                                
                                # 根据关系类型分类
                                if relation_type in ["precedes", "follows"]:
                                    predecessor_successor_relations.append((relation_type, new_id, id_mapping[to_id]))
                                else:
                                    other_relations.append((relation_type, new_id, id_mapping[to_id]))
                    
                    # 计算总关系数
                    total_relations = len(parent_child_relations) + len(predecessor_successor_relations) + len(other_relations)
                    print(f"找到 {total_relations} 个关系需要处理")
                    
                    if total_relations > 0:
                        current_progress = 0
                        
                        # 第一阶段：处理父子关系
                        if progress_callback:
                            progress_callback("处理关系", current_progress, total_relations, 
                                            f"处理父子关系 (0/{len(parent_child_relations)})")
                        
                        parent_child_successful = 0
                        for i, (relation_type, from_id, to_id) in enumerate(parent_child_relations):
                            result = process_relation(relation_type, from_id, to_id)
                            if result:
                                parent_child_successful += 1
                            
                            # 每处理一个关系就等待一小段时间
                            time.sleep(1.5)
                            
                            current_progress += 1
                            if progress_callback and (i % 5 == 0 or i == len(parent_child_relations) - 1):
                                progress_callback("处理关系", current_progress, total_relations, 
                                                f"处理父子关系 ({i+1}/{len(parent_child_relations)})")
                        
                        relations_created += parent_child_successful
                        relations_failed += len(parent_child_relations) - parent_child_successful
                        
                        # 在处理完父子关系后等待后再处理其他关系
                        wait_time = 10
                        print(f"父子关系处理完成，等待{wait_time}秒再处理前置后置关系...")
                        time.sleep(wait_time)
                        
                        # 第二阶段：处理前置后置关系
                        if progress_callback:
                            progress_callback("处理关系", current_progress, total_relations, 
                                            f"处理前置/后置关系 (0/{len(predecessor_successor_relations)})")
                        
                        pred_succ_successful = 0
                        for i, (relation_type, from_id, to_id) in enumerate(predecessor_successor_relations):
                            result = process_relation(relation_type, from_id, to_id)
                            if result:
                                pred_succ_successful += 1
                            
                            # 每处理一个关系就等待一小段时间
                            time.sleep(1.5)
                            
                            current_progress += 1
                            if progress_callback and (i % 5 == 0 or i == len(predecessor_successor_relations) - 1):
                                progress_callback("处理关系", current_progress, total_relations, 
                                                f"处理前置/后置关系 ({i+1}/{len(predecessor_successor_relations)})")
                        
                        relations_created += pred_succ_successful
                        relations_failed += len(predecessor_successor_relations) - pred_succ_successful
                        
                        # 在处理完前置后置关系后等待后再处理其他关系
                        wait_time = 10
                        print(f"前置后置关系处理完成，等待{wait_time}秒再处理其他关系...")
                        time.sleep(wait_time)
                        
                        # 第三阶段：处理其他关系
                        if progress_callback:
                            progress_callback("处理关系", current_progress, total_relations, 
                                            f"处理其他关系 (0/{len(other_relations)})")
                        
                        other_successful = 0
                        for i, (relation_type, from_id, to_id) in enumerate(other_relations):
                            result = process_relation(relation_type, from_id, to_id)
                            if result:
                                other_successful += 1
                            
                            # 每处理一个关系就等待一小段时间
                            time.sleep(1.5)
                            
                            current_progress += 1
                            if progress_callback and (i % 5 == 0 or i == len(other_relations) - 1):
                                progress_callback("处理关系", current_progress, total_relations, 
                                                f"处理其他关系 ({i+1}/{len(other_relations)})")
                        
                        relations_created += other_successful
                        relations_failed += len(other_relations) - other_successful
                        
                        # 更新最终进度
                        if progress_callback:
                            progress_callback("处理关系", total_relations, total_relations, 
                                            f"关系处理完成: 成功 {relations_created}, 失败 {relations_failed}")
                        
                        print(f"关系处理完成: 成功 {relations_created}, 失败 {relations_failed}")
                    else:
                        if progress_callback:
                            progress_callback("处理关系", 1, 1, "没有找到需要处理的关系")
                        print("没有找到需要处理的关系")
            
            # 记录导入耗时
            end_time = time.time()
            print(f"项目导入完成，共耗时: {end_time - start_time:.2f}秒")
            
            return new_project_id
            
        except Exception as e:
            error_msg = f"导入项目失败: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return None
    
    def _create_work_package_relation(self, from_id, to_id, relation_type):
        """创建工作包之间的关系
        
        Args:
            from_id: 源工作包ID
            to_id: 目标工作包ID
            relation_type: 关系类型 (follows, precedes, relates, etc.)
            
        Returns:
            bool: 是否成功创建关系
        """
        try:
            url = f"{self.api_url}/api/v3/relations"
            relation_data = {
                "_links": {
                    "from": {
                        "href": f"/api/v3/work_packages/{from_id}"
                    },
                    "to": {
                        "href": f"/api/v3/work_packages/{to_id}"
                    }
                },
                "type": relation_type
            }
            
            response = self._session.post(
                url,
                json=relation_data,
                auth=self.auth
            )
            
            if response.status_code in [201, 200]:
                print(f"创建关系成功: {from_id} -> {to_id}, 类型: {relation_type}")
                return True
            else:
                print(f"创建关系失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"创建关系时出错: {str(e)}")
            return False

    def get_cities(self):
        """获取城市列表"""
        # 添加缓存
        if hasattr(self, '_cities_cache') and self._cities_cache:
            # 确保城市对象包含name字段
            for city in self._cities_cache:
                if "value" in city and "name" not in city:
                    city["name"] = city["value"]
            print("从缓存返回城市列表")
            return self._cities_cache
            
        print("正在获取城市列表...")
        
        # 获取城市字段ID - 这里会使用缓存，不会重复查询
        city_field_id = self.get_city_field_id()
        city_field_key = f"customField{city_field_id}"
        print(f"使用城市字段ID: {city_field_id}, 字段键: {city_field_key}")
        
        # 从获取的工作包中提取城市信息
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # 获取项目列表
                projects = self.get_projects(force_refresh=(retry_count > 0))
                if not projects:
                    print(f"无法获取项目列表 (尝试 {retry_count+1}/{max_retries})")
                    retry_count += 1
                    time.sleep(1)  # 等待一秒后重试
                    continue
                
                project_id = projects[0].get("id")
                
                # 尝试直接从自定义字段选项获取城市列表（更高效）
                cities = self.get_custom_field_options(city_field_id)
                if cities:
                    print(f"从自定义字段选项获取到 {len(cities)} 个城市")
                    # 确保每个城市对象都有name字段
                    for city in cities:
                        if "value" in city and "name" not in city:
                            city["name"] = city["value"]
                    # 缓存结果
                    self._cities_cache = cities
                    return cities
                
                print(f"从自定义字段选项获取城市失败，尝试从工作包提取 (尝试 {retry_count+1}/{max_retries})")
                
                # 如果从选项获取失败，尝试不同页大小的工作包
                page_sizes = [200, 100, 50]
                for page_size in page_sizes:
                    print(f"尝试获取 {page_size} 个工作包...")
                    work_packages = self.get_work_packages(project_id, page=1, page_size=page_size)
                    if work_packages:
                        break
                
                if not work_packages:
                    print(f"无法获取工作包列表 (尝试 {retry_count+1}/{max_retries})")
                    retry_count += 1
                    time.sleep(1)  # 等待一秒后重试
                    continue
                
                print(f"成功获取 {len(work_packages)} 个工作包，开始提取城市信息...")
                
                # 从工作包中提取城市信息
                cities_dict = {}
                
                for wp in work_packages:
                    if "_links" in wp and city_field_key in wp["_links"]:
                        city_link = wp["_links"][city_field_key]
                        
                        # 处理不同格式的城市字段
                        if isinstance(city_link, dict):
                            city_href = city_link.get("href", "")
                            city_title = city_link.get("title", "")
                            
                            if city_href and city_title:
                                # 从href中提取ID
                                city_id = city_href.split("/")[-1]
                                
                                # 添加到字典中
                                if city_id not in cities_dict:
                                    cities_dict[city_id] = {
                                        "id": city_id,
                                        "name": city_title,  # 确保使用name字段
                                        "value": city_title,
                                        "href": city_href
                                    }
                        
                        # 如果是列表，处理多个城市
                        elif isinstance(city_link, list):
                            for city in city_link:
                                if isinstance(city, dict):
                                    city_href = city.get("href", "")
                                    city_title = city.get("title", "")
                                    
                                    if city_href and city_title:
                                        # 从href中提取ID
                                        city_id = city_href.split("/")[-1]
                                        
                                        # 添加到字典中
                                        if city_id not in cities_dict:
                                            cities_dict[city_id] = {
                                                "id": city_id,
                                                "name": city_title,  # 确保使用name字段
                                                "value": city_title,
                                                "href": city_href
                                            }
                
                # 转换为列表
                cities = list(cities_dict.values())
                print(f"从工作包中提取到 {len(cities)} 个城市")
                
                # 如果找到了城市，返回结果
                if cities:
                    # 缓存结果
                    self._cities_cache = cities
                    return cities
                else:
                    print(f"未能从工作包中提取到城市 (尝试 {retry_count+1}/{max_retries})")
                    retry_count += 1
                    time.sleep(1)  # 等待一秒后重试
            
            except Exception as e:
                print(f"从工作包获取城市列表出错: {str(e)} (尝试 {retry_count+1}/{max_retries})")
                retry_count += 1
                time.sleep(1)  # 等待一秒后重试
        
        # 如果所有重试都失败，尝试额外的方法
        print("所有常规方法获取城市失败，尝试备用方案...")
        
        try:
            # 尝试获取更多项目
            all_projects = self.get_projects(force_refresh=True)
            
            # 尝试在所有项目中搜索城市字段
            for project in all_projects:
                project_id = project.get("id")
                print(f"尝试在项目 {project_id} 中搜索城市...")
                
                # 获取项目表单配置
                form_config = self.get_project_form_configuration(project_id)
                if form_config:
                    # 查找城市字段
                    field_key = f"customField{city_field_id}"
                    if "fields" in form_config and field_key in form_config["fields"]:
                        field_info = form_config["fields"][field_key]
                        
                        # 从links或embedded中查找选项
                        if "_links" in field_info and "allowedValues" in field_info["_links"]:
                            values = field_info["_links"]["allowedValues"]
                            cities = []
                            
                            for value in values:
                                if "href" in value and "title" in value:
                                    option_id = value["href"].split("/")[-1]
                                    option = {
                                        "id": option_id,
                                        "name": value["title"],  # 确保使用name字段
                                        "value": value["title"],
                                        "href": value["href"]
                                    }
                                    cities.append(option)
                            
                            if cities:
                                print(f"从项目 {project_id} 配置中获取到 {len(cities)} 个城市")
                                self._cities_cache = cities
                                return cities
        except Exception as e:
            print(f"备用方案获取城市失败: {str(e)}")
            
        # 如果所有方法都失败，返回空列表
        print("所有方法都无法获取城市列表，返回空结果")
        return []
    
    def _get_work_package_form_configuration(self, project_id):
        """通过工作包表单获取配置信息"""
        try:
            url = f"{self.api_url}/api/v3/projects/{project_id}/work_packages/form"
            
            print(f"正在获取工作包表单配置: {project_id}")
            response = self._session.post(
                url,
                json={},
                auth=self.auth
            )
            
            if response.status_code == 200:
                form_data = response.json()
                print("成功获取工作包表单配置")
                return form_data
            else:
                print(f"获取工作包表单配置失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"获取工作包表单配置出错: {str(e)}")
            return None
    
    def _get_custom_fields_from_work_packages(self):
        """从工作包中提取自定义字段信息"""
        try:
            # 获取项目列表
            projects = self.get_projects()
            if not projects:
                print("无法获取项目列表，返回空字段列表")
                return []
            
            project_id = projects[0].get("id")
            if not project_id:
                print("无法获取项目ID，返回空字段列表")
                return []
            
            # 尝试从工作包表单配置获取
            try:
                form_data = self._get_work_package_form_configuration(project_id)
                if form_data and "fields" in form_data:
                    custom_fields = []
                    for field_key, field_info in form_data["fields"].items():
                        if field_key.startswith("customField"):
                            field_id = field_key.replace("customField", "")
                            field_name = field_info.get("name", f"自定义字段{field_id}")
                            custom_fields.append({
                                "id": field_id,
                                "name": field_name
                            })
                    
                    if custom_fields:
                        print(f"从工作包表单配置提取到 {len(custom_fields)} 个自定义字段")
                        return custom_fields
            except Exception as e:
                print(f"从工作包表单提取字段出错: {str(e)}")
                
            # 获取工作包列表
            print("尝试从工作包列表提取自定义字段...")
            work_packages = self.get_work_packages(project_id, page=1, page_size=50)
            if not work_packages:
                print("无法获取工作包列表，返回空字段列表")
                return []
            
            # 提取自定义字段信息
            custom_fields = {}
            
            # 检查schema信息
            if isinstance(work_packages, dict) and "_schema" in work_packages:
                schema = work_packages.get("_schema", {})
                for key, value in schema.items():
                    if key.startswith("customField"):
                        field_id = key.replace("customField", "")
                        field_name = value.get("name", f"自定义字段{field_id}")
                        custom_fields[field_id] = {
                            "id": field_id,
                            "name": field_name
                        }
                
                if custom_fields:
                    print(f"从schema提取到 {len(custom_fields)} 个自定义字段")
                    return list(custom_fields.values())
            
            # 从工作包的links提取
            for wp in work_packages:
                if "_links" in wp:
                    links = wp["_links"]
                    for key, value in links.items():
                        if key.startswith("customField"):
                            field_id = key.replace("customField", "")
                            field_title = ""
                            
                            if isinstance(value, dict) and "title" in value:
                                field_title = value.get("title", "")
                            
                            if field_id not in custom_fields:
                                custom_fields[field_id] = {
                                    "id": field_id,
                                    "name": f"自定义字段{field_id}",
                                    "value": field_title
                                }
            
            result = list(custom_fields.values())
            print(f"从工作包links提取到 {len(result)} 个自定义字段")
            return result
            
        except Exception as e:
            print(f"从工作包提取自定义字段出错: {str(e)}")
            print("返回空字段列表")
            return []

    def get_custom_field_id_by_name(self, field_name):
        """通过字段名称获取自定义字段ID
        
        Args:
            field_name: 自定义字段名称，如"城市"
            
        Returns:
            字段ID号码（例如1），如果未找到则返回None
        """
        # 检查缓存
        if field_name in self._field_name_to_id_cache:
            cached_id = self._field_name_to_id_cache[field_name]
            print(f"从缓存获取字段 '{field_name}' 的ID: {cached_id}")
            return cached_id
            
        try:
            print(f"正在查找名为 '{field_name}' 的自定义字段...")
            
            # 直接获取自定义字段列表，这样更高效
            custom_fields = self.get_custom_fields()
            if custom_fields:
                for field in custom_fields:
                    if field.get("name") == field_name:
                        field_id = field.get("id")
                        if field_id:
                            print(f"找到字段 '{field_name}' 对应编号: {field_id}")
                            # 缓存结果
                            self._field_name_to_id_cache[field_name] = field_id
                            return field_id
            
            # 如果自定义字段列表中未找到，尝试通过项目表单配置
            projects = self.get_projects()
            if not projects:
                print("无法获取项目列表")
                # 缓存结果为None
                self._field_name_to_id_cache[field_name] = None
                return None
            
            project_id = projects[0].get("id")
            if not project_id:
                print("无法获取项目ID")
                # 缓存结果为None
                self._field_name_to_id_cache[field_name] = None
                return None
            
            # 获取项目表单配置
            form_config = self.get_project_form_configuration(project_id)
            if not form_config:
                print("无法获取项目表单配置")
                # 缓存结果为None
                self._field_name_to_id_cache[field_name] = None
                return None
                
            # 查找匹配的字段
            fields = form_config.get("fields", {})
            for field_key, field_info in fields.items():
                if field_key.startswith("customField") and field_info.get("name") == field_name:
                    field_id = field_key.replace("customField", "")
                    print(f"找到字段 '{field_name}' 对应编号: {field_id}")
                    # 缓存结果
                    self._field_name_to_id_cache[field_name] = field_id
                    return field_id
            
            # 标记为未找到并缓存，避免重复查询
            print(f"未找到名为 '{field_name}' 的自定义字段，将缓存此结果")
            self._field_name_to_id_cache[field_name] = None
            return None
            
        except Exception as e:
            print(f"查找自定义字段时出错: {str(e)}")
            # 发生错误时不缓存，下次可以重试
            return None

    def get_city_field_id(self):
        """获取"城市"字段的ID
        
        Returns:
            城市字段ID（如1），如果未找到则返回默认值1
        """
        # 添加缓存属性，避免重复查询
        if hasattr(self, '_city_field_id_cache'):
            return self._city_field_id_cache
            
        print("首次查找城市字段ID...")
        field_id = self.get_custom_field_id_by_name("城市")
        
        if field_id is not None:
            # 缓存结果
            self._city_field_id_cache = field_id
            print(f"找到城市字段ID: {field_id}，已缓存")
            return field_id
        
        # 设置默认值为1并缓存（兼容旧版本）
        print("未找到'城市'字段，使用默认ID: 1")
        self._city_field_id_cache = "1"
        return "1"

# 创建API客户端实例
api_client = OpenProjectClient()