import json
import os

GRADE_MAP = {
    "V0": ["6A", "6A+", "6B"],
    "V1": ["6B", "6B+"],
    "V2": ["6B+", "6C"],
    "V3": ["6C", "6C+", "7A"]
}

def extract_holds(route):
    """
    🌟 终极解析器：兼容字符串与底层 [x, y] 坐标数组！
    """
    holds = []
    
    # 提取 Moves 格式
    if "Moves" in route and isinstance(route["Moves"], list):
        for m in route["Moves"]:
            if isinstance(m, dict) and "Description" in m:
                holds.append(m["Description"])
            elif isinstance(m, str):
                holds.append(m)
                
    # 提取 Start/Mid/Top 或 start/mid/end 格式 (兼容大小写)
    for key in ["Start", "Mid", "Top", "start", "mid", "end"]:
        if key in route and isinstance(route[key], list):
            holds.extend(route[key])

    cleaned_holds = []
    for h in holds:
        # 情况 1: 如果是人类可读的字符串，如 "D5"
        if isinstance(h, str) and len(h) >= 2:
            cleaned_holds.append(h.strip().upper())
            
        # 🌟 情况 2: 如果是底层数字坐标，如 [3, 5] (X, Y)
        elif isinstance(h, (list, tuple)) and len(h) >= 2:
            try:
                x, y = int(h[0]), int(h[1])
                # X = 0-10 映射到 A-K
                char_x = chr(x + ord('A'))
                # 月亮板的 Y 轴直接拼接即可
                cleaned_holds.append(f"{char_x}{y}")
            except:
                pass

    return list(set(cleaned_holds))

def score_route(route, holds, target_v):
    hold_count = len(holds)
    if hold_count < 6 or hold_count > 12:
        return -1 
        
    x_indices = [ord(h[0]) - ord('A') for h in holds if h[0].isalpha()]
    if not x_indices: return -1
    x_span = max(x_indices) - min(x_indices) + 1
    
    min_span = {"V0": 3, "V1": 4, "V2": 5, "V3": 6}
    if x_span < min_span.get(target_v, 3):
        return -1

    score = 0
    is_benchmark = route.get("is_benchmark", False)
    if is_benchmark in [True, "true", "True", 1]:
        score += 1000  

    repeats = route.get("repeats", 0)
    try:
        repeats = int(repeats) if repeats else 0
    except:
        repeats = 0
    score += min(repeats * 0.5, 500) 
    score += (x_span * 20)
    
    return score

def run_filter():
    input_file = "raw_datasets/moonGen_scrape_2016_final" 
    output_file = "filtered_skeletons.json" 
    
    print("🚀 [阶段一] 启动粗筛：提取所有满足张力与标杆条件的路线池...")
    
    if not os.path.exists(input_file):
        print(f"❌ 找不到原始文件: {input_file}")
        return

    # 1. 暴力解开 Pickle 二进制
    try:
        import pickle
        with open(input_file, "rb") as f:
            raw_data = pickle.load(f)
            print("🔓 成功以 Pickle 二进制模式解开原始矿脉！")
    except Exception as e1:
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                print("🔓 成功以 JSON 文本模式解开原始矿脉！")
        except Exception as e2:
            print(f"❌ 数据读取彻底失败！Pickle报错: {e1} | JSON报错: {e2}")
            return

    # 🌟 核心修复：智能识别数据结构，提取出真正的“字典列表”
    if isinstance(raw_data, dict):
        if "data" in raw_data:
            routes_list = raw_data["data"]
        elif "routes" in raw_data:
            routes_list = raw_data["routes"]
        else:
            # 应对 { "ID": {路线数据} } 格式，强行抽取所有路线数据（Values）
            routes_list = list(raw_data.values())
    else:
        routes_list = raw_data

    filtered_db = {"V0": [], "V1": [], "V2": [], "V3": []}

    for v_grade, allowed_grades in GRADE_MAP.items():
        candidates = []
        for r in routes_list:
            # 🌟 防弹检测：如果 r 依然不是字典，直接跳过，绝不崩溃
            if not isinstance(r, dict):
                continue
                
            grade = r.get("Grade", r.get("grade", "")).upper()
            if grade in allowed_grades:
                holds = extract_holds(r)
                score = score_route(r, holds, v_grade)
                if score > 0:
                    candidates.append({
                        "score": score, 
                        "name": r.get("Name", r.get("name", "Unnamed")), 
                        "grade": grade, 
                        "holds": holds, 
                        "is_benchmark": r.get("is_benchmark", False)
                    })
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        filtered_db[v_grade] = candidates
        
        bench_count = sum(1 for c in candidates if c["is_benchmark"])
        print(f"💎 [{v_grade}] 骨架入库: 找到 {len(candidates)} 条合法骨架 (包含 {bench_count} 条官方 Benchmark 标杆线)")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(filtered_db, f, ensure_ascii=False, indent=2)
    print(f"✅ 粗筛完毕！所有优质骨架大盘已保存至: {output_file}")

if __name__ == "__main__":
    run_filter()