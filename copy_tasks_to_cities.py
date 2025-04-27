#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
复制任务脚本
从"省厅"城市下的任务获取信息，然后为所有其他城市创建相同的任务
"""

import json
import time
import sys
import argparse
from api_client import api_client
from config import config

def log(message):
    """输出日志信息"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_cities():
    """获取城市列表（自定义字段选项）"""
    log("正在获取城市列表...")
    
    # 直接使用API客户端的方法获取城市列表
    cities = api_client.get_cities()
    
    if not cities:
        log("无法获取城市列表")
        return None
    
    log(f"成功获取 {len(cities)} 个城市选项")
    return cities

def get_city_by_name(cities, city_name):
    """根据城市名称查找城市信息"""
    for city in cities:
        if city["name"] == city_name:
            return city
    return None

def get_tasks_by_city(project_id, city):
    """获取指定城市的任务列表，包括所有分页数据"""
    log(f"正在获取城市 '{city['name']}' 的任务...")
    
    # 获取所有任务，然后在客户端筛选
    all_tasks = []
    all_city_tasks = []
    page = 1
    page_size = 100  # 使用较大的页面大小
    city_id = city["id"]
    city_href = city.get("href", f"/api/v3/custom_options/{city_id}")

    # 不使用过滤器获取所有任务
    while True:
        log(f"正在获取第 {page} 页数据...")
        tasks = api_client.get_work_packages(project_id, filters=None, page=page, page_size=page_size)
        
        # 确保tasks是列表
        if tasks is None:
            tasks = []
            
        if not tasks:
            log("没有更多任务")
            break
            
        log(f"获取到 {len(tasks)} 个任务")
        all_tasks.extend(tasks)
        
        # 如果获取的任务数量小于页面大小，说明已经是最后一页
        if len(tasks) < page_size:
            log("已到达最后一页")
            break
            
        page += 1
    
    log(f"总共获取到 {len(all_tasks)} 个任务")
    
    # 在客户端筛选城市任务
    for task in all_tasks:
        # 检查任务的自定义字段
        city_matched = False
        
        # 直接检查_links中的customField1字段
        if "_links" in task and "customField1" in task["_links"]:
            task_city = task["_links"]["customField1"]
            # 检查是否为对象
            if isinstance(task_city, dict) and "href" in task_city:
                # 精确匹配城市的href链接
                if task_city["href"] == city_href:
                    city_matched = True
            # 检查是否为数组
            elif isinstance(task_city, list):
                for city_link in task_city:
                    if isinstance(city_link, dict) and "href" in city_link and city_link["href"] == city_href:
                        city_matched = True
                        break
        
        # 如果匹配城市，添加到筛选结果
        if city_matched:
            all_city_tasks.append(task)
    
    log(f"筛选后得到 {len(all_city_tasks)} 个 '{city['name']}' 的任务")
    
    return all_city_tasks

def get_parent_tasks(tasks):
    """获取顶级任务（没有父任务的任务）"""
    parent_tasks = []
    for task in tasks:
        # 检查是否有父任务
        has_parent = False
        if "_links" in task and "parent" in task["_links"]:
            parent = task["_links"]["parent"]
            if parent and "href" in parent and parent["href"]:
                has_parent = True
        
        if not has_parent:
            parent_tasks.append(task)
    
    log(f"找到 {len(parent_tasks)} 个顶级任务")
    if len(parent_tasks) > 0:
        task_subjects = [task.get("subject", "未命名") for task in parent_tasks]
        log(f"顶级任务列表: {', '.join(task_subjects)}")
    
    return parent_tasks

def get_child_tasks(tasks, parent_id):
    """获取指定父任务的子任务"""
    child_tasks = []
    for task in tasks:
        # 检查是否有父任务
        if "_links" in task and "parent" in task["_links"]:
            parent = task["_links"]["parent"]
            if parent and "href" in parent and parent["href"]:
                # 提取父任务ID
                parent_task_id = parent["href"].split("/")[-1]
                if parent_task_id == str(parent_id):
                    child_tasks.append(task)
    
    log(f"找到 {len(child_tasks)} 个子任务, 父任务ID: {parent_id}")
    if len(child_tasks) > 0:
        task_subjects = [task.get("subject", "未命名") for task in child_tasks]
        log(f"子任务列表: {', '.join(task_subjects)}")
    
    return child_tasks

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='将一个城市的任务复制到其他城市')
    
    parser.add_argument('-s', '--source', default='省厅',
                        help='源城市名称 (默认: 省厅)')
    
    parser.add_argument('-p', '--project',
                        help='项目名称 (默认: 使用第一个项目)')
    
    parser.add_argument('-t', '--target',
                        help='目标城市名称 (默认: 复制到所有城市)')
    
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='仅模拟运行，不实际创建任务')
    
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='输出详细日志信息')
    
    return parser.parse_args()

