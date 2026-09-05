"""Invite-only accounts stored in the application's backed-up data directory."""
import hashlib
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import bcrypt
from core.pilot_access import PilotAccessManager, PilotAccessError, LoginBlockedError, InvalidCredentialsError


class MemberAccounts(PilotAccessManager):
    def authenticate(self, username, password, client_ip):
        with self._lock:
            failures = self._prune_failures((client_ip, '__login__'), time.time())
            if len(failures) >= self.failure_limit:
                raise LoginBlockedError('登录尝试过多，请15分钟后再试。')
            try:
                result = super().authenticate(username, password, client_ip)
            except InvalidCredentialsError:
                failures.append(time.time())
                raise
            failures.clear()
            return result

    def lease_status(self, username):
        return {'active': True, 'owned_by_me': True, 'expires_at': time.time() + self.lease_seconds}

    def acquire_lease(self, user):
        return self.lease_status(user.username)

    def heartbeat_lease(self, user):
        return self.lease_status(user.username)

    def release_lease(self, user):
        return self.lease_status(user.username)

    def __init__(self, *, database, **kwargs):
        super().__init__(**kwargs)
        self.database = Path(database)

    @contextmanager
    def connect(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=15)
        db.execute('CREATE TABLE IF NOT EXISTS members (username TEXT PRIMARY KEY, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, created_at REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS invites (digest TEXT PRIMARY KEY, expires_at REAL NOT NULL, used_by TEXT)')
        db.commit()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _load_users(self):
        # Legacy users are deliberately not imported: their identities remain reserved.
        with self.connect() as db:
            return {u: {'display_name': n, 'password_hash': p, 'active': True}
                    for u, n, p in db.execute('SELECT username,display_name,password_hash FROM members')}

    def create_invite(self):
        code = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute('INSERT INTO invites VALUES (?,?,NULL)',
                       (hashlib.sha256(code.encode()).hexdigest(), time.time() + 7*86400))
        return code

    def register(self, username, display_name, password, invite, client_ip):
        username = username.strip().lower()
        display_name = display_name.strip()
        with self._lock:
            attempts = self._prune_failures((client_ip, '__registration__'), time.time())
            if len(attempts) >= self.failure_limit:
                raise LoginBlockedError('注册尝试过多，请15分钟后再试。')
            attempts.append(time.time())
            if not re.fullmatch(r'[a-z][a-z0-9_]{2,31}', username) or username in {'owner','admin','root','ma_trial','deng_trial'}:
                raise PilotAccessError('用户名需为3–32位小写字母、数字或下划线，并以字母开头。')
            if not 1 <= len(display_name) <= 40 or any(ord(c) < 32 for c in display_name):
                raise PilotAccessError('昵称需为1–40个字符。')
            if not 10 <= len(password) or len(password.encode()) > 72:
                raise PilotAccessError('密码至少10个字符，UTF-8长度不超过72字节。')
            # Reserve every former identity, including custom legacy accounts.
            try:
                old_users = super()._load_users()
            except PilotAccessError:
                old_users = {}
            if username in old_users:
                raise PilotAccessError('该用户名不可注册。')
            digest = hashlib.sha256(invite.strip().encode()).hexdigest()
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT expires_at,used_by FROM invites WHERE digest=?', (digest,)).fetchone()
                if not row or row[1] or row[0] <= time.time():
                    raise PilotAccessError('邀请码无效、已使用或已过期，请向负责人获取新的邀请码。')
                if db.execute('SELECT 1 FROM members WHERE username=?', (username,)).fetchone():
                    raise PilotAccessError('该用户名不可注册。')
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                db.execute('INSERT INTO members VALUES (?,?,?,?)', (username, display_name, hashed, time.time()))
                db.execute('UPDATE invites SET used_by=? WHERE digest=?', (username, digest))
            return self.create_session_for_user(username)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='生成7天内可使用一次的注册邀请码')
    parser.add_argument('action', choices=['invite'])
    parser.add_argument('--database', default='/var/lib/ai-climbing/data/accounts.sqlite3')
    args = parser.parse_args()
    manager = MemberAccounts(database=args.database, users_file='/etc/ai-climbing/pilot-users.json', audit_file='/dev/null')
    print(manager.create_invite())
