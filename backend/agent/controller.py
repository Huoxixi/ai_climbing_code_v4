"""
Legacy recipe-based generation path.

The redesigned AI Lab uses agent.experiments for board-based compose/review modes.
This module remains as a compatibility adapter for old RouteRequest payloads.
"""

import asyncio
from typing import Dict, List, Set

from core.a_star_solver import AStarSolver
from core.generator import RouteGenerator
from core.models import FinalRoute, RouteCandidate, RouteRequest, RouteResponse
from core.validator import PhysicsValidator


async def generate_route_with_reflection(request: RouteRequest, task_id: str | None = None) -> RouteResponse:
    generator = RouteGenerator()
    solver = AStarSolver(request.climber_height_cm, request.climber_span_cm)
    validator = PhysicsValidator()
    successful_candidates: List[RouteCandidate] = []

    max_iterations = 200
    target_success_count = 3

    for _ in range(max_iterations):
        if len(successful_candidates) >= target_success_count:
            break

        board_holds, inventory_budget = await asyncio.to_thread(
            generator.generate_board,
            request.recipe,
            request.target_difficulty,
            request.hold_pool,
        )
        if not board_holds:
            await asyncio.sleep(0)
            continue

        candidate, report = await asyncio.to_thread(solver.solve, board_holds, inventory_budget)
        if candidate:
            balanced, _ = validator.validate_beta_balance(candidate.beta_sequence, board_holds)
            if balanced:
                successful_candidates.append(candidate)

        await asyncio.sleep(0)

    if not successful_candidates:
        return RouteResponse(
            selected_routes=[],
            failure_suggestion="所有尝试均失败。请调整岩点配方、难度或检查当前运动学参数。",
        )

    def candidate_hold_set(candidate: RouteCandidate) -> Set[str]:
        sequence_ids = {step.hold_id for step in candidate.beta_sequence}
        return sequence_ids or {hold.id for hold in candidate.placed_holds}

    def candidate_signature(candidate: RouteCandidate) -> str:
        return "|".join(sorted(candidate_hold_set(candidate)))

    def jaccard_overlap(left: Set[str], right: Set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 1.0

    dedup_candidates: Dict[str, RouteCandidate] = {}
    for candidate in successful_candidates:
        signature = candidate_signature(candidate)
        existing = dedup_candidates.get(signature)
        if not existing or (candidate.flow_score, len(candidate.placed_holds)) > (
            existing.flow_score,
            len(existing.placed_holds),
        ):
            dedup_candidates[signature] = candidate

    unique_candidates = list(dedup_candidates.values())
    primary = max(unique_candidates, key=lambda c: (len(c.placed_holds), c.flow_score))
    selected = [
        (
            primary,
            "满负载专家",
            "这条路线最大化利用了配方岩点，路径完整且有明确完攀动作。",
        )
    ]

    primary_set = candidate_hold_set(primary)
    diverse_pool = [
        (jaccard_overlap(primary_set, candidate_hold_set(candidate)), candidate)
        for candidate in unique_candidates
        if candidate is not primary
    ]
    diverse_pool = [item for item in diverse_pool if item[0] <= 0.85]
    if diverse_pool:
        diverse = max(diverse_pool, key=lambda item: (item[1].flow_score, len(item[1].placed_holds), -item[0]))[1]
        selected.append(
            (
                diverse,
                "精英流向",
                "这条路线在保持高流畅度的同时，与第一条路线有不同动作结构。",
            )
        )

    final_routes: List[FinalRoute] = []
    for candidate, name, comment in selected:
        used_ids = {step.hold_id for step in candidate.beta_sequence}
        final_routes.append(
            FinalRoute(
                route_name=name,
                setter_commentary=comment,
                placed_holds=[hold for hold in candidate.placed_holds if hold.id in used_ids],
                beta_sequence=candidate.beta_sequence,
                difficulty=request.target_difficulty,
            )
        )

    return RouteResponse(selected_routes=final_routes)
