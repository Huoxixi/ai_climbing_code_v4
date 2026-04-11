
"""
backend/agent/controller.py
"""

import json
import asyncio
from typing import List, Dict, Optional
from openai import AsyncOpenAI
import httpx

from core.config import settings
from core.models import RouteRequest, RouteResponse, RouteCandidate, HoldType
from core.generator import RouteGenerator
from core.a_star_solver import AStarSolver
from agent.tools_def import SELECT_ROUTE_TOOL

SYSTEM_PROMPT = """
你现在是「智行通途 (ZXT)」攀岩定线引擎的艺术总监 (Curator)。
你的任务是从 A* 物理引擎筛选出的 5 条候选路线中，挑选出最符合用户审美和定线艺术的一条。

# 候选路线数据说明：
- ID: 路线的唯一标识。
- Total Cost: A* 算法计算的体力/技巧总消耗。越低代表越容易爬，越高代表越具有挑战性。
- Crux: 路线中最难的一个动作描述。
- Recipe: 岩点配方组成。

# 你的工作：
1. 评估这些路线的 Cost 和 Crux。
2. 结合用户的目标难度（Target Difficulty）进行权衡。
3. 为选中的路线起一个富有诗意或硬核的名字 (route_name)。
4. 写一段定线员寄语 (setter_commentary)，解释你为什么选择这条线，以及它的攀爬风格。

请调用 `select_and_package_route` 工具提交你的决定。
"""

async def generate_route_with_reflection(request: RouteRequest) -> RouteResponse:
    """
    PCG 漏斗模型核心逻辑：
    1. 批量生成并初筛 (Generator)
    2. A* 物理试爬与评分 (Solver)
    3. LLM 艺术总监决选 (Curator)
    """
    
    # 步骤 1：批量生成并初筛 (Generator)
    generator = RouteGenerator()
    batch_size = 50  # 演示用，实际可设为 1000
    candidate_holds_list = generator.generate_batch_routes(request.recipe, batch_size=batch_size)
    
    if not candidate_holds_list:
        raise ValueError("无法生成符合初筛规则的路线，请调整配方。")

    # 步骤 2：A* 物理试爬与评分 (Solver)
    solver = AStarSolver(request.climber_height_cm, request.climber_span_cm)
    successful_candidates: List[RouteCandidate] = []
    
    for holds in candidate_holds_list:
        result = solver.solve(holds)
        if result:
            successful_candidates.append(result)
    
    if not successful_candidates:
        raise ValueError("所有生成的候选路线均无法通过 A* 物理完攀测试。")

    # 按 Total Cost 排序，取前 5 条
    successful_candidates.sort(key=lambda x: x.total_cost)
    top_5 = successful_candidates[:5]
    
    # 给 top_5 分配临时 ID 方便 LLM 选择
    candidates_meta = []
    candidates_map: Dict[str, RouteCandidate] = {}
    for i, c in enumerate(top_5):
        route_id = f"route_{i+1}"
        candidates_map[route_id] = c
        candidates_meta.append({
            "id": route_id,
            "total_cost": f"{c.total_cost:.1f}",
            "crux": c.crux_step,
            "recipe_summary": {k.value: v for k, v in request.recipe.items()}
        })

    # 步骤 3：LLM 艺术总监决选 (Curator)
    custom_http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60.0, connect=15.0))
    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url, http_client=custom_http)

    user_content = f"""
用户需求：
- 目标难度：{request.target_difficulty}
- 攀爬者身高/臂展：{request.climber_height_cm}cm / {request.climber_span_cm}cm

候选路线：
{json.dumps(candidates_meta, indent=2, ensure_ascii=False)}

请挑选出最完美的一条路线。
"""

    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        tools=[SELECT_ROUTE_TOOL],
        tool_choice={"type": "function", "function": {"name": "select_and_package_route"}},
        temperature=0.7
    )

    message = response.choices[0].message
    if not message.tool_calls:
        # 兜底：如果 LLM 没调工具，默认选第一条
        best_candidate = top_5[0]
        return RouteResponse(
            route_name="默认探险者",
            setter_commentary="LLM 决选超时，自动选择代价最优路线。",
            placed_holds=best_candidate.placed_holds,
            beta_sequence=best_candidate.beta_sequence
        )

    tool_call = message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    
    selected_id = args.get("selected_route_id", "route_1")
    final_candidate = candidates_map.get(selected_id, top_5[0])

    return RouteResponse(
        route_name=args.get("route_name", "无名之路"),
        setter_commentary=args.get("setter_commentary", "未提供寄语"),
        placed_holds=final_candidate.placed_holds,
        beta_sequence=final_candidate.beta_sequence
    )
