import os
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

async def test_connection():
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.apiyi.com/v1")
    
    print(f"📡 正在尝试连接 API...\nURL: {base_url}\nKey: {api_key[:8]}...")
    
    import httpx
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=10.0,
        # 🌟 免疫系统升级：新版 httpx 的强行直连语法
        http_client=httpx.AsyncClient(trust_env=False)
    )
    
    try:
        response = await client.chat.completions.create(
            model="gpt-5.4", # 根据你的实际模型名称修改
            messages=[{"role": "user", "content": "Ping!"}]
        )
        print("✅ 连接成功！大模型回复:", response.choices[0].message.content)
    except Exception as e:
        print("❌ 连接失败！错误信息:", type(e).__name__, "-", e)

asyncio.run(test_connection())