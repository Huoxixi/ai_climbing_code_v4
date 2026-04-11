import os
import json
import math
import asyncio
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from pydantic import ValidationError
from dotenv import load_dotenv
import httpx

load_dotenv()
# 引入最新 models 中的枚举与模型
from models import Hold, ClimberProfile, RouteResponse

def calculate_real_distance(hold_1: str, hold_2: str) -> float:
    """计算物理岩板上两点之间的真实直线距离 (cm)"""
    if not hold_1 or not hold_2: return 0.0
    x1, y1 = ord(hold_1[0].upper()) - ord('A'), int(hold_1[1:]) - 1
    x2, y2 = ord(hold_2[0].upper()) - ord('A'), int(hold_2[1:]) - 1
    return round(math.sqrt((x2 - x1)**2 + (y2 - y1)**2) * 20, 2)

# ==========================================
# 🚀 缓存优化区 1：全局预加载，消除磁盘 I/O
# ==========================================
def load_and_cache_classic_routes():
    """在服务器启动时，一次性将经典路线题库读入内存"""
    file_path = "classic_routes.json"
    if not os.path.exists(file_path): 
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 题库预加载读取失败 ({e})")
        return []

GLOBAL_ROUTES = load_and_cache_classic_routes()

def get_deterministic_examples(target_difficulty: str) -> str:
    """
    🚀 缓存优化区 2：生成绝对固定的 Few-Shot 字符串。
    消除了原来的 random.choice()，确保相同难度的前缀 100% 相同，从而触发大模型的 Prompt Caching。
    """
    fallback_route = """
    [
      {
        "route_name": "默认参考线 (标准 V1 动态折返)",
        "beta_sequence": [
          {"step": 0, "limb": "LH", "hold_id": "D5", "intent": "", "shape_type": "Jug"},
          {"step": 0, "limb": "RH", "hold_id": "E6", "intent": "", "shape_type": "Jug"},
          {"step": 0, "limb": "LF", "hold_id": "B2", "intent": "", "shape_type": "Foot"},
          {"step": 0, "limb": "RF", "hold_id": "G2", "intent": "", "shape_type": "Foot"},
          {"step": 1, "limb": "LH", "hold_id": "D8", "intent": "左手向左上方抓握侧拉点", "shape_type": "Crimp"},
          {"step": 2, "limb": "RH", "hold_id": "G10", "intent": "右手向右上方跨度转移", "shape_type": "Jug"},
          {"step": 3, "limb": "LF", "hold_id": "D5", "intent": "左脚踩之前左手抓过的起步点", "shape_type": "Jug"},
          {"step": 4, "limb": "LH", "hold_id": "E14", "intent": "左手大跨度发力抓握大把手", "shape_type": "Jug"},
          {"step": 5, "limb": "RF", "hold_id": "G6", "intent": "右脚向上调整重心", "shape_type": "Foot"},
          {"step": 6, "limb": "RH", "hold_id": "F18", "intent": "右手完攀锁定", "is_top": true, "shape_type": "Jug"}
        ]
      }
    ]
    """
    
    if not GLOBAL_ROUTES: return fallback_route
        
    grade_map = {
        "V0": ["6A", "6A+", "6B"],
        "V1": ["6B", "6B+"],
        "V2": ["6B+", "6C"],
        "V3": ["6C", "6C+", "7A"]
    }
    allowed_grades = grade_map.get(target_difficulty, ["6B+"])
    
    # 筛选符合难度的路线
    matching_routes = [r for r in GLOBAL_ROUTES if r.get("original_grade") in allowed_grades]
    
    # 强制按路线名称排序，并截取前 3 条，彻底消除随机性
    matching_routes = sorted(matching_routes, key=lambda x: str(x.get("route_name", "")))[:3]
    
    if not matching_routes: return fallback_route
        
    examples = [{"route_name": r["route_name"], "beta_sequence": r["beta_sequence"]} for r in matching_routes]
    return json.dumps(examples, ensure_ascii=False, indent=2)

