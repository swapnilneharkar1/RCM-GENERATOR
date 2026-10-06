"""
auth.py - simple per-user login for the RCM Generator Streamlit app.

Why this instead of a pip package (streamlit-authenticator, bcrypt, etc.):
Your server has no open internet access, and every extra dependency means
another offline wheel-download-and-transfer round trip (same as you already
did for faster-whisper). This uses ONLY Python's standard library
(hashlib + secrets), so the only new package you need to get onto the server
for the whole interface is Streamlit itself.

How accounts are stored:
    users.json (next to this file) - one entry per user:
        {
          "swapnil": {"salt": "<hex>", "hash": "<hex>", "display_name": "Swapnil"}
        }
    Passwords are never stored in plain text - PBKDF2-HMAC-SHA256 with a
    random 16-byte salt per user, 200,000 iterations (OWASP-recommended
    minimum as of 2023+ guidance).

Adding/removing users:
    Use create_user.py (run on the server, no internet needed):
        python create_user.py add swapnil "Swapnil"
        python create_user.py remove swapnil
        python create_user.py list

Usage in app.py:
    import auth
    user = auth.login_gate()   # shows a login form, halts the script (st.stop())
                                # until a valid login happens; returns the
                                # logged-in username once authenticated.
    ...
    auth.logout_button()       # put in the sidebar
"""

import hashlib
import hmac
import json
import secrets
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).parent
USERS_FILE = BASE_DIR / "users.json"

PBKDF2_ITERATIONS = 200_000


def _load_users() -> dict:
    # 1) Local / server: use users.json if it exists
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    # 2) Streamlit Cloud: read users from Secrets
    try:
        return {name: dict(info) for name, info in st.secrets["users"].items()}
    except Exception:
        return {}


def export_secrets_toml():
    """Print users.json in the format to paste into Streamlit Secrets."""
    for name, info in _load_users().items():
        print(f'[users."{name}"]')
        print(f'salt = "{info["salt"]}"')
        print(f'hash = "{info["hash"]}"')
        print(f'display_name = "{info.get("display_name", name)}"')
        print()


def _save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def hash_password(password: str, salt: bytes = None) -> tuple:
    """Returns (salt_hex, hash_hex). Generates a new random salt if not given."""
    if salt is None:
        salt = secrets.token_bytes(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), pw_hash.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    _, candidate_hash_hex = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash_hex, hash_hex)


def add_user(username: str, password: str, display_name: str = ""):
    users = _load_users()
    salt_hex, hash_hex = hash_password(password)
    users[username] = {
        "salt": salt_hex,
        "hash": hash_hex,
        "display_name": display_name or username,
    }
    _save_users(users)


def remove_user(username: str) -> bool:
    users = _load_users()
    if username in users:
        del users[username]
        _save_users(users)
        return True
    return False


def list_users() -> list:
    return sorted(_load_users().keys())


def authenticate(username: str, password: str) -> bool:
    users = _load_users()
    entry = users.get(username)
    if not entry:
        return False
    return verify_password(password, entry["salt"], entry["hash"])


def login_gate() -> str:
    """
    Renders a login form if the user isn't authenticated yet, and calls
    st.stop() so the rest of the page doesn't render until they log in.
    Returns the logged-in username when authentication has succeeded
    (on this call or a previous one in the same browser session).
    """
    if st.session_state.get("authenticated_user"):
        return st.session_state["authenticated_user"]

    st.title("RCM Generator - Sign in")

    if not USERS_FILE.exists() or not _load_users():
        st.warning(
            "No user accounts have been set up yet. Ask your admin to run:\n\n"
            "`python create_user.py add <username> \"<Display Name>\"`\n\n"
            "on the server to create the first account."
        )
        st.stop()

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if authenticate(username, password):
            st.session_state["authenticated_user"] = username
            st.rerun()
        else:
            st.error("Incorrect username or password.")

    st.stop()


def logout_button():
    user = st.session_state.get("authenticated_user")
    if user:
        users = _load_users()
        display = users.get(user, {}).get("display_name", user)
        st.sidebar.markdown(f"Signed in as **{display}**")
        if st.sidebar.button("Log out"):
            del st.session_state["authenticated_user"]
            st.rerun()
