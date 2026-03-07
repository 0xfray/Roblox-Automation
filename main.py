#!/usr/bin/env python3
"""Headless Roblox CLI — minimal-rendering AFK launcher."""

import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt, Confirm

from config import Config
from auth import AuthManager
from roblox_api import RobloxAPI
from headless import HeadlessManager
from launcher import GameLauncher
from anti_afk import AntiAFK
from utils import is_roblox_running, kill_roblox_processes
from constants import MIN_AFK_INTERVAL, MAX_AFK_INTERVAL

BANNER = r"""
 _   _                _ _                 ____  _     _
| | | | ___  __ _  __| | | ___  ___ ___  |  _ \| |__ | |_  __
| |_| |/ _ \/ _` |/ _` | |/ _ \/ __/ __| | |_) | '_ \| \ \/ /
|  _  |  __/ (_| | (_| | |  __/\__ \__ \ |  _ <| |_) | |>  <
|_| |_|\___|\__,_|\__,_|_|\___||___/___/ |_| \_\_.__/|_/_/\_\
"""


class HeadlessRobloxCLI:
    def __init__(self):
        self.console = Console()
        self.config = Config()
        self.auth = AuthManager(self.config, self.console)
        self.headless = HeadlessManager(self.console)
        self.anti_afk = AntiAFK(self.console, self.config.get("afk_interval", 60))
        self.launcher: GameLauncher | None = None

    # ── display helpers ───────────────────────────────────────────────────

    def _banner(self):
        self.console.print(Panel(BANNER, style="bold cyan", subtitle="CLI AFK Launcher"))

    def _status(self):
        table = Table(title="Status", show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")

        # auth
        if self.auth.is_authenticated():
            u = self.auth.user_info
            table.add_row("User", f"{u['displayName']} (@{u['name']})")
        else:
            table.add_row("User", "[red]Not logged in[/]")

        # roblox process
        table.add_row(
            "Roblox",
            "[green]Running[/]" if is_roblox_running() else "[dim]Not running[/]",
        )

        # headless
        profile = self.headless.get_active_profile()
        table.add_row(
            "Headless",
            f"[green]{profile}[/]" if profile else "[dim]Off[/]",
        )

        # anti-afk
        if self.anti_afk.is_running():
            table.add_row(
                "Anti-AFK",
                f"[green]On[/] (every {self.anti_afk.interval}s, {self.anti_afk.strategy})",
            )
        else:
            table.add_row("Anti-AFK", "[dim]Off[/]")

        # auto-rejoin
        if self.launcher and self.launcher.is_auto_rejoin_active():
            table.add_row("Auto-Rejoin", "[green]On[/]")
        else:
            table.add_row("Auto-Rejoin", "[dim]Off[/]")

        # current game
        if self.launcher:
            st = self.launcher.get_status()
            if st["place_id"]:
                table.add_row("Game", str(st["place_id"]))

        self.console.print(table)
        self.console.print()

    # ── menus ─────────────────────────────────────────────────────────────

    def _main_menu(self):
        self.console.print("[bold]Main Menu[/]")
        self.console.print("  [1] Login")
        self.console.print("  [2] Join Game")
        self.console.print("  [3] Toggle Headless Mode")
        self.console.print("  [4] Toggle Anti-AFK")
        self.console.print("  [5] Settings")
        self.console.print("  [6] Status")
        self.console.print("  [7] Toggle Auto-Rejoin")
        self.console.print("  [8] Kill Roblox")
        self.console.print("  [0] Exit")
        return Prompt.ask(
            "[cyan]>[/]",
            choices=["0", "1", "2", "3", "4", "5", "6", "7", "8"],
            console=self.console,
        )

    # ── 1: login ──────────────────────────────────────────────────────────

    def _login_menu(self):
        self.console.print("[bold]Login[/]")
        self.console.print("  [1] Paste .ROBLOSECURITY cookie")
        self.console.print("  [2] Login via browser")
        self.console.print("  [3] Logout")
        self.console.print("  [0] Back")
        choice = Prompt.ask("[cyan]>[/]", choices=["0", "1", "2", "3"], console=self.console)
        if choice == "1":
            self.auth.login_with_cookie()
        elif choice == "2":
            self.auth.login_with_browser()
        elif choice == "3":
            self.auth.logout()
        self._ensure_launcher()

    # ── 2: join ───────────────────────────────────────────────────────────

    def _join_menu(self):
        if not self.auth.is_authenticated():
            self.console.print("[red]Login first.[/]")
            return
        self._ensure_launcher()

        self.console.print("[bold]Join Game[/]")
        self.console.print("  [1] By Place ID")
        self.console.print("  [2] Server browser")
        self.console.print("  [3] Join friend's game")
        self.console.print("  [4] Deep link")
        self.console.print("  [0] Back")
        choice = Prompt.ask(
            "[cyan]>[/]",
            choices=["0", "1", "2", "3", "4"],
            console=self.console,
        )
        if choice == "1":
            self.launcher.join_by_place_id()
        elif choice == "2":
            self.launcher.join_specific_server()
        elif choice == "3":
            self.launcher.join_friend(self.auth.user_info["id"])
        elif choice == "4":
            self.launcher.join_deep_link()

    # ── 3: headless ───────────────────────────────────────────────────────

    def _headless_menu(self):
        self.console.print("[bold]Headless Mode[/]")
        self.console.print("  [1] Enable Potato Mode (recommended)")
        self.console.print("  [2] Enable Legacy Headless (likely ignored)")
        self.console.print("  [3] Disable / restore original")
        self.console.print("  [4] Show current FFlags")
        self.console.print("  [5] Show allowlist status")
        self.console.print("  [0] Back")
        choice = Prompt.ask(
            "[cyan]>[/]",
            choices=["0", "1", "2", "3", "4", "5"],
            console=self.console,
        )
        if choice == "1":
            self.headless.apply_profile("potato")
        elif choice == "2":
            self.headless.apply_profile("legacy")
        elif choice == "3":
            self.headless.remove_profile()
        elif choice == "4":
            self.headless.show_current_flags()
        elif choice == "5":
            status = self.headless.get_allowlist_status()
            self.console.print(f"[green]Allowed ({len(status['allowed'])}):[/] {', '.join(status['allowed']) or 'none'}")
            self.console.print(f"[red]Blocked ({len(status['blocked'])}):[/] {', '.join(status['blocked']) or 'none'}")

    # ── 4: anti-afk ──────────────────────────────────────────────────────

    def _toggle_anti_afk(self):
        if self.anti_afk.is_running():
            self.anti_afk.stop()
        else:
            self.anti_afk.set_interval(self.config.get("afk_interval", 60))
            self.anti_afk.set_strategy(self.config.get("afk_strategy", "foreground"))
            self.anti_afk.start()

    # ── 7: auto-rejoin ────────────────────────────────────────────────────

    def _toggle_auto_rejoin(self):
        if not self.auth.is_authenticated():
            self.console.print("[red]Login first.[/]")
            return
        self._ensure_launcher()

        if self.launcher.is_auto_rejoin_active():
            self.launcher.stop_auto_rejoin()
        else:
            self.launcher.start_auto_rejoin()

    # ── 5: settings ───────────────────────────────────────────────────────

    def _settings_menu(self):
        self.console.print("[bold]Settings[/]")
        self.console.print(f"  [1] Anti-AFK interval (current: {self.config.get('afk_interval')}s)")
        self.console.print(f"  [2] Anti-AFK strategy (current: {self.config.get('afk_strategy')})")
        self.console.print(f"  [3] Default headless profile (current: {self.config.get('headless_profile')})")
        self.console.print("  [4] Clear saved cookie")
        self.console.print("  [0] Back")
        choice = Prompt.ask(
            "[cyan]>[/]",
            choices=["0", "1", "2", "3", "4"],
            console=self.console,
        )
        if choice == "1":
            val = IntPrompt.ask(
                f"[cyan]Interval in seconds ({MIN_AFK_INTERVAL}-{MAX_AFK_INTERVAL})[/]",
                console=self.console,
            )
            val = max(MIN_AFK_INTERVAL, min(MAX_AFK_INTERVAL, val))
            self.config.set("afk_interval", val)
            self.anti_afk.set_interval(val)
            self.console.print(f"[green]Anti-AFK interval set to {val}s.[/]")
        elif choice == "2":
            strat = Prompt.ask(
                "[cyan]Strategy[/]",
                choices=["foreground", "sendmessage"],
                console=self.console,
            )
            self.config.set("afk_strategy", strat)
            self.anti_afk.set_strategy(strat)
            self.console.print(f"[green]Strategy set to {strat}.[/]")
        elif choice == "3":
            prof = Prompt.ask(
                "[cyan]Profile[/]",
                choices=["potato", "legacy"],
                console=self.console,
            )
            self.config.set("headless_profile", prof)
            self.console.print(f"[green]Default profile set to {prof}.[/]")
        elif choice == "4":
            self.config.clear_cookie()
            self.console.print("[yellow]Cookie cleared.[/]")

    # ── helpers ───────────────────────────────────────────────────────────

    def _ensure_launcher(self):
        if self.auth.is_authenticated() and self.launcher is None:
            self.launcher = GameLauncher(self.auth.get_api(), self.console)

    def _cleanup(self):
        if self.launcher and self.launcher.is_auto_rejoin_active():
            self.launcher.stop_auto_rejoin()
        if self.anti_afk.is_running():
            self.anti_afk.stop()
        if self.headless.is_active():
            if Confirm.ask(
                "[yellow]Restore original Roblox settings?[/]",
                default=True,
                console=self.console,
            ):
                self.headless.restore()
        self.config.save()

    # ── run ───────────────────────────────────────────────────────────────

    def run(self):
        self._banner()

        # auto-login with saved cookie
        if self.auth.try_saved_cookie():
            self.console.print(
                f"[green]Auto-logged in as {self.auth.user_info['displayName']}[/]"
            )
            self._ensure_launcher()
        else:
            self.console.print("[yellow]No saved session — please login.[/]")

        self.console.print()

        try:
            while True:
                self._status()
                choice = self._main_menu()
                self.console.print()

                if choice == "0":
                    break
                elif choice == "1":
                    self._login_menu()
                elif choice == "2":
                    self._join_menu()
                elif choice == "3":
                    self._headless_menu()
                elif choice == "4":
                    self._toggle_anti_afk()
                elif choice == "5":
                    self._settings_menu()
                elif choice == "6":
                    pass  # status is printed every loop
                elif choice == "7":
                    self._toggle_auto_rejoin()
                elif choice == "8":
                    if Confirm.ask("[red]Kill all Roblox processes?[/]", default=False, console=self.console):
                        kill_roblox_processes()
                        self.console.print("[yellow]Roblox processes killed.[/]")

                self.console.print()
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Interrupted.[/]")
        finally:
            self._cleanup()
            self.console.print("[dim]Goodbye.[/]")


if __name__ == "__main__":
    HeadlessRobloxCLI().run()
