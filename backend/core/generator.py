
"""
backend/core/generator.py
"""

import random
from typing import List, Dict, Tuple
from collections import Counter
from core.models import Hold, HoldType, RecipeItem

class RouteGenerator:
    """
    基于配方生成高密度候选点阵图 (Board)。
    """
    def __init__(self):
        self.GRID_WIDTH = 11  # A-K
        self.GRID_HEIGHT = 18 # 1-18
        self.X_LABELS = [chr(ord('A') + i) for i in range(self.GRID_WIDTH)]

    def generate_board(self, recipe: Dict[HoldType, RecipeItem], target_difficulty: str) -> Tuple[List[Hold], Dict[HoldType, int]]:
        """
        核心方法：生成一个远大于实际需求的“候选点阵图 (Board)”。
        返回 (点阵图, 剩余预算)
        """
        max_retries = 20
        for _ in range(max_retries):
            board_holds = []
            inventory_budget = {ht: item.count for ht, item in recipe.items()}

            # 预先为完攀点扣除一个 JUG 配额
            inventory_budget[HoldType.JUG] = inventory_budget.get(HoldType.JUG, 0) - 1
            
            # 第一步：生成起步点
            start_mode = random.choice([1, 2, 3])
            if start_mode in [1, 2] and inventory_budget.get(HoldType.JUG, 0) < 2:
                start_mode = 3

            start_holds = self._generate_start_anchors(start_mode, inventory_budget, recipe)
            for hold in start_holds:
                board_holds.append(hold)
                inventory_budget[hold.hold_type] -= 1
            
            # 第二步：基于起步点计算重心走廊
            sum_x = sum(self.X_LABELS.index(h.x) for h in start_holds)
            count = len(start_holds)
            center_x = int(round(sum_x / count)) if count > 0 else self.GRID_WIDTH // 2

            difficulty_offset = 2  # Default for V0
            if target_difficulty == "V1":
                difficulty_offset = 3
            elif target_difficulty == "V2":
                difficulty_offset = 4
            
            left_bound = max(0, center_x - difficulty_offset)
            right_bound = min(self.GRID_WIDTH - 1, center_x + difficulty_offset)
            
            print(f"[走廊锁定] 中心点: {self.X_LABELS[center_x]}, 有效列范围: {self.X_LABELS[left_bound]} 到 {self.X_LABELS[right_bound]}")

            # 第三步：在走廊内生成完攀点
            finish_x_idx = random.randint(left_bound, right_bound)
            finish_x = self.X_LABELS[finish_x_idx]
            finish_variant = recipe.get(HoldType.JUG, RecipeItem(count=0, variant='random')).variant
            finish_hold = Hold(
                id=f"{finish_x}{self.GRID_HEIGHT}", x=finish_x, y=self.GRID_HEIGHT,
                hold_type=HoldType.JUG, rotation=0, 
                variant=finish_variant if finish_variant != 'random' else 'default' 
            )
            board_holds.append(finish_hold)

            # 第四步：在走廊内撒点
            scatter_holds = self._proportional_scattering(inventory_budget, 5, recipe, left_bound, right_bound)
            board_holds.extend(scatter_holds)

            if self._is_vertically_coherent(board_holds):
                for hold_type in inventory_budget:
                    inventory_budget[hold_type] = max(0, inventory_budget[hold_type])
                return board_holds, inventory_budget
        
        # 如果重试后仍然失败，返回一个空的结果或抛出异常
        # print("警告: 无法生成符合垂直连续性要求的岩点布局。")
        return [], {}

    def _generate_start_anchors(self, mode: int, budget: Dict[HoldType, int], recipe: Dict[HoldType, RecipeItem]) -> List[Hold]:
        """根据3种模式生成底部姿态"""
        holds = []
        occupied_coords = set()
        
        def get_unique_coord(y_range, x_range=(0, self.GRID_WIDTH - 1)):
            for _ in range(50): # 尝试50次
                x = self.X_LABELS[random.randint(*x_range)]
                y = random.randint(*y_range)
                if (x, y) not in occupied_coords:
                    occupied_coords.add((x, y))
                    return x, y
            # 如果50次都失败，返回一个随机坐标（可能重复，但不应发生）
            return self.X_LABELS[random.randint(*x_range)], random.randint(*y_range)

        if mode == 1: # 双手同点
            variant_jug = recipe.get(HoldType.JUG, RecipeItem(count=0, variant='default')).variant
            variant_foot = recipe.get(HoldType.FOOT, RecipeItem(count=0, variant='default')).variant
            
            hx, hy = get_unique_coord((3, 4))
            holds.append(Hold(id=f"{hx}{hy}", x=hx, y=hy, hold_type=HoldType.JUG, is_start=True, variant=variant_jug if variant_jug != 'random' else 'default'))
            
            fx1, fy1 = get_unique_coord((1, 2), (0, 4))
            holds.append(Hold(id=f"{fx1}{fy1}", x=fx1, y=fy1, hold_type=HoldType.FOOT, is_start=True, variant=variant_foot if variant_foot != 'random' else 'default'))
            
            fx2, fy2 = get_unique_coord((1, 2), (6, 10))
            holds.append(Hold(id=f"{fx2}{fy2}", x=fx2, y=fy2, hold_type=HoldType.FOOT, is_start=True, variant=variant_foot if variant_foot != 'random' else 'default'))

        elif mode == 2: # 双脚同点
            variant_jug = recipe.get(HoldType.JUG, RecipeItem(count=0, variant='default')).variant
            variant_foot = recipe.get(HoldType.FOOT, RecipeItem(count=0, variant='default')).variant

            hx1, hy1 = get_unique_coord((3, 4), (0, 4))
            holds.append(Hold(id=f"{hx1}{hy1}", x=hx1, y=hy1, hold_type=HoldType.JUG, is_start=True, variant=variant_jug if variant_jug != 'random' else 'default'))
            
            hx2, hy2 = get_unique_coord((3, 4), (6, 10))
            holds.append(Hold(id=f"{hx2}{hy2}", x=hx2, y=hy2, hold_type=HoldType.JUG, is_start=True, variant=variant_jug if variant_jug != 'random' else 'default'))
            
            fx, fy = get_unique_coord((1, 2))
            holds.append(Hold(id=f"{fx}{fy}", x=fx, y=fy, hold_type=HoldType.FOOT, is_start=True, variant=variant_foot if variant_foot != 'random' else 'default'))

        else: # 模式 3 (四点独立)
            available_hand_types = [ht for ht, count in budget.items() if ht not in [HoldType.JUG, HoldType.FOOT] and count > 0]

            if not available_hand_types:
                hand_type_1, hand_type_2 = HoldType.CRIMP, HoldType.CRIMP
            elif len(available_hand_types) == 1:
                hand_type_1 = hand_type_2 = available_hand_types[0]
            else:
                hand_type_1, hand_type_2 = random.sample(available_hand_types, 2)

            variant1 = recipe.get(hand_type_1, RecipeItem(count=0, variant='default')).variant
            variant2 = recipe.get(hand_type_2, RecipeItem(count=0, variant='default')).variant
            variant_foot = recipe.get(HoldType.FOOT, RecipeItem(count=0, variant='default')).variant

            hx1, hy1 = get_unique_coord((3, 4), (0, 4))
            holds.append(Hold(id=f"{hx1}{hy1}", x=hx1, y=hy1, hold_type=hand_type_1, is_start=True, variant=variant1 if variant1 != 'random' else 'default'))

            hx2, hy2 = get_unique_coord((3, 4), (6, 10))
            holds.append(Hold(id=f"{hx2}{hy2}", x=hx2, y=hy2, hold_type=hand_type_2, is_start=True, variant=variant2 if variant2 != 'random' else 'default'))

            fx1, fy1 = get_unique_coord((1, 2), (0, 4))
            holds.append(Hold(id=f"{fx1}{fy1}", x=fx1, y=fy1, hold_type=HoldType.FOOT, is_start=True, variant=variant_foot if variant_foot != 'random' else 'default'))

            fx2, fy2 = get_unique_coord((1, 2), (6, 10))
            holds.append(Hold(id=f"{fx2}{fy2}", x=fx2, y=fy2, hold_type=HoldType.FOOT, is_start=True, variant=variant_foot if variant_foot != 'random' else 'default'))
        
        return holds

    def _is_vertically_coherent(self, holds: List[Hold], segment_height: int = 3, min_holds_per_segment: int = 2) -> bool:
        """检查点阵图在垂直方向上是否连续，避免出现大的空白区域。"""
        # 我们只关心 Y 轴 5 到 17 的中间区域
        y_coords = sorted([h.y for h in holds if 5 <= h.y < self.GRID_HEIGHT])
        if not y_coords:
            return True # 如果没有岩点，就没所谓断层

        min_y, max_y = 5, self.GRID_HEIGHT -1
        
        # 从低到高扫描
        for y_start in range(min_y, max_y - segment_height + 2):
            y_end = y_start + segment_height - 1
            
            # 统计当前 Y 轴段内的岩点数量
            count = sum(1 for y in y_coords if y_start <= y <= y_end)
            
            if count < min_holds_per_segment:
                # print(f"垂直性检查失败: Y 轴 {y_start}-{y_end} 段只有 {count} 个岩点。")
                return False
        return True


    def _proportional_scattering(self, budget: Dict[HoldType, int], multiplier: int, recipe: Dict[HoldType, RecipeItem], left_bound: int, right_bound: int) -> List[Hold]:
        """按配额比例在中间区域撒点"""
        
        total_holds_to_scatter = sum(budget.values()) * multiplier
        if total_holds_to_scatter <= 0:
            return []

        # 计算比例
        total_budget = sum(budget.values())
        proportions = {ht: count / total_budget for ht, count in budget.items() if count > 0}

        # 生成待放置的岩点清单，附带变体信息
        scatter_list = []
        for hold_type, prop in proportions.items():
            count = round(total_holds_to_scatter * prop)
            variant = recipe.get(hold_type, RecipeItem(count=0, variant='default')).variant
            scatter_list.extend([(hold_type, variant)] * count)
        
        random.shuffle(scatter_list)

        # 在岩板中间区域撒点 (Y in [5, 17])
        placed_holds = []
        
        # 获取所有可能的坐标点并随机打乱
        available_coords = []
        for y in range(5, self.GRID_HEIGHT):
            for x_idx in range(left_bound, right_bound + 1):
                available_coords.append((self.X_LABELS[x_idx], y))
        random.shuffle(available_coords)

        # 放置岩点
        for i, (hold_type, variant) in enumerate(scatter_list):
            if i >= len(available_coords): break # 避免坐标用尽
            
            x, y = available_coords[i]
            placed_holds.append(Hold(
                id=f"{x}{y}", x=x, y=y,
                hold_type=hold_type,
                rotation=random.randint(0, 359),
                variant=variant if variant != 'random' else 'default'
            ))
            
        return placed_holds
