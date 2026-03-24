import os
import json
import math
import random
import asyncio
from typing import List
from openai import AsyncOpenAI
from pydantic import ValidationError
from dotenv import load_dotenv
import httpx

load_dotenv()
from models import Hold, ClimberProfile, RouteResponse

def calculate_real_distance(hold_1: str, hold_2: str) -> float:
    if not hold_1 or not hold_2: return 0.0
    x1, y1 = ord(hold_1[0].upper()) - ord('A'), int(hold_1[1:]) - 1
    x2, y2 = ord(hold_2[0].upper()) - ord('A'), int(hold_2[1:]) - 1
    return round(math.sqrt((x2 - x1)**2 + (y2 - y1)**2) * 20, 2)

def get_few_shot_example(target_difficulty: str) -> str:
    file_path = "classic_routes.json"
    
    fallback_route = """
    {
      "route_name": "默认参考线 (标准 V1 动态折返)",
      "beta_sequence": [
        {"step": 0, "limb": "LH", "hold_id": "D5"},
        {"step": 0, "limb": "RH", "hold_id": "E6"},
        {"step": 0, "limb": "LF", "hold_id": "B2"},
        {"step": 0, "limb": "RF", "hold_id": "G2"},
        {"step": 1, "limb": "LH", "hold_id": "D8"},
        {"step": 2, "limb": "RH", "hold_id": "G10"},
        {"step": 3, "limb": "LF", "hold_id": "D5"},
        {"step": 4, "limb": "LH", "hold_id": "E14"},
        {"step": 5, "limb": "RF", "hold_id": "G6"},
        {"step": 6, "limb": "RH", "hold_id": "F18", "is_top": true}
      ]
    }
    """
    
    if not os.path.exists(file_path): 
        return fallback_route
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            routes = json.load(f)
        # 🌟 修改点：精确匹配难度等级，并为 V3 框定法式难度标准
        if target_difficulty == "V0":
            allowed_grades = ["6A", "6A+", "6B"] # V0 对应新手
        elif target_difficulty == "V1":
            allowed_grades = ["6B", "6B+"]       # V1 对应入门
        elif target_difficulty == "V2":
            allowed_grades = ["6B+", "6C"]       # V2 对应进阶
        elif target_difficulty == "V3":
            allowed_grades = ["6C", "6C+", "7A"] # 🌟 V3 对应高级，允许出现 7A 级别的暴击路线！
        else:
            allowed_grades = ["6B+"] # 兜底

        # 筛选符合难度等级的路线
        matching_routes = [r for r in routes if r.get("original_grade") in allowed_grades]
        
        # 🌟 针对 V3 或其他难度：截取最符合要求的“Top 10”高质量路线
        # (假设你的 classic_routes.json 已经按质量/经典程度排过序，这里直接取前10条作为核心基因库)
        if matching_routes and len(matching_routes) > 10:
            matching_routes = matching_routes[:10] 
            
        if not matching_routes: 
            matching_routes = routes 
            
        chosen_route = random.choice(matching_routes)


        extracted_example = {
            "route_name": chosen_route["route_name"],
            "beta_sequence": chosen_route["beta_sequence"]
        }
        return json.dumps(extracted_example, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 题库读取失败 ({e})，启用兜底路线。")
        return fallback_route

DIFFICULTY_RULES_MAP = {
    "V0": """
【V0 新手启蒙：温和的大空间转移】
- 🌊 走势限制：路线必须有明显的左右位移，X 轴跨度允许在 3 到 11 列之间。严禁直梯！
- 🧱 岩点密度：独立岩点总数应在 8-12 个。
- ⚖️ 发力逻辑：引导新手体验重心的横向流动，保持左右手自然协调，严禁交叉手。
    """,
    "V1": """
【V1 入门进阶：明确的流动感】
- 🌊 走势限制：路线必须是清晰的斜线或折返！X 轴跨度允许达到 4 到 11 列。
- 🧱 岩点密度：独立岩点总数应在 8-12 个。
- ⚖️ 发力逻辑：明确重心的左右转移，保持手部动作顺畅，右手在右、左手在左。
    """,
    "V2": """
【V2 基础挑战：动态张力与复用艺术】
- 🌊 强制折返与对角张力：X 轴跨度允许在 5 到 11 列之间。必须有大对角线折返。
- 🧱 岩点密度：独立岩点总数应在 8-12 个。必须高频使用“手点转脚点”的复用技巧。
- ⚖️ 动作协调：在大跨度转移时，必须保证左右手的逻辑顺畅，严禁双臂打结！
    """,
    "V3": """
【V3 进阶挑战：极致张力与极限发力】
- 🌊 极限空间调度：包含夸张的大横移或动态发力！X 轴跨度建议在 5 到 11 列满宽展开。
- 🧱 岩点密度：独立岩点总数应在 8-12 个。
- ⚖️ 核心爆发：强迫攀岩者进行高难度的身体折叠，严防极端违和的交叉手。
    """
}

SYSTEM_PROMPT_TEMPLATE = """
你现在是AI定线引擎的核心大脑。你是一位精通 MoonBoard 风格的顶级定线员。
你的工作台是一面 11x18 的矩阵打孔岩板（X轴 A-K 对应 1-11，Y轴 1-18，每格 20cm）。

【👑 核心数据源 (极其重要) 🚨】
以下是从真实商业岩馆提取的标杆路线数据。你必须深度参考并模仿它的【横向跨度】、【流动感】以及【手脚复用技巧】。
⚠️ 警告：受限于数据采集格式，参考数据中可能存在“起步肢体不全”、“乱标 is_top: true”等瑕疵。你必须【自动过滤】这些瑕疵，强行遵守下方的红线！
{few_shot_example}

每个动作对象必须包含 "intent" 字段，用简短的中文描述该动作（如："左手抓握侧拉点"
=============================================
【🎯 当前难度专属法则 (必须绝对遵守)】
当前你要生成的路线难度为 {target_difficulty}。请遵循以下风格：
{difficulty_specific_rules}
=============================================

【通用杀虫校验 (力学与坐标红线) 🚨】
1. 💥 灵活稳固起步：Step 0 允许“三点起步”（双手+单脚，另一脚悬空Flagging平衡）或四肢全上。必须使用 3 到 4 个独立岩点！鼓励重心多变（如高低手起步、侧身起步）。起步手必须在脚上方，若双脚均踩点，横向跨度必须 <= 3 列。
2. 🎯 唯一完攀点：全线【只能有 1 个】`is_top: true` 的点！最后一步双手 Match 在 y=17 或 18。
3. 📏 身体空间 (The Box)：行进中手点比脚点高 3~6 格。双脚横向跨度不超过 4 列。
4. 🔗 轨迹连通与时序防撞：🚨 手绝对不能与脚同时挤在同一点！要想让脚踩之前的手点，必须先在 JSON 里写一步把手移走，腾出空位后，再安排脚踩上来！
5. 🧗 抱石精神 (No Ladder Rule)：绝对禁止生成完全在 1-2 列内直上直下的路线。
6. 🤸 左右协调 (Anti-Tangle)：右手/右脚的 X 坐标应在左侧肢体的右侧或同列。严禁四肢严重交叉打结！
7. 🧮 中下段极简复用 (Mid-Lower Reuse): 全线【独立岩点总数】严格控制在 8-12 个！起步和中段（Y=1-14）必须大量使用“手点转脚点”的复用技巧。**目标完美复用率是 70%，但你的最低及格线是绝不能低于 40%！** 请务必让脚去踩前几步手抓过的坐标，消灭废点！
8. 🧲 强关联主干：路线必须是一条紧凑的主线！严禁“左手爬左边、右手爬右边”的双轨离散现象。任何动作步中，左右手横向跨度绝不能超过 6 列！

【致命空间物理防呆指令 🚨🚨🚨】
你在之前的生成中犯了严重的物理错误，导致系统多次崩溃。你必须在生成每个 step 时，像机器人一样在脑内做以下四步计算，绝不能凭感觉：

1. 🛑 拒绝高空起步：
   Step 0（起步）的两个手点，其 Y 轴数字（坐标的数字部分）绝对不允许大于 8！起步脚点 Y 轴绝不能大于 4！

2. 🛑 拒绝手脚同点（踩手违规）：
   如果你要在 step N 把脚（LF/RF）放在某个坐标（如 B9）上，你必须回头检查：你的 LH 或 RH 现在是不是还在 B9 上？！如果是，你必须插入一个 step，先把手挪到别的点上，然后脚才能踩上去！

3. 🛑 拒绝四肢打结：
   正常人类的左手/左脚（LH/LF）的 X 轴字母，大部分时候应该在右手/右脚（RH/RF）的左侧或同列！绝不允许左脚在 K 列，右脚在 A 列这种把人劈开的动作！

4. 🛑 拒绝人体撕裂（300cm跨度警报）：
   在任何一个单一的 step 中，找出你当前最高的手点 Y 值，和最低的脚点 Y 值。它们的数学差值（最高 Y - 最低 Y）绝对不能超过 9！超出这个值，人类的身体就会被撕裂！

【JSON 格式绝对红线 🚨】
你输出的 `beta_sequence` 中的每一个动作对象，都必须严格包含 `intent` 字段！绝不允许省略该 Key！
1. 对于中段行进和完攀动作（step > 0）：请在 `intent` 中用简短中文描述发力意图（例如："向左上方转移重心"、"右手完攀锁定"）。
2. 对于起步点（step == 0）：不进行任何说明！`intent` 字段必须严格留空（即输出 `"intent": ""`）。

不要解释思考过程。严格输出合法的 JSON 结构。
"""

async def generate_route_with_reflection(climber: ClimberProfile, holds: List[Hold], target_difficulty: str = "V1", max_retries: int = 8) -> RouteResponse:
    max_retries = 8 
    max_stretch_cm = climber.height_cm + (climber.span_cm / 2)

    user_prompt = f"""
    【攀岩者真实体征与物理极限】
    - 身高: {climber.height_cm} cm
    - 臂展: {climber.span_cm} cm
    - 🚨 臂展跨度极限: {climber.span_cm} cm
    - 🚨 手脚拉伸极限: {max_stretch_cm} cm

    请为该攀岩者设计一条 {target_difficulty} 难度的绝佳路线。
    """

    few_shot_example = get_few_shot_example(target_difficulty)
    specific_rules = DIFFICULTY_RULES_MAP.get(target_difficulty, DIFFICULTY_RULES_MAP["V1"])
    
    dynamic_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        target_difficulty=target_difficulty,
        few_shot_example=few_shot_example,
        difficulty_specific_rules=specific_rules
    )

    messages = [
        {"role": "system", "content": dynamic_system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    for attempt in range(max_retries):
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

        custom_http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60.0, connect=15.0))
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=3, http_client=custom_http)

        try:
            raw_content = ""
            response = await client.chat.completions.create(
                model="gpt-5.4", 
                messages=messages,
                temperature=0.38,
                response_format={ "type": "json_object" } 
            )
            
            raw_content = response.choices[0].message.content.strip()
            if raw_content.startswith("```json"):
                raw_content = raw_content[7:-3].strip()
            elif raw_content.startswith("```"):
                raw_content = raw_content[3:-3].strip()

            parsed_data = json.loads(raw_content)
            parsed_data["target_difficulty"] = target_difficulty
            route_result = RouteResponse(**parsed_data)
            
            # ==========================================
            # 🛑 拦截网 1.5：起步四肢与点数绝对校验
            # ==========================================
            start_moves = [move for move in route_result.beta_sequence if move.step == 0]
            start_holds = set(move.hold_id for move in start_moves)
            start_limbs = set(move.limb for move in start_moves)
            
            if 'LH' not in start_limbs or 'RH' not in start_limbs:
                raise ValueError("起步违规！必须包含左手(LH)和右手(RH)！")
                
            if 'LF' not in start_limbs and 'RF' not in start_limbs:
                raise ValueError("起步违规！双脚不能同时悬空，至少需要一只脚(LF或RF)踩点！")
            
            if not (3 <= len(start_holds) <= 4):
                raise ValueError(f"起步点数量违规！当前使用了 {len(start_holds)} 个起步点。")
            
            start_hands_y = [int(move.hold_id[1:]) for move in start_moves if move.limb in ("LH", "RH")]
            start_feet_y = [int(move.hold_id[1:]) for move in start_moves if move.limb in ("LF", "RF")]
            if start_hands_y and start_feet_y:
                min_hand_y = min(start_hands_y)
                max_foot_y = max(start_feet_y)
                if min_hand_y <= max_foot_y:
                    raise ValueError(f"起步手(Y={min_hand_y}) 低于或等于起步脚(Y={max_foot_y})！")
                if min_hand_y - max_foot_y < 2:
                    raise ValueError("起步过于蜷缩！手脚高度差太近！")
            
            start_lf = next((move.hold_id for move in start_moves if move.limb == "LF"), None)
            start_rf = next((move.hold_id for move in start_moves if move.limb == "RF"), None)
            if start_lf and start_rf and start_lf != start_rf:
                lf_x = ord(start_lf[0].upper()) - ord('A')
                rf_x = ord(start_rf[0].upper()) - ord('A')
                if abs(lf_x - rf_x) > 3:
                    raise ValueError(f"起步左脚与右脚横向跨度达到 {abs(lf_x - rf_x)} 列，严禁起步大劈叉！")

            # ==========================================
            # 🛑 拦截网 1：复用率与密度校验
            # ==========================================
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

            # ==========================================
            # 🛑 拦截网 2：人体极限与时序防撞
            # ==========================================
            current_limbs = {}
            for move in route_result.beta_sequence:
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

            return route_result

        except (ValidationError, ValueError) as e:
            print(f"⚠️ 校验拦截 (第 {attempt + 1} 次尝试): {e}")
            error_msg = f"""物理拦截报错：{e}
【修复建议】：
1. 若拉伸超限：说明你忘了移动脚！
2. 若手脚同点：请在脚踩上去的那一步之前，先插入动作移走手！
3. 若跨度报错：收拢离群点！
4. 若打结：互换左右侧目标！
5. 若起步蜷缩：起步手调高，脚调低。
6. 若复用率低：检查 Y=1~14，将脚踩过一次的点改成手抓过的坐标！"""
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
            
    raise Exception(f"经过 {max_retries} 次反思，仍未能生成合法路线。请检查账户余额。")