def main():
    # 解析命令行参数
    args = parse_arguments()
    
    source_city = args.source
    target_project = args.project
    target_city = args.target
    dry_run = args.dry_run
    verbose = args.verbose
    
    if verbose:
        log(f"源城市: {source_city}")
        log(f"目标项目: {target_project or '(使用第一个项目)'}")
        log(f"目标城市: {target_city or '(所有城市)'}")
        log(f"仅模拟运行: {'是' if dry_run else '否'}")
    
    # 执行任务复制
    result = copy_tasks_to_cities(
        source_city_name=source_city,
        target_project_name=target_project,
        target_city_name=target_city,
        dry_run=dry_run,
        verbose=verbose
    )
    
    if result:
        log("脚本执行成功")
    else:
        log("脚本执行失败")
        sys.exit(1)

def copy_tasks_to_cities(source_city_name="省厅", target_project_name=None, target_city_name=None, 
                         dry_run=False, verbose=False):
    """将源城市的任务复制到所有其他城市或指定城市
    
    Args:
        source_city_name: 源城市名称，默认为"省厅"
        target_project_name: 目标项目名称，默认为None（使用第一个项目）
        target_city_name: 目标城市名称，默认为None（复制到所有城市）
        dry_run: 仅模拟运行，不实际创建任务
        verbose: 输出详细日志信息
    """
    log("开始复制任务...")
    
    if dry_run:
        log("模拟运行模式: 不会实际创建任务")
        
    # 检查API凭证
    if not api_client.test_connection():
        log("API连接测试失败，请检查配置")
        return False
    
    # 获取城市列表
    cities = get_cities()
    if not cities:
        log("无法获取城市列表，任务终止")
        return False
    
    # 获取源城市信息
    source_city = get_city_by_name(cities, source_city_name)
    if not source_city:
        log(f"找不到名为 '{source_city_name}' 的城市，任务终止")
        return False
    
    # 获取目标城市列表
    target_cities = []
    if target_city_name:
        # 指定了目标城市
        target_city = get_city_by_name(cities, target_city_name)
        if not target_city:
            log(f"找不到名为 '{target_city_name}' 的目标城市，任务终止")
            return False
        
        if target_city["name"] == source_city_name:
            log(f"目标城市与源城市相同，任务终止")
            return False
            
        target_cities = [target_city]
        log(f"将只复制到城市: {target_city['name']}")
    else:
        # 所有城市（排除源城市）
        target_cities = [city for city in cities if city["name"] != source_city_name]
        log(f"找到 {len(target_cities)} 个目标城市")
    
    # 获取项目列表
    projects = api_client.get_projects()
    if not projects:
        log("无法获取项目列表，任务终止")
        return False
    
    # 确定目标项目
    target_project = None
    if target_project_name:
        # 按名称搜索项目
        for project in projects:
            if project.get("name") == target_project_name:
                target_project = project
                break
        
        if not target_project:
            log(f"找不到名为 '{target_project_name}' 的项目，任务终止")
            return False
    else:
        # 使用第一个项目
        target_project = projects[0]
    
    log(f"使用项目: {target_project.get('name')}")
    project_id = target_project.get("id")
    
    # 获取源城市的任务
    log(f"获取源城市 '{source_city_name}' 的所有任务...")
    source_tasks = get_tasks_by_city(project_id, source_city)
    if not source_tasks:
        log(f"源城市 '{source_city_name}' 下没有任务，任务终止")
        return False
    
    if verbose:
        log(f"源城市 '{source_city_name}' 下的任务列表:")
        for i, task in enumerate(source_tasks):
            log(f"  {i+1}. {task.get('subject')} (ID: {task.get('id')})")
    
    # 获取源城市的顶级任务
    parent_tasks = get_parent_tasks(source_tasks)
    if not parent_tasks:
        log(f"源城市 '{source_city_name}' 下没有顶级任务，任务终止")
        return False
    
    # 统计数据
    city_stats = {}
    
    # 调试输出所有父任务
    log(f"源城市所有顶级任务({len(parent_tasks)}):")
    for idx, task in enumerate(parent_tasks):
        log(f"  {idx+1}. {task.get('subject')} (ID: {task.get('id')})")
    
    # 为每个目标城市复制任务
    total_cities = len(target_cities)
    for city_idx, city in enumerate(target_cities):
        log(f"正在处理城市 [{city_idx+1}/{total_cities}]: {city['name']}")
        
        # 初始化城市统计数据
        city_stats[city['name']] = {
            'parent_tasks_created': 0,
            'parent_tasks_skipped': 0,
            'child_tasks_created': 0,
            'child_tasks_skipped': 0,
            'failed_tasks': 0
        }
        
        # 获取该城市已有的任务
        existing_tasks = get_tasks_by_city(project_id, city)
        existing_subjects = [task.get("subject") for task in existing_tasks]
        
        if verbose:
            log(f"城市 '{city['name']}' 下已有 {len(existing_tasks)} 个任务")
            for i, subject in enumerate(existing_subjects):
                log(f"  {i+1}. {subject}")
        
        # 任务映射：源任务ID -> 目标任务ID
        task_mapping = {}
        
        # 首先创建顶级任务
        parent_count = len(parent_tasks)
        log(f"开始处理 {parent_count} 个顶级任务")
        for task_idx, parent_task in enumerate(parent_tasks):
            log(f"处理顶级任务 [{task_idx+1}/{parent_count}]: {parent_task.get('subject')}")
            
            # 检查任务是否已存在
            if parent_task.get("subject") in existing_subjects:
                log(f"任务 '{parent_task.get('subject')}' 已存在，跳过")
                # 查找对应的已存在任务ID
                existing_task_id = None
                for existing_task in existing_tasks:
                    if existing_task.get("subject") == parent_task.get("subject"):
                        existing_task_id = existing_task.get("id")
                        task_mapping[parent_task.get("id")] = existing_task_id
                        break
                
                city_stats[city['name']]['parent_tasks_skipped'] += 1
                
                # 即使父任务已存在，也需要处理其子任务
                child_tasks = get_child_tasks(source_tasks, parent_task.get("id"))
                log(f"找到 {len(child_tasks)} 个子任务, 父任务ID: {parent_task.get('id')}")
                
                # 创建子任务
                if child_tasks and existing_task_id:
                    child_count = len(child_tasks)
                    for child_idx, child_task in enumerate(child_tasks):
                        log(f"处理子任务 [{child_idx+1}/{child_count}]: {child_task.get('subject')}")
                        
                        # 检查子任务是否已存在
                        if child_task.get("subject") in existing_subjects:
                            log(f"子任务 '{child_task.get('subject')}' 已存在，跳过")
                            city_stats[city['name']]['child_tasks_skipped'] += 1
                            continue
                        
                        # 创建子任务
                        new_child_task = create_subtask_for_city(
                            project_id, 
                            child_task, 
                            city, 
                            existing_task_id,
                            dry_run,
                            verbose
                        )
                        
                        if new_child_task:
                            city_stats[city['name']]['child_tasks_created'] += 1
                        else:
                            city_stats[city['name']]['failed_tasks'] += 1
                        
                        # 避免API限制，添加延迟
                        if not dry_run:
                            time.sleep(1)
                
                continue
            
            # 创建顶级任务
            new_task = create_task_for_city(project_id, parent_task, city, dry_run, verbose)
            if new_task:
                # 记录任务映射
                task_mapping[parent_task.get("id")] = new_task.get("id")
                city_stats[city['name']]['parent_tasks_created'] += 1
                
                # 获取子任务
                child_tasks = get_child_tasks(source_tasks, parent_task.get("id"))
                log(f"找到 {len(child_tasks)} 个子任务")
                
                # 创建子任务
                if child_tasks:
                    child_count = len(child_tasks)
                    for child_idx, child_task in enumerate(child_tasks):
                        log(f"处理子任务 [{child_idx+1}/{child_count}]: {child_task.get('subject')}")
                        
                        # 检查子任务是否已存在
                        if child_task.get("subject") in existing_subjects:
                            log(f"子任务 '{child_task.get('subject')}' 已存在，跳过")
                            city_stats[city['name']]['child_tasks_skipped'] += 1
                            continue
                        
                        # 创建子任务
                        new_child_task = create_subtask_for_city(
                            project_id, 
                            child_task, 
                            city, 
                            new_task.get("id"),
                            dry_run,
                            verbose
                        )
                        
                        if new_child_task:
                            city_stats[city['name']]['child_tasks_created'] += 1
                        else:
                            city_stats[city['name']]['failed_tasks'] += 1
                        
                        # 避免API限制，添加延迟
                        if not dry_run:
                            time.sleep(1)
            else:
                city_stats[city['name']]['failed_tasks'] += 1
        
        # 在城市之间添加延迟，避免API限制
        if not dry_run:
            time.sleep(2)
    
    # 显示统计信息
    log("\n复制任务完成! 统计信息:")
    for city_name, stats in city_stats.items():
        log(f"城市 {city_name}:")
        log(f"  创建顶级任务: {stats['parent_tasks_created']} 个")
        log(f"  跳过顶级任务: {stats['parent_tasks_skipped']} 个")
        log(f"  创建子任务: {stats['child_tasks_created']} 个")
        log(f"  跳过子任务: {stats['child_tasks_skipped']} 个")
        log(f"  失败任务: {stats['failed_tasks']} 个")
        log(f"  总共处理: {stats['parent_tasks_created'] + stats['parent_tasks_skipped'] + stats['child_tasks_created'] + stats['child_tasks_skipped']} 个")
    
    log("任务复制完成")
    return True

