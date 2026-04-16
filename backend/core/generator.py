
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

    def _generate_path_template(self) -> List[Tuple[int, int]]:
        """生成路径模板 (锚点)，决定路线风格。"""
        template_style = random.choice(["z_shaped", "traverse_right", "traverse_left", "straightish"])
        
        start_x = random.randint(1, self.GRID_WIDTH - 2)
        end_x = random.randint(1, self.GRID_WIDTH - 2)
        
        path = [(start_x, random.randint(3, 5))]

        if template_style == "z_shaped":
            path.append((random.randint(0, 4), random.randint(7, 9)))
            path.append((random.randint(6, 10), random.randint(11, 13)))
        elif template_style == "traverse_right":
            path.append((start_x + random.randint(2, 4), random.randint(8, 10)))
            path.append((start_x + random.randint(4, 6), random.randint(12, 14)))
        elif template_style == "traverse_left":
            path.append((start_x - random.randint(2, 4), random.randint(8, 10)))
            path.append((start_x - random.randint(4, 6), random.randint(12, 14)))
        else: # straightish
            path.append((start_x + random.randint(-2, 2), random.randint(9, 11)))

        path.append((end_x, random.randint(17, 18)))
        
        # 保证 X 坐标在界内
        return [(max(0, min(x, self.GRID_WIDTH - 1)), y) for x, y in path]

    def _generate_single_route(self, recipe: Dict[HoldType, int]) -> List[Hold]:
        """V2: 遵循路径模板的岩点生成逻辑"""
        
        path_anchors = self._generate_path_template()
        
        target_coords = []
        # 1. 起步区
        start_anchor_x, start_anchor_y = path_anchors[0]
        target_coords.append((self.X_LABELS[start_anchor_x], start_anchor_y))
        target_coords.append((self.X_LABELS[min(self.GRID_WIDTH - 1, start_anchor_x + 1)], start_anchor_y + random.randint(-1,1)))
        target_coords.append((self.X_LABELS[start_anchor_x], random.randint(1, 2))) # 脚点

        # 2. 中间点: 在锚点附近撒点
        total_holds = sum(recipe.values())
        mid_holds_needed = total_holds - 4 # 减去起步和结束点

        for i in range(len(path_anchors) - 1):
            p1 = path_anchors[i]
            p2 = path_anchors[i+1]
            
            # 在两个锚点之间插值生成点
            num_points_between = mid_holds_needed // (len(path_anchors) - 1)
            for j in range(1, num_points_between + 1):
                ratio = j / (num_points_between + 1)
                interp_x = int(p1[0] + (p2[0] - p1[0]) * ratio)
                interp_y = int(p1[1] + (p2[1] - p1[1]) * ratio)
                
                # 增加随机扰动
                rand_x = interp_x + random.randint(-1, 1)
                rand_y = interp_y + random.randint(-1, 1)
                
                # 保证坐标合法
                final_x = self.X_LABELS[max(0, min(rand_x, self.GRID_WIDTH - 1))]
                final_y = max(1, min(rand_y, self.GRID_HEIGHT))
                target_coords.append((final_x, final_y))
                
        # 3. 完攀点
        top_anchor_x, top_anchor_y = path_anchors[-1]
        target_coords.append((self.X_LABELS[top_anchor_x], top_anchor_y))

        # 去重
        unique_coords = list(set(target_coords))
        random.shuffle(unique_coords)

        # 按照 recipe 分配类型，但优先保证 Foot 类型给脚点，其他类型分配给手点
        # 注意：这里的分配逻辑较为简化，实际 A* 会重新检查 Limb 是否匹配
        hold_types_pool = []
        for h_type, count in recipe.items():
            hold_types_pool.extend([h_type] * count)
        
        random.shuffle(hold_types_pool)

        for i, (x, y) in enumerate(unique_coords):
            if i >= len(hold_types_pool): break
            hold_id = f"{x}{y}"
            new_hold = Hold(
                id=hold_id,
                x=x,
                y=y,
                hold_type=hold_types_pool[i],
                rotation=random.randint(0, 359)
            )
            placed_holds.append(new_hold)
        
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
