"""
auth.py
-------
Simple multi-user accounts: anyone can sign up with a username + password,
and each account gets its own private folder (data/users/<id>/) holding
that student's curriculum, completed courses, wishlist and preferences.

Passwords are hashed with werkzeug (never stored in plaintext). Course
offerings (course_offerings.json) are shared between accounts since they're
the same registrar data for everybody.
"""

import json
import os
import re
import secrets
import shutil
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = "data"
USERS_PATH = os.path.join(DATA_DIR, "users.json")
USERS_DIR = os.path.join(DATA_DIR, "users")
SECRET_KEY_PATH = os.path.join(DATA_DIR, ".flask_secret")

# Files that used to live directly in data/ before accounts existed. The
# very first account created adopts them, so an existing curriculum isn't
# lost when sign-up is introduced.
_LEGACY_USER_FILES = ["degree_requirements.json", "wishlist.json"]

# Username format: 3-30 characters; letters, numbers, dot, underscore, hyphen
# (no spaces); must start and end with a letter or number. Uniqueness is
# case-insensitive ("Alice" and "alice" are the same account).
USERNAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._\-]{1,28}[A-Za-z0-9]"
USERNAME_RE = re.compile(f"^{USERNAME_PATTERN}$")
MIN_PASSWORD_LEN = 6


def _load_all():
    try:
        with open(USERS_PATH) as f:
            return json.load(f).get("users", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_all(users):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_PATH, "w") as f:
        json.dump({"users": users}, f, indent=2)


def all_users():
    return _load_all()


def is_admin(user):
    """The first account ever created is the admin (it's whoever set the app
    up), unless an account is explicitly flagged. Admins edit the shared
    academic calendar."""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    users = _load_all()
    return bool(users) and users[0]["id"] == user["id"]


def has_users():
    return bool(_load_all())


def get_user(user_id):
    for u in _load_all():
        if u["id"] == user_id:
            return u
    return None


def _find_by_username(username):
    wanted = (username or "").strip().lower()
    for u in _load_all():
        if u["username"].lower() == wanted:
            return u
    return None


def user_dir(user_id):
    path = os.path.join(USERS_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def create_user(username, password, confirm):
    """Returns (user, error). Exactly one of the two is None."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        return None, ("Username must be 3-30 characters: letters, numbers, and . _ - only "
                      "(no spaces), starting and ending with a letter or number.")
    if len(password or "") < MIN_PASSWORD_LEN:
        return None, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if password != confirm:
        return None, "Passwords don't match."
    if _find_by_username(username):
        return None, "That username is already taken — pick another, or log in."

    users = _load_all()
    first_account = not users
    user = {
        "id": secrets.token_hex(8),
        "username": username,
        "password_hash": generate_password_hash(password),
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    users.append(user)
    _save_all(users)

    folder = user_dir(user["id"])
    if first_account:
        for name in _LEGACY_USER_FILES:
            legacy = os.path.join(DATA_DIR, name)
            if os.path.exists(legacy):
                shutil.move(legacy, os.path.join(folder, name))
    return user, None


def authenticate(username, password):
    user = _find_by_username(username)
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


def get_or_create_secret_key():
    """A stable Flask session secret key persisted to disk, so sessions
    survive the dev server's auto-reload instead of logging everyone out
    on every file save."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH) as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(key)
    return key
