import os
import json
from dotenv import load_dotenv

class Config:
    def __init__(self):
        self.config_file = "op_config.json"
        self.api_url = ""
        self.api_token = ""
        self.load_config()
    
    def load_config(self):
        """从配置文件加载配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    self.api_url = config_data.get('api_url', '')
                    self.api_token = config_data.get('api_token', '')
            except Exception as e:
                print(f"加载配置文件出错: {e}")
        else:
            # 尝试从环境变量加载（用于开发测试）
            load_dotenv()
            self.api_url = os.getenv('OPENPROJECT_API_URL', '')
            self.api_token = os.getenv('OPENPROJECT_API_TOKEN', '')
    
    def save_config(self):
        """保存配置到文件"""
        config_data = {
            'api_url': self.api_url,
            'api_token': self.api_token
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置文件出错: {e}")
            return False
    
    def is_configured(self):
        """检查是否已配置API信息"""
        return bool(self.api_url and self.api_token)

# 全局配置实例
config = Config()