# OpenProject 数据同步工具 v1.0.0

这是一个基于OpenProject API的数据同步工具，用于管理和同步OpenProject中的项目和工作包信息。

## 功能特性

1. 配置并保存OpenProject的访问URL和访问令牌
2. 获取并显示OpenProject的项目列表
3. 查看选定项目的基本信息和工作包信息（包含自定义字段）
4. 支持修改、新增、删除工作包信息并同步到OpenProject
5. 支持导出导入项目工作包数据
6. 支持生成项目报表和数据分析
7. 支持复制任务到不同城市项目

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### GUI模式

运行主程序：

```bash
python main.py
```

### 命令行模式

启动报表服务器：

```bash
python main.py --report
```

查看帮助信息：

```bash
python main.py --help
```

## 配置说明

首次运行时，需要在配置界面设置OpenProject的API访问URL和访问令牌。您可以通过以下两种方式配置：

1. 通过GUI界面配置
2. 或者直接编辑op_config.json文件：
   ```json
   {
     "api_url": "https://your-openproject-instance.com",
     "api_token": "your-api-token-here"
   }
   ```

## 项目结构

- `main.py` - 主程序入口
- `api_client.py` - OpenProject API客户端实现
- `config.py` - 配置管理
- `main_window.py` - 主窗口UI实现
- `ui_*.py` - 各种功能界面实现
- `report_*.py` - 报表功能相关实现

## 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 获取详细更新记录。

## 许可证

MIT 