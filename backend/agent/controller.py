
"""
backend/agent/controller.py
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
import httpx
import traceback

# 从 main.py 引入 active_tasks
from core.state import active_tasks

from core.config import settings
from core.models import RouteRequest, RouteResponse, RouteCandidate, HoldType, FinalRoute
from core.generator import RouteGenerator
from core.a_star_solver import AStarSolver
from agent.tools_def import SELECT_ROUTE_TOOL

SYSTEM_PROMPT = """
你现在是「智行通途 (ZXT)」攀岩定线引擎的艺术总监 (Curator)。
你的任务是从一个候选项列表中（最多5条）挑选出最优秀、最有趣的 **两条** 路线，同时必须严格参考用户的特殊需求。

# 用户特殊需求
你必须在评估时优先考虑用户的特殊需求，例如：“我想要多一点动态飞跃 (dyno) 的动作”，或者“我是新手，希望路线友好一些，大点多一些”。

# 路线数据说明：
- `id`: 每条路线的唯一标识符，如 "route_0"。
- `total_cost`: A* 算法计算的体力/技巧总消耗。越低代表越容易爬。
- `crux`: 路线中最难的一个动作描述。

# 你的工作：
1.  **综合评估**：仔细评估列表中的每一条候选路线，不仅仅是看 `total_cost`，还要结合用户的`special_requirements`，分析路线风格是否匹配。
2.  **选择最佳两条**：挑选出你认为最符合用户需求、最具创意或攀爬体验最佳的两条路线。
3.  **最终包装**：
    -   为你选中的两条路线分别起一个富有诗意或硬核的名字 (`route_name`)。
    -   为每条路线写一段定线员寄语 (`setter_commentary`)，解释它的攀爬风格、特点，以及你为什么选择它。
    -   **至关重要：** 在 `setter_commentary` 中，你必须明确回应用户的特殊需求，解释这条路线是如何满足这些需求的。
    -   在 `selections` 列表中，必须包含你选择的那两条路线 of `id`。

请调用 `select_and_package_routes` 工具提交你的最终决定。
"""

async def generate_route_with_reflection(request: RouteRequest, task_id: str) -> RouteResponse:
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

    try:
        # 寻找成功的样本，直到收集到足够的样本或达到最大尝试次数
        target_success_count = 3  # 我们尝试收集至少 3 条成功路线来进行筛选
        for i in range(MAX_ITERATIONS):
            if len(successful_candidates) >= target_success_count:
                break

            print(f"[进度 {i+1}/{MAX_ITERATIONS}] 正在生成样本 (已成功: {len(successful_candidates)})")
            
            board_holds, inventory_budget = await asyncio.to_thread(generator.generate_board, request.recipe, request.target_difficulty)
            if not board_holds:
                failure_heights.append(0)
                continue

            result, report = await asyncio.to_thread(solver.solve, board_holds, inventory_budget)
            
            if result and report.get('reason') == "成功":
                successful_candidates.append(result)
                print(f"✅ 找到成功路线! Flow: {result.flow_score:.2f}, Holds: {len(result.placed_holds)}")
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

            await asyncio.sleep(0)
    except asyncio.CancelledError:
        print("❌ 生成任务被用户取消。")
        return RouteResponse(selected_routes=[], failure_suggestion="生成任务已被取消。")

    # 如果没有找到任何成功的候选路线，进行失败分析并返回
    if not successful_candidates:
        suggestion = "所有尝试均失败。请根据以上分析报告调整配方或检查运动学参数。"
        return RouteResponse(selected_routes=[], failure_suggestion=suggestion)

    # 策略筛选机制
    # 路线 ① (Max Capacity): 数量最多的路线
    max_capacity_candidate = max(successful_candidates, key=lambda c: len(c.placed_holds))
    # 路线 ② (Elite Flow): 分数最高的路线
    elite_flow_candidate = max(successful_candidates, key=lambda c: c.flow_score)

    selected_candidates = [
        {"type": "Max Capacity", "data": max_capacity_candidate, "name": "满负载专家", "comment": "这条路线最大化地利用了你的配方岩点，路径曲折且充满挑战。"},
        {"type": "Elite Flow", "data": elite_flow_candidate, "name": "精英流向", "comment": "系统筛选出的物理效率最高的路径，动作衔接丝滑顺畅。"}
    ]

    final_routes = []
    for selection in selected_candidates:
        c = selection["data"]
        # 确保只包含 sequence 中用到的点
        used_ids = {step.hold_id for step in c.beta_sequence}
        final_holds = [h for h in c.placed_holds if h.id in used_ids]
        
        final_routes.append(FinalRoute(
            route_name=selection["name"],
            setter_commentary=selection["comment"],
            placed_holds=final_holds,
            beta_sequence=c.beta_sequence
        ))

    result_response = RouteResponse(selected_routes=final_routes)

    # 打印调试信息：确认后端发出的 JSON 里确实有右脚数据
    if result_response.selected_routes:
        sample_route = result_response.selected_routes[0]
        if sample_route.beta_sequence:
            print(f"Sample RF path: {sample_route.beta_sequence[0].rf}")
    
    # 解决 404 与结果丢失 (System Level)
    # 结果持久化：一旦寻路成功，立即通过 asyncio.create_task 将结果写入 active_tasks，并设置 status="SUCCESS"
    async def persist_result():
        active_tasks[task_id] = {"status": "SUCCESS", "result": result_response}
        print(f"[Task ID: {task_id}] 结果已通过异步任务持久化")

    asyncio.create_task(persist_result())
    
    # 为了防止 main.py 中的 race condition (在 persist_result 运行前检查状态)，
    # 我们在这里也直接同步设置一次，双重保险
    active_tasks[task_id] = {"status": "SUCCESS", "result": result_response}

    return result_response