def create_task_for_city(project_id, task_data, city, dry_run=False, verbose=False):
    """为指定城市创建任务"""
    # 获取城市字段ID
    city_field_id = api_client.get_city_field_id()
    city_field_key = f"customField{city_field_id}"
    
    # 准备任务数据
    new_task_data = {
        "subject": task_data["subject"],
        "_links": {
            "project": {
                "href": f"/api/v3/projects/{project_id}"
            },
            city_field_key: {
                "href": city["href"]
            }
        }
    }
    
    # 复制描述
    if "description" in task_data:
        new_task_data["description"] = task_data["description"]
    
    # 复制类型
    if "_links" in task_data and "type" in task_data["_links"]:
        new_task_data["_links"]["type"] = task_data["_links"]["type"]
    
    # 复制状态
    if "_links" in task_data and "status" in task_data["_links"]:
        new_task_data["_links"]["status"] = task_data["_links"]["status"]
    
    # 创建任务
    log(f"正在为城市 '{city['name']}' 创建任务 '{task_data['subject']}'...")
    
    if verbose:
        log(f"任务数据: {json.dumps(new_task_data, ensure_ascii=False)}")
    
    if dry_run:
        log("(模拟) 任务创建成功")
        # 模拟返回一个带有ID的结果
        return {"id": f"mock_{int(time.time())}"}
    
    result = api_client.create_work_package(project_id, new_task_data)
    
    if result:
        log(f"任务创建成功，ID: {result.get('id')}")
        return result
    else:
        log(f"任务创建失败")
        return None

