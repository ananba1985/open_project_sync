#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from api_client import api_client, _HAS_PYQT

# 检查是否能够导入PyQt5，如果在服务器模式下运行时不需要GUI
if not _HAS_PYQT:
    print("注意：PyQt5库未安装，仅支持基础API功能。")
    print("如果您需要完整的GUI功能，请安装PyQt5及其依赖:")
    print("  - Ubuntu/Debian: sudo apt-get install python3-pyqt5 libgl1-mesa-glx")
    print("  - CentOS/RHEL: sudo yum install python3-qt5 mesa-libGL")
    print("  - 或使用pip: pip install PyQt5")

# 继续导入其他模块
import json
import time
from datetime import datetime  # 修改为直接导入datetime类，而不是整个模块
import uuid
import threading
import queue
import mimetypes
import random
import re
import csv
import io
import zipfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import traceback

# 创建全局进度消息队列，用于存储加载进度信息
progress_queues = {}
# 添加报表数据缓存，避免重复生成
report_data_cache = {"data": None, "timestamp": None}

class ReportHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            # 返回加载页面，显示进度条
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # 生成带有进度条的加载页面
            loading_page = self.generate_loading_page()
            self.wfile.write(loading_page.encode())
        elif self.path.startswith('/api/progress/'):
            # 提取进度ID
            progress_id = self.path.split('/')[-1]
            
            if progress_id in progress_queues:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                # 尝试从队列获取进度更新
                try:
                    progress_data = progress_queues[progress_id].get(block=False)
                    self.wfile.write(json.dumps(progress_data).encode())
                except queue.Empty:
                    # 没有新进度时，返回空结果
                    self.wfile.write(json.dumps({"status": "waiting"}).encode())
            else:
                self.send_error(404)
        elif self.path == '/api/report':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # 创建一个进度ID和队列
            progress_id = str(uuid.uuid4())
            progress_queues[progress_id] = queue.Queue()
            
            # 在响应中包含进度ID
            self.wfile.write(json.dumps({"progress_id": progress_id}).encode())
            
            # 在后台启动数据生成任务
            threading.Thread(target=self.background_report_generation, args=(progress_id,)).start()
        elif self.path == '/api/report_data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            report_data = self.get_report_data()
            self.wfile.write(json.dumps(report_data).encode())
        elif self.path == '/report_page':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # 优先使用缓存数据
            if report_data_cache["data"] is not None and report_data_cache["timestamp"] is not None:
                current_time = time.time()
                cache_age = current_time - report_data_cache["timestamp"]
                # 如果缓存存在且不超过5分钟，则使用缓存数据
                if cache_age < 300:  # 5分钟 = 300秒
                    print(f"使用缓存数据，缓存年龄: {cache_age:.1f}秒")
                    report_data = report_data_cache["data"]
                else:
                    print(f"缓存数据已过期({cache_age:.1f}秒)，重新获取数据")
                    report_data = self.get_report_data()
            else:
                print("无缓存数据，获取新数据")
                report_data = self.get_report_data()
            
            # 生成HTML内容 - 标准版本不显示任务ID
            html_content = self.generate_html(report_data, show_task_ids=False)
            self.wfile.write(html_content.encode())
        elif self.path == '/debug_report_page':
            # 调试版本的报表页面，显示任务ID
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # 优先使用缓存数据
            if report_data_cache["data"] is not None and report_data_cache["timestamp"] is not None:
                current_time = time.time()
                cache_age = current_time - report_data_cache["timestamp"]
                # 如果缓存存在且不超过5分钟，则使用缓存数据
                if cache_age < 300:  # 5分钟 = 300秒
                    print(f"调试模式：使用缓存数据，缓存年龄: {cache_age:.1f}秒")
                    report_data = report_data_cache["data"]
                else:
                    print(f"调试模式：缓存数据已过期({cache_age:.1f}秒)，重新获取数据")
                    report_data = self.get_report_data()
            else:
                print("调试模式：无缓存数据，获取新数据")
                report_data = self.get_report_data()
            
            # 生成HTML内容 - 调试版本显示任务ID
            html_content = self.generate_html(report_data, show_task_ids=True)
            self.wfile.write(html_content.encode())
        elif self.path == '/favicon.ico':
            # 处理浏览器自动请求favicon的情况
            self.send_response(204)  # No Content
            self.end_headers()
        else:
            self.send_error(404)

    def background_report_generation(self, progress_id):
        """在后台生成报表数据，并更新进度"""
        try:
            queue_obj = progress_queues[progress_id]
            
            # 发送初始进度
            queue_obj.put({"status": "progress", "message": "开始生成报表数据...", "percent": 5})
            
            # 获取项目列表
            projects = api_client.get_projects()
            if not projects:
                queue_obj.put({"status": "error", "message": "无法获取项目列表"})
                return
            
            # 获取第一个项目的数据
            project = projects[0]
            project_id = project.get("id")
            queue_obj.put({"status": "progress", "message": f"使用项目: {project.get('name')}", "percent": 20})
            
            # 获取城市列表
            queue_obj.put({"status": "progress", "message": "获取城市列表...", "percent": 30})
            cities = self.get_cities(project_id, progress_id)
            if not cities:
                queue_obj.put({"status": "error", "message": "无法获取城市列表"})
                return
            
            # 获取所有任务
            queue_obj.put({"status": "progress", "message": "获取工作包...", "percent": 40})
            # 传递 progress_id 和当前进度，以便在 get_all_work_packages 中更新详细进度
            all_work_packages = self.get_all_work_packages(project_id, progress_id, 40)
            
            if not all_work_packages:
                queue_obj.put({"status": "error", "message": "无法获取任务数据"})
                return
            
            queue_obj.put({"status": "progress", "message": f"处理 {len(all_work_packages)} 个工作包", "percent": 70})
            
            # 按城市分类任务和计算统计数据
            tasks_by_city = {}
            tasks_status = {}
            city_statistics = {}
            
            # 获取省厅的任务作为模板 - 增加错误处理和数据检查
            try:
                # 先确保所有城市对象都有name字段
                for city in cities:
                    if "name" not in city and "value" in city:
                        city["name"] = city["value"]
                
                # 查找省厅城市
                province_city = next((city for city in cities if city.get("name", "") == "省厅"), None)
                
                # 如果没找到省厅，尝试模糊匹配
                if not province_city:
                    province_city = next((city for city in cities if "省" in city.get("name", "")), None)
                    if province_city:
                        print(f"找到省相关城市作为省厅替代: {province_city.get('name', '')}")
                
                # 如果仍然没找到，使用第一个城市
                if not province_city and cities:
                    province_city = cities[0]
                    print(f"使用第一个城市作为省厅替代: {province_city.get('name', '')}")
                
                if not province_city:
                    error_msg = "找不到省厅城市且城市列表为空"
                    print(error_msg)
                    queue_obj.put({"status": "error", "message": error_msg})
                    return
                
                print(f"使用省厅城市: {province_city.get('name', '')}")
            except Exception as e:
                error_msg = f"获取省厅城市出错: {str(e)}"
                print(error_msg)
                queue_obj.put({"status": "error", "message": error_msg})
                return
            
            # 分析任务层级关系
            queue_obj.put({"status": "progress", "message": "分析任务关系...", "percent": 75})
            all_tasks_dict = {wp["id"]: wp for wp in all_work_packages}
            
            # 构建任务树
            tasks_tree = {}
            child_tasks = set()
            
            # 记录任务的最终状态信息（用于调试）
            missing_status_count = 0
            for wp in all_work_packages:
                wp_id = wp.get("id")
                # 验证每个工作包是否有状态信息
                has_status = "_links" in wp and "status" in wp["_links"] and wp["_links"]["status"] and "title" in wp["_links"]["status"]
                if not has_status:
                    missing_status_count += 1
                    print(f"警告: 工作包 {wp_id} 仍然缺少状态信息")
                
                # 处理父子关系
                if "_links" in wp and "parent" in wp["_links"] and wp["_links"]["parent"]:
                    parent_link = wp["_links"]["parent"]
                    # 检查parent_link是否包含href
                    if isinstance(parent_link, dict) and "href" in parent_link and parent_link["href"]:
                        try:
                            parent_href = parent_link["href"]
                            parent_id = int(parent_href.split("/")[-1])
                            
                            if parent_id not in tasks_tree:
                                tasks_tree[parent_id] = []
                            
                            tasks_tree[parent_id].append(wp["id"])
                            child_tasks.add(wp["id"])
                        except (ValueError, TypeError, IndexError) as e:
                            print(f"处理任务 {wp['id']} 的父任务链接时出错: {e}")
            
            if missing_status_count > 0:
                print(f"在所有工作包中有 {missing_status_count} 个仍然缺少状态信息")
            
            # 找出顶级任务
            top_level_tasks = [wp for wp in all_work_packages if wp["id"] not in child_tasks]
            
            # 获取每个城市的任务完成情况
            queue_obj.put({"status": "progress", "message": "处理城市任务数据...", "percent": 80})
            city_count = len(cities)
            for i, city in enumerate(cities):
                city_name = city["name"]
                city_tasks = []
                
                # 获取该城市的所有任务
                for wp in all_work_packages:
                    if self.is_task_belongs_to_city(wp, city):
                        city_tasks.append(wp)
                
                # 记录城市任务
                tasks_by_city[city_name] = city_tasks
                
                # 记录该城市的顶级任务
                city_top_tasks = [task for task in city_tasks if task["id"] not in child_tasks]
                
                # 计算任务状态统计
                status_count = {"未开始": 0, "进行中": 0, "已完成": 0, "挂起": 0, "拒绝": 0, "总计": len(city_tasks)}
                
                print(f"\n处理城市 {city_name} 的任务状态:")
                # 记录任务状态
                for task in city_tasks:
                    task_id = task["id"]
                    task_status = "未开始"
                    
                    if "_links" in task and "status" in task["_links"] and task["_links"]["status"]:
                        status_title = task["_links"]["status"].get("title", "")
                        
                        # 根据状态title判断任务状态
                        if status_title == "In progress":
                            task_status = "进行中"
                            status_count["进行中"] += 1
                        elif status_title == "Closed":
                            task_status = "已完成"
                            status_count["已完成"] += 1
                        elif status_title == "New":
                            task_status = "未开始"
                            status_count["未开始"] += 1
                        elif status_title == "On hold":
                            task_status = "挂起"
                            if "挂起" not in status_count:
                                status_count["挂起"] = 0
                            status_count["挂起"] += 1
                        elif status_title == "Rejected":
                            task_status = "拒绝"
                            if "拒绝" not in status_count:
                                status_count["拒绝"] = 0
                            status_count["拒绝"] += 1
                    else:
                        status_count["未开始"] += 1
                        print(f"  工作包 {task_id} 缺少状态信息，默认为'未开始'")
                    
                    if task_id not in tasks_status:
                        tasks_status[task_id] = {}
                    
                    tasks_status[task_id][city_name] = task_status
                    print(f"  设置工作包 {task_id} 在 {city_name} 的状态为: {task_status}")
                
                # 保存统计信息
                city_statistics[city_name] = status_count
                print(f"城市 {city_name} 状态统计: {status_count}")
            
            # 计算父任务的状态（基于子任务状态）
            queue_obj.put({"status": "progress", "message": "计算任务状态...", "percent": 90})
            for city in cities:
                city_name = city["name"]
                for task_id, children_ids in tasks_tree.items():
                    if children_ids:  # 只处理有子任务的任务
                        # 获取所有子任务状态
                        children_statuses = []
                        for child_id in children_ids:
                            if child_id in tasks_status and city_name in tasks_status[child_id]:
                                children_statuses.append(tasks_status[child_id][city_name])
                        
                        # 计算父任务状态
                        parent_status = "未开始"
                        if children_statuses:
                            if all(status == "已完成" for status in children_statuses):
                                parent_status = "已完成"
                            elif any(status == "进行中" for status in children_statuses) or any(status == "已完成" for status in children_statuses):
                                parent_status = "进行中"
                        
                        # 更新父任务状态
                        if task_id not in tasks_status:
                            tasks_status[task_id] = {}
                        tasks_status[task_id][city_name] = parent_status
                        #print(f"根据子任务状态，设置父工作包 {task_id} 在 {city_name} 的状态为: {parent_status}")
            
            # 获取省厅作为模板的任务树
            template_tasks = []
            if "省厅" in tasks_by_city:
                template_top_tasks = [task for task in tasks_by_city["省厅"] if task["id"] not in child_tasks]
                
                # 按顶级任务构建完整的任务树
                for top_task in template_top_tasks:
                    task_tree = self.build_task_tree(top_task, tasks_tree, all_tasks_dict)
                    template_tasks.append(task_tree)
            
            # 创建报表数据
            final_report_data = {
                "project": project,
                "cities": cities,
                "template_tasks": template_tasks,
                "tasks_by_city": tasks_by_city,
                "tasks_status": tasks_status,
                "all_tasks_count": len(all_work_packages),
                "city_statistics": city_statistics,
                "tasks_tree": tasks_tree
            }
            
            # 保存到缓存
            global report_data_cache
            report_data_cache["data"] = final_report_data
            report_data_cache["timestamp"] = time.time()
            print("报表数据已保存到缓存")
            
            # 最后发送完成消息
            queue_obj.put({"status": "done", "message": "数据加载完成", "percent": 100})
            
        except Exception as e:
            if progress_id in progress_queues:
                import traceback
                error_msg = f"生成报表数据时出错: {str(e)}"
                traceback.print_exc()
                progress_queues[progress_id].put({"status": "error", "message": error_msg})
        finally:
            # 等待一段时间后清理队列
            time.sleep(15)
            if progress_id in progress_queues:
                del progress_queues[progress_id]

    def generate_loading_page(self):
        """生成带有加载进度条的初始页面"""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>任务报表 - 加载中</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                /* 基础样式 */
                :root {
                    --primary-color: #409eff;
                    --success-color: #67c23a;
                    --progress-color: #19be6b;
                    --warning-color: #e6a23c;
                    --danger-color: #f56c6c;
                    --info-color: #909399;
                }
                
                * {
                    box-sizing: border-box;
                }
                
                body { 
                    font-family: 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif; 
                    margin: 0; 
                    padding: 0; 
                    background-color: #f5f7fa; 
                    color: #333;
                    line-height: 1.5;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                }
                
                .loading-container {
                    width: 90%;
                    max-width: 600px;
                    background-color: #fff;
                    border-radius: 8px;
                    box-shadow: 0 2px 12px rgba(0,0,0,0.1);
                    padding: 30px;
                    text-align: center;
                }
                
                .loading-title {
                    font-size: 24px;
                    font-weight: 600;
                    margin-bottom: 20px;
                    color: var(--primary-color);
                }
                
                .loading-progress {
                    margin: 30px 0;
                }
                
                .progress-bar {
                    height: 8px;
                    background-color: #e9ecef;
                    border-radius: 4px;
                    margin: 15px 0;
                    overflow: hidden;
                    position: relative;
                }
                
                .progress-bar-fill {
                    height: 100%;
                    background-color: var(--primary-color);
                    border-radius: 4px;
                    transition: width 0.3s ease;
                    width: 0%;
                    position: absolute;
                    top: 0;
                    left: 0;
                }
                
                .progress-percent {
                    font-size: 18px;
                    font-weight: 600;
                    color: var(--primary-color);
                    margin-bottom: 15px;
                }
                
                .loading-message {
                    font-size: 14px;
                    color: #606266;
                    margin: 10px 0;
                    min-height: 20px;
                }
                
                .loading-logs {
                    text-align: left;
                    height: 150px;
                    overflow-y: auto;
                    margin-top: 20px;
                    padding: 10px;
                    background-color: #f7f7f7;
                    border-radius: 4px;
                    font-family: monospace;
                    font-size: 12px;
                    color: #606266;
                    border: 1px solid #ebeef5;
                }
                
                .loading-log-item {
                    margin: 5px 0;
                    padding: 5px 0;
                    border-bottom: 1px dashed #ebeef5;
                }
                
                .loading-spinner {
                    display: inline-block;
                    width: 50px;
                    height: 50px;
                    border: 3px solid rgba(64, 158, 255, 0.2);
                    border-radius: 50%;
                    border-top-color: var(--primary-color);
                    animation: spin 1s ease-in-out infinite;
                    margin-bottom: 20px;
                }
                
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                
                .error-message {
                    color: var(--danger-color);
                    font-weight: 600;
                    margin: 15px 0;
                    padding: 10px;
                    background-color: rgba(245, 108, 108, 0.1);
                    border-radius: 4px;
                    display: none;
                }
                
                .success-message {
                    color: var(--success-color);
                    font-weight: 600;
                    margin: 15px 0;
                    padding: 10px;
                    background-color: rgba(103, 194, 58, 0.1);
                    border-radius: 4px;
                    display: none;
                }
            </style>
        </head>
        <body>
            <div class="loading-container">
                <div class="loading-spinner"></div>
                <div class="loading-title">正在加载任务报表数据</div>
                <div class="progress-percent">0%</div>
                <div class="progress-bar">
                    <div class="progress-bar-fill" style="width: 0%"></div>
                </div>
                <div class="loading-message">初始化...</div>
                <div class="error-message"></div>
                <div class="success-message">数据加载完成！正在跳转到报表页面...</div>
                <div class="loading-logs"></div>
            </div>
            
            <script>
                // 立即开始获取数据
                document.addEventListener('DOMContentLoaded', function() {
                    startLoading();
                });
                
                function startLoading() {
                    fetch('/api/report')
                        .then(response => response.json())
                        .then(data => {
                            if (data.progress_id) {
                                // 开始轮询进度
                                pollProgress(data.progress_id);
                            } else if (data.error) {
                                showError(data.error);
                            }
                        })
                        .catch(error => {
                            showError('获取数据时出错: ' + error);
                        });
                }
                
                function pollProgress(progressId) {
                    const progressBar = document.querySelector('.progress-bar-fill');
                    const progressPercent = document.querySelector('.progress-percent');
                    const loadingMessage = document.querySelector('.loading-message');
                    const loadingLogs = document.querySelector('.loading-logs');
                    const errorMessage = document.querySelector('.error-message');
                    const successMessage = document.querySelector('.success-message');
                    
                    let errorCount = 0;
                    const maxErrors = 5;
                    
                    // 开始轮询进度
                    const pollInterval = setInterval(() => {
                        fetch(`/api/progress/${progressId}`)
                            .then(response => {
                                if (!response.ok) {
                                    // 返回404表示队列已删除，数据加载完成，直接跳转
                                    if (response.status === 404 && progressBar.style.width === '100%') {
                                        clearInterval(pollInterval);
                                        window.location.href = '/report_page';
                                        return null;
                                    }
                                    throw new Error(`服务器返回状态码: ${response.status}`);
                                }
                                return response.json();
                            })
                            .then(data => {
                                if (data === null) return; // 处理上面的404跳转情况
                                
                                errorCount = 0; // 重置错误计数
                                
                                if (data.status === 'error') {
                                    clearInterval(pollInterval);
                                    showError(data.message);
                                } else if (data.status === 'done') {
                                    clearInterval(pollInterval);
                                    // 更新UI显示完成
                                    progressBar.style.width = '100%';
                                    progressPercent.textContent = '100%';
                                    loadingMessage.textContent = data.message || '数据加载完成';
                                    
                                    // 添加到日志
                                    addLogItem(data.message || '数据加载完成');
                                    
                                    // 显示成功消息
                                    successMessage.style.display = 'block';
                                    
                                    // 延迟后跳转到报表页面
                                    setTimeout(() => {
                                        window.location.href = '/report_page';
                                    }, 1000);
                                } else if (data.status === 'progress') {
                                    // 更新进度条
                                    const percent = data.percent || 0;
                                    progressBar.style.width = `${percent}%`;
                                    progressPercent.textContent = `${percent}%`;
                                    
                                    if (data.message) {
                                        loadingMessage.textContent = data.message;
                                        addLogItem(data.message);
                                    }
                                }
                            })
                            .catch(error => {
                                // 错误处理，增加错误计数
                                errorCount++;
                                console.error('轮询进度时出错:', error);
                                addLogItem(`轮询进度出错(${errorCount}/${maxErrors}): ${error.message}`);
                                
                                // 如果进度条已经100%，多次失败后尝试直接跳转
                                if (progressBar.style.width === '100%' && errorCount >= 2) {
                                    clearInterval(pollInterval);
                                    window.location.href = '/report_page';
                                    return;
                                }
                                
                                // 如果错误达到最大次数，停止轮询
                                if (errorCount >= maxErrors) {
                                    clearInterval(pollInterval);
                                    showError(`轮询进度多次失败(${maxErrors}次)，请刷新页面重试`);
                                }
                            });
                    }, 500);
                    
                    function addLogItem(message) {
                        const logItem = document.createElement('div');
                        logItem.className = 'loading-log-item';
                        logItem.textContent = message;
                        loadingLogs.appendChild(logItem);
                        loadingLogs.scrollTop = loadingLogs.scrollHeight;
                    }
                    
                    function showError(message) {
                        errorMessage.textContent = message;
                        errorMessage.style.display = 'block';
                        loadingMessage.textContent = '加载失败';
                        addLogItem('错误: ' + message);
                    }
                }
                
                function showError(message) {
                    const errorMessage = document.querySelector('.error-message');
                    const loadingMessage = document.querySelector('.loading-message');
                    const loadingLogs = document.querySelector('.loading-logs');
                    
                    errorMessage.textContent = message;
                    errorMessage.style.display = 'block';
                    loadingMessage.textContent = '加载失败';
                    
                    // 添加到日志
                    const logItem = document.createElement('div');
                    logItem.className = 'loading-log-item';
                    logItem.textContent = '错误: ' + message;
                    loadingLogs.appendChild(logItem);
                    loadingLogs.scrollTop = loadingLogs.scrollHeight;
                }
            </script>
        </body>
        </html>
        """

    def get_report_data(self):
        try:
            # 检查是否有缓存数据
            global report_data_cache
            if report_data_cache["data"] is not None and report_data_cache["timestamp"] is not None:
                current_time = time.time()
                cache_age = current_time - report_data_cache["timestamp"]
                # 如果缓存存在且不超过5分钟，则使用缓存数据
                if cache_age < 300:  # 5分钟 = 300秒
                    print(f"get_report_data: 使用缓存数据，缓存年龄: {cache_age:.1f}秒")
                    return report_data_cache["data"]
                else:
                    print(f"get_report_data: 缓存数据已过期({cache_age:.1f}秒)，重新获取数据")
            else:
                print("get_report_data: 无缓存数据，获取新数据")
            
            print("开始生成报表数据...")
            # 获取项目列表
            print("获取项目列表...")
            projects = api_client.get_projects()
            if not projects:
                return {"error": "无法获取项目列表"}
                
            # 获取第一个项目的数据作为示例
            project = projects[0]
            project_id = project.get("id")
            print(f"使用项目: {project.get('name')} (ID: {project_id})")
            
            # 获取城市列表
            print("获取城市列表...")
            cities = self.get_cities(project_id)
            if not cities:
                return {"error": "无法获取城市列表"}
            
            print(f"找到 {len(cities)} 个城市")
            
            # 获取所有任务
            print("开始获取所有工作包...")
            all_work_packages = self.get_all_work_packages(project_id)
            
            if not all_work_packages:
                return {"error": "无法获取任务数据"}
            
            print(f"成功获取 {len(all_work_packages)} 个工作包")
            
            # 按城市分类任务
            print("开始按城市分类任务...")
            tasks_by_city = {}
            tasks_status = {}
            city_statistics = {}
            
            # 获取省厅的任务作为模板
            province_city = next((city for city in cities if city["name"] == "省厅"), None)
            if not province_city:
                return {"error": "找不到省厅城市"}
            
            print("找到省厅城市")
            
            # 分析任务层级关系
            all_tasks_dict = {wp["id"]: wp for wp in all_work_packages}
            
            # 构建任务树
            tasks_tree = {}
            child_tasks = set()
            
            for wp in all_work_packages:
                if "_links" in wp and "parent" in wp["_links"] and wp["_links"]["parent"]:
                    parent_link = wp["_links"]["parent"]
                    # 检查parent_link是否包含href
                    if isinstance(parent_link, dict) and "href" in parent_link and parent_link["href"]:
                        try:
                            parent_href = parent_link["href"]
                            parent_id = int(parent_href.split("/")[-1])
                            
                            if parent_id not in tasks_tree:
                                tasks_tree[parent_id] = []
                            
                            tasks_tree[parent_id].append(wp["id"])
                            child_tasks.add(wp["id"])
                        except (ValueError, TypeError, IndexError) as e:
                            print(f"处理任务 {wp['id']} 的父任务链接时出错: {e}")
                            print(f"问题的父任务链接: {parent_link}")
            
            # 找出顶级任务
            top_level_tasks = [wp for wp in all_work_packages if wp["id"] not in child_tasks]
            print(f"找到 {len(top_level_tasks)} 个顶级任务")
            
            # 获取每个城市的任务完成情况
            for city in cities:
                city_name = city["name"]
                city_tasks = []
                
                # 获取该城市的所有任务
                for wp in all_work_packages:
                    if self.is_task_belongs_to_city(wp, city):
                        city_tasks.append(wp)
                
                # 记录城市任务
                tasks_by_city[city_name] = city_tasks
                
                # 记录该城市的顶级任务
                city_top_tasks = [task for task in city_tasks if task["id"] not in child_tasks]
                print(f"城市 {city_name} 有 {len(city_top_tasks)} 个顶级任务, 总共 {len(city_tasks)} 个任务")
                
                # 计算任务状态统计
                status_count = {"未开始": 0, "进行中": 0, "已完成": 0, "挂起": 0, "拒绝": 0, "总计": len(city_tasks)}
                
                # 记录任务状态
                for task in city_tasks:
                    task_id = task["id"]
                    task_status = "未开始"
                    
                    if "_links" in task and "status" in task["_links"] and task["_links"]["status"]:
                        status_title = task["_links"]["status"].get("title", "")
                        
                        # 根据状态title判断任务状态
                        if status_title == "In progress":
                            task_status = "进行中"
                            status_count["进行中"] += 1
                        elif status_title == "Closed":
                            task_status = "已完成"
                            status_count["已完成"] += 1
                        elif status_title == "New":
                            task_status = "未开始"
                            status_count["未开始"] += 1
                        elif status_title == "On hold":
                            task_status = "挂起"
                            if "挂起" not in status_count:
                                status_count["挂起"] = 0
                            status_count["挂起"] += 1
                        elif status_title == "Rejected":
                            task_status = "拒绝"
                            if "拒绝" not in status_count:
                                status_count["拒绝"] = 0
                            status_count["拒绝"] += 1
                    else:
                        status_count["未开始"] += 1
                    
                    if task_id not in tasks_status:
                        tasks_status[task_id] = {}
                    
                    tasks_status[task_id][city_name] = task_status
                
                # 保存统计信息
                city_statistics[city_name] = status_count
            
            # 计算父任务的状态（基于子任务状态）
            print("计算父任务状态...")
            for city in cities:
                city_name = city["name"]
                for task_id, children_ids in tasks_tree.items():
                    if children_ids:  # 只处理有子任务的任务
                        # 获取所有子任务状态
                        children_statuses = []
                        for child_id in children_ids:
                            if child_id in tasks_status and city_name in tasks_status[child_id]:
                                children_statuses.append(tasks_status[child_id][city_name])
                        
                        # 计算父任务状态
                        parent_status = "未开始"
                        if children_statuses:
                            if all(status == "已完成" for status in children_statuses):
                                parent_status = "已完成"
                            elif any(status == "进行中" for status in children_statuses) or any(status == "已完成" for status in children_statuses):
                                parent_status = "进行中"
                        
                        # 更新父任务状态
                        if task_id not in tasks_status:
                            tasks_status[task_id] = {}
                        tasks_status[task_id][city_name] = parent_status
            
            # 获取省厅作为模板的任务树
            template_tasks = []
            if "省厅" in tasks_by_city:
                template_top_tasks = [task for task in tasks_by_city["省厅"] if task["id"] not in child_tasks]
                
                # 按顶级任务构建完整的任务树
                for top_task in template_top_tasks:
                    task_tree = self.build_task_tree(top_task, tasks_tree, all_tasks_dict)
                    template_tasks.append(task_tree)
                
                print(f"省厅共有 {len(template_top_tasks)} 个顶级任务树")
            
            report_data = {
                "project": project,
                "cities": cities,
                "template_tasks": template_tasks,
                "tasks_by_city": tasks_by_city,  # 这里包含了每个城市的任务
                "tasks_status": tasks_status,
                "all_tasks_count": len(all_work_packages),
                "city_statistics": city_statistics,
                "tasks_tree": tasks_tree
            }
            
            # 保存到缓存
            report_data_cache["data"] = report_data
            report_data_cache["timestamp"] = time.time()
            
            print("报表数据生成完成")
            return report_data
            
        except Exception as e:
            print(f"生成报表数据时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"error": f"生成报表数据时出错: {str(e)}"}

    def build_task_tree(self, task, tasks_tree, all_tasks_dict):
        """构建任务树"""
        task_id = task["id"]
        task_tree = {
            "id": task_id,
            "subject": task.get("subject", "未命名任务"),
            "status": task.get("_links", {}).get("status", {}).get("title", ""),
            "children": []
        }
        
        # 添加描述字段
        if "description" in task:
            if isinstance(task["description"], dict) and "raw" in task["description"]:
                task_tree["description"] = task["description"]["raw"]
            else:
                task_tree["description"] = str(task["description"])
        
        # 添加子任务
        if task_id in tasks_tree:
            for child_id in tasks_tree[task_id]:
                if child_id in all_tasks_dict:
                    child_task = all_tasks_dict[child_id]
                    child_tree = self.build_task_tree(child_task, tasks_tree, all_tasks_dict)
                    task_tree["children"].append(child_tree)
        
        return task_tree

    def get_all_work_packages(self, project_id, progress_id=None, base_percent=0):
        """获取项目的所有工作包"""
        try:
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({"status": "progress", "message": "获取工作包数据...", "percent": base_percent + 1})
            
            print("尝试获取所有工作包...")
            all_work_packages = []
            
            # 首先使用较小的页面大小获取，以了解总数
            test_packages = api_client.get_work_packages(project_id, page=1, page_size=50)
            total_count = api_client.get_last_work_packages_total()
            
            # 设置合适的页面大小，确保能一次性获取所有工作包
            page_size = total_count + 50 if total_count > 0 else 500
            print(f"项目包含 {total_count} 个工作包，调整页面大小为 {page_size}")
            
            # 使用动态计算的页面大小，一次性获取所有工作包
            work_packages = api_client.get_work_packages(project_id, page=1, page_size=page_size)
            
            if work_packages:
                msg = f"获取到 {len(work_packages)} 个工作包"
                print(msg)
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({"status": "progress", "message": msg, "percent": base_percent + 10})
                
                # 检查主工作包列表中已有的ID
                work_package_ids = {wp.get("id") for wp in work_packages if "id" in wp}
                print(f"主列表中包含 {len(work_package_ids)} 个工作包ID")
                
                # 查找所有在子任务引用中的工作包ID
                referenced_ids = set()
                for wp in work_packages:
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
                
                # 找出被引用但不在主列表中的ID
                missing_referenced_ids = [id for id in referenced_ids if id not in work_package_ids]
                if missing_referenced_ids:
                    missing_count = len(missing_referenced_ids)
                    missing_ids_str = ", ".join([str(id) for id in missing_referenced_ids[:20]])
                    if missing_count > 20:
                        missing_ids_str += f"... (共{missing_count}个)"
                    
                    print(f"发现 {missing_count} 个被引用但不在主列表中的工作包: {missing_ids_str}")
                    
                    # 并行获取被引用的工作包详情
                    print(f"开始并行获取 {missing_count} 个被引用的工作包详情...")
                    referenced_details = self.get_work_packages_details_parallel(missing_referenced_ids)
                    
                    # 添加获取到的工作包
                    for wp_id, wp_data in referenced_details.items():
                        if wp_data:
                            print(f"成功获取被引用的工作包 {wp_id} 详情，添加到列表")
                            work_packages.append(wp_data)
                            # 添加到已知ID集合
                            work_package_ids.add(wp_id)
                        else:
                            print(f"无法获取被引用的工作包 {wp_id} 的详细信息")
                
                # 检查哪些工作包缺少状态信息或状态信息不完整
                packages_without_status = []
                print("\n开始检查工作包状态信息:")
                
                for wp in work_packages:
                    wp_id = wp.get("id", "未知ID")
                    
                    # 详细检查状态信息
                    has_links = "_links" in wp
                    has_status_link = has_links and "status" in wp["_links"]
                    
                    # 更严格的检查：不仅检查是否存在status字段，还检查status对象是否完整
                    status_link_valid = False
                    status_info = "未知"
                    
                    if has_status_link:
                        status_link = wp["_links"]["status"]
                        # 检查status是否为None或空对象，或者是否缺少title或href
                        if status_link and isinstance(status_link, dict):
                            has_title = "title" in status_link
                            has_href = "href" in status_link
                            status_link_valid = has_title and has_href
                            
                            if has_title:
                                status_info = status_link.get("title", "无标题")
                    
                    # 打印状态检查日志
                    status_check_result = "正常" if (has_links and has_status_link and status_link_valid) else "缺少状态"
                    print(f"工作包 {wp_id}: 状态={status_info}, 检查结果={status_check_result}")
                    
                    # 判断工作包是否缺少状态 - 更严格的条件
                    if not has_links or not has_status_link or not status_link_valid:
                        packages_without_status.append(wp_id)
                
                # 如果有缺少状态的工作包，并行获取详细信息
                if packages_without_status:
                    missing_count = len(packages_without_status)
                    missing_ids = ", ".join([str(id) for id in packages_without_status[:20]])
                    if len(packages_without_status) > 20:
                        missing_ids += f"... (共{missing_count}个)"
                    
                    log_msg = f"发现 {missing_count} 个工作包缺少状态信息: {missing_ids}，开始并行获取..."
                    print(log_msg)
                    if progress_id and progress_id in progress_queues:
                        progress_queues[progress_id].put({"status": "progress", 
                                                         "message": log_msg, 
                                                         "percent": base_percent + 12})
                    
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
                            
                            print(f"工作包 {wp_id} 详细信息获取成功，状态: {status_info}, 包含完整状态信息: {has_status}")
                            
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
                                print(f"工作包 {wp_id} 添加到列表中，因为找不到现有记录")
                            else:
                                print(f"工作包 {wp_id} 信息已更新")
                    
                    update_msg = f"完成 {missing_count} 个缺少状态信息的工作包更新，成功更新 {updated_count} 个"
                    print(update_msg)
                    if progress_id and progress_id in progress_queues:
                        progress_queues[progress_id].put({"status": "progress", 
                                                         "message": update_msg, 
                                                         "percent": base_percent + 15})
                else:
                    print("所有工作包都包含状态信息，无需单独获取")
                
                # 将任务添加到结果集
                all_work_packages = work_packages
            else:
                msg = "获取工作包失败，未返回数据"
                print(msg)
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({"status": "progress", "message": msg, "percent": base_percent + 5})
                raise Exception("无法从API获取工作包数据")
            
            # 验证获取的任务数量和状态分布
            if all_work_packages:
                status_counts = {}
                missing_status_count = 0
                still_missing_ids = []
                
                for task in all_work_packages:
                    task_id = task.get("id", "未知")
                    
                    # 检查状态信息是否完整
                    status_link = task.get("_links", {}).get("status", {})
                    has_complete_status = isinstance(status_link, dict) and "title" in status_link and "href" in status_link
                    
                    if has_complete_status:
                        status = status_link.get("title", "未知")
                        if status not in status_counts:
                            status_counts[status] = 0
                        status_counts[status] += 1
                    else:
                        missing_status_count += 1
                        still_missing_ids.append(task_id)
                        print(f"警告: 工作包 {task_id} 在最终结果中仍然缺少状态信息")
                
                print("\n最终任务状态统计:")
                for status, count in sorted(status_counts.items()):
                    print(f"  {status}: {count}个")
                
                if missing_status_count > 0:
                    missing_ids_str = ", ".join([str(id) for id in still_missing_ids[:20]])
                    if len(still_missing_ids) > 20:
                        missing_ids_str += f"... (共{missing_status_count}个)"
                    print(f"  仍然缺少状态: {missing_status_count}个 (ID: {missing_ids_str})")
                
                return all_work_packages
            else:
                msg = "警告：没有获取到任何工作包数据"
                print(msg)
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({"status": "progress", "message": msg, "percent": base_percent + 15})
                raise Exception("获取的工作包数据为空")
        
        except Exception as e:
            msg = f"获取所有工作包时出错: {str(e)}"
            print(msg)
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({"status": "progress", "message": msg, "percent": base_percent + 10})
                
            import traceback
            traceback.print_exc()
            raise Exception(f"获取工作包失败: {str(e)}")

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
                executor.submit(self.get_work_package_details, wp_id): wp_id 
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
            
            # 打印响应状态码
            print(f"工作包 {work_package_id} API响应状态码: {response.status_code}")
            
            # 详细日志
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
                response.raise_for_status()
            
            return None
        except Exception as e:
            print(f"获取工作包 {work_package_id} 详细信息时出错: {str(e)}")
            return None

    def is_task_belongs_to_city(self, task, city):
        """检查任务是否属于指定城市"""
        # 获取城市字段ID
        city_field_id = api_client.get_city_field_id()
        city_field_key = f"customField{city_field_id}"
        
        # 调试信息，帮助追踪问题
        task_id = task.get("id", "未知")
        
        # 检查是否有城市字段
        if "_links" not in task or city_field_key not in task["_links"]:
            return False
        
        # 获取任务的城市信息
        task_city = task["_links"][city_field_key]
        
        # 尝试多种方式获取城市ID和名称，以增强健壮性
        city_id = city.get("id", "")
        city_name = city.get("name", "")
        if not city_name and "value" in city:
            city_name = city.get("value", "")
        
        city_href = city.get("href", "")
        if not city_href and city_id:
            city_href = f"/api/v3/custom_options/{city_id}"
        
        # 打印调试信息
        print(f"匹配城市: 任务ID={task_id}, 城市检查: {city_name}(ID={city_id}, href={city_href})")
        print(f"任务城市数据: {task_city}")
        
        # 精确匹配城市的href (最准确的方法)
        if isinstance(task_city, dict) and "href" in task_city:
            is_match = task_city["href"] == city_href
            if is_match:
                print(f"通过href匹配: 任务={task_id}, 城市={city_name}")
            return is_match
        
        # 如果是城市列表，检查是否包含目标城市
        if isinstance(task_city, list):
            for city_entry in task_city:
                if isinstance(city_entry, dict):
                    # 匹配href
                    if "href" in city_entry and city_entry["href"] == city_href:
                        print(f"通过列表href匹配: 任务={task_id}, 城市={city_name}")
                        return True
                    
                    # 匹配名称
                    for field in ["title", "name", "value"]:
                        if field in city_entry and city_entry[field] == city_name:
                            print(f"通过列表{field}匹配: 任务={task_id}, 城市={city_name}")
                            return True
            
            # 如果以上匹配都失败，则返回False
            return False
        
        # 单个城市对象，通过各种字段尝试匹配
        if isinstance(task_city, dict):
            # 尝试通过不同字段匹配
            for field in ["title", "name", "value"]:
                if field in task_city and task_city[field] == city_name:
                    print(f"通过{field}匹配: 任务={task_id}, 城市={city_name}")
                    return True
            
            # 尝试匹配ID
            if "id" in task_city and task_city["id"] == city_id:
                print(f"通过ID匹配: 任务={task_id}, 城市={city_name}")
                return True
        
        # 如果所有匹配方式都失败，则返回False
        return False

    def get_cities(self, project_id, progress_id=None, base_percent=0):
        """获取项目的城市列表"""
        if progress_id and progress_id in progress_queues:
            progress_queues[progress_id].put({"status": "progress", "message": "获取城市列表...", "percent": base_percent + 2})
        
        max_retries = 2
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # 直接使用api_client的get_cities方法
                if retry_count > 0:
                    # 在第一次失败后尝试刷新API连接
                    print(f"尝试重置API连接（尝试 {retry_count+1}/{max_retries}）")
                    if progress_id and progress_id in progress_queues:
                        progress_queues[progress_id].put({"status": "progress", "message": "重置API连接...", "percent": base_percent + 2})
                    api_client.update_credentials(api_client.api_url, api_client.api_token)
                
                cities = api_client.get_cities()
                
                if not cities:
                    error_msg = f"城市列表为空 (尝试 {retry_count+1}/{max_retries})"
                    print(error_msg)
                    
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        if progress_id and progress_id in progress_queues:
                            progress_queues[progress_id].put({"status": "progress", "message": f"城市列表为空，正在重试 ({retry_count}/{max_retries})...", "percent": base_percent + 3})
                        time.sleep(2)  # 等待两秒后重试
                        continue
                    else:
                        raise Exception(error_msg)
                
                # 验证城市对象数据完整性
                valid_cities = []
                for city in cities:
                    # 确保城市对象有name属性
                    if "name" not in city:
                        if "value" in city:
                            city["name"] = city["value"]
                        elif "title" in city:
                            city["name"] = city["title"]
                        else:
                            print(f"警告: 城市对象缺少name字段: {city}")
                            continue
                    valid_cities.append(city)
                
                if not valid_cities:
                    error_msg = f"没有有效的城市数据 (尝试 {retry_count+1}/{max_retries})"
                    print(error_msg)
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        if progress_id and progress_id in progress_queues:
                            progress_queues[progress_id].put({"status": "progress", "message": f"没有有效的城市数据，正在重试 ({retry_count}/{max_retries})...", "percent": base_percent + 3})
                        time.sleep(2)
                        continue
                    else:
                        raise Exception(error_msg)
                
                if progress_id and progress_id in progress_queues and valid_cities:
                    progress_queues[progress_id].put({"status": "progress", "message": f"已获取{len(valid_cities)}个城市", "percent": base_percent + 5})
                
                # 成功获取城市列表
                print(f"成功获取 {len(valid_cities)} 个城市")
                
                # 打印城市列表供调试
                print("城市列表：")
                for city in valid_cities:
                    print(f"  - {city.get('name', 'Unknown')} (ID: {city.get('id', 'Unknown')})")
                
                return valid_cities
                
            except Exception as e:
                error_msg = f"获取城市列表失败 (尝试 {retry_count+1}/{max_retries}): {str(e)}"
                print(error_msg)
                
                if retry_count < max_retries - 1:
                    retry_count += 1
                    if progress_id and progress_id in progress_queues:
                        progress_queues[progress_id].put({"status": "progress", "message": f"获取城市列表失败，正在重试 ({retry_count}/{max_retries})...", "percent": base_percent + 3})
                    time.sleep(2)  # 等待两秒后重试
                else:
                    # 最后一次尝试后仍然失败
                    final_error_msg = f"获取城市列表失败: {str(e)}\n请确认：\n1. API服务器是否正常运行\n2. API凭证是否有效\n3. 是否有城市自定义字段并已配置城市数据"
                    print(final_error_msg)
                    raise Exception(final_error_msg)
        
        # 不应该执行到这里，但为安全起见
        raise Exception("获取城市列表失败：所有重试均已失败")

    def generate_html(self, report_data, show_task_ids=False):
        if "error" in report_data:
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>任务报表</title>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{ 
                        font-family: 'PingFang SC', 'Helvetica Neue', Arial, sans-serif; 
                        margin: 0; 
                        padding: 0; 
                        background-color: #f5f7fa; 
                        color: #333;
                    }}
                    .error-container {{ 
                        max-width: 800px; 
                        margin: 100px auto; 
                        padding: 30px; 
                        background-color: #fff; 
                        border-radius: 8px; 
                        box-shadow: 0 4px 12px rgba(0,0,0,0.1); 
                        text-align: center;
                    }}
                    .error-icon {{
                        font-size: 60px;
                        color: #f56c6c;
                        margin-bottom: 20px;
                    }}
                    .error-title {{
                        font-size: 24px;
                        color: #f56c6c;
                        margin-bottom: 15px;
                    }}
                    .error {{ 
                        color: #f56c6c; 
                        font-size: 16px;
                        line-height: 1.6;
                    }}
                    .btn {{
                        display: inline-block;
                        padding: 10px 20px;
                        background-color: #409eff;
                        color: white;
                        border-radius: 4px;
                        text-decoration: none;
                        margin-top: 20px;
                        transition: background-color 0.3s;
                    }}
                    .btn:hover {{
                        background-color: #337ecc;
                    }}
                </style>
            </head>
            <body>
                <div class="error-container">
                    <div class="error-icon">⚠️</div>
                    <h1 class="error-title">获取数据时出错</h1>
                    <div class="error">{report_data["error"]}</div>
                    <a href="/" class="btn">刷新页面</a>
                </div>
            </body>
            </html>
            """

        # 生成报表HTML
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>任务报表 - {report_data['project']['name']}</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                /* 基础样式 */
                :root {{
                    --primary-color: #409eff;
                    --success-color: #67c23a;
                    --progress-color: #19be6b;
                    --warning-color: #e6a23c;
                    --danger-color: #f56c6c;
                    --info-color: #909399;
                }}
                
                * {{
                    box-sizing: border-box;
                }}
                
                body {{ 
                    font-family: 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif; 
                    margin: 0; 
                    padding: 0; 
                    background-color: #f5f7fa; 
                    color: #333;
                    line-height: 1.5;
                }}
                
                .container {{ 
                    max-width: 1440px; 
                    margin: 0 auto; 
                    padding: 20px; 
                    position: relative;
                }}
                
                /* 顶部信息栏 */
                .header {{ 
                    background-color: #fff; 
                    padding: 25px 30px; 
                    border-radius: 8px; 
                    box-shadow: 0 2px 12px rgba(0,0,0,0.1); 
                    margin-bottom: 25px; 
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: space-between;
                    align-items: center;
                }}
                
                .header-info {{
                    flex: 1;
                }}
                
                .header-actions {{
                    display: flex;
                    align-items: center;
                }}
                
                .header h1 {{ 
                    margin: 0 0 10px 0; 
                    color: #333; 
                    font-size: 28px;
                    font-weight: 600;
                }}
                
                .header p {{ 
                    margin: 5px 0; 
                    color: #606266; 
                    font-size: 14px;
                }}
                
                .header .highlight {{
                    color: var(--primary-color);
                    font-weight: bold;
                }}
                
                /* 表格样式 */
                .report-card {{
                    background-color: #fff;
                    border-radius: 8px;
                    box-shadow: 0 2px 12px rgba(0,0,0,0.1);
                    margin-bottom: 25px;
                    overflow: hidden;
                }}
                
                .card-header {{
                    padding: 16px 20px;
                    border-bottom: 1px solid #ebeef5;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }}
                
                .card-header h2 {{
                    margin: 0;
                    font-size: 18px;
                    font-weight: 600;
                    color: #303133;
                }}
                
                .card-body {{
                    padding: 20px;
                }}
                
                .table-container {{
                    width: 100%;
                }}
                
                .report-table {{ 
                    width: 100%; 
                    border-collapse: collapse; 
                    border-spacing: 0;
                    table-layout: auto;
                }}
                
                .report-table th, .report-table td {{ 
                    padding: 12px 8px; 
                    text-align: center; 
                    border: 1px solid #ebeef5; 
                    font-size: 14px;
                    word-break: break-word;
                    vertical-align: middle;
                    white-space: normal;
                    overflow: visible;
                }}
                
                .report-table th {{ 
                    background-color: #f5f7fa; 
                    font-weight: 600; 
                    color: #606266; 
                    white-space: normal;
                    word-wrap: break-word;
                }}
                
                .loading.active {{ 
                    display: inline-block; 
                }}
                
                .spinner {{
                    width: 20px;
                    height: 20px;
                    border: 2px solid rgba(255,255,255,0.3);
                    border-radius: 50%;
                    border-top-color: white;
                    animation: spin 1s linear infinite;
                    display: inline-block;
                    vertical-align: middle;
                }}
                
                @keyframes spin {{
                    to {{ transform: rotate(360deg); }}
                }}
                
                /* 统计信息卡片 */
                .stats {{ 
                    background-color: #fff; 
                    border-radius: 8px; 
                    box-shadow: 0 2px 12px rgba(0,0,0,0.1); 
                }}
                
                .stats h2 {{ 
                    margin: 0; 
                    padding: 16px 20px;
                    font-size: 18px;
                    font-weight: 600;
                    color: #303133;
                    border-bottom: 1px solid #ebeef5;
                }}
                
                .stats-content {{
                    padding: 20px;
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                    gap: 20px;
                }}
                
                .stats-city {{ 
                    padding: 15px;
                    border-radius: 6px;
                    background-color: #f5f7fa;
                    transition: all 0.3s;
                }}
                
                .stats-city:hover {{
                    box-shadow: 0 2px 12px rgba(0,0,0,0.1);
                    transform: translateY(-2px);
                }}
                
                .stats-city-name {{
                    font-weight: 600;
                    font-size: 16px;
                    color: #303133;
                    margin-bottom: 10px;
                    padding-bottom: 8px;
                    border-bottom: 1px solid #ebeef5;
                }}
                
                .stats-details {{
                    display: flex;
                    flex-wrap: wrap;
                    margin-top: 10px;
                }}
                
                .stats-detail-item {{
                    margin-right: 15px;
                    margin-bottom: 10px;
                }}
                
                .stats-progress {{
                    height: 6px;
                    background-color: #e9ecef;
                    border-radius: 3px;
                    margin-top: 8px;
                    overflow: hidden;
                }}
                
                .stats-progress-bar {{
                    height: 100%;
                    border-radius: 3px;
                }}
                
                .stats-label {{ 
                    font-weight: 600; 
                    color: #606266;
                }}
                
                .stats-value {{
                    font-weight: 600;
                }}
                
                .stats-completion {{
                    text-align: right;
                    font-weight: 600;
                    margin-top: 5px;
                    color: var(--primary-color);
                }}
                
                /* 响应式设计 */
                @media (max-width: 768px) {{
                    .header {{
                        flex-direction: column;
                        align-items: flex-start;
                    }}
                    
                    .header-actions {{
                        margin-top: 15px;
                        width: 100%;
                    }}
                    
                    .refresh-btn {{
                        width: 100%;
                        margin-left: 0;
                    }}
                    
                    .stats-content {{
                        grid-template-columns: 1fr;
                    }}
                }}
                
                /* 现代滚动条样式 */
                ::-webkit-scrollbar {{
                    width: 8px;
                    height: 8px;
                }}
                
                ::-webkit-scrollbar-track {{
                    background: #f1f1f1;
                    border-radius: 4px;
                }}
                
                ::-webkit-scrollbar-thumb {{
                    background: #c1c1c1;
                    border-radius: 4px;
                }}
                
                ::-webkit-scrollbar-thumb:hover {{
                    background: #a8a8a8;
                }}
                
                .parent-task {{ 
                    background-color: #ecf5ff; 
                    font-weight: 600; 
                    color: #303133;
                    white-space: normal;
                    word-wrap: break-word;
                }}
                
                .child-task {{ 
                    color: #606266;
                    white-space: normal;
                    word-wrap: break-word;
                    overflow-wrap: break-word;
                }}
                
                .status-cell {{
                    padding: 4px 8px;
                    border-radius: 4px;
                    display: inline-block;
                    width: 100%;
                    max-width: none;
                    text-align: center;
                    white-space: normal;
                    word-wrap: break-word;
                    overflow-wrap: break-word;
                }}
                
                /* 状态样式 */
                .status-not-started {{ 
                    color: #909399; 
                    font-weight: 600;
                    background-color: rgba(144, 147, 153, 0.2);
                }}
                
                .status-in-progress {{ 
                    color: #19be6b; 
                    font-weight: 600;
                    background-color: rgba(25, 190, 107, 0.2);
                }}
                
                .status-completed {{ 
                    color: #67c23a; 
                    font-weight: 600;
                    background-color: rgba(103, 194, 58, 0.2);
                }}
                
                .status-on-hold {{ 
                    color: #e6a23c; 
                    font-weight: 600;
                    background-color: rgba(230, 162, 60, 0.2);
                }}
                
                .status-rejected {{ 
                    color: #f56c6c; 
                    font-weight: 600;
                    background-color: rgba(245, 108, 108, 0.2);
                }}
                
                .report-table tr:hover {{ 
                    background-color: #f5f7fa; 
                }}
                
                .report-table tr:nth-child(even) {{
                    background-color: #fafafa;
                }}
                
                .report-table tr td:first-child {{
                    font-weight: 600;
                    background-color: #f5f7fa;
                    position: sticky;
                    left: 0;
                    z-index: 1;
                }}
                
                /* 自定义悬浮提示样式 - 使用JavaScript实现 */
                .report-table td {{
                    position: relative;
                }}
                
                .tooltip {{
                    position: absolute;
                    bottom: 100%;
                    left: 50%;
                    transform: translateX(-50%);
                    background-color: rgba(0,0,0,0.8);
                    color: white;
                    padding: 8px 12px;
                    border-radius: 4px;
                    font-size: 14px;
                    font-weight: normal;
                    white-space: pre-wrap;
                    max-width: 300px;
                    min-width: 200px;
                    z-index: 2000;
                    text-align: left;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                    line-height: 1.4;
                    pointer-events: none;
                    display: none;
                }}
                
                .tooltip:after {{
                    content: '';
                    position: absolute;
                    top: 100%;
                    left: 50%;
                    transform: translateX(-50%);
                    border-width: 5px;
                    border-style: solid;
                    border-color: rgba(0,0,0,0.8) transparent transparent transparent;
                }}
            </style>
            <link rel="icon" href="data:,">
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="header-info">
                        <h1>任务完成报表</h1>
                        <p>项目：<span class="highlight">""" + report_data['project']['name'] + """</span></p>
                        <p>生成时间：""" + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
                        <p>工作包总数：<span class="highlight">""" + str(report_data['all_tasks_count']) + """</span> 个</p>
                    </div>
                    <div class="header-actions">
                        <button class="btn btn-primary refresh-btn" onclick="refreshData()">
                            刷新数据
                            <span class="loading"><span class="spinner"></span></span>
                        </button>
                    </div>
                </div>
                
                <div class="report-card">
                    <div class="card-header">
                        <h2>任务完成情况</h2>
                    </div>
                    <div class="card-body">
        """

        # 只有在有模板任务时才生成表格
        if report_data.get('template_tasks'):
            html += self.generate_task_table(report_data, show_task_ids)
        else:
            html += """
                        <div class="empty-data">
                            <p style="text-align:center;color:#909399;padding:30px;">没有找到省厅的任务数据，无法生成报表</p>
                        </div>
            """
        
        html += """
                    </div>
                </div>
        """

        # 添加城市统计信息
        html += """
                <div class="stats">
                    <h2>城市任务统计</h2>
                    <div class="stats-content">
        """
        
        for city in report_data['cities']:
            city_name = city['name']
            stats = report_data.get('city_statistics', {}).get(city_name, {})
            total = stats.get('总计', 0)
            not_started = stats.get('未开始', 0)
            in_progress = stats.get('进行中', 0)
            completed = stats.get('已完成', 0)
            on_hold = stats.get('挂起', 0)
            rejected = stats.get('拒绝', 0)
            
            # 计算完成率
            completion_rate = 0
            if total > 0:
                completion_rate = round((completed / total) * 100, 1)
            
            html += f"""
                        <div class="stats-city">
                            <div class="stats-city-name">{city_name}</div>
                            <div><span class="stats-label">总计：</span><span class="stats-value">{total}</span> 个任务</div>
                            <div class="stats-details">
                                <div class="stats-detail-item">
                                    <span class="status-not-started">{not_started}</span> 未开始
                                </div>
                                <div class="stats-detail-item">
                                    <span class="status-in-progress">{in_progress}</span> 进行中
                                </div>
                                <div class="stats-detail-item">
                                    <span class="status-completed">{completed}</span> 已完成
                                </div>
                                <div class="stats-detail-item">
                                    <span class="status-on-hold">{on_hold}</span> 挂起
                                </div>
                                <div class="stats-detail-item">
                                    <span class="status-rejected">{rejected}</span> 拒绝
                                </div>
                            </div>
                            <div class="stats-progress">
                                <div class="stats-progress-bar" style="width: {completion_rate}%; background-color: {self.get_progress_color(completion_rate)}"></div>
                            </div>
                            <div class="stats-completion">完成率 {completion_rate}%</div>
                        </div>
            """
        
        html += """
                    </div>
                </div>
            </div>
            <div class="footer">
                <p>报表ID: """ + report_data.get('report_id', '') + """</p>
                <p>生成时间：""" + report_data.get('generated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + """</p>
                <p>© 2023-2024 OpenProject数据同步工具</p>
            </div>
            <div id="custom-tooltip" style="position:absolute; background-color:rgba(0,0,0,0.8); color:white; padding:8px 12px; border-radius:4px; font-size:14px; max-width:300px; min-width:200px; display:none; z-index:2000; pointer-events:none;"></div>
            <script>
                function refreshData() {
                    const loading = document.querySelector('.loading');
                    const refreshBtn = document.querySelector('.refresh-btn');
                    
                    loading.classList.add('active');
                    refreshBtn.disabled = true;
                    
                    // 直接跳转到加载页面重新加载数据
                    window.location.href = '/';
                }
                
                // 添加表格固定表头和首列的功能
                document.addEventListener('DOMContentLoaded', function() {
                    const tableContainer = document.querySelector('.table-container');
                    if (tableContainer) {
                        tableContainer.addEventListener('scroll', function() {
                            const headerCells = document.querySelectorAll('.report-table th');
                            const firstCells = document.querySelectorAll('.report-table td:first-child');
                            
                            headerCells.forEach(cell => {
                                cell.style.transform = `translateY(${this.scrollTop}px)`;
                            });
                            
                            firstCells.forEach(cell => {
                                cell.style.transform = `translateX(${this.scrollLeft}px)`;
                            });
                        });
                    }
                    
                    // 单一悬浮提示实现
                    const tooltip = document.getElementById('custom-tooltip');
                    const cells = document.querySelectorAll('.report-table td[title]');
                    
                    cells.forEach(cell => {
                        // 保存原始title内容并移除
                        const tooltipText = cell.getAttribute('title');
                        cell.removeAttribute('title');
                        cell.dataset.tooltip = tooltipText;
                        
                        // 鼠标进入显示提示
                        cell.addEventListener('mouseenter', function() {
                            // 首先确保所有其他提示都被隐藏
                            tooltip.style.display = 'none';
                            
                            // 设置提示内容
                            tooltip.textContent = this.dataset.tooltip;
                            
                            // 计算位置
                            const rect = this.getBoundingClientRect();
                            tooltip.style.left = rect.left + rect.width/2 - tooltip.offsetWidth/2 + 'px';
                            tooltip.style.top = rect.top - tooltip.offsetHeight - 10 + 'px';
                            
                            // 显示提示
                            tooltip.style.display = 'block';
                        });
                        
                        // 鼠标离开隐藏提示
                        cell.addEventListener('mouseleave', function() {
                            tooltip.style.display = 'none';
                        });
                    });
                });
            </script>
        </body>
        </html>
        """
        
        return html

    def generate_task_table(self, report_data, show_task_ids=False):
        """生成任务表格，列是任务，行是地市，表头分为两行"""
        template_tasks = report_data['template_tasks']
        cities = report_data['cities']
        tasks_by_city = report_data.get('tasks_by_city', {})
        
        html = """
                <div class="table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th rowspan="2" style="min-width: 80px;">城市</th>
        """
        
        # 生成表头第一行 - 父任务
        for task_tree in template_tasks:
            children_count = len(task_tree.get('children', []))
            task_id_text = f" (ID:{task_tree['id']})" if show_task_ids else ""
            
            if children_count > 0:
                # 如果有子任务，父任务占据多列（只包含子任务的列数）
                html += f'<th colspan="{children_count}" class="parent-task" title="{task_tree["subject"]}">{task_tree["subject"]}{task_id_text}</th>'
            else:
                # 如果没有子任务，父任务只占一列
                html += f'<th rowspan="2" class="parent-task" title="{task_tree["subject"]}">{task_tree["subject"]}{task_id_text}</th>'
        
        html += """
                            </tr>
                            <tr>
        """
        
        # 生成表头第二行 - 只显示子任务
        for task_tree in template_tasks:
            children = task_tree.get('children', [])
            if children:
                # 只添加子任务列，不再显示父任务自身
                for child in children:
                    task_id_text = f" (ID:{child['id']})" if show_task_ids else ""
                    html += f'<th class="child-task" title="{child["subject"]}">{child["subject"]}{task_id_text}</th>'
        
        html += """
                            </tr>
                        </thead>
                        <tbody>
        """
        
        # 为每个城市生成一行
        for city in cities:
            city_name = city['name']
            city_tasks = tasks_by_city.get(city_name, [])
            html += f"""
                            <tr>
                                <td>{city_name}</td>
            """
            
            # 添加每个任务的状态
            for task_tree in template_tasks:
                template_subject = task_tree.get('subject', '')
                children = task_tree.get('children', [])
                
                if not children:
                    # 如果没有子任务，查找对应城市的该任务
                    template_id = task_tree['id']
                    
                    # 尝试在该城市找到相同名字的任务
                    city_task = next((t for t in city_tasks if t.get('subject') == template_subject), None)
                    
                    if city_task:
                        # 找到了对应城市的同名任务，使用该任务的实际状态
                        city_task_id = city_task.get('id', 'unknown')
                        
                        # 直接从任务中获取状态，而不是从状态缓存中获取
                        status_title = "未开始"
                        if "_links" in city_task and "status" in city_task["_links"] and city_task["_links"]["status"]:
                            status_link = city_task["_links"]["status"]
                            if isinstance(status_link, dict) and "title" in status_link:
                                status_title = status_link["title"]
                        
                        # 转换状态为中文标签
                        status_label = self.get_status_label(status_title)
                        status_class = self.get_status_class(status_label)
                        
                        # 获取任务描述
                        task_description = ""
                        if "description" in city_task:
                            if isinstance(city_task["description"], dict) and "raw" in city_task["description"]:
                                task_description = city_task["description"]["raw"]
                            else:
                                task_description = str(city_task["description"])
                            # 处理描述文本，清理HTML标签等
                            task_description = task_description.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                        
                        # 构建悬浮提示内容
                        tooltip_content = f"ID:{city_task_id} - {status_label}"
                        if task_description:
                            tooltip_content = f"{tooltip_content}\n\n{task_description}"
                        
                        # 根据参数决定是否显示任务ID
                        if show_task_ids:
                            html += f'<td class="{status_class}" title="{tooltip_content}"><div class="status-cell">ID:{city_task_id} - {status_label}</div></td>'
                        else:
                            html += f'<td class="{status_class}" title="{tooltip_content}"><div class="status-cell">{status_label}</div></td>'
                    else:
                        # 未找到对应城市的任务，使用省厅状态计算的状态
                        parent_status = self.get_task_status_for_city(template_id, city_name, report_data)
                        status_class = self.get_status_class(parent_status)
                        status_label = self.get_status_label(parent_status)
                        
                        if show_task_ids:
                            html += f'<td class="{status_class}" title="无ID - {status_label}"><div class="status-cell">无ID - {status_label}</div></td>'
                        else:
                            html += f'<td class="{status_class}" title="{status_label}"><div class="status-cell">{status_label}</div></td>'
                else:
                    # 如果有子任务，显示子任务状态
                    for child in children:
                        child_subject = child.get('subject', '')
                        template_id = child['id']
                        
                        # 尝试在该城市找到相同名字的子任务
                        city_child_task = next((t for t in city_tasks if t.get('subject') == child_subject), None)
                        
                        if city_child_task:
                            # 找到了对应城市的同名任务，使用该任务的ID和实际状态
                            city_child_id = city_child_task.get('id', 'unknown')
                            
                            # 直接从任务中获取状态，而不是从状态缓存中获取
                            status_title = "未开始"
                            if "_links" in city_child_task and "status" in city_child_task["_links"] and city_child_task["_links"]["status"]:
                                status_link = city_child_task["_links"]["status"]
                                if isinstance(status_link, dict) and "title" in status_link:
                                    status_title = status_link["title"]
                            
                            # 转换状态为中文标签
                            status_label = self.get_status_label(status_title)
                            status_class = self.get_status_class(status_label)
                            
                            # 获取任务描述
                            task_description = ""
                            if "description" in city_child_task:
                                if isinstance(city_child_task["description"], dict) and "raw" in city_child_task["description"]:
                                    task_description = city_child_task["description"]["raw"]
                                else:
                                    task_description = str(city_child_task["description"])
                                # 处理描述文本，清理HTML标签等
                                task_description = task_description.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                            
                            # 构建悬浮提示内容
                            tooltip_content = f"ID:{city_child_id} - {status_label}"
                            if task_description:
                                tooltip_content = f"{tooltip_content}\n\n{task_description}"
                            
                            if show_task_ids:
                                html += f'<td class="{status_class}" title="{tooltip_content}"><div class="status-cell">ID:{city_child_id} - {status_label}</div></td>'
                            else:
                                html += f'<td class="{status_class}" title="{tooltip_content}"><div class="status-cell">{status_label}</div></td>'
                        else:
                            # 未找到对应城市的任务，使用省厅状态计算的状态
                            child_status = self.get_task_status_for_city(template_id, city_name, report_data)
                            status_class = self.get_status_class(child_status)
                            status_label = self.get_status_label(child_status)
                            
                            if show_task_ids:
                                html += f'<td class="{status_class}" title="无ID - {status_label}"><div class="status-cell">无ID - {status_label}</div></td>'
                            else:
                                html += f'<td class="{status_class}" title="{status_label}"><div class="status-cell">{status_label}</div></td>'
            
            html += """
                            </tr>
            """
        
        html += """
                        </tbody>
                    </table>
                </div>
        """
        
        return html

    def get_status_class(self, status):
        """获取状态对应的CSS类"""
        if status == "已完成" or status == "Closed":
            return "status-completed"
        elif status == "进行中" or status == "In progress":
            return "status-in-progress"
        elif status == "挂起" or status == "On hold":
            return "status-on-hold"
        elif status == "拒绝" or status == "Rejected":
            return "status-rejected"
        else:
            return "status-not-started"

    def get_status_label(self, status):
        """获取状态对应的中文显示标签"""
        if status == "Closed":
            return "已完成"
        elif status == "In progress":
            return "进行中"
        elif status == "On hold":
            return "挂起"
        elif status == "Rejected":
            return "拒绝"
        elif status == "New":
            return "未开始"
        else:
            return status

    def get_task_status_for_city(self, task_id, city_name, report_data):
        """获取指定城市的任务状态"""
        tasks_status = report_data.get('tasks_status', {})
        
        if task_id in tasks_status and city_name in tasks_status[task_id]:
            return tasks_status[task_id][city_name]
        
        return "未开始"

    def process_city_tasks(self, project_id, city, tasks, total_cities, current_city_index, progress_id=None, base_percent=40):
        """处理特定城市的任务数据"""
        if progress_id and progress_id in progress_queues:
            # 计算当前城市的进度百分比范围 (40-80% 平均分配给各城市)
            city_percent_range = 40  # 总共占 40% (从 40% 到 80%)
            per_city_percent = city_percent_range / total_cities
            city_start_percent = base_percent + (current_city_index * per_city_percent)
            
            progress_queues[progress_id].put({
                "status": "progress", 
                "message": f"处理城市数据：{city['name']} ({current_city_index + 1}/{total_cities})", 
                "percent": city_start_percent
            })
        
        city_result = {"city": city, "tasks": [], "status_counts": {}}
        status_counts = {}
        
        try:
            if not tasks:
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({
                        "status": "progress", 
                        "message": f"{city['name']}：无任务数据", 
                        "percent": city_start_percent + (per_city_percent * 0.3)
                    })
                return city_result
            
            # 筛选当前城市的任务
            city_key = city.get('id', '').lower()
            city_name = city.get('name', '')
            
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": f"筛选{city_name}的任务...", 
                    "percent": city_start_percent + (per_city_percent * 0.4)
                })
            
            # 任务筛选逻辑
            city_tasks = []
            for task in tasks:
                # 检查任务的城市字段或名称中包含城市名
                task_city = task.get('city', '').lower()
                task_title = task.get('subject', '').lower()
                
                if (city_key and task_city and city_key in task_city) or \
                   (city_name and task_title and city_name in task_title.lower()):
                    city_tasks.append(task)
            
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": f"{city_name}：找到 {len(city_tasks)} 个相关任务", 
                    "percent": city_start_percent + (per_city_percent * 0.6)
                })
            
            # 统计各状态的任务数量
            for task in city_tasks:
                status = task.get('status', {}).get('name', 'Unknown')
                if status in status_counts:
                    status_counts[status] += 1
                else:
                    status_counts[status] = 1
            
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": f"{city_name}：任务状态统计完成", 
                    "percent": city_start_percent + (per_city_percent * 0.8)
                })
            
            # 整理城市结果
            city_result = {
                "city": city,
                "tasks": city_tasks,
                "status_counts": status_counts
            }
            
            if progress_id and progress_id in progress_queues:
                status_summary = ", ".join([f"{status}: {count}" for status, count in status_counts.items()])
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": f"{city_name}处理完成：{status_summary}", 
                    "percent": city_start_percent + per_city_percent
                })
            
        except Exception as e:
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": f"处理{city_name}数据时出错: {str(e)}", 
                    "percent": city_start_percent + (per_city_percent * 0.5)
                })
            print(f"处理{city_name}数据时出错: {str(e)}")
        
        return city_result

    def generate_report(self, project_id, progress_id=None):
        """生成特定项目的报告"""
        try:
            # 创建进度队列
            if progress_id:
                progress_queues[progress_id] = queue.Queue()
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": "开始生成报告...", 
                    "percent": 0
                })
            
            # 获取项目信息
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": "正在获取项目信息...", 
                    "percent": 5
                })
            
            project_info = self.get_project_info(project_id)
            if not project_info:
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({
                        "status": "error", 
                        "message": f"找不到项目信息：{project_id}", 
                        "percent": 10
                    })
                return {"status": "error", "message": f"找不到项目信息：{project_id}"}
            
            # 获取项目任务列表
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": "正在获取项目任务列表...", 
                    "percent": 15
                })
            
            tasks = self.get_tasks(project_id)
            if not tasks:
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({
                        "status": "error", 
                        "message": "找不到任务数据", 
                        "percent": 20
                    })
                return {"status": "error", "message": "找不到任务数据"}
            
            # 获取城市列表
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": "正在获取城市列表...", 
                    "percent": 25
                })
            
            cities = self.get_cities(progress_id=progress_id, base_percent=25)
            if not cities:
                if progress_id and progress_id in progress_queues:
                    progress_queues[progress_id].put({
                        "status": "error", 
                        "message": "找不到城市数据", 
                        "percent": 30
                    })
                return {"status": "error", "message": "找不到城市数据"}
            
            # 处理每个城市的任务
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": f"开始处理{len(cities)}个城市的任务数据...", 
                    "percent": 40
                })
            
            city_results = []
            for i, city in enumerate(cities):
                city_result = self.process_city_tasks(
                    project_id, 
                    city, 
                    tasks, 
                    total_cities=len(cities), 
                    current_city_index=i,
                    progress_id=progress_id,
                    base_percent=40
                )
                city_results.append(city_result)
            
            # 计算汇总统计数据
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": "正在计算汇总统计数据...", 
                    "percent": 80
                })
            
            # 计算所有任务的总状态统计
            all_status_counts = {}
            total_tasks = 0
            for city_result in city_results:
                for status, count in city_result.get('status_counts', {}).items():
                    if status in all_status_counts:
                        all_status_counts[status] += count
                    else:
                        all_status_counts[status] = count
                    total_tasks += count
            
            # 计算各状态的百分比
            status_percentages = {}
            for status, count in all_status_counts.items():
                status_percentages[status] = round((count / total_tasks * 100), 2) if total_tasks > 0 else 0
            
            # 准备报告数据
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "progress", 
                    "message": "正在生成最终报告...", 
                    "percent": 90
                })
            
            report_data = {
                "project": project_info,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_tasks": total_tasks,
                "cities_count": len(cities),
                "status_counts": all_status_counts,
                "status_percentages": status_percentages,
                "cities": city_results
            }
            
            # 完成报告生成
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "complete", 
                    "message": "报告生成完成", 
                    "percent": 100
                })
            
            return {"status": "success", "data": report_data}
            
        except Exception as e:
            error_message = f"生成报告时发生错误: {str(e)}"
            print(error_message)
            if progress_id and progress_id in progress_queues:
                progress_queues[progress_id].put({
                    "status": "error", 
                    "message": error_message, 
                    "percent": 0
                })
            return {"status": "error", "message": error_message}

    def get_progress_color(self, completion_rate):
        """根据完成率获取进度条颜色"""
        if completion_rate < 50:
            return "#f56c6c"  # 红色
        elif completion_rate < 80:
            return "#e6a23c"  # 黄色
        else:
            return "#67c23a"  # 绿色

def start_server(port=8000):
    """启动报表服务器"""
    try:
        server = HTTPServer(('0.0.0.0', port), ReportHandler)
        print(f"启动报表服务器在端口 {port}")
        print(f"访问地址: http://localhost:{port}/")
        server.serve_forever()
    except Exception as e:
        print(f"启动服务器失败: {e}")
        raise

if __name__ == "__main__":
    # 如果直接运行该脚本，启动服务器在端口 8000
    start_server(8000) 