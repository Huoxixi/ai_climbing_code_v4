from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bcrypt


@dataclass(frozen=True)
class PilotUser:
    username: str
    display_name: str


class PilotAccessError(Exception):
    pass


class LoginBlockedError(PilotAccessError):
    pass


class InvalidCredentialsError(PilotAccessError):
    pass


class EditLeaseError(PilotAccessError):
    pass


class PilotAccessManager:
    def __init__(
        self,
        *,
        users_file: str,
        audit_file: str,
        session_seconds: int = 8 * 60 * 60,
        lease_seconds: int = 15 * 60,
        failure_window_seconds: int = 15 * 60,
        failure_limit: int = 5,
    ) -> None:
        self.users_file = Path(users_file)
        self.audit_file = Path(audit_file)
        self.session_seconds = session_seconds
        self.lease_seconds = lease_seconds
        self.failure_window_seconds = failure_window_seconds
        self.failure_limit = failure_limit
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lease: dict[str, Any] | None = None

    def _load_users(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.users_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PilotAccessError("试用账号配置不可用。") from exc
        users = payload.get("users")
        if not isinstance(users, dict):
            raise PilotAccessError("试用账号配置格式不正确。")
        return users

    def _prune_failures(self, key: tuple[str, str], now: float) -> deque[float]:
        failures = self._failures[key]
        cutoff = now - self.failure_window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def _active_user(self, username: str) -> tuple[str, dict[str, Any]]:
        normalized = username.strip().lower()
        users = self._load_users()
        entry = users.get(normalized)
        if not isinstance(entry, dict) or not entry.get("active", True):
            raise InvalidCredentialsError("试用账号不可用。")
        return normalized, entry

    def _issue_session(
        self,
        normalized: str,
        entry: dict[str, Any],
        now: float,
    ) -> tuple[str, PilotUser]:
        token = secrets.token_urlsafe(32)
        user = PilotUser(
            username=normalized,
            display_name=str(entry.get("display_name") or normalized),
        )
        self._sessions[token] = {
            "user": user,
            "expires_at": now + self.session_seconds,
        }
        return token, user

    def create_session(self, user: PilotUser) -> tuple[str, PilotUser]:
        with self._lock:
            token = secrets.token_urlsafe(32)
            self._sessions[token] = {
                "user": user,
                "expires_at": time.time() + self.session_seconds,
            }
            return token, user

    def active_user(self, username: str) -> PilotUser:
        with self._lock:
            normalized, entry = self._active_user(username)
            return PilotUser(
                username=normalized,
                display_name=str(entry.get("display_name") or normalized),
            )

    def create_session_for_user(self, username: str) -> tuple[str, PilotUser]:
        with self._lock:
            normalized, entry = self._active_user(username)
            return self._issue_session(normalized, entry, time.time())

    def authenticate(self, username: str, password: str, client_ip: str) -> tuple[str, PilotUser]:
        normalized = username.strip().lower()
        now = time.time()
        key = (client_ip, normalized)
        with self._lock:
            failures = self._prune_failures(key, now)
            if len(failures) >= self.failure_limit:
                raise LoginBlockedError("登录尝试过多，请15分钟后再试。")

            users = self._load_users()
            entry = users.get(normalized)
            stored_hash = str(entry.get("password_hash") or "") if isinstance(entry, dict) else ""
            password_valid = False
            if stored_hash:
                try:
                    password_valid = bcrypt.checkpw(
                        password.encode("utf-8"),
                        stored_hash.encode("utf-8"),
                    )
                except (ValueError, TypeError):
                    password_valid = False

            if not entry or not entry.get("active", True) or not password_valid:
                failures.append(now)
                raise InvalidCredentialsError("用户名或密码不正确。")

            failures.clear()
            return self._issue_session(normalized, entry, now)

    def session_user(self, token: str | None) -> PilotUser | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            if float(session["expires_at"]) <= now:
                self._sessions.pop(token, None)
                return None
            return session["user"]

    def logout(self, token: str | None) -> PilotUser | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.pop(token, None)
            if not session:
                return None
            user: PilotUser = session["user"]
            if self._lease and self._lease["username"] == user.username:
                self._lease = None
            return user

    def _active_lease(self, now: float | None = None) -> dict[str, Any] | None:
        current = time.time() if now is None else now
        if self._lease and float(self._lease["expires_at"]) <= current:
            self._lease = None
        return self._lease

    def lease_status(self, username: str) -> dict[str, Any]:
        with self._lock:
            lease = self._active_lease()
            if not lease:
                return {"active": False, "owned_by_me": False}
            return {
                "active": True,
                "owned_by_me": lease["username"] == username,
                "holder_display_name": lease["display_name"],
                "expires_at": lease["expires_at"],
            }

    def acquire_lease(self, user: PilotUser) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            lease = self._active_lease(now)
            if lease and lease["username"] != user.username:
                raise EditLeaseError(f"当前由{lease['display_name']}编辑，请稍后再试。")
            self._lease = {
                "username": user.username,
                "display_name": user.display_name,
                "expires_at": now + self.lease_seconds,
            }
            return self.lease_status(user.username)

    def heartbeat_lease(self, user: PilotUser) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            lease = self._active_lease(now)
            if not lease or lease["username"] != user.username:
                raise EditLeaseError("编辑权已失效，请重新取得编辑权。")
            lease["expires_at"] = now + self.lease_seconds
            return self.lease_status(user.username)

    def release_lease(self, user: PilotUser) -> dict[str, Any]:
        with self._lock:
            lease = self._active_lease()
            if lease and lease["username"] == user.username:
                self._lease = None
            return self.lease_status(user.username)

    def require_lease(self, username: str) -> None:
        with self._lock:
            lease = self._active_lease()
            if not lease or lease["username"] != username:
                raise EditLeaseError("当前没有编辑权，请先点击“开始编辑”。")

    def audit(
        self,
        *,
        username: str,
        request_id: str,
        method: str,
        path: str,
        status: int,
        event: str | None = None,
    ) -> None:
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "username": username,
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status,
        }
        if event:
            record["event"] = event
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_file.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
