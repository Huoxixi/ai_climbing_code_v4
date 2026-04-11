import json
import os
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv
import httpx

load_dotenv()

SYSTEM_PROMPT = """
你是一位顶级的攀岩定线员。我将提供一条真实 MoonBoard 路线的【核心岩点坐标数组】。
请你发挥空间想象力，脑补人类攀爬这组岩点时的真实动作，将其翻译为包含 `step` 和 `limb` (LH/RH/LF/RF) 的 JSON 数组。

🚨 绝对遵守的物理法则：
1. 必须四肢起步 (Step 0 包含 3-4 个点)。起步手必须在起步脚上方！
2. 必须遵守【先挪手，后上脚】的逻辑。如果脚要踩之前手抓过的点，必须先在更早的 step 中把手移走！
3. 最后一个点必须带有 "is_top": true。
4. 确保左右手、左右脚不会严重交叉打结。

严格输出纯 JSON 对象，格式如下：
{
  "route_name": "提供给你的路线名",
  "beta_sequence": [
    {"step": 0, "limb": "LH", "hold_id": "D5"},
    // ... 后续动作
  ]
}
"""

async def annotate_route(client, route_data, v_grade):
    holds_str = ", ".join(route_data["holds"])
    user_prompt = f"路线名称: {route_data['name']}\n难度: {v_grade}\n可用岩点: [{holds_str}]\n请将这些点串联成符合人类力学的 beta_sequence。"
    
    try:
        response = await client.chat.completions.create(
            model="gpt-5.4", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={ "type": "json_object" } 
        )
        content = response.choices[0].message.content.strip()
        return json.loads(content)
    except Exception as e:
        print(f"⚠️ {route_data['name']} 附魔失败: {e}")
        return None

async def run_annotator():
    input_file = "filtered_skeletons.json"
    output_file = "classic_routes.json" 
    
    if not os.path.exists(input_file):
        print(f"❌ 找不到骨架文件: {input_file}，请先运行 1_rough_filter.py")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        filtered_db = json.load(f)

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    custom_http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60.0))
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=3, http_client=custom_http)

    # 🌟 核心控制台：你可以在这里自由控制每次要翻译多少条！
    TARGET_COUNT_PER_GRADE = 10 

    print(f"🚀 [阶段二] 启动 AI 附魔：每个难度提取 Top {TARGET_COUNT_PER_GRADE} 路线进行翻译...")
    final_routes = []

    for v_grade, routes in filtered_db.items():
        # 🌟 核心修改：在这一步，才真正进行数据截取（取出大盘里的前 10 名）
        top_routes_to_process = routes[:TARGET_COUNT_PER_GRADE]
        
        print(f"🔄 正在处理 {v_grade} 难度的 Top {len(top_routes_to_process)} 路线...")
        for route in top_routes_to_process:
            print(f"   🪄 翻译中: {route['name']} (得分: {route['score']}) ...")
            annotated_data = await annotate_route(client, route, v_grade)
            
            if annotated_data and "beta_sequence" in annotated_data:
                annotated_data["difficulty_label"] = f"{v_grade}标杆"
                annotated_data["original_grade"] = route.get("grade", "未知")
                annotated_data["is_benchmark"] = route.get("is_benchmark", False)
                final_routes.append(annotated_data)
                
            await asyncio.sleep(1) # 防并发限流

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_routes, f, ensure_ascii=False, indent=2)
        
    print(f"\n✅ 全部附魔及打标完毕！专属的纯血基因库已覆盖至: {output_file}")

if __name__ == "__main__":
    asyncio.run(run_annotator())