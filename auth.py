import time

from rich.console import Console
from rich.prompt import Prompt

from config import Config
from roblox_api import RobloxAPI


class AuthManager:
    """Handles Roblox authentication via cookie or browser login."""

    def __init__(self, config: Config, console: Console):
        self.config = config
        self.console = console
        self.api: RobloxAPI | None = None
        self.user_info: dict | None = None

    # ── cookie login ──────────────────────────────────────────────────────

    def login_with_cookie(self, cookie: str | None = None) -> bool:
        if cookie is None:
            cookie = Prompt.ask(
                "[cyan]Paste your .ROBLOSECURITY cookie[/]",
                console=self.console,
            )
        cookie = cookie.strip()
        if not cookie:
            self.console.print("[red]Empty cookie.[/]")
            return False

        api = RobloxAPI(cookie)
        user = api.get_authenticated_user()
        if user is None:
            self.console.print("[red]Invalid cookie or request failed.[/]")
            return False

        self.api = api
        self.user_info = user
        self.config.store_cookie(cookie)
        self.console.print(
            f"[green]Logged in as [bold]{user['displayName']}[/bold] "
            f"(@{user['name']}, ID: {user['id']})[/]"
        )
        return True

    # ── browser login ─────────────────────────────────────────────────────

    def login_with_browser(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.console.print(
                "[red]Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium[/]"
            )
            return False

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

                # Poll for the .ROBLOSECURITY cookie (up to 5 minutes)
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
            self.console.print(
                "[yellow]You may need to run: playwright install chromium[/]"
            )
            return False

        if not cookie_value:
            self.console.print("[red]Timed out waiting for login.[/]")
            return False

        return self.login_with_cookie(cookie_value)

    # ── saved cookie ──────────────────────────────────────────────────────

    def try_saved_cookie(self) -> bool:
        cookie = self.config.get_cookie()
        if not cookie:
            return False
        api = RobloxAPI(cookie)
        user = api.get_authenticated_user()
        if user is None:
            return False
        self.api = api
        self.user_info = user
        return True

    # ── helpers ───────────────────────────────────────────────────────────

    def is_authenticated(self) -> bool:
        return self.api is not None and self.user_info is not None

    def get_api(self) -> RobloxAPI:
        if self.api is None:
            raise RuntimeError("Not authenticated")
        return self.api

    def logout(self):
        self.api = None
        self.user_info = None
        self.config.clear_cookie()
        self.console.print("[yellow]Logged out.[/]")
