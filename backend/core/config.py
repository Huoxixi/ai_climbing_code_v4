# backend/core/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# 显式加载环境变量，确保能读到你 .env 里的 OPENAI_ 变量
load_dotenv()

class Settings(BaseSettings):
    # 兼容你 .env 里的 OPENAI_API_KEY
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    # 外部模型地址必须由部署环境明确提供，避免误用未经审核的默认供应商。
    base_url: str = os.getenv("OPENAI_BASE_URL", "")
    model_name: str = os.getenv("LLM_MODEL_NAME", "gpt-4o")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET", "hold-images")

    # 🌟 核心修复：Pydantic V2 的配置字典
    model_config = SettingsConfigDict(
        env_file=None if os.getenv("PYTHON_DOTENV_DISABLED") == "1" else ".env",
        env_file_encoding='utf-8',
        extra='ignore'  # 告诉 Pydantic 忽略 .env 里没定义在上面的多余变量
    )

settings = Settings()
