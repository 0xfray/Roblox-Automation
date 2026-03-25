import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

from constants import CONFIG_FILE, KEY_FILE, DEFAULT_AFK_INTERVAL


class Config:
    DEFAULTS = {
        "cookie": "",
        "default_headless": False,
        "afk_interval": DEFAULT_AFK_INTERVAL,
        "afk_enabled": True,
        "headless_profile": "potato",
        "restaurant_profile": "",
        "restaurant_auto_start": False,
        "accounts": [],
    }

    def __init__(self, base_dir: str | None = None):
        self._base = Path(base_dir) if base_dir else Path(__file__).parent
        self._path = self._base / CONFIG_FILE
        self._key_path = self._base / KEY_FILE
        self._data: dict = {}
        self.load()

    # ── persistence ───────────────────────────────────────────────────────

    def load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}
        # fill in missing keys with defaults
        for k, v in self.DEFAULTS.items():
            self._data.setdefault(k, v)

    def save(self):
        self._path.write_text(
            json.dumps(self._data, indent=2),
            encoding="utf-8",
        )

    # ── getters / setters ─────────────────────────────────────────────────

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    # ── cookie encryption ─────────────────────────────────────────────────

    def _get_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        return key

    def encrypt_value(self, plaintext: str) -> str:
        fernet = Fernet(self._get_or_create_key())
        return fernet.encrypt(plaintext.encode()).decode()

    def decrypt_value(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            fernet = Fernet(self._get_or_create_key())
            return fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    def store_cookie(self, cookie: str):
        self.set("cookie", self.encrypt_value(cookie))

    def get_cookie(self) -> str:
        return self.decrypt_value(self._data.get("cookie", ""))

    def clear_cookie(self):
        self.set("cookie", "")
