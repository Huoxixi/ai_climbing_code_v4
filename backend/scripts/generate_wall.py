# backend/generate_wall.py
import json

# 定义 11x18 标准矩阵
X_AXIS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K']
Y_AXIS = list(range(1, 19)) # 1 到 18

holes = []

# 生成纯净的孔位网格，不包含任何岩点类型和角度
for y in Y_AXIS:
    for x in X_AXIS:
        hole = {
            "id": f"{x}{y}",
            "x": x,
            "y": y
        }
        holes.append(hole)

# 写入 JSON 数据库，建议改名为 empty_wall_grid.json 以示区分
with open("empty_wall_grid.json", "w", encoding="utf-8") as f:
    json.dump(holes, f, indent=2, ensure_ascii=False)

print(f"✅ 创世成功！一面包含 {len(holes)} 个纯净孔位的标准矩阵墙已写入 empty_wall_grid.json")