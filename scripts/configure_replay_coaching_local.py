"""Import a Bailian key into the local replay-coaching configuration.

The key is read from an explicitly named local file or a hidden terminal prompt.
It is never accepted as a command-line argument or printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9._-]{20,}")
CONFIG_PATTERN = re.compile(
    rb"(?m)^\s*(?:export\s+)?REPLAY_COACHING_(?:API_KEY|BASE_URL)\s*="
)


def load_key(key_file: Path | None) -> str:
    if key_file is None:
        value = getpass.getpass("粘贴百炼 API Key（输入不显示）：").strip()
    else:
        if not key_file.is_file() or key_file.stat().st_size > 64 * 1024:
            raise ValueError("密钥文件不存在或过大")
        content = key_file.read_text(encoding="utf-8-sig")
        matches = set(KEY_PATTERN.findall(content))
        if len(matches) != 1:
            raise ValueError("文件中未找到唯一的完整 API Key")
        value = matches.pop()
    if not KEY_PATTERN.fullmatch(value):
        raise ValueError("API Key 格式不正确")
    return value


def validate_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".cn-beijing.maas.aliyuncs.com")
        or parsed.path != "/compatible-mode/v1"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("需要北京业务空间的 OpenAI 兼容地址")
    return value.strip()


def append_config(target: Path, key: str, base_url: str) -> None:
    if target.is_symlink():
        raise ValueError("配置路径是符号链接，已停止")
    previous = target.read_bytes() if target.exists() else b""
    if CONFIG_PATTERN.search(previous):
        raise ValueError("复盘配置已存在，已停止以避免覆盖")

    newline = b"\r\n" if b"\r\n" in previous else b"\n"
    prefix = b"" if not previous or previous.endswith((b"\r", b"\n")) else newline
    addition = (
        prefix
        + b"REPLAY_COACHING_API_KEY="
        + key.encode("ascii")
        + newline
        + b"REPLAY_COACHING_BASE_URL="
        + base_url.encode("ascii")
        + newline
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        with os.fdopen(fd, "ab", closefd=False) as stream:
            stream.write(addition)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="将百炼密钥安全写入本地复盘配置")
    parser.add_argument("--base-url", required=True, help="控制台显示的 OpenAI 兼容地址")
    parser.add_argument("--key-file", type=Path, help="已下载的密钥文件；留空时安全提示输入")
    args = parser.parse_args()
    try:
        base_url = validate_base_url(args.base_url)
        key = load_key(args.key_file)
        root = Path(__file__).resolve().parents[1]
        append_config(root / ".local" / "photo-vision.env", key, base_url)
    except (OSError, UnicodeError, ValueError, EOFError) as exc:
        print(f"未写入配置：{exc if isinstance(exc, ValueError) else '无法读取或写入本地文件'}", file=sys.stderr)
        return 1
    print("本地复盘密钥已保存；请重启后端使其生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
