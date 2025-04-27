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
        
        # 清空缓存
        self._projects_cache = None
        self._project_form_config_cache = {}
    
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
                return custom_fields
            else:
                print(f"获取自定义字段失败: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"获取自定义字段出错: {str(e)}")
            return []
    
    def get_work_packages(self, project_id, page=1, page_size=100):
        """获取项目的工作包列表"""
        try:
            url = f"{self.api_url}/api/v3/projects/{project_id}/work_packages"
            params = {
                "pageSize": page_size,
                "offset": (page - 1) * page_size
            }
            
            print(f"正在获取项目 {project_id} 的工作包...")
            response = self._session.get(
                url,
                params=params,
                auth=self.auth
            )
            
            if response.status_code == 200:
                result = response.json()
                work_packages = result.get("_embedded", {}).get("elements", [])
                total = result.get("total", 0)
                self._last_work_packages_total = total
                print(f"获取到 {len(work_packages)} 个工作包，总共 {total} 个")
                return work_packages
            else:
                print(f"获取工作包失败: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"获取工作包出错: {str(e)}")
            return []
    
    def test_connection(self):
        """测试API连接"""
        try:
            # 尝试获取项目列表，只需要一个项目即可验证连接
            url = f"{self.api_url}/api/v3/projects"
            params = {"pageSize": 1}
            
            response = self._session.get(
                url,
                params=params,
                auth=self.auth
            )
            
            # 如果状态码为200表示连接成功
            return response.status_code == 200
        except Exception as e:
            print(f"连接测试失败: {str(e)}")
            return False
            
    # 注意：这只是简化版API客户端，完整版包含更多功能
    # 更多方法请参考完整源代码

# 全局API客户端实例
api_client = OpenProjectClient()