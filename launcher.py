import os
import glob
import time
import random
import re
import threading
from pathlib import Path
from urllib.parse import quote

from rich.console import Console
from rich.table import Table
from rich.prompt import IntPrompt, Prompt

from roblox_api import RobloxAPI
from constants import ASSET_GAME_URL
from utils import is_roblox_running, kill_roblox_processes, get_roblox_base_path

DEFAULT_REJOIN_DELAY = 15   # seconds to wait before rejoining
LOG_POLL_INTERVAL = 3       # how often to check log for disconnects

# Log patterns that mean the player got disconnected / kicked
DISCONNECT_PATTERNS = re.compile(
    r"leaveUGCGameInternal"
    r"|Idle Timeout"
    r"|ERR_IDLE_CLOSE"
    r"|Connection closed by server"
    r"|Disconnected from server for reason"
    r"|Connection lost"
    r"|hardDisconnect"
    r"|kicked",
    re.IGNORECASE,
)


class GameLauncher:
    """Handles joining Roblox games via the roblox-player: protocol."""

    def __init__(self, api: RobloxAPI, console: Console):
        self.api = api
        self.console = console
        self.current_place_id: int | None = None
        self.current_game_id: str | None = None

        # auto-rejoin state
        self._rejoin_enabled = False
        self._rejoin_thread: threading.Thread | None = None
        self._rejoin_delay = DEFAULT_REJOIN_DELAY

    # ── internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _browser_tracker_id() -> int:
        return random.randint(10_000_000_000, 99_999_999_999)

    def _place_launcher_url(self, place_id: int, game_id: str | None = None) -> str:
        url = (
            f"{ASSET_GAME_URL}"
            f"?request=RequestGame"
            f"&browserTrackerId={self._browser_tracker_id()}"
            f"&placeId={place_id}"
            f"&isPlayTogetherGame=false"
            f"&robloxLocale=en_us"
            f"&gameLocale=en_us"
            f"&channel="
        )
        if game_id:
            url += f"&gameId={game_id}"
        return url

    # ── core launch ───────────────────────────────────────────────────────

    def _launch(self, place_id: int, game_id: str | None = None) -> bool:
        ticket = self.api.get_auth_ticket()
        if ticket is None:
            self.console.print("[red]Failed to get auth ticket.[/]")
            return False

        launcher_url = self._place_launcher_url(place_id, game_id)
        launch_time = int(time.time() * 1000)

        # Modern Roblox launch protocol
        protocol_uri = (
            f"roblox-player:1"
            f"+launchmode:play"
            f"+gameinfo:{ticket}"
            f"+launchtime:{launch_time}"
            f"+placelauncherurl:{quote(launcher_url, safe='')}"
            f"+browsertrackerid:{self._browser_tracker_id()}"
            f"+robloxLocale:en_us"
            f"+gameLocale:en_us"
            f"+channel:"
        )

        self.console.print(f"[cyan]Joining place {place_id}...[/]")

        try:
            os.startfile(protocol_uri)
        except OSError as exc:
            self.console.print(f"[red]Failed to launch Roblox: {exc}[/]")
            return False

        self.current_place_id = place_id
        self.current_game_id = game_id

        self.console.print("[green]Roblox launch triggered.[/]")

        # Wait a moment and verify
        time.sleep(5)
        if is_roblox_running():
            self.console.print("[green]Roblox process is running.[/]")
        else:
            self.console.print(
                "[yellow]Roblox process not detected yet — "
                "it may still be starting.[/]"
            )
        return True

    # ── join methods ──────────────────────────────────────────────────────

    def join_by_place_id(self) -> bool:
        raw = Prompt.ask("[cyan]Enter Place ID[/]", console=self.console)
        try:
            place_id = int(raw.strip())
        except ValueError:
            self.console.print("[red]Invalid Place ID.[/]")
            return False
        return self._launch(place_id)

    def join_specific_server(self) -> bool:
        raw = Prompt.ask("[cyan]Enter Place ID[/]", console=self.console)
        try:
            place_id = int(raw.strip())
        except ValueError:
            self.console.print("[red]Invalid Place ID.[/]")
            return False

        self.console.print("[cyan]Fetching servers...[/]")
        data = self.api.get_servers(place_id, limit=10)
        if data is None or not data.get("data"):
            self.console.print("[red]No servers found or request failed.[/]")
            return False

        servers = data["data"]
        table = Table(title=f"Servers for Place {place_id}")
        table.add_column("#", style="bold")
        table.add_column("Players", justify="center")
        table.add_column("Max", justify="center")
        table.add_column("FPS", justify="center")
        table.add_column("Ping", justify="center")
        table.add_column("Server ID", style="dim")

        for i, s in enumerate(servers, 1):
            table.add_row(
                str(i),
                str(s.get("playing", "?")),
                str(s.get("maxPlayers", "?")),
                str(s.get("fps", "?")),
                str(s.get("ping", "?")),
                s.get("id", "?")[:16] + "...",
            )
        self.console.print(table)

        choice = IntPrompt.ask(
            "[cyan]Pick a server #[/]",
            choices=[str(i) for i in range(1, len(servers) + 1)],
            console=self.console,
        )
        selected = servers[choice - 1]
        return self._launch(place_id, game_id=selected["id"])

    def join_friend(self, user_id: int) -> bool:
        self.console.print("[cyan]Fetching friends...[/]")
        friends = self.api.get_friends(user_id)
        if not friends:
            self.console.print("[red]No friends found.[/]")
            return False

        friend_ids = [f["id"] for f in friends]
        # presence API accepts up to 100 ids per call
        presences = []
        for i in range(0, len(friend_ids), 100):
            batch = friend_ids[i : i + 100]
            presences.extend(self.api.get_user_presence(batch))

        in_game = [p for p in presences if p.get("userPresenceType") == 2]
        if not in_game:
            self.console.print("[yellow]No friends currently in a game.[/]")
            return False

        # map user_id → friend name
        name_map = {f["id"]: f.get("displayName", f["name"]) for f in friends}

        table = Table(title="Friends In-Game")
        table.add_column("#", style="bold")
        table.add_column("Name")
        table.add_column("Game")
        table.add_column("Place ID", justify="right")

        for i, p in enumerate(in_game, 1):
            table.add_row(
                str(i),
                name_map.get(p["userId"], str(p["userId"])),
                p.get("lastLocation", "Unknown"),
                str(p.get("placeId", "?")),
            )
        self.console.print(table)

        choice = IntPrompt.ask(
            "[cyan]Pick a friend #[/]",
            choices=[str(i) for i in range(1, len(in_game) + 1)],
            console=self.console,
        )
        selected = in_game[choice - 1]
        place_id = selected.get("rootPlaceId") or selected.get("placeId")
        game_id = selected.get("gameId")
        if not place_id:
            self.console.print("[red]Could not determine Place ID.[/]")
            return False
        return self._launch(int(place_id), game_id=game_id)

    def join_deep_link(self) -> bool:
        link = Prompt.ask("[cyan]Paste deep link URL[/]", console=self.console)
        link = link.strip()

        place_id = None
        game_id = None

        # roblox://placeId=123
        m = re.search(r"placeId=(\d+)", link)
        if m:
            place_id = int(m.group(1))

        m = re.search(r"gameInstanceId=([a-f0-9\-]+)", link, re.I)
        if m:
            game_id = m.group(1)

        if place_id is None:
            self.console.print("[red]Could not parse Place ID from link.[/]")
            return False

        return self._launch(place_id, game_id=game_id)

    # ── auto-rejoin ──────────────────────────────────────────────────────

    @staticmethod
    def _find_latest_log() -> Path | None:
        """Find the most recent Roblox Player log file."""
        log_dir = get_roblox_base_path() / "logs"
        if not log_dir.exists():
            return None
        logs = sorted(
            log_dir.glob("*_Player_*_last.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return logs[0] if logs else None

    def _rejoin_loop(self):
        # Give Roblox time to start and create a log file
        waited = 0
        while self._rejoin_enabled and waited < 30:
            if is_roblox_running():
                break
            time.sleep(1)
            waited += 1

        # Find the current log and seek to the end so we only watch NEW lines
        log_path = self._find_latest_log()
        log_pos = 0
        if log_path and log_path.exists():
            log_pos = log_path.stat().st_size

        while self._rejoin_enabled:
            # interruptible sleep
            for _ in range(LOG_POLL_INTERVAL):
                if not self._rejoin_enabled:
                    return
                time.sleep(1)

            place_id = self.current_place_id
            if place_id is None:
                continue

            triggered = False
            reason = ""

            # ── Check 1: process died (crash / force close) ──
            if not is_roblox_running():
                triggered = True
                reason = "Roblox process exited"

            # ── Check 2: scan log for disconnect / kick events ──
            if not triggered:
                # The log file may have rotated (new Roblox session = new file)
                current_log = self._find_latest_log()
                if current_log and current_log != log_path:
                    log_path = current_log
                    log_pos = 0

                if log_path and log_path.exists():
                    try:
                        size = log_path.stat().st_size
                        if size > log_pos:
                            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                                f.seek(log_pos)
                                new_data = f.read()
                            log_pos = size

                            match = DISCONNECT_PATTERNS.search(new_data)
                            if match:
                                triggered = True
                                reason = match.group(0)
                        elif size < log_pos:
                            # file got truncated / replaced
                            log_pos = size
                    except OSError:
                        pass

            if not triggered:
                continue

            # ── Disconnect detected — rejoin ──
            self.console.print(
                f"\n[yellow]Disconnect detected ({reason}) — "
                f"rejoining in {self._rejoin_delay}s...[/]"
            )

            # interruptible delay
            for _ in range(self._rejoin_delay):
                if not self._rejoin_enabled:
                    return
                time.sleep(1)

            if not self._rejoin_enabled:
                return

            # Kill stale Roblox process sitting on the disconnect screen
            if is_roblox_running():
                self.console.print("[dim]Closing stale Roblox process...[/]")
                kill_roblox_processes()
                time.sleep(3)

            self.console.print(f"[cyan]Auto-rejoining place {place_id}...[/]")
            self._launch(place_id, game_id=self.current_game_id)

            # Wait for the new Roblox to start, then reset log tracking
            waited = 0
            while self._rejoin_enabled and waited < 30:
                if is_roblox_running():
                    break
                time.sleep(1)
                waited += 1

            # Point to the new log file and seek to end
            time.sleep(5)  # let Roblox write its startup lines
            log_path = self._find_latest_log()
            if log_path and log_path.exists():
                log_pos = log_path.stat().st_size

    def start_auto_rejoin(self, delay: int | None = None):
        if self.current_place_id is None:
            self.console.print("[red]Join a game first so auto-rejoin knows where to go.[/]")
            return
        if self._rejoin_enabled:
            return
        if delay is not None:
            self._rejoin_delay = delay
        self._rejoin_enabled = True
        self._rejoin_thread = threading.Thread(target=self._rejoin_loop, daemon=True)
        self._rejoin_thread.start()
        self.console.print(
            f"[green]Auto-rejoin enabled (delay: {self._rejoin_delay}s, "
            f"place: {self.current_place_id}).[/]"
        )

    def stop_auto_rejoin(self):
        self._rejoin_enabled = False
        if self._rejoin_thread:
            self._rejoin_thread.join(timeout=5)
            self._rejoin_thread = None
        self.console.print("[yellow]Auto-rejoin disabled.[/]")

    def is_auto_rejoin_active(self) -> bool:
        return self._rejoin_enabled

    # ── status ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "running": is_roblox_running(),
            "place_id": self.current_place_id,
            "game_id": self.current_game_id,
            "auto_rejoin": self._rejoin_enabled,
        }
