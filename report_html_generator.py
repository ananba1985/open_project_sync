"""
报表HTML生成器模块
负责生成与报表相关的HTML内容
"""

import time
import re
import json
from datetime import datetime
from report_utils import (
    get_status_class, 
    get_status_label, 
    get_task_status_for_city, 
    get_progress_color,
    calculate_progress_percentage
)

class ReportHTMLGenerator:
    """报表HTML生成器类，负责生成各种HTML报表内容"""
    
    def generate_loading_page(self, report_id, project_name):
        """
        生成加载页面HTML
        
        参数:
            report_id: 报表ID
            project_name: 项目名称
            
        返回:
            str: 加载页面HTML字符串
        """
        html = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>报表生成中 - {project_name}</title>
            <style>
                {self.generate_css_styles()}
                .loading-container {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    min-height: 80vh;
                    text-align: center;
                    padding: 20px;
                }}
                .progress-container {{
                    width: 80%;
                    max-width: 600px;
                    margin: 20px auto;
                }}
                .progress-bar {{
                    height: 24px;
                    background-color: #e9ecef;
                    border-radius: 12px;
                    overflow: hidden;
                    margin-bottom: 10px;
                }}
                .progress-bar-fill {{
                    height: 100%;
                    background-color: #0079BF;
                    border-radius: 12px;
                    transition: width 0.5s ease;
                    width: 0%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-weight: bold;
                }}
                .status-text {{
                    font-size: 16px;
                    margin-top: 10px;
                    color: #666;
                }}
                .error-container {{
                    display: none;
                    background-color: #FEE;
                    border: 1px solid #E99;
                    border-radius: 5px;
                    padding: 15px;
                    margin-top: 20px;
                    color: #C33;
                }}
                .btn-home {{
                    margin-top: 20px;
                    padding: 10px 20px;
                    background-color: #0079BF;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 16px;
                }}
                .btn-home:hover {{
                    background-color: #005f9e;
                }}
            </style>
        </head>
        <body>
            <div class="loading-container">
                <h1>项目"{project_name}"报表生成中</h1>
                <div class="progress-container">
                    <div class="progress-bar">
                        <div class="progress-bar-fill" id="progressBar">0%</div>
                    </div>
                </div>
                <div class="status-text" id="statusText">正在初始化...</div>
                <div class="error-container" id="errorContainer">
                    <h3>生成报表时出错</h3>
                    <p id="errorMessage"></p>
                    <button class="btn-home" onclick="window.location.href='/'">返回首页</button>
                </div>
            </div>
            
            <script>
                // 初始进度
                let progress = 0;
                const progressBar = document.getElementById('progressBar');
                const statusText = document.getElementById('statusText');
                const errorContainer = document.getElementById('errorContainer');
                const errorMessage = document.getElementById('errorMessage');
                
                // 更新进度函数
                function updateProgress() {{
                    fetch(`/api/report/progress/{report_id}`)
                        .then(response => {{
                            if (!response.ok) {{
                                throw new Error('获取进度失败');
                            }}
                            return response.json();
                        }})
                        .then(data => {{
                            if (data.error) {{
                                showError(data.error);
                                return;
                            }}
                            
                            progress = data.progress || 0;
                            progressBar.style.width = progress + '%';
                            progressBar.innerText = Math.round(progress) + '%';
                            
                            if (data.status) {{
                                statusText.innerText = data.status;
                            }}
                            
                            // 如果进度到达100%，重定向到报表页面
                            if (progress >= 100) {{
                                window.location.href = `/report/{report_id}`;
                            }} else {{
                                // 否则继续轮询
                                setTimeout(updateProgress, 1000);
                            }}
                        }})
                        .catch(error => {{
                            showError(error.message);
                        }});
                }}
                
                // 显示错误
                function showError(message) {{
                    statusText.style.display = 'none';
                    errorContainer.style.display = 'block';
                    errorMessage.innerText = message;
                }}
                
                // 开始进度更新
                updateProgress();
            </script>
        </body>
        </html>
        """
        return html
        
    def generate_css_styles(self):
        """
        生成CSS样式
        
        返回:
            str: CSS样式字符串
        """
        return """
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            
            body {
                font-family: "Helvetica Neue", Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                background-color: #f8f9fa;
                padding: 0;
                margin: 0;
            }
            
            .container {
                max-width: 100%;
                margin: 0 auto;
                padding: 20px;
            }
            
            .report-header {
                background-color: #fff;
                padding: 20px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            
            .report-title {
                font-size: 24px;
                margin-bottom: 15px;
                color: #333;
                border-bottom: 2px solid #0079BF;
                padding-bottom: 10px;
            }
            
            .report-info {
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                margin-bottom: 15px;
            }
            
            .info-item {
                flex: 1;
                min-width: 200px;
            }
            
            .info-label {
                font-weight: bold;
                color: #666;
                margin-bottom: 5px;
            }
            
            .info-value {
                font-size: 16px;
            }
            
            .report-actions {
                display: flex;
                justify-content: flex-end;
                margin: 15px 0;
            }
            
            .btn {
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                text-decoration: none;
                display: inline-block;
                margin-left: 10px;
            }
            
            .btn-export {
                background-color: #0079BF;
                color: white;
            }
            
            .btn-export:hover {
                background-color: #005f9e;
            }
            
            .btn-print {
                background-color: #6c757d;
                color: white;
            }
            
            .btn-print:hover {
                background-color: #5a6268;
            }
            
            .report-table {
                width: 100%;
                border-collapse: collapse;
                background-color: #fff;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                margin-bottom: 20px;
                font-size: 14px;
            }
            
            .report-table th {
                background-color: #f1f3f5;
                padding: 12px 15px;
                text-align: left;
                border-bottom: 2px solid #dee2e6;
                position: sticky;
                top: 0;
                z-index: 10;
            }
            
            .report-table td {
                padding: 10px 15px;
                border-bottom: 1px solid #dee2e6;
                vertical-align: middle;
            }
            
            .report-table tr:nth-child(even) {
                background-color: #f8f9fa;
            }
            
            .report-table tr:hover {
                background-color: #f1f3f5;
            }
            
            .city-header {
                white-space: nowrap;
                text-align: center;
            }
            
            .task-row {
                font-weight: bold;
            }
            
            .subtask-row {
                font-size: 13px;
            }
            
            .status-cell {
                text-align: center;
                padding: 5px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            
            .status-new {
                background-color: #E0F7FA;
                color: #00838F;
            }
            
            .status-in-progress {
                background-color: #E3F2FD;
                color: #1565C0;
            }
            
            .status-review {
                background-color: #E8F5E9;
                color: #2E7D32;
            }
            
            .status-done, .status-closed {
                background-color: #E8F5E9;
                color: #2E7D32;
            }
            
            .status-cancelled {
                background-color: #FFEBEE;
                color: #C62828;
            }
            
            .status-on-hold {
                background-color: #FFF8E1;
                color: #FF8F00;
            }
            
            .status-rejected {
                background-color: #FFEBEE;
                color: #C62828;
            }
            
            .status-default {
                background-color: #ECEFF1;
                color: #546E7A;
            }
            
            /* 责任人样式 */
            .assignee {
                display: inline-block;
                padding: 3px 6px;
                background-color: #e9ecef;
                border-radius: 3px;
                font-size: 12px;
                margin-top: 3px;
            }
            
            /* 进度条样式 */
            .progress-bar {
                width: 100%;
                background-color: #e9ecef;
                border-radius: 4px;
                height: 8px;
                overflow: hidden;
                margin-top: 5px;
            }
            
            .progress-fill {
                height: 100%;
                border-radius: 4px;
            }
            
            /* 可折叠内容 */
            .collapsible {
                cursor: pointer;
            }
            
            .collapse-icon {
                display: inline-block;
                margin-right: 5px;
                transition: transform 0.3s;
            }
            
            .collapsed .collapse-icon {
                transform: rotate(-90deg);
            }
            
            .task-children {
                display: none;
            }
            
            /* 错误页面样式 */
            .error-page {
                text-align: center;
                padding: 50px 20px;
                max-width: 600px;
                margin: 0 auto;
            }
            
            .error-icon {
                font-size: 60px;
                color: #dc3545;
                margin-bottom: 20px;
            }
            
            .error-title {
                font-size: 24px;
                color: #333;
                margin-bottom: 15px;
            }
            
            .error-message {
                font-size: 16px;
                color: #666;
                margin-bottom: 30px;
                line-height: 1.5;
            }
            
            /* 对于打印优化 */
            @media print {
                body {
                    background-color: white;
                }
                
                .report-actions, .btn {
                    display: none;
                }
                
                .container {
                    padding: 0;
                    width: 100%;
                }
                
                .report-header {
                    box-shadow: none;
                    border: 1px solid #dee2e6;
                }
                
                .report-table {
                    box-shadow: none;
                    border: 1px solid #dee2e6;
                }
                
                .report-table th {
                    background-color: #f8f9fa !important;
                    color: black !important;
                }
            }
        """
        
    def generate_report_table(self, report_data):
        """
        生成报表表格HTML
        
        参数:
            report_data: 报表数据字典
            
        返回:
            str: 报表表格HTML字符串
        """
        project_name = report_data.get('project_name', '未知项目')
        generation_time = report_data.get('generation_time', datetime.now().strftime('%Y年%m月%d日 %H:%M'))
        tasks = report_data.get('tasks', [])
        cities = report_data.get('cities', [])
        
        # 生成表头部分
        table_header = f'''
        <div class="report-header">
            <h1 class="report-title">{project_name} - 项目任务状态报表</h1>
            <div class="report-info">
                <div class="info-item">
                    <div class="info-label">生成时间:</div>
                    <div class="info-value">{generation_time}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">任务总数:</div>
                    <div class="info-value">{len(tasks)}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">城市数量:</div>
                    <div class="info-value">{len(cities)}</div>
                </div>
            </div>
        </div>
        
        <div class="report-actions">
            <button class="btn btn-export" onclick="exportToExcel()">导出为Excel</button>
            <button class="btn btn-print" onclick="window.print()">打印报表</button>
        </div>
        '''
        
        # 生成表格部分
        table_content = f'''
        <table class="report-table" id="reportTable">
            <thead>
                <tr>
                    <th style="width: 5%">序号</th>
                    <th style="width: 25%">任务名称</th>
                    <th style="width: 10%">当前状态</th>
                    <th style="width: 10%">创建时间</th>
                    <th style="width: 10%">更新时间</th>
        '''
        
        # 添加城市列
        for city in cities:
            table_content += f'<th class="city-header">{city}</th>'
            
        table_content += '''
                </tr>
            </thead>
            <tbody>
        '''
        
        # 添加任务行
        for index, task in enumerate(tasks):
            task_id = task.get('id', '')
            task_name = task.get('subject', '未命名任务')
            task_status = task.get('status', '')
            created_at = task.get('created_at', '')
            updated_at = task.get('updated_at', '')
            
            # 为有子任务的任务添加可折叠功能
            has_children = len(task.get('children', [])) > 0
            collapsible_class = 'collapsible' if has_children else ''
            collapse_icon = '<span class="collapse-icon">▼</span>' if has_children else ''
            
            table_content += f'''
                <tr class="task-row {collapsible_class}" data-task-id="{task_id}">
                    <td>{index + 1}</td>
                    <td>{collapse_icon}{task_name}</td>
                    <td><div class="status-cell {get_status_class(task_status)}">{get_status_label(task_status)}</div></td>
                    <td>{created_at}</td>
                    <td>{updated_at}</td>
            '''
            
            # 添加城市状态单元格
            for city in cities:
                city_status = get_task_status_for_city(task_id, city, report_data)
                status_class = get_status_class(city_status)
                status_label = get_status_label(city_status)
                
                table_content += f'''
                    <td><div class="status-cell {status_class}">{status_label}</div></td>
                '''
                
            table_content += '</tr>'
            
            # 如果有子任务，添加子任务行
            if has_children:
                table_content += f'<tr class="task-children" data-parent="{task_id}"><td colspan="{5 + len(cities)}">'
                table_content += '<table class="report-table" style="box-shadow: none; margin-bottom: 0;">'
                table_content += '<tbody>'
                
                for child_index, child in enumerate(task.get('children', [])):
                    child_id = child.get('id', '')
                    child_name = child.get('subject', '未命名子任务')
                    child_status = child.get('status', '')
                    child_created_at = child.get('created_at', '')
                    child_updated_at = child.get('updated_at', '')
                    
                    table_content += f'''
                        <tr class="subtask-row">
                            <td style="width: 5%">{index + 1}.{child_index + 1}</td>
                            <td style="width: 25%; padding-left: 25px;">{child_name}</td>
                            <td style="width: 10%"><div class="status-cell {get_status_class(child_status)}">{get_status_label(child_status)}</div></td>
                            <td style="width: 10%">{child_created_at}</td>
                            <td style="width: 10%">{child_updated_at}</td>
                    '''
                    
                    # 添加城市状态单元格
                    for city in cities:
                        city_status = get_task_status_for_city(child_id, city, report_data)
                        status_class = get_status_class(city_status)
                        status_label = get_status_label(city_status)
                        
                        table_content += f'''
                            <td><div class="status-cell {status_class}">{status_label}</div></td>
                        '''
                        
                    table_content += '</tr>'
                
                table_content += '</tbody></table></td></tr>'
                
        table_content += '''
            </tbody>
        </table>
        '''
        
        # 添加JavaScript功能
        js_functionality = '''
        <script>
            // 折叠/展开子任务功能
            document.addEventListener('DOMContentLoaded', function() {
                const collapsibles = document.querySelectorAll('.collapsible');
                
                collapsibles.forEach(function(element) {
                    element.addEventListener('click', function() {
                        const taskId = this.getAttribute('data-task-id');
                        const childrenRow = document.querySelector(`[data-parent="${taskId}"]`);
                        
                        if (childrenRow) {
                            this.classList.toggle('collapsed');
                            
                            if (childrenRow.style.display === 'table-row') {
                                childrenRow.style.display = 'none';
                            } else {
                                childrenRow.style.display = 'table-row';
                            }
                        }
                    });
                });
            });
            
            // Excel导出功能
            function exportToExcel() {
                const table = document.getElementById('reportTable');
                const html = table.outerHTML;
                
                // 使用Blob创建下载链接
                const blob = new Blob([html], { type: 'application/vnd.ms-excel' });
                const url = URL.createObjectURL(blob);
                
                // 创建下载链接并自动点击
                const downloadLink = document.createElement("a");
                const fileName = document.querySelector('.report-title').textContent.trim() + '.xls';
                
                downloadLink.href = url;
                downloadLink.download = fileName;
                downloadLink.click();
            }
        </script>
        '''
        
        return table_header + table_content + js_functionality
    
    def generate_error_page(self, error_message):
        """
        生成错误页面HTML
        
        参数:
            error_message: 错误信息
            
        返回:
            str: 错误页面HTML字符串
        """
        html = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>报表生成错误</title>
            <style>
                {self.generate_css_styles()}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error-page">
                    <div class="error-icon">⚠️</div>
                    <h1 class="error-title">报表生成失败</h1>
                    <p class="error-message">{error_message}</p>
                    <button class="btn btn-export" onclick="window.location.href='/'">返回首页</button>
                </div>
            </div>
        </body>
        </html>
        """
        return html
    
    def generate_complete_report_html(self, report_data):
        """
        生成完整报表HTML
        
        参数:
            report_data: 报表数据字典
            
        返回:
            str: 完整报表HTML字符串
        """
        project_name = report_data.get('project_name', '未知项目')
        
        html = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>项目报表 - {project_name}</title>
            <style>
                {self.generate_css_styles()}
            </style>
        </head>
        <body>
            <div class="container">
                {self.generate_report_table(report_data)}
            </div>
        </body>
        </html>
        """
        return html 