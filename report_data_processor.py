"""
报表数据处理模块
负责数据获取、处理和分析
"""

import concurrent.futures
import requests
import time
from api_client import api_client
from report_utils import get_status_label

class ReportDataProcessor:
    def __init__(self):
        pass

    def build_task_tree(self, task, tasks_tree, all_tasks_dict):
        """递归构建任务树结构"""
        result = {
            "id": task["id"],
            "subject": task.get("subject", "无标题"),
            "children": []
        }
        
        # 添加任务的状态信息
        if "_links" in task and "status" in task["_links"] and task["_links"]["status"]:
            status_link = task["_links"]["status"]
            if isinstance(status_link, dict) and "title" in status_link:
                result["status"] = status_link["title"]
        
        # 获取子任务
        children = tasks_tree.get(task["id"], [])
        for child_id in children:
            child_task = all_tasks_dict.get(child_id)
            if child_task:
                child_result = self.build_task_tree(child_task, tasks_tree, all_tasks_dict)
                result["children"].append(child_result)
        
        return result

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

    def is_task_belongs_to_city(self, task, city):
        """检查任务是否属于指定城市"""
        city_id = city.get("id", "")
        city_name = city.get("name", "")
        
        # 检查任务的自定义字段中是否包含城市信息
        # 假设自定义字段1是城市字段
        task_city = None
        if "customField1" in task:
            task_city = task["customField1"]
        
        # 检查是否有_links中的customField1
        if not task_city and "_links" in task and "customField1" in task["_links"]:
            task_city = task["_links"]["customField1"]
        
        if isinstance(task_city, dict):
            return (
                task_city.get("id") == city_id or 
                task_city.get("title") == city_name or 
                task_city.get("name") == city_name or
                task_city.get("value") == city_name
            )
        
        # 其他情况
        return False

    def get_cities(self, project_id, progress_id=None, progress_callback=None):
        """获取项目的城市列表"""
        if progress_callback:
            progress_callback("获取城市列表...", 2)
        
        try:
            # 直接使用api_client的get_cities方法
            cities = api_client.get_cities()
            
            if not cities:
                error_msg = "城市列表为空"
                print(error_msg)
                raise Exception(error_msg)
            
            if progress_callback and cities:
                progress_callback(f"已获取{len(cities)}个城市", 5)
                
            return cities
        except Exception as e:
            error_msg = f"获取城市列表失败: {str(e)}"
            print(error_msg)
            raise Exception(error_msg)

    def get_all_work_packages(self, project_id, progress_callback=None, base_percent=0):
        """获取项目所有工作包"""
        if progress_callback:
            progress_callback("获取工作包数据...", base_percent + 1)
        
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
            if progress_callback:
                progress_callback(msg, base_percent + 10)
            
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
                if progress_callback:
                    progress_callback(log_msg, base_percent + 12)
                
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
                if progress_callback:
                    progress_callback(update_msg, base_percent + 15)
            else:
                print("所有工作包都包含状态信息，无需单独获取")
            
            # 将任务添加到结果集
            all_work_packages = work_packages
        else:
            msg = "获取工作包失败，未返回数据"
            print(msg)
            if progress_callback:
                progress_callback(msg, base_percent + 5)
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
            if progress_callback:
                progress_callback(msg, base_percent + 15)
            raise Exception("获取的工作包数据为空")

    def process_city_tasks(self, project_id, city, tasks, total_cities, current_city_index, progress_callback=None, base_percent=40):
        """处理特定城市的任务数据"""
        if progress_callback:
            # 计算当前城市的进度百分比范围 (40-80% 平均分配给各城市)
            city_percent_range = 40  # 总共占 40% (从 40% 到 80%)
            per_city_percent = city_percent_range / total_cities
            city_start_percent = base_percent + (current_city_index * per_city_percent)
            
            progress_callback(f"处理城市数据：{city['name']} ({current_city_index + 1}/{total_cities})", city_start_percent)
        
        city_result = {"city": city, "tasks": [], "status_counts": {}}
        status_counts = {}
        
        try:
            if not tasks:
                if progress_callback:
                    progress_callback(f"{city['name']}：无任务数据", city_start_percent + (per_city_percent * 0.3))
                return city_result
            
            # 筛选当前城市的任务
            city_key = city.get('id', '').lower()
            city_name = city.get('name', '')
            
            if progress_callback:
                progress_callback(f"筛选{city_name}的任务...", city_start_percent + (per_city_percent * 0.4))
            
            # 任务筛选逻辑
            city_tasks = []
            for task in tasks:
                # 检查任务的城市字段或名称中包含城市名
                if self.is_task_belongs_to_city(task, city):
                    city_tasks.append(task)
            
            if progress_callback:
                progress_callback(f"{city_name}：找到 {len(city_tasks)} 个相关任务", city_start_percent + (per_city_percent * 0.6))
            
            # 统计各状态的任务数量
            for task in city_tasks:
                status_link = task.get("_links", {}).get("status", {})
                if isinstance(status_link, dict) and "title" in status_link:
                    status = status_link["title"]
                    status_label = get_status_label(status)
                    
                    if status_label not in status_counts:
                        status_counts[status_label] = 0
                    status_counts[status_label] += 1
            
            if progress_callback:
                progress_callback(f"{city_name}：任务状态统计完成", city_start_percent + (per_city_percent * 0.8))
            
            # 整理城市结果
            city_result = {
                "city": city,
                "tasks": city_tasks,
                "status_counts": status_counts
            }
            
            return city_result
        except Exception as e:
            print(f"处理城市 {city.get('name', 'unknown')} 数据失败: {str(e)}")
            return city_result 