# 在内存中固化 4 个难度的 Few-Shot 前缀
CACHED_FEW_SHOTS = {
    "V0": get_deterministic_examples("V0"),
    "V1": get_deterministic_examples("V1"),
    "V2": get_deterministic_examples("V2"),
    "V3": get_deterministic_examples("V3"),
}

# 替换原有的 DIFFICULTY_RULES_MAP
DIFFICULTY_RULES_MAP = {
    "V0": "V0新手：温和横移，X轴跨度3-11列，禁直梯，重心横向流动，手脚自然不交叉。",
    "V1": "V1入门：清晰斜线或折返，X轴跨度4-11列，明确重心转移，右手在右/左手在左。",
    "V2": "V2基础：动态张力，X轴跨度5-11列，含大对角线折返。高频使用“手点转脚点”复用，防双臂交叉。",
    "V3": "V3进阶：极限空间调度，X轴跨度5-11列满宽，夸张大横移或动态爆发，强迫身体折叠，严防交叉打结。"
}

# ==========================================
# 🚀 缓存优化区 3：绝对纯净、不可变的系统基座提示词
# ==========================================
# 替换原有的 BASE_SYSTEM_PROMPT
BASE_SYSTEM_PROMPT = """
# 角色
你是定线大脑，精通11x18矩阵打孔岩板（X轴:A-K对应1-11，Y轴:1-18，每格20cm）的MoonBoard风格定线。仅输出合法JSON。

# 岩点形态物理法则 (Semantic Holds) 🚨
你必须根据岩点的 `shape_type` 规划动作，严禁违背人类生理学：
- Jug (大把手): 极易抓握，允许做大跨度动态、爆发性动作。
- Crimp (小抠口): 极小边缘。仅允许小跨度行进(<=3格)，严禁动态跳跃！
- Sloper (大斜面): 无明显抓握点。极度依赖摩擦力和重心控制。
- Pinch (捏点): 需拇指发力对捏。
- Pocket (指洞): 仅容纳一两根手指。
- Foot (纯脚点): 🚨绝对严禁用手(LH/RH)抓握！仅能分配给脚(LF/RF)！
⚠️ 逻辑一致性：若同一个 hold_id 被复用多次，它的 shape_type 必须保持绝对一致！岩壁上的点不会自动变形。

# 物理与空间强制约束
1. 起步(Step 0)：
   - 包含3至4个独立岩点（如双手+单脚/双脚）。
   - 🚨【起步严格坐标法则】：起步脚点(LF/RF)的 Y 轴【必须且只能】在第 1 到 2 行之间！起步手点(LH/RH)的 Y 轴【必须且只能】在第 3 到 6 行之间！
   - 起步手必须高于起步脚。若双脚均踩点，横向跨度 <= 3列。
2. 完攀：全线仅允许1个 `is_top: true` 的点。最后一步必须是双手Match在Y=17或18。
3. 身体空间(The Box)：
   - 行进中，手点比脚点高3~6格。
   - 任何单一Step中，最高手点Y与最低脚点Y的差值 <= 9（防人体撕裂）。
   - 左右手横向跨度 <= 6列（确保主干紧凑）。
   - 双脚横向跨度 <= 4列。
4. 时序防撞(重点)：严禁手脚同点。若脚需踩原手点，必须先插入一个Step将手移走。
5. 肢体防结：左侧肢体(LH/LF)的X坐标需在右侧肢体(RH/RF)的左侧或同列，严禁双手/双脚交叉劈叉。
6. 拒绝直梯：禁止全线完全在1-2列内直上直下。
7. 岩点复用：全线独立岩点总数严格限制在8-12个。起步和中段(Y=1~14)的脚点必须大量踩踏前序手点坐标，复用率 >= 40%。

# JSON 字段输出规范
`beta_sequence` 数组内每个动作对象必需包含 `intent` 和 `shape_type` 字段：
- step == 0：`intent` 严格留空（即 `""`）。
- step > 0：`intent` 用简短中文描述发力意图（如"向左上方转移重心"）。
- `shape_type`：必须是 Jug, Crimp, Sloper, Pinch, Pocket, Foot 之一。
严禁解释思考过程。
"""

