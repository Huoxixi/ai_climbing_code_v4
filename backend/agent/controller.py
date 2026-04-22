
"""
backend/agent/controller.py
"""

import json
import asyncio
from typing import List, Dict, Optional
from openai import AsyncOpenAI
import httpx

from core.config import settings
from core.models import RouteRequest, RouteResponse, RouteCandidate, HoldType, FinalRoute
from core.generator import RouteGenerator
from core.a_star_solver import AStarSolver
from agent.tools_def import SELECT_ROUTE_TOOL

SYSTEM_PROMPT = """
你现在是「智行通途 (ZXT)」攀岩定线引擎的艺术总监 (Curator)。
你的任务是从一个候选项列表中（最多5条）挑选出最优秀、最有趣的 **两条** 路线。

# 路线数据说明：
- `id`: 每条路线的唯一标识符，如 "route_0"。
- `total_cost`: A* 算法计算的体力/技巧总消耗。越低代表越容易爬。
- `crux`: 路线中最难的一个动作描述。

# 你的工作：
1.  **综合评估**：仔细评估列表中的每一条候选路线，不仅仅是看 `total_cost`，还要考虑路线的风格、可能的动作序列等。
2.  **选择最佳两条**：挑选出你认为最符合用户需求、最具创意或攀爬体验最佳的两条路线。
3.  **最终包装**：
    -   为你选中的两条路线分别起一个富有诗意或硬核的名字 (`route_name`)。
    -   为每条路线写一段定线员寄语 (`setter_commentary`)，解释它的攀爬风格、特点，以及你为什么选择它。
    -   **关键：** 在 `selections` 列表中，必须包含你选择的那两条路线的 `id`。

请调用 `select_and_package_routes` 工具提交你的最终决定。
"""

async def generate_route_with_reflection(request: RouteRequest) -> RouteResponse:
    """
    核心架构: 实施「带预算配额的密集图寻路」与「大基数择优」
    - 增加实时监控仪表盘与深度失败分析
    """
    
    generator = RouteGenerator()
    solver = AStarSolver(request.climber_height_cm, request.climber_span_cm)
    
    successful_candidates: List[RouteCandidate] = []
    
    # 深度失败分析所需的数据结构
    failure_heights = []
    rule_violations = {}
    low_y_failures = 0

    MAX_ITERATIONS = 200

    for i in range(MAX_ITERATIONS):
        print(f"[进度 {i+1}/{MAX_ITERATIONS}] 正在生成随机点阵并启动 A* 寻路...")
        
        board_holds, inventory_budget = generator.generate_board(request.recipe)
        if not board_holds:
            print(f"❌ 尝试失败。最高爬升高度: Y=0, 失败原因: 生成器无法创建符合条件的板")
            failure_heights.append(0)
            continue

        result, report = solver.solve(board_holds, inventory_budget)
        
        if result:
            print(f"✅ 找到路线! 总代价(Cost): {result.total_cost:.2f}, 岩点数: {len(result.placed_holds)}")
            successful_candidates.append(result)
        else:
            max_y = report.get('max_y', 0)
            reason = report.get('reason', '未知')
            rule = report.get('rule_violation')

            print(f"❌ 尝试失败。最高爬升高度: Y={max_y}, 失败原因: {reason}")
            
            # 统计数据
            failure_heights.append(max_y)
            if rule:
                rule_violations[rule] = rule_violations.get(rule, 0) + 1
            
            # 容错补丁 1: 打印 Board 状态
            from collections import Counter
            hold_counts = Counter(h.hold_type.value for h in board_holds)
            print(f"   BOARD状态: {dict(hold_counts)}")

            # 容错补丁 2: 自动放水逻辑
            if max_y < 10:
                low_y_failures += 1
            if i > 20 and low_y_failures == i:
                 print("   [自动放水逻辑]: 检测到低位高频失败，建议检查起步点生成的坐标逻辑!")

    # 初级筛选
    if not successful_candidates:
        print("\n" + "="*20 + " 深度失败分析报告 " + "="*20)
        
        # 1. 失败高度分布
        y_lt5 = sum(1 for y in failure_heights if y < 5)
        y_5_15 = sum(1 for y in failure_heights if 5 <= y <= 15)
        y_gt15 = sum(1 for y in failure_heights if y > 15)
        print(f"失败高度分布: Y<5: {y_lt5}次 | Y=5~15: {y_5_15}次 | Y>15: {y_gt15}次")

        # 2. 最高频物理规则
        if rule_violations:
            most_common_rule = max(rule_violations, key=rule_violations.get)
            print(f"出现频率最高的物理拦截规则: {most_common_rule} ({rule_violations[most_common_rule]} 次)")
        else:
            print("无特定物理拦截规则，问题可能出在起步区或点阵图生成。")

        print("="*58 + "\n")
        
        suggestion = "所有尝试均失败。请根据以上分析报告调整配方或检查运动学参数。"
        return RouteResponse(selected_routes=[], failure_suggestion=suggestion)

    successful_candidates.sort(key=lambda x: x.total_cost)
    top_candidates = successful_candidates[:5]

    # 4. LLM 艺术总监决选 (Curator)
    custom_http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60.0, connect=15.0))
    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url, http_client=custom_http)

    candidates_meta = [
        {
            "id": f"route_{i}",
            "total_cost": f"{candidate.total_cost:.1f}",
            "crux": candidate.crux_step or "N/A"
        }
        for i, candidate in enumerate(top_candidates)
    ]

    user_content = f"""
用户需求：
- 目标难度：{request.target_difficulty}
- 攀爬者身高/臂展：{request.climber_height_cm}cm / {request.climber_span_cm}cm

候选路线列表：
{json.dumps(candidates_meta, indent=2, ensure_ascii=False)}

请从以上列表中挑选出最佳的两条路线，并为其进行最终点评。
"""

    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        tools=[SELECT_ROUTE_TOOL],
        tool_choice={"type": "function", "function": {"name": "select_and_package_routes"}},
        temperature=0.7
    )

    message = response.choices[0].message
    final_routes = []

    if message.tool_calls:
        tool_call = message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        selections = args.get("selections", [])

        for selection in selections:
            route_id = selection.get("selected_route_id")
            route_index = -1
            if route_id and route_id.startswith("route_"):
                try:
                    route_index = int(route_id.split("_")[1])
                except (ValueError, IndexError):
                    pass
            
            if 0 <= route_index < len(top_candidates):
                candidate = top_candidates[route_index]
                final_routes.append(FinalRoute(
                    route_name=selection.get("route_name", "无名之路"),
                    setter_commentary=selection.get("setter_commentary", ""),
                    placed_holds=candidate.placed_holds,
                    beta_sequence=candidate.beta_sequence
                ))

    # Fallback：如果 LLM 返回数据不足两条，则用 cost 最低的路线补足
    if len(final_routes) < 2:
        print("LLM 返回数据不足两条，使用 cost 最低的路线进行补充。")
        used_indices = []
        if final_routes:
            # 获取已选路线的索引
            # (此步简化，假设 LLM 返回的 ID 格式正确)
            pass
        
        for candidate in top_candidates:
            if len(final_routes) >= 2: break
            # 简单地用 cost 最低的补齐，不去重了
            final_routes.append(FinalRoute(
                route_name=f"备选-{candidate.total_cost:.1f}",
                setter_commentary="由系统自动选出的高性价比备选路线。",
                placed_holds=candidate.placed_holds,
                beta_sequence=candidate.beta_sequence
            ))

    return RouteResponse(selected_routes=final_routes)
