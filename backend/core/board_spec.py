"""Shared physical board specification for the default AI board."""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class BoardSpec:
    preset_id: str
    template_key: str
    columns: int
    rows: int
    hole_spacing_x_mm: int
    hole_spacing_y_mm: int
    board_width_mm: int
    board_height_mm: int
    margin_left_mm: int
    margin_right_mm: int
    margin_bottom_mm: int
    margin_top_mm: int
    angle_degrees: int
    reference_system: str
    unit: str = "mm"

    @property
    def grid_width_mm(self) -> int:
        return (self.columns - 1) * self.hole_spacing_x_mm

    @property
    def grid_height_mm(self) -> int:
        return (self.rows - 1) * self.hole_spacing_y_mm

    @property
    def total_holes(self) -> int:
        return self.columns * self.rows

    @property
    def hole_spacing_m(self) -> float:
        return self.hole_spacing_x_mm / 1000.0

    @property
    def x_labels(self) -> List[str]:
        return [chr(ord("A") + index) for index in range(self.columns)]

    def coord_to_mm(self, x_label: str, y_label: int) -> Dict[str, int]:
        x_index = ord(x_label.upper()) - ord("A")
        y_index = y_label - 1
        return {
            "x_mm": self.margin_left_mm + x_index * self.hole_spacing_x_mm,
            "y_mm": self.margin_bottom_mm + y_index * self.hole_spacing_y_mm,
        }

    def to_snapshot(self) -> Dict[str, int | str]:
        return {
            "preset_id": self.preset_id,
            "template_key": self.template_key,
            "columns": self.columns,
            "cols": self.columns,
            "rows": self.rows,
            "hole_spacing_x_mm": self.hole_spacing_x_mm,
            "hole_spacing_y_mm": self.hole_spacing_y_mm,
            "board_width_mm": self.board_width_mm,
            "board_height_mm": self.board_height_mm,
            "grid_width_mm": self.grid_width_mm,
            "grid_height_mm": self.grid_height_mm,
            "margin_left_mm": self.margin_left_mm,
            "margin_right_mm": self.margin_right_mm,
            "margin_bottom_mm": self.margin_bottom_mm,
            "margin_top_mm": self.margin_top_mm,
            "angle_degrees": self.angle_degrees,
            "total_holes": self.total_holes,
            "unit": self.unit,
            "reference_system": self.reference_system,
        }


DEFAULT_BOARD_SPEC = BoardSpec(
    preset_id="classic-11x18",
    template_key="spray-small",
    columns=11,
    rows=18,
    hole_spacing_x_mm=200,
    hole_spacing_y_mm=200,
    board_width_mm=2440,
    board_height_mm=3660,
    margin_left_mm=220,
    margin_right_mm=220,
    margin_bottom_mm=130,
    margin_top_mm=130,
    angle_degrees=40,
    reference_system="moonboard-derived",
)