def create_subtask_for_city(project_id, task_data, city, parent_id, dry_run=False, verbose=False):
    """为指定城市创建子任务"""
    # 获取城市字段ID
    city_field_id = api_client.get_city_field_id()
    city_field_key = f"customField{city_field_id}"
    
    # 准备任务数据
    new_task_data = {
        "subject": task_data["subject"],
        "_links": {
            "project": {
                "href": f"/api/v3/projects/{project_id}"
            },
            city_field_key: {
                "href": city["href"]
            },
            "parent": {
                "href": f"/api/v3/work_packages/{parent_id}"
            }
        }
    }
    
    # 复制描述
    if "description" in task_data:
        new_task_data["description"] = task_data["description"]
    
    # 复制类型
    if "_links" in task_data and "type" in task_data["_links"]:
        new_task_data["_links"]["type"] = task_data["_links"]["type"]
    
    # 复制状态
    if "_links" in task_data and "status" in task_data["_links"]:
        new_task_data["_links"]["status"] = task_data["_links"]["status"]
    
    # 创建任务
    log(f"正在为城市 '{city['name']}' 创建子任务 '{task_data['subject']}'...")
    
    if verbose:
        log(f"子任务数据: {json.dumps(new_task_data, ensure_ascii=False)}")
    
    if dry_run:
        log("(模拟) 子任务创建成功")
        # 模拟返回一个带有ID的结果
        return {"id": f"mock_{int(time.time())}"}
    
    result = api_client.create_work_package(project_id, new_task_data)
    
    if result:
        log(f"子任务创建成功，ID: {result.get('id')}")
        return result
    else:
        log(f"子任务创建失败")
        return None

if __name__ == "__main__":
    main() 