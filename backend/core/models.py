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
    scale: float = Field(1.0, description="岩点缩放比例")
    is_start: bool = Field(False, description="是否为起步点")
    variant: str = Field("default", description="岩点形状变体")

class BetaStep(BaseModel):
    """单个攀爬动作步骤"""
    step: int = Field(..., description="第几个动作")
    limb: Limb = Field(..., description="使用哪个肢体 (LH, RH, LF, RF)")
    hold_id: str = Field(..., description="目标岩点ID")
    intent: str = Field(..., description="动作意图描述")
    is_top: bool = Field(default=False, description="是否为完攀动作")
    
    # 冗余记录当前所有肢体的位置，方便前端渲染
    lh: Optional[str] = Field(None, description="左手当前岩点ID")
    rh: Optional[str] = Field(None, description="右手当前岩点ID")
    lf: Optional[str] = Field(None, description="左脚当前岩点ID")
    rf: Optional[str] = Field(None, description="右脚当前岩点ID")

class RouteCandidate(BaseModel):
    """初筛后的路线候选模型"""
    placed_holds: List[Hold] = Field(..., description="该路线放置的岩点列表")
    beta_sequence: List[BetaStep] = Field(default_factory=list, description="A* 物理模拟计算出的动作序列")
    total_cost: float = Field(default=0.0, description="A* 算法计算出的总代价")
    flow_score: float = Field(default=0.0, description="路线流畅度评分")
    crux_step: Optional[str] = Field(None, description="关键步骤描述")
    quota_violations: Dict[HoldType, int] = Field(default_factory=dict, description="配额违规详情")

class RecipeItem(BaseModel):
    count: int
    variant: str

class HoldSpec(BaseModel):
    """前端岩点池中的单个岩点实例配置"""
    hold_type: HoldType
    variant: str = "default"
    rotation: int = 0
    scale: float = 1.0

class RouteRequest(BaseModel):
    climber_height_cm: int = Field(..., description="攀爬者身高 (厘米)")
    climber_span_cm: int = Field(..., description="攀爬者臂展 (厘米)")
    target_difficulty: str = Field(..., description="目标难度 (如 V1, V3, V5)")
    special_requirements: str = Field("", description="用户的特殊需求，例如“需要很多侧拉动作”")
    recipe: Dict[HoldType, RecipeItem] = Field(default_factory=dict, description="岩点配方预算 (如 {'Jug': {'count': 4, 'variant': 'random'}})")
    hold_pool: List[HoldSpec] = Field(default_factory=list, description="岩点实例池（保留每个岩点独立的变体/旋转/缩放）")


class FinalRoute(BaseModel):
    """最终呈现给用户的单条路线"""
    saved_id: Optional[str] = Field(None, description="收藏后的唯一ID")
    route_name: str
    setter_commentary: str
    placed_holds: List[Hold]
    beta_sequence: List[BetaStep]


class RenameBoardRequest(BaseModel):
    """收藏岩板重命名请求体"""
    route_name: str = Field(..., description="新的路线名称")

class RouteResponse(BaseModel):
    """AI 定线结果响应包，可能包含多条精选路线"""
    selected_routes: List[FinalRoute] = Field(..., description="经过 AI 精选的路线列表")
    failure_suggestion: Optional[str] = Field(None, description="如果生成失败，给用户的建议")
    task_id: Optional[str] = Field(None, description="用于取消操作的后台任务ID")

class GenerationInitiated(BaseModel):
    task_id: str
