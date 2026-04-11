# backend/upgrade_map.py
import json
import random

def generate_upgraded_map():
    columns = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K']
    rows = range(1, 19) # 1 到 18 行
    
    upgraded_holds = []
    
    print("🌍 正在重塑 11x18 物理世界地图...")
    
    for y in rows:
        for x in columns:
            hold_id = f"{x}{y}"
            
            # 🌟 核心：注入定线员常识逻辑
            if y <= 5:
                # 底部：70% 大把手，20% 纯脚点，10% 抠口
                hold_type = random.choices(["Jug", "Foot", "Crimp"], weights=[70, 20, 10])[0]
            elif y >= 16:
                # 顶部：60% 大把手，30% 抠口，10% 大斜面
                hold_type = random.choices(["Jug", "Crimp", "Sloper"], weights=[60, 30, 10])[0]
            else:
                # 中部：40% 抠口，20% 捏点，20% 大斜面，20% 大把手
                hold_type = random.choices(["Crimp", "Pinch", "Sloper", "Jug"], weights=[40, 20, 20, 20])[0]
                
            hold = {
                "id": hold_id,
                "x": x,
                "y": y,
                "hold_type": hold_type,
                "usable_as": ["hand", "foot"] if hold_type != "Foot" else ["foot"],
                "rotation": random.choice([0, 45, 90, 315]) # 随机给个安装角度增加真实感
            }
            upgraded_holds.append(hold)
            
    # 覆盖写入 mock_holds.json
    output_file = "mock_holds.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(upgraded_holds, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 地图重塑完成！成功生成 {len(upgraded_holds)} 个带有物理属性标签的岩点。")

if __name__ == "__main__":
    generate_upgraded_map()