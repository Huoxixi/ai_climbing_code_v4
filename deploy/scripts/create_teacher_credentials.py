#!/usr/bin/env python3
from __future__ import annotations

import crypt
import grp
import os
from pathlib import Path
import secrets
import string


HTPASSWD_PATH = Path("/etc/nginx/ai-climbing-teacher-users.htpasswd")
CREDENTIALS_PATH = Path("/root/ai-climbing-teacher-credentials.txt")
USERS = (
    ("ma-teacher", "Ma teacher"),
    ("deng-teacher", "Deng teacher"),
)
PASSWORD_ALPHABET = string.ascii_letters + string.digits + "-_"


def exclusive_write(path: Path, content: str, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run this script as root.")
    if HTPASSWD_PATH.exists() or CREDENTIALS_PATH.exists():
        raise SystemExit(
            "Teacher credentials already exist; refusing to overwrite them."
        )

    HTPASSWD_PATH.parent.mkdir(parents=True, exist_ok=True)
    password_rows: list[str] = []
    htpasswd_rows: list[str] = []

    for username, label in USERS:
        password = "".join(
            secrets.choice(PASSWORD_ALPHABET) for _ in range(24)
        )
        password_hash = crypt.crypt(
            password,
            crypt.mksalt(crypt.METHOD_SHA512),
        )
        password_rows.extend(
            (
                f"{label}",
                f"username: {username}",
                f"temporary password: {password}",
                "",
            )
        )
        htpasswd_rows.append(f"{username}:{password_hash}")

    credential_text = "\n".join(
        (
            "AI Climbing Pilot teacher access",
            "Website: https://climb.panyandingxian.cn",
            "Keep each account private and send it only to its named teacher.",
            "",
            *password_rows,
        )
    )
    exclusive_write(CREDENTIALS_PATH, credential_text, 0o600)
    try:
        exclusive_write(
            HTPASSWD_PATH,
            "\n".join(htpasswd_rows) + "\n",
            0o640,
        )
        os.chown(
            HTPASSWD_PATH,
            0,
            grp.getgrnam("www-data").gr_gid,
        )
    except Exception:
        CREDENTIALS_PATH.unlink(missing_ok=True)
        raise

    print(f"Created {HTPASSWD_PATH}")
    print(f"Created {CREDENTIALS_PATH}")
    print("No passwords were printed.")


if __name__ == "__main__":
    main()