async def generate_route_with_reflection(
    climber: ClimberProfile, 
    holds: List[Hold], 
    target_difficulty: str = "V1", 
    recipe: Optional[Dict[str, int]] = None, # 🌟 接收前端传入的配方
    max_retries: int = 8
) -> RouteResponse:
    """核心定线工作流 (带自动防碰撞反思与缓存优化)"""
    max_stretch_cm = climber.height_cm + (climber.span_cm / 2)

    # ==========================================
    # 🧱 组装阶梯式 Prompt 数组 (专为命中 Caching 设计)
    # ==========================================
    messages = []
    
    # [前缀区块 1] 核心基础物理规则 (所有请求 100% 相同，极易命中缓存)
    messages.append({"role": "system", "content": BASE_SYSTEM_PROMPT})
    
    # 修改 generate_route_with_reflection 内的拼接逻辑：
    
    # [前缀区块 2] 难度专属规则与标杆数据
    specific_rules = DIFFICULTY_RULES_MAP.get(target_difficulty, DIFFICULTY_RULES_MAP["V1"])
    few_shot_data = CACHED_FEW_SHOTS.get(target_difficulty, "[]")
    
    difficulty_system_prompt = f"""
# 难度要求: {target_difficulty}
设计规则: {specific_rules}

# 标杆参考路线
模仿以下路线的横向跨度、流动感及复用逻辑（忽略其中的瑕疵）：
{few_shot_data}
"""
    messages.append({"role": "system", "content": difficulty_system_prompt})
    
    # 🌟 动态处理用户输入的岩点配方，放入动态 User Prompt 区块
    recipe_instruction = ""
    if recipe:
        recipe_str = "\n".join([f"- {k}: {v} 个" for k, v in recipe.items() if v > 0])
        if recipe_str:
            recipe_instruction = f"""
# 🧪 用户专属岩点配方要求 🚨
请你在这条路线中，尽可能利用以下形态及其指定数量的岩点进行组合：
{recipe_str}
(注：若配方数量无法完美连成合法路线，可自行增减少许岩点以保证物理可行性，但优先遵从上述种类。)
"""

    # [动态区块] 用户的真实数据
    user_prompt = f"""
# 攀岩者物理参数
- 身高: {climber.height_cm} cm
- 臂展(横向极限): {climber.span_cm} cm
- 手脚拉伸(高低极限): {max_stretch_cm} cm
{recipe_instruction}
请生成 {target_difficulty} 难度路线。
"""
    messages.append({"role": "user", "content": user_prompt})

    # ==========================================
    # 🔄 Agentic Reflection Loop (反思纠错循环)
    # ==========================================
    for attempt in range(max_retries):
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

        custom_http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60.0, connect=15.0))
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=3, http_client=custom_http)

        try:
            raw_content = ""
            response = await client.chat.completions.create(
                model="gpt-5", # 建议后续在此处实现模型路由（如初稿用小模型，反思用大模型）
                messages=messages,
                temperature=0.38,
                response_format={ "type": "json_object" } 
            )
            
            raw_content = response.choices[0].message.content.strip()
            
            # 清理 Markdown 代码块标记
            if raw_content.startswith("```json"):
                raw_content = raw_content[7:-3].strip()
            elif raw_content.startswith("```"):
                raw_content = raw_content[3:-3].strip()

            parsed_data = json.loads(raw_content)
            parsed_data["target_difficulty"] = target_difficulty
            route_result = RouteResponse(**parsed_data)
            
            # ------------------------------------------
            # 🛑 物理拦截网 1：起步四肢与点数绝对校验
            # ------------------------------------------
            start_moves = [move for move in route_result.beta_sequence if move.step == 0]
            start_holds = set(move.hold_id for move in start_moves)
            start_limbs = set(move.limb for move in start_moves)
            
            if 'LH' not in start_limbs or 'RH' not in start_limbs:
                raise ValueError("起步违规！必须包含左手(LH)和右手(RH)！")
                
            if 'LF' not in start_limbs and 'RF' not in start_limbs:
                raise ValueError("起步违规！双脚不能同时悬空，至少需要一只脚(LF或RF)踩点！")
            
            if not (3 <= len(start_holds) <= 4):
                raise ValueError(f"起步点数量违规！当前使用了 {len(start_holds)} 个起步点。")
            
            # 🌟 核心修正：严格校验 1-2 行与 3-6 行的起步规则
            for move in start_moves:
                y_val = int(move.hold_id[1:])
                if move.limb in ("LF", "RF") and not (1 <= y_val <= 2):
                    raise ValueError(f"起步脚点违规！起步脚点({move.limb}) 必须在第 1-2 行，你目前定在了第 {y_val} 行！")
                if move.limb in ("LH", "RH") and not (3 <= y_val <= 6):
                    raise ValueError(f"起步手点违规！起步手点({move.limb}) 必须在第 3-6 行，你目前定在了第 {y_val} 行！")
            
            start_lf = next((move.hold_id for move in start_moves if move.limb == "LF"), None)
            start_rf = next((move.hold_id for move in start_moves if move.limb == "RF"), None)
            if start_lf and start_rf and start_lf != start_rf:
                lf_x = ord(start_lf[0].upper()) - ord('A')
                rf_x = ord(start_rf[0].upper()) - ord('A')
                if abs(lf_x - rf_x) > 3:
                    raise ValueError(f"起步左脚与右脚横向跨度达到 {abs(lf_x - rf_x)} 列，严禁起步大劈叉！")
            # ------------------------------------------
            # 🛑 物理拦截网 2：复用率与密度校验
            # ------------------------------------------
            unique_holds = set(move.hold_id for move in route_result.beta_sequence)
            hold_count = len(unique_holds)
            x_indices = [ord(h[0].upper()) - ord('A') for h in unique_holds]
            x_span = max(x_indices) - min(x_indices) + 1 
            
            mid_lower_moves = [m for m in route_result.beta_sequence if int(m.hold_id[1:]) <= 14]
            mid_lower_holds = set(m.hold_id for m in mid_lower_moves)
            ml_hand_holds = set(m.hold_id for m in mid_lower_moves if m.limb in ("LH", "RH"))
            ml_foot_holds = set(m.hold_id for m in mid_lower_moves if m.limb in ("LF", "RF"))
            
            ml_reused_holds = ml_hand_holds.intersection(ml_foot_holds)
            ml_reuse_rate = len(ml_reused_holds) / len(mid_lower_holds) if len(mid_lower_holds) > 0 else 0

            if x_span < 3:
                raise ValueError(f"抱石不是爬直梯！X轴跨度仅 {x_span} 列！")

            if hold_count < 7 or hold_count > 13: 
                raise ValueError(f"岩点数量违规！使用了 {hold_count} 个点。请删减废点复用！")

            if ml_reuse_rate < 0.40:
                raise ValueError(f"废点太多！中下段复用率仅 {int(ml_reuse_rate*100)}%。请将脚修改为前一个手点！")

            # ------------------------------------------
            # 🛑 物理拦截网 3：人体极限、时序防撞与形态一致性
            # ------------------------------------------
            current_limbs = {}
            shape_consistency_map = {} # 🌟 新增：记录被复用点的固定形态
            
            for move in route_result.beta_sequence:
                # 兼容枚举和字符串：提取当前的 limb 和 shape
                current_limb = move.limb if isinstance(move.limb, str) else move.limb.value
                current_shape = move.shape_type if isinstance(move.shape_type, str) else move.shape_type.value
                
                # 🌟 校验 3.1：形态逻辑一致性 (岩壁上的点不会变形)
                if move.hold_id in shape_consistency_map:
                    if shape_consistency_map[move.hold_id] != current_shape:
                        raise ValueError(f"逻辑错误：点 {move.hold_id} 之前被设定为 {shape_consistency_map[move.hold_id]}，现在却变成了 {current_shape}！岩点在墙上是不会变形的。")
                else:
                    shape_consistency_map[move.hold_id] = current_shape

                # 🌟 校验 3.2：非法抓握 (手不能抓 Foot)
                if current_shape == "Foot" and current_limb in ("LH", "RH"):
                    raise ValueError(f"违背常理：手 ({current_limb}) 绝对不能抓握纯脚点(Foot) {move.hold_id}！")

                current_limbs[move.limb] = move.hold_id
                
                current_hands = [current_limbs.get("LH"), current_limbs.get("RH")]
                current_feet = [current_limbs.get("LF"), current_limbs.get("RF")]
                for hand_pos in current_hands:
                    if hand_pos and hand_pos in current_feet:
                        h_limb = "LH" if current_limbs.get("LH") == hand_pos else "RH"
                        f_limb = "LF" if current_limbs.get("LF") == hand_pos else "RF"
                        raise ValueError(f"时序错误：{f_limb} 踩到了 {hand_pos}，但 {h_limb} 没挪开！")
                
                if "LH" in current_limbs and "RH" in current_limbs:
                    lh_x = ord(current_limbs["LH"][0].upper()) - ord('A')
                    rh_x = ord(current_limbs["RH"][0].upper()) - ord('A')
                    if lh_x - rh_x > 1:
                        raise ValueError("左手越过了右手，双臂严重交叉打结！")
                    if abs(rh_x - lh_x) > 6:
                        raise ValueError("点位过于离散！左右手横向跨度超过 6 列！")
                
                if "LF" in current_limbs and "RF" in current_limbs:
                    lf_x = ord(current_limbs["LF"][0].upper()) - ord('A')
                    rf_x = ord(current_limbs["RF"][0].upper()) - ord('A')
                    if lf_x - rf_x > 1:
                        raise ValueError("左脚越过了右脚打结！")
                    if abs(rf_x - lf_x) > 5:
                        raise ValueError("脚点过于离散大劈叉！")

                hands = [current_limbs[l] for l in ["LH", "RH"] if l in current_limbs]
                feet = [current_limbs[l] for l in ["LF", "RF"] if l in current_limbs]
                if hands and feet:
                    for h in hands:
                        for f in feet:
                            hf_dist = calculate_real_distance(h, f)
                            if hf_dist > max_stretch_cm:
                                raise ValueError(f"手脚距离 {hf_dist}cm 超出极限！")

                y_val = int(move.hold_id[1:]) 
                if move.step == 0 and y_val > 6:
                    raise ValueError("起步点太高无法悬空！")
                if move.is_top and y_val < 17:
                    raise ValueError("真正的完攀必须在 y=17 或 18！")

            # 校验全部通过，返回成功路线
            return route_result

        except (ValidationError, ValueError) as e:
            print(f"⚠️ 校验拦截 (第 {attempt + 1} 次尝试): {e}")
            # 替换为极简的反思提示词，加入形态错误指引
            error_msg = f"""校验失败: {e}
修复指南:
1. 形态矛盾: 确保复用的 hold_id 拥有完全相同的 shape_type。
2. 抓握非法: 手绝不能抓 Foot，请将 shape_type 改为 Jug、Crimp 等。
3. 拉伸超限: 补充移动脚的 Step。
4. 手脚同点: 在踩脚的 Step 前插入移手 Step。
5. 跨度超限: 聚拢离群点坐标。
6. 肢体打结: 调整左右侧目标 X 坐标。"""
            if raw_content:
                messages.append({"role": "assistant", "content": raw_content})
                messages.append({"role": "user", "content": error_msg})
            await asyncio.sleep(1.5)
            
        except Exception as e:
            print(f"⚠️ 网络/解析错误 (第 {attempt + 1} 次尝试): {type(e).__name__} - {e}")
            if attempt == max_retries - 1: raise e
            sleep_time = 2 ** (attempt + 1)
            print(f"🔄 网络保护，等待 {sleep_time} 秒后重连...")
            await asyncio.sleep(sleep_time)
            
    raise Exception(f"经过 {max_retries} 次反思，仍未能生成合法路线。请检查难度设置或账户余额。")