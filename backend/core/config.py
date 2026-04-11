# backend/core/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# 显式加载环境变量，确保能读到你 .env 里的 OPENAI_ 变量
load_dotenv()

class Settings(BaseSettings):
    # 兼容你 .env 里的 OPENAI_API_KEY
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    # 兼容你 .env 里的 OPENAI_BASE_URL
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.apiyi.com/v1")
    model_name: str = os.getenv("LLM_MODEL_NAME", "gpt-4o")

    # 🌟 核心修复：Pydantic V2 的配置字典
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding='utf-8',
        extra='ignore'  # 告诉 Pydantic 忽略 .env 里没定义在上面的多余变量
    )

settings = Settings()