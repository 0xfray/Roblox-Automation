import time
import uuid

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from config import Config
from roblox_api import RobloxAPI


class AccountManager:
    """Manages multiple Roblox accounts with encrypted cookie storage."""

    def __init__(self, config: Config, console: Console):
        self.config = config
        self.console = console
        self._migrate_legacy_cookie()

    # ── migration ──────────────────────────────────────────────────────────

    def _migrate_legacy_cookie(self):
        """Migrate single-cookie config to accounts list on first run."""
        accounts = self.config.get("accounts", [])
        legacy_cookie = self.config.get_cookie()
        if legacy_cookie and not accounts:
            api = RobloxAPI(legacy_cookie)
            user = api.get_authenticated_user()
            if user:
                account = {
                    "id": str(uuid.uuid4()),
                    "roblox_user_id": user["id"],
                    "username": user["name"],
                    "display_name": user["displayName"],
                    "nickname": "",
                    "encrypted_cookie": self.config.encrypt_value(legacy_cookie),
                    "place_id": 0,
                    "game_id": "",
                }
                self.config.set("accounts", [account])
                self.config.clear_cookie()
                self.console.print(
                    f"[green]Migrated existing login ({user['displayName']}) "
                    f"to accounts list.[/]"
                )

    # ── CRUD ───────────────────────────────────────────────────────────────

    def get_all_accounts(self) -> list[dict]:
        return self.config.get("accounts", [])

    def _save_accounts(self, accounts: list[dict]):
        self.config.set("accounts", accounts)

    def _find_account(self, account_id: str) -> dict | None:
        for acc in self.get_all_accounts():
            if acc["id"] == account_id:
                return acc
        return None

    def add_account(self, cookie: str | None = None, nickname: str = "") -> dict | None:
        if cookie is None:
            cookie = Prompt.ask(
                "[cyan]Paste .ROBLOSECURITY cookie[/]",
                console=self.console,
            )
        cookie = cookie.strip()
        if not cookie:
            self.console.print("[red]Empty cookie.[/]")
            return None

        api = RobloxAPI(cookie)
        user = api.get_authenticated_user()
        if user is None:
            self.console.print("[red]Invalid cookie or request failed.[/]")
            return None

        # reject duplicates
        accounts = self.get_all_accounts()
        for acc in accounts:
            if acc["roblox_user_id"] == user["id"]:
                self.console.print(
                    f"[yellow]Account {user['displayName']} (@{user['name']}) "
                    f"already exists.[/]"
                )
                return None

        account = {
            "id": str(uuid.uuid4()),
            "roblox_user_id": user["id"],
            "username": user["name"],
            "display_name": user["displayName"],
            "nickname": nickname,
            "encrypted_cookie": self.config.encrypt_value(cookie),
            "place_id": 0,
            "game_id": "",
        }
        accounts.append(account)
        self._save_accounts(accounts)
        self.console.print(
            f"[green]Added account: {user['displayName']} (@{user['name']})[/]"
        )
        return account

    def add_account_browser(self, nickname: str = "") -> dict | None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.console.print(
                "[red]Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium[/]"
            )
            return None

        self.console.print(
            "[cyan]Opening browser — log in to Roblox, then wait...[/]"
        )

        cookie_value = None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://www.roblox.com/login")

                deadline = time.time() + 300
                while time.time() < deadline:
                    cookies = context.cookies("https://www.roblox.com")
                    for c in cookies:
                        if c["name"] == ".ROBLOSECURITY":
                            cookie_value = c["value"]
                            break
                    if cookie_value:
                        break
                    time.sleep(2)
                browser.close()
        except Exception as exc:
            self.console.print(f"[red]Browser error: {exc}[/]")
            return None

        if not cookie_value:
            self.console.print("[red]Timed out waiting for login.[/]")
            return None

        return self.add_account(cookie_value, nickname)

    def remove_account(self, account_id: str) -> bool:
        accounts = self.get_all_accounts()
        updated = [a for a in accounts if a["id"] != account_id]
        if len(updated) == len(accounts):
            return False
        self._save_accounts(updated)
        return True

    def rename_account(self, account_id: str, nickname: str):
        accounts = self.get_all_accounts()
        for acc in accounts:
            if acc["id"] == account_id:
                acc["nickname"] = nickname
                self._save_accounts(accounts)
                return True
        return False

    def set_place(self, account_id: str, place_id: int, game_id: str = ""):
        accounts = self.get_all_accounts()
        for acc in accounts:
            if acc["id"] == account_id:
                acc["place_id"] = place_id
                acc["game_id"] = game_id
                self._save_accounts(accounts)
                return True
        return False

    def get_decrypted_cookie(self, account_id: str) -> str:
        acc = self._find_account(account_id)
        if acc is None:
            return ""
        return self.config.decrypt_value(acc.get("encrypted_cookie", ""))

    def validate_account(self, account_id: str) -> bool:
        cookie = self.get_decrypted_cookie(account_id)
        if not cookie:
            return False
        api = RobloxAPI(cookie)
        return api.get_authenticated_user() is not None

    # ── display helpers ────────────────────────────────────────────────────

    def display_name(self, account: dict) -> str:
        nick = account.get("nickname", "")
        if nick:
            return f"{nick} ({account['display_name']})"
        return f"{account['display_name']} (@{account['username']})"

    def print_accounts_table(self):
        accounts = self.get_all_accounts()
        if not accounts:
            self.console.print("[dim]No accounts saved.[/]")
            return

        table = Table(title="Saved Accounts")
        table.add_column("#", style="bold")
        table.add_column("Nickname", style="cyan")
        table.add_column("Display Name")
        table.add_column("Username", style="dim")
        table.add_column("Place ID", justify="right")
        table.add_column("ID", style="dim")

        for i, acc in enumerate(accounts, 1):
            table.add_row(
                str(i),
                acc.get("nickname", "") or "-",
                acc["display_name"],
                f"@{acc['username']}",
                str(acc.get("place_id", 0)) if acc.get("place_id") else "-",
                acc["id"][:8],
            )
        self.console.print(table)
