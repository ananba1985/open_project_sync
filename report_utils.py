"""
报表工具函数模块
提供用于报表生成的辅助函数
"""

def get_status_class(status):
    """
    根据状态获取对应的CSS类名
    """
    status_mapping = {
        '新建': 'status-new',
        '进行中': 'status-in-progress',
        '审核中': 'status-review',
        '已完成': 'status-done',
        '已取消': 'status-cancelled',
        '已暂停': 'status-on-hold',
        '已拒绝': 'status-rejected',
        '已关闭': 'status-closed'
    }
    
    return status_mapping.get(status, 'status-default')

def get_status_label(status):
    """
    获取状态显示标签，如果状态为空则返回"未开始"
    """
    if not status:
        return "未开始"
    return status

def get_task_status_for_city(task_id, city_name, report_data):
    """
    获取指定任务在指定城市的状态
    """
    city_tasks = report_data.get('city_tasks', {}).get(city_name, {})
    task_statuses = city_tasks.get('task_statuses', {})
    
    return task_statuses.get(task_id, "")

def get_progress_color(percent):
    """
    根据百分比返回对应的颜色
    """
    if percent < 20:
        return "#EB5A46"  # 红色
    elif percent < 40:
        return "#FF9F1A"  # 橙色
    elif percent < 60:
        return "#F2D600"  # 黄色
    elif percent < 80:
        return "#61BD4F"  # 浅绿色
    else:
        return "#0079BF"  # 蓝色

def calculate_progress_percentage(status_counts):
    """
    根据状态计数计算进度百分比
    """
    if not status_counts:
        return 0
    
    # 计算完成的任务数量
    completed_count = status_counts.get('已完成', 0) + status_counts.get('已关闭', 0)
    
    # 计算总任务数
    total_count = sum(status_counts.values())
    
    if total_count == 0:
        return 0
        
    return (completed_count / total_count) * 100

def format_datetime(dt):
    """
    格式化日期时间
    """
    if not dt:
        return ""
    
    try:
        # 假设dt是ISO格式的字符串
        if isinstance(dt, str):
            # 简单处理ISO格式，只取日期部分
            if 'T' in dt:
                date_part = dt.split('T')[0]
                parts = date_part.split('-')
                if len(parts) == 3:
                    return f"{parts[0]}年{parts[1]}月{parts[2]}日"
            return dt
        
        # 如果是datetime对象
        return dt.strftime("%Y年%m月%d日")
    except Exception:
        return dt

def cleanup_task_data(task_data):
    """
    清理任务数据，移除不需要的字段，格式化日期等
    """
    if not task_data:
        return {}
    
    # 创建一个新字典，只包含需要的字段
    cleaned_data = {
        'id': task_data.get('id', ''),
        'subject': task_data.get('subject', '未命名任务'),
        'status': task_data.get('status', {}).get('name', '') if task_data.get('status') else '',
        'progress': task_data.get('percentageDone', 0),
        'created_at': format_datetime(task_data.get('createdAt', '')),
        'updated_at': format_datetime(task_data.get('updatedAt', '')),
        'children': []
    }
    
    # 处理子任务
    if 'children' in task_data and task_data['children']:
        for child in task_data['children']:
            cleaned_data['children'].append(cleanup_task_data(child))
    
    return cleaned_data 