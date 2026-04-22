'''
backend/core/models.py
'''

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class HoldType(str, Enum):
    JUG = "Jug"       # 大把手
    CRIMP = "Crimp"   # 小抠点
    SLOPER = "Sloper" # 斜面点
    PINCH = "Pinch"   # 捏点
    POCKET = "Pocket" # 指洞
    FOOT = "Foot"     # 脚点

class Limb(str, Enum):
    LH = "LH" # 左手
    RH = "RH" # 右手
    LF = "LF" # 左脚
    RF = "RF" # 右脚

class Hold(BaseModel):
    """单格岩点物理模型"""
    id: str = Field(..., description="唯一网格坐标，如 'C5'")
    x: str = Field(..., description="横轴：A到K")
    y: int = Field(..., description="纵轴：1到18")
    hold_type: HoldType = Field(..., description="岩点形态")
    rotation: int = Field(0, description="安装角度 (0-360)")
    is_start: bool = Field(False, description="是否为起步点")
    variant: str = Field("default", description="岩点形状变体")

class BetaStep(BaseModel):
    """单个攀爬动作步骤"""
    step: int = Field(..., description="第几个动作")
    limb: Limb = Field(..., description="使用哪个肢体 (LH, RH, LF, RF)")
    hold_id: str = Field(..., description="目标岩点ID")
    intent: str = Field(..., description="动作意图描述")
    is_top: bool = Field(default=False, description="是否为完攀动作")

class RouteCandidate(BaseModel):
    """初筛后的路线候选模型"""
    placed_holds: List[Hold] = Field(..., description="该路线放置的岩点列表")
    beta_sequence: List[BetaStep] = Field(default_factory=list, description="A* 物理模拟计算出的动作序列")
    total_cost: float = Field(default=0.0, description="A* 算法计算出的总代价")
    flow_score: float = Field(default=0.0, description="路线流畅度评分")
    crux_step: Optional[str] = Field(None, description="关键步骤描述")

class RecipeItem(BaseModel):
    count: int
    variant: str

class RouteRequest(BaseModel):
    climber_height_cm: int = Field(..., description="攀爬者身高 (厘米)")
    climber_span_cm: int = Field(..., description="攀爬者臂展 (厘米)")
    target_difficulty: str = Field(..., description="目标难度 (如 V1, V3, V5)")
    recipe: Dict[HoldType, RecipeItem] = Field(default_factory=dict, description="岩点配方预算 (如 {'Jug': {'count': 4, 'variant': 'random'}})")


class FinalRoute(BaseModel):
    """最终呈现给用户的单条路线"""
    route_name: str
    setter_commentary: str
    placed_holds: List[Hold]
    beta_sequence: List[BetaStep]

class RouteResponse(BaseModel):
    """AI 定线结果响应包，可能包含多条精选路线"""
    selected_routes: List[FinalRoute] = Field(..., description="经过 AI 精选的路线列表")
    failure_suggestion: Optional[str] = Field(None, description="如果生成失败，给用户的建议")
