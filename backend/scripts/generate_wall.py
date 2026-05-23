import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.board_spec import DEFAULT_BOARD_SPEC


def build_empty_wall():
    holes = []
    for y in range(1, DEFAULT_BOARD_SPEC.rows + 1):
        for x in DEFAULT_BOARD_SPEC.x_labels:
            holes.append({
                "id": f"{x}{y}",
                "x": x,
                "y": y,
                **DEFAULT_BOARD_SPEC.coord_to_mm(x, y),
                "unit": DEFAULT_BOARD_SPEC.unit,
                "hole_spacing_x_mm": DEFAULT_BOARD_SPEC.hole_spacing_x_mm,
                "hole_spacing_y_mm": DEFAULT_BOARD_SPEC.hole_spacing_y_mm,
            })
    return holes


if __name__ == "__main__":
    output_path = ROOT / "data" / "empty_wall_grid.json"
    output_path.write_text(json.dumps(build_empty_wall(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {DEFAULT_BOARD_SPEC.total_holes} holes to {output_path}")
