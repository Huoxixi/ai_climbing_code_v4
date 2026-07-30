#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
from pathlib import Path

import bcrypt


DEFAULT_USERS_PATH = Path("/etc/ai-climbing/pilot-users.json")
DEFAULT_CREDENTIALS_PATH = Path("/root/ai-climbing-pilot-credentials.txt")
PASSWORD_ALPHABET = string.ascii_letters + string.digits + "-_"
USERS = (
    ("ma-trial", "马老师"),
    ("deng-trial", "邓老师"),
    ("owner", "负责人"),
)


def exclusive_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Create pilot web accounts without printing passwords.")
    parser.add_argument("--users-file", type=Path, default=DEFAULT_USERS_PATH)
    parser.add_argument("--credentials-file", type=Path, default=DEFAULT_CREDENTIALS_PATH)
    args = parser.parse_args()

    if os.name != "nt" and os.geteuid() != 0:
        raise SystemExit("Run this script as root.")
    if args.users_file.exists() or args.credentials_file.exists():
        raise SystemExit("Pilot account files already exist; refusing to overwrite them.")

    users: dict[str, dict[str, object]] = {}
    credential_rows = [
        "攀岩定线系统小范围试用账号",
        "请分别私下发送，每位人员只接收自己的账号。",
        "临时网址请从 /run/ai-climbing-tunnel/url 获取。",
        "",
    ]
    for username, display_name in USERS:
        password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(24))
        users[username] = {
            "display_name": display_name,
            "active": True,
            "password_hash": bcrypt.hashpw(
                password.encode("utf-8"),
                bcrypt.gensalt(rounds=12),
            ).decode("utf-8"),
        }
        credential_rows.extend(
            (
                display_name,
                f"用户名：{username}",
                f"密码：{password}",
                "",
            )
        )

    users_payload = json.dumps(
        {"version": 1, "users": users},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    credentials_payload = "\n".join(credential_rows)
    exclusive_write(args.credentials_file, credentials_payload, 0o600)
    try:
        exclusive_write(args.users_file, users_payload, 0o640)
        if os.name != "nt":
            import grp

            os.chown(args.users_file, 0, grp.getgrnam("ai-climbing").gr_gid)
    except Exception:
        args.credentials_file.unlink(missing_ok=True)
        raise

    print(f"Created {args.users_file}")
    print(f"Created {args.credentials_file}")
    print("Passwords were saved to the root-only credentials file and were not printed.")


if __name__ == "__main__":
    main()
