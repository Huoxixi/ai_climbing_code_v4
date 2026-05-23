
"""
backend/core/generator.py
"""

import random
from typing import List, Dict, Tuple, Set, Optional
from collections import Counter
from core.board_spec import DEFAULT_BOARD_SPEC
from core.models import Hold, HoldType, RecipeItem, HoldSpec

class RouteGenerator:
    """
    基于配方生成高密度候选点阵图 (Board)。
    """
    def __init__(self):
        self.board_spec = DEFAULT_BOARD_SPEC
        self.GRID_WIDTH = self.board_spec.columns
        self.GRID_HEIGHT = self.board_spec.rows
        self.X_LABELS = self.board_spec.x_labels

    def _build_hold_spec_buckets(self, hold_pool: List[HoldSpec]) -> Dict[HoldType, List[HoldSpec]]:
        """按类型分组实例池，便于后续按类型顺序消费"""
        buckets: Dict[HoldType, List[HoldSpec]] = {}
        for spec in hold_pool:
            buckets.setdefault(spec.hold_type, []).append(spec)
        return buckets

    def _resolve_hold_config(
        self,
        hold_type: HoldType,
        recipe: Dict[HoldType, RecipeItem],
        hold_spec_buckets: Dict[HoldType, List[HoldSpec]],
        default_rotation: Optional[int] = None,
        default_scale: float = 1.0
    ) -> Tuple[str, int, float]:
        """
        优先消费实例池中的 variant/rotation/scale。
        若实例池不足则回退到 recipe + 旧默认逻辑。
        """
        recipe_variant = recipe.get(hold_type, RecipeItem(count=0, variant='default')).variant
        fallback_variant = recipe_variant if recipe_variant != 'random' else 'default'

        specs = hold_spec_buckets.get(hold_type, [])
        if specs:
            spec = specs.pop(0)
            chosen_variant = spec.variant if spec.variant != 'random' else fallback_variant
            rotation = int(spec.rotation) % 360
            scale = max(0.5, min(2.0, float(spec.scale)))
            return chosen_variant, rotation, scale

        rotation = random.randint(0, 359) if default_rotation is None else (default_rotation % 360)
        return fallback_variant, rotation, default_scale

    def generate_board(
        self,
        recipe: Dict[HoldType, RecipeItem],
        target_difficulty: str,
        hold_pool: Optional[List[HoldSpec]] = None
    ) -> Tuple[List[Hold], Dict[HoldType, int]]:
        """
        核心方法：生成一个远大于实际需求的“候选点阵图 (Board)”。
        返回 (点阵图, 剩余预算)
        """
        max_retries = 20
        for _ in range(max_retries):
            board_holds = []
            inventory_budget = {ht: item.count for ht, item in recipe.items()}
            hold_spec_buckets = self._build_hold_spec_buckets(hold_pool or [])

            # 预先为完攀点扣除一个 JUG 配额
            inventory_budget[HoldType.JUG] = inventory_budget.get(HoldType.JUG, 0) - 1
            
            # 第一步：生成起步点
            # 共有 5 种起步模式
            start_mode = random.choice([1, 2, 3, 4, 5])

            start_holds = self._generate_start_anchors(start_mode, inventory_budget, recipe, hold_spec_buckets)
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
            finish_variant, finish_rotation, finish_scale = self._resolve_hold_config(
                HoldType.JUG,
                recipe,
                hold_spec_buckets,
                default_rotation=0,
                default_scale=1.0
            )
            finish_hold = Hold(
                id=f"{finish_x}{self.GRID_HEIGHT}", x=finish_x, y=self.GRID_HEIGHT,
                hold_type=HoldType.JUG,
                rotation=finish_rotation,
                scale=finish_scale,
                variant=finish_variant
            )
            board_holds.append(finish_hold)

            # 第四步：在走廊内撒点
            start_hold_ids = {h.id for h in start_holds}
            scatter_holds = self._proportional_scattering(
                inventory_budget,
                5,
                recipe,
                left_bound,
                right_bound,
                start_hold_ids,
                hold_spec_buckets
            )
            board_holds.extend(scatter_holds)

            if self._is_vertically_coherent(board_holds):
                # 返回原始配额，让 Solver 统一处理扣除逻辑
                original_budget = {ht: item.count for ht, item in recipe.items()}
                return board_holds, original_budget
        
        # 如果重试后仍然失败，返回一个空的结果或抛出异常
        # print("警告: 无法生成符合垂直连续性要求的岩点布局。")
        return [], {}

    def _generate_start_anchors(
        self,
        mode: int,
        budget: Dict[HoldType, int],
        recipe: Dict[HoldType, RecipeItem],
        hold_spec_buckets: Dict[HoldType, List[HoldSpec]]
    ) -> List[Hold]:
        """根据5种模式生成确定的起步姿态"""
        holds = []
        
        # 辅助函数：根据预算确定手点类型
        def get_hand_types(count: int) -> List[HoldType]:
            res = []
            temp_budget = {ht: c for ht, c in budget.items()}
            
            for _ in range(count):
                if temp_budget.get(HoldType.JUG, 0) > 0:
                    res.append(HoldType.JUG)
                    temp_budget[HoldType.JUG] -= 1
                else:
                    others = [ht for ht, c in temp_budget.items() if ht != HoldType.FOOT and c > 0]
                    if others:
                        others.sort(key=lambda x: temp_budget[x], reverse=True)
                        chosen = others[0]
                        res.append(chosen)
                        temp_budget[chosen] -= 1
                    else:
                        res.append(HoldType.CRIMP)
            return res

        def build_hold(coord_id: str, x: str, y: int, hold_type: HoldType) -> Hold:
            variant, rotation, scale = self._resolve_hold_config(
                hold_type,
                recipe,
                hold_spec_buckets,
                default_rotation=0,
                default_scale=1.0
            )
            return Hold(
                id=coord_id,
                x=x,
                y=y,
                hold_type=hold_type,
                is_start=True,
                variant=variant,
                rotation=rotation,
                scale=scale
            )

        hand_types = get_hand_types(2)
        foot_type = HoldType.FOOT if budget.get(HoldType.FOOT, 0) > 0 else HoldType.FOOT

        if mode == 1:
            # 模式 1：经典双手同点（稳固张脚）
            ht = hand_types[0]
            holds.append(build_hold("F5", 'F', 5, ht))
            holds.append(build_hold("D2", 'D', 2, foot_type))
            holds.append(build_hold("H2", 'H', 2, foot_type))
        elif mode == 2:
            # 模式 2：经典双脚同点（宽阔展臂）
            ht1, ht2 = hand_types[0], hand_types[1]
            holds.append(build_hold("D5", 'D', 5, ht1))
            holds.append(build_hold("H5", 'H', 5, ht2))
            holds.append(build_hold("F2", 'F', 2, foot_type))
        elif mode == 3:
            # 模式 3：左高右低（不对称动态发力）
            ht1, ht2 = hand_types[0], hand_types[1]
            holds.append(build_hold("E6", 'E', 6, ht1))
            holds.append(build_hold("G5", 'G', 5, ht2))
            holds.append(build_hold("D2", 'D', 2, foot_type))
            holds.append(build_hold("F1", 'F', 1, foot_type))
        elif mode == 4:
            # 模式 4：右高左低（不对称发力）
            ht1, ht2 = hand_types[0], hand_types[1]
            holds.append(build_hold("D5", 'D', 5, ht1))
            holds.append(build_hold("F6", 'F', 6, ht2))
            holds.append(build_hold("E1", 'E', 1, foot_type))
            holds.append(build_hold("G2", 'G', 2, foot_type))
        else:
            # 模式 5：极端宽距（大字型延展）
            ht1, ht2 = hand_types[0], hand_types[1]
            holds.append(build_hold("C5", 'C', 5, ht1))
            holds.append(build_hold("I5", 'I', 5, ht2))
            holds.append(build_hold("B2", 'B', 2, foot_type))
            holds.append(build_hold("J2", 'J', 2, foot_type))

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


    def _proportional_scattering(
        self,
        budget: Dict[HoldType, int],
        multiplier: int,
        recipe: Dict[HoldType, RecipeItem],
        left_bound: int,
        right_bound: int,
        start_hold_ids: Set[str],
        hold_spec_buckets: Dict[HoldType, List[HoldSpec]]
    ) -> List[Hold]:
        """按配额比例在全区域撒点（避开起步层和起步点）"""
        
        total_holds_to_scatter = sum(budget.values()) * multiplier
        if total_holds_to_scatter <= 0:
            return []

        # 计算比例
        total_budget = sum(budget.values())
        proportions = {ht: count / total_budget for ht, count in budget.items() if count > 0}

        # 生成待放置的岩点清单
        scatter_list = []
        for hold_type, prop in proportions.items():
            count = round(total_holds_to_scatter * prop)
            scatter_list.extend([hold_type] * count)
        
        random.shuffle(scatter_list)

        # 在全区域撒点 (Y in [1, 17])
        placed_holds = []
        
        # 获取所有可能的坐标点并随机打乱
        available_coords = []
        avoid_y = {1, 2, 5, 6}
        for y in range(1, self.GRID_HEIGHT):
            if y in avoid_y:
                continue
            for x_idx in range(left_bound, right_bound + 1):
                coord_id = f"{self.X_LABELS[x_idx]}{y}"
                if coord_id not in start_hold_ids:
                    available_coords.append((self.X_LABELS[x_idx], y))
        random.shuffle(available_coords)

        # 放置岩点
        for i, hold_type in enumerate(scatter_list):
            if i >= len(available_coords): break # 避免坐标用尽
            
            x, y = available_coords[i]
            variant, rotation, scale = self._resolve_hold_config(
                hold_type,
                recipe,
                hold_spec_buckets,
                default_rotation=None,
                default_scale=1.0
            )
            placed_holds.append(Hold(
                id=f"{x}{y}", x=x, y=y,
                hold_type=hold_type,
                rotation=rotation,
                scale=scale,
                variant=variant
            ))
            
        return placed_holds
