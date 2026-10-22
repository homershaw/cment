"""Users and sessions. Viewing needs no login; batch control and alarm acknowledge need an operator."""
import hashlib
import hmac
import secrets
import time

from .store import Store

ROLES = ("viewer", "operator", "admin")
SESSION_S = 12 * 3600
ITER = 200_000


def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${dk.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), dk)
    except ValueError:
        return False


def add_user(store: Store, username: str, password: str, role: str):
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    store.x("INSERT OR REPLACE INTO users (username, pw_hash, role, created) VALUES (?, ?, ?, ?)",
            (username, hash_pw(password), role, time.time()))


def login(store: Store, username: str, password: str) -> str | None:
    rows = store.q("SELECT pw_hash FROM users WHERE username = ?", (username,))
    if not rows or not check_pw(password, rows[0]["pw_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    store.x("INSERT INTO sessions (token, username, expires) VALUES (?, ?, ?)",
            (token, username, time.time() + SESSION_S))
    return token


def session_user(store: Store, token: str | None) -> dict | None:
    if not token:
        return None
    rows = store.q("SELECT u.username, u.role FROM sessions s JOIN users u ON u.username = s.username "
                   "WHERE s.token = ? AND s.expires > ?", (token, time.time()))
    return rows[0] if rows else None


def logout(store: Store, token: str | None):
    if token:
        store.x("DELETE FROM sessions WHERE token = ?", (token,))
