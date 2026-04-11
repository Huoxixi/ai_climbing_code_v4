
"""
backend/core/generator.py
"""

import random
from typing import List, Dict, Tuple
from core.models import Hold, HoldType
from core.validator import PhysicsValidator

class RouteGenerator:
    """
    批量生成并通过初筛的路线生成器。
    """
    def __init__(self):
        self.GRID_WIDTH = 11  # A-K
        self.GRID_HEIGHT = 18 # 1-18
        self.X_LABELS = [chr(ord('A') + i) for i in range(self.GRID_WIDTH)]
        self.Y_LABELS = list(range(1, self.GRID_HEIGHT + 1))
        self.validator = PhysicsValidator()

    def _generate_single_route(self, recipe: Dict[HoldType, int]) -> List[Hold]:
        """
        根据配方随机生成单条路线。
        """
        placed_holds: List[Hold] = []
        
        # 获取所有可能的坐标点
        all_coords = [(x, y) for x in self.X_LABELS for y in self.Y_LABELS]
        
        # 检查配方中的岩点总数是否超过了总孔位数
        total_holds_in_recipe = sum(recipe.values())
        if total_holds_in_recipe > len(all_coords):
            raise ValueError("配方中的岩点总数超过了墙上的总孔位数。")

        # 随机抽取不重复的坐标点
        try:
            sampled_coords = random.sample(all_coords, total_holds_in_recipe)
        except ValueError:
             # 这段代码理论上在上面的检查后不会被触发，但作为安全措施保留
            return []

        coord_idx = 0
        for hold_type, count in recipe.items():
            for _ in range(count):
                if coord_idx < len(sampled_coords):
                    x, y = sampled_coords[coord_idx]
                    hold_id = f"{x}{y}"
                    rotation = random.randint(0, 359)
                    
                    new_hold = Hold(
                        id=hold_id,
                        x=x,
                        y=y,
                        hold_type=hold_type,
                        rotation=rotation
                    )
                    placed_holds.append(new_hold)
                    coord_idx += 1
        
        return placed_holds

    def generate_batch_routes(self, recipe: Dict[HoldType, int], batch_size: int = 1000) -> List[List[Hold]]:
        """
        根据传入的 recipe (各类型岩点数量)，在 11x18 矩阵中随机生成坐标，
        并调用 validator.validate_baseline 进行过滤，直到收集满一定数量的合法候选路线。
        """
        valid_routes: List[List[Hold]] = []
        attempts = 0
        max_attempts = batch_size * 20  # 设置一个上限，防止因配方过于奇葩导致死循环

        while len(valid_routes) < batch_size and attempts < max_attempts:
            attempts += 1
            candidate_holds = self._generate_single_route(recipe)
            
            if not candidate_holds: continue

            is_valid, _ = self.validator.validate_baseline(candidate_holds)
            
            if is_valid:
                valid_routes.append(candidate_holds)
        
        if len(valid_routes) < batch_size:
            print(f"警告: 尝试了 {max_attempts} 次后，仅生成了 {len(valid_routes)}/{batch_size} 条合法路线。可能配方过于严苛。")

        return valid_routes
