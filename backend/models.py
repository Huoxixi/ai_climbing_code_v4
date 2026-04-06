# backend/models.py
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

# ==========================================
# 🧗‍♂️ 1. 物理枚举常量字典 (The Physics Lexicon)
# ==========================================
class HoldType(str, Enum):
    """岩点形态分类：决定了抓握难度和发力方式"""
    JUG = "Jug"       # 大把手：最好抓，新手友好 (V0-V2 主力) -> 视觉：大圆、粗光圈
    CRIMP = "Crimp"   # 小抠口：需要指力，边缘锋利 (V3+ 常见) -> 视觉：小圆、虚线边
    SLOPER = "Sloper" # 大斜面：无明显抓握点，全靠摩擦力和重心 -> 视觉：大范围半透明模糊圆
    PINCH = "Pinch"   # 捏点：需要大拇指对位发力捏住 -> 视觉：醒目的厚实光圈
    POCKET = "Pocket" # 指洞：只能塞进一根或两根手指
    FOOT = "Foot"     # 纯脚点：极小，绝对无法用手抓握 -> 视觉：极小的点

class UsageType(str, Enum):
    """可用性标签：打破死板的手脚分类"""
    HAND = "hand"
    FOOT = "foot"

class Limb(str, Enum):
    """四肢定义"""
    LH = "LH" # 左手 (Left Hand)
    RH = "RH" # 右手 (Right Hand)
    LF = "LF" # 左脚 (Left Foot)
    RF = "RF" # 右脚 (Right Foot)

# ==========================================
# 🧱 2. 数字岩板核心实体 (The Virtual Wall)
# ==========================================
class Hold(BaseModel):
    """单格岩点物理模型"""
    id: str = Field(..., description="唯一网格坐标，严格格式：横轴A-K + 纵轴1-18，如 'C5', 'K18'")
    x: str = Field(..., description="横轴：A到K")
    y: int = Field(..., description="纵轴：1到18")
    hold_type: HoldType = Field(..., description="岩点形态")
    usable_as: List[UsageType] = Field(..., description="可用性：['hand', 'foot'] 或仅 ['foot']")
    rotation: int = Field(0, description="安装角度 (0-360)。0为正朝上，180为倒扣(Undercling)")
    
    # --- 新增：用于前端视觉渲染与 A* 物理计算的扩展字段 ---
    shape_variant: str = Field("default.png", description="映射的图片文件名或形状编号 (如 jug_01.png)")
    scale: float = Field(1.0, description="图片缩放比例，结合原图尺寸确定前端实际渲染大小")
    base_score: float = Field(5.0, description="基础得分(1-10分)，分数越高代表越好抓/耗能越低")

# ==========================================
# 📡 3. 客户端请求与响应契约 (API Contracts)
# ==========================================
class ClimberProfile(BaseModel):
    """攀岩者数字孪生体征"""
    height_cm: int = Field(..., description="身高 (厘米)，影响垂直触达极限")
    span_cm: int = Field(..., description="臂展 (厘米)，影响横向与对角线触达极限")

class RouteRequest(BaseModel):
    """AI 定线请求包"""
    climber: ClimberProfile
    target_difficulty: str = Field(..., description="目标难度 (如 V1, V3, V5)")
    
    # --- 新增：攀岩风格偏好，方便大模型和 A* 调整权重 ---
    preferred_style: Optional[str] = Field("balanced", description="偏好风格：dynamic(动态), static(静态), balanced(均衡)")

class BetaStep(BaseModel):
    """单步动作拆解模型 (包含严格的状态机设定)"""
    step: int = Field(..., description="步骤序号。0 代表起步姿态，1 及以上代表移动步骤")
    limb: Limb = Field(..., description="当前移动或受力的肢体")
    hold_id: str = Field(..., description="目标岩点的网格坐标，如 'C5'")
    intent: str = Field(..., description="AI 的物理思考：为什么要选这个点？发力方式是什么？")
    is_top: bool = Field(False, description="是否为完攀(Top)。必须双手Match在最高点才为True")

class RouteResponse(BaseModel):
    """AI 定线结果响应包"""
    route_name: str = Field(..., description="AI 为这条路线起的炫酷名字")
    status: str = Field("success")
    target_difficulty: str = Field("V1", description="AI 降维匹配后的 V 难度") 
    
    # --- 新增：为了方便前端一键高亮路线，以及记录 A* 的评分 ---
    total_score: float = Field(0.0, description="系统对该路线的总评分 (结合难度、流畅度)")
    route_holds: List[str] = Field(..., description="该路线包含的所有岩点 ID 列表 (如 ['C5', 'F5', 'G9'])")
    
    beta_sequence: List[BetaStep] = Field(..., description="动作解析时间轴")