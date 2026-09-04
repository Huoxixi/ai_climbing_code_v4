"""Migrate active local boards to the MoonBoard Font grading contract.

Archived boards are intentionally left untouched and are migrated by the
restore endpoint.  The operation is idempotent and keeps the previous public V
grade only in ``legacy_difficulty`` for audit purposes.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.moonboard_grading import font_grade_tag, normalize_font_grade  # noqa: E402
from main import SAVED_BOARDS_FILE, dump_board, normalize_board_payload  # noqa: E402


def migrate_board(board: dict) -> dict:
    if board.get("archived_at"):
        return board

    migrated = dump_board(
        normalize_board_payload(board, saved_id=str(board.get("saved_id") or ""))
    )
    grade = normalize_font_grade(migrated.get("difficulty"))
    tags = [
        tag
        for tag in migrated.get("tags", [])
        if not re.fullmatch(r"difficulty:v(?:[0-9]|1[0-2])", str(tag), re.I)
    ]
    if grade:
        tags = [tag for tag in tags if not str(tag).startswith("difficulty:")]
        tags.append(font_grade_tag(grade))
    migrated["tags"] = list(dict.fromkeys(tags))

    commentary = str(migrated.get("setter_commentary") or "")
    if grade and migrated.get("source_type") != "imported":
        commentary = re.sub(
            r"预测难度\s*V(?:[0-9]|1[0-2])",
            f"MoonBoard 等效难度 {grade}",
            commentary,
            flags=re.I,
        )
    migrated["setter_commentary"] = commentary
    return migrated


def main() -> int:
    path = Path(SAVED_BOARDS_FILE)
    boards = json.loads(path.read_text(encoding="utf-8"))
    migrated = [migrate_board(board) for board in boards]
    if migrated == boards:
        print("No active board migration was required.")
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = path.parent / "demo_backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / "saved_boards_pre_font.json")

    temp_path = path.with_suffix(".font.tmp")
    temp_path.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
    active_count = sum(1 for board in migrated if not board.get("archived_at"))
    print(f"Migrated {active_count} active boards; archived boards were unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
