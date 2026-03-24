# backend/generate_wall.py
import json
import random

# 定义 11x18 标准矩阵
X_AXIS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K']
Y_AXIS = list(range(1, 19)) # 1 到 18

holds = []

for y in Y_AXIS:
    for x in X_AXIS:
        # 约 60% 的网格交叉点上会被安装岩点（避免太密）
        if random.random() < 0.6:
            
            # 智能分配岩点类型 (符合真实定线逻辑)
            if y <= 3:
                # 底部 1-3 行：70% 是纯脚点，30% 是大把手(起步用)
                h_type = random.choices(["Foot", "Jug"], weights=[0.7, 0.3])[0]
            elif y >= 16:
                # 顶部 16-18 行：全是大把手(完攀用)
                h_type = "Jug"
            else:
                # 中间地带：随机分布抠口、斜面、捏点和少量把手
                h_type = random.choices(["Crimp", "Sloper", "Pinch", "Pocket", "Jug"], 
                                        weights=[0.4, 0.2, 0.2, 0.1, 0.1])[0]
            
            # 定义可用性
            usable = ["foot"] if h_type == "Foot" else ["hand", "foot"]
            
            # 定义角度 (每 45 度一个朝向)
            rotation = random.choice([0, 45, 90, 135, 180, 225, 270, 315])
            
            hold = {
                "id": f"{x}{y}",
                "x": x,
                "y": y,
                "hold_type": h_type,
                "usable_as": usable,
                "rotation": rotation
            }
            holds.append(hold)

# 写入 JSON 数据库
with open("mock_holds.json", "w", encoding="utf-8") as f:
    json.dump(holds, f, indent=2, ensure_ascii=False)

print(f"✅ 创世成功！一面包含 {len(holds)} 个岩点的标准矩阵墙已写入 mock_holds.json")