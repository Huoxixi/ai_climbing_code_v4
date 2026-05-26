"""
Import existing JSON data into Supabase.

Run from backend/ after the database migration has been applied and these
environment variables are set:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.supabase_repo import SupabaseRepository  # noqa: E402


DATA_DIR = ROOT / "data"


def read_json(name: str, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


async def import_holds(repo: SupabaseRepository) -> None:
    mapping = read_json("holds_mapping.json", {})
    vectors = read_json("holds_vectors.json", {})

    for hold_type, variants in mapping.items():
        for variant, image_path in variants.items():
            svg_path = vectors.get(hold_type, {}).get(variant, "")
            await repo.upsert_hold_asset(
                hold_type=hold_type,
                variant=variant,
                image_path=image_path,
                svg_path=svg_path,
                owner_id=None,
                is_system=True,
            )


async def import_boards(repo: SupabaseRepository) -> None:
    for board in read_json("saved_boards.json", []):
        await repo.create_board(board, owner_id=None)


async def main() -> None:
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    repo = SupabaseRepository()
    await import_holds(repo)
    await import_boards(repo)
    print("Imported JSON hold assets and saved boards into Supabase.")


if __name__ == "__main__":
    asyncio.run(main())
