import os
import re
import time
import random
import threading

from launcher import _open_uri
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from roblox_api import RobloxAPI
from account_manager import AccountManager
from launcher import build_protocol_uri, DISCONNECT_PATTERNS, LOG_POLL_INTERVAL, DEFAULT_REJOIN_DELAY
from constants import AFK_KEYS
from utils import (
    find_roblox_pids,
    get_window_handle_for_pid,
    kill_roblox_process,
    is_pid_alive,
    close_roblox_mutex,
    acquire_roblox_singleton,
    close_roblox_singleton_in_processes,
    get_roblox_base_path,
)
from background_input import send_key, send_click, get_window_size


@dataclass
class RobloxInstance:
    account_id: str
    account_name: str
    api: RobloxAPI
    pid: int | None = None
    place_id: int | None = None
    game_id: str | None = None
    hwnd: int | None = None
    rejoin_enabled: bool = False
    rejoin_thread: threading.Thread | None = field(default=None, repr=False)
    afk_enabled: bool = False
    afk_thread: threading.Thread | None = field(default=None, repr=False)
    status: str = "idle"
    sandbox: object | None = field(default=None, repr=False)


class InstanceManager:
    """Manages multiple simultaneous Roblox instances."""

    def __init__(self, console: Console, account_manager: AccountManager):
        self.console = console
        self.account_manager = account_manager
        self._instances: dict[str, RobloxInstance] = {}  # account_id -> instance
        self._launch_lock = threading.Lock()

    # ── launching ──────────────────────────────────────────────────────────

    def launch(
        self,
        account_id: str,
        place_id: int | None = None,
        game_id: str | None = None,
        sandbox=None,
    ) -> RobloxInstance | None:
        """Launch a Roblox instance for the given account."""
        # Get account info
        acc = self.account_manager._find_account(account_id)
        if acc is None:
            self.console.print("[red]Account not found.[/]")
            return None

        # Use account's saved place if none provided
        if place_id is None:
            place_id = acc.get("place_id", 0)
        if game_id is None:
            game_id = acc.get("game_id", "") or None

        if not place_id:
            self.console.print(
                f"[red]No Place ID set for {self.account_manager.display_name(acc)}. "
                f"Set one in Accounts > Set game.[/]"
            )
            return None

        cookie = self.account_manager.get_decrypted_cookie(account_id)
        if not cookie:
            self.console.print("[red]Failed to decrypt cookie.[/]")
            return None

        api = RobloxAPI(cookie)
        name = self.account_manager.display_name(acc)

        with self._launch_lock:
            # STEP 1: Close singleton handles in any already-running Roblox
            # processes. This is the key to multi-instance — each running
            # Roblox holds a mutex+event that blocks new instances.
            running_pids = find_roblox_pids()
            if running_pids:
                self.console.print(
                    f"[dim]Closing singleton handles in {len(running_pids)} "
                    f"running Roblox process(es)...[/]"
                )
                closed = close_roblox_singleton_in_processes()
                if closed > 0:
                    self.console.print(f"[dim]Closed {closed} singleton handle(s).[/]")
                else:
                    self.console.print(
                        "[yellow]Warning: Could not find singleton handles to close. "
                        "Multi-instance may fail.[/]"
                    )
                # Give Windows time to fully release the kernel objects
                time.sleep(2)

            # STEP 2: Get auth ticket
            ticket = api.get_auth_ticket()
            if ticket is None:
                self.console.print(f"[red]Failed to get auth ticket for {name}.[/]")
                return None

            protocol_uri = build_protocol_uri(ticket, place_id, game_id)

            # STEP 3: Snapshot PIDs before launch
            pids_before = find_roblox_pids()

            self.console.print(f"[cyan]Launching {name} into place {place_id}...[/]")

            # STEP 4: Launch
            if sandbox and sandbox.is_active():
                if not sandbox.launch(protocol_uri):
                    self.console.print(f"[red]Failed to launch on sandbox for {name}.[/]")
                    return None
            else:
                try:
                    _open_uri(protocol_uri)
                except OSError as exc:
                    self.console.print(f"[red]Failed to launch Roblox for {name}: {exc}[/]")
                    return None

            # STEP 5: Wait for the new Roblox process to appear
            new_pid = self._wait_for_new_pid(pids_before, timeout=30)

        # Create instance record
        instance = RobloxInstance(
            account_id=account_id,
            account_name=name,
            api=api,
            pid=new_pid,
            place_id=place_id,
            game_id=game_id,
            status="running" if new_pid else "launching",
            sandbox=sandbox,
        )

        # Find window handle after a brief delay
        if new_pid:
            time.sleep(3)
            instance.hwnd = get_window_handle_for_pid(new_pid)
            self.console.print(f"[green]{name} is running (PID: {new_pid}).[/]")
        else:
            self.console.print(
                f"[yellow]{name} launch triggered but PID not detected yet.[/]"
            )

        self._instances[account_id] = instance

        # Rejoin and anti-AFK are OFF by default — user enables via toggles

        return instance

    def launch_all(self, sandbox=None) -> list[RobloxInstance]:
        """Launch all saved accounts using their saved Place IDs."""
        accounts = self.account_manager.get_all_accounts()
        results = []
        for i, acc in enumerate(accounts):
            if acc["id"] in self._instances:
                self.console.print(
                    f"[yellow]{self.account_manager.display_name(acc)} "
                    f"is already running, skipping.[/]"
                )
                continue
            instance = self.launch(acc["id"], sandbox=sandbox)
            if instance:
                results.append(instance)
            # Delay between launches — Roblox needs time to fully start
            # before we can close its singleton handles for the next one
            if i < len(accounts) - 1:
                self.console.print("[dim]Waiting before next launch...[/]")
                time.sleep(8)
        return results

    def _wait_for_new_pid(self, pids_before: set[int], timeout: int = 20) -> int | None:
        """Wait for a new Roblox process to appear."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(1)
            current_pids = find_roblox_pids()
            new_pids = current_pids - pids_before
            if new_pids:
                return new_pids.pop()
        return None

    # ── stopping ───────────────────────────────────────────────────────────

    def stop(self, account_id: str):
        """Stop a specific instance."""
        instance = self._instances.get(account_id)
        if instance is None:
            return

        self._stop_rejoin(instance)
        self._stop_afk(instance)

        if instance.pid and is_pid_alive(instance.pid):
            kill_roblox_process(instance.pid)
            self.console.print(f"[yellow]Stopped {instance.account_name}.[/]")

        instance.status = "stopped"
        del self._instances[account_id]

    def stop_all(self):
        """Stop all running instances."""
        for account_id in list(self._instances.keys()):
            self.stop(account_id)

    # ── per-instance auto-rejoin ───────────────────────────────────────────

    def _start_rejoin(self, instance: RobloxInstance):
        if instance.rejoin_enabled:
            return
        instance.rejoin_enabled = True
        instance.rejoin_thread = threading.Thread(
            target=self._rejoin_loop,
            args=(instance,),
            daemon=True,
        )
        instance.rejoin_thread.start()

    def _stop_rejoin(self, instance: RobloxInstance):
        instance.rejoin_enabled = False
        if instance.rejoin_thread:
            instance.rejoin_thread.join(timeout=5)
            instance.rejoin_thread = None

    def toggle_rejoin(self, account_id: str):
        instance = self._instances.get(account_id)
        if instance is None:
            return
        if instance.rejoin_enabled:
            self._stop_rejoin(instance)
            self.console.print(f"[yellow]Auto-rejoin disabled for {instance.account_name}.[/]")
        else:
            self._start_rejoin(instance)
            self.console.print(f"[green]Auto-rejoin enabled for {instance.account_name}.[/]")

    def toggle_rejoin_all(self):
        for instance in self._instances.values():
            if not instance.rejoin_enabled:
                self._start_rejoin(instance)
        self.console.print("[green]Auto-rejoin enabled for all instances.[/]")

    def _find_log_for_instance(self, instance: RobloxInstance) -> Path | None:
        """Find the log file associated with this instance's PID."""
        log_dir = get_roblox_base_path() / "logs"
        if not log_dir.exists():
            return None

        # Try to find a log file that matches this instance
        # Roblox logs are named like: timestamp_GUID_Player_GUID_last.log
        logs = sorted(
            log_dir.glob("*_Player_*_last.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not logs:
            return None

        # If we have a PID, try to find the log that references it
        # Otherwise just use the most recent one not claimed by another instance
        claimed_logs = set()
        for other in self._instances.values():
            if other.account_id != instance.account_id and hasattr(other, '_log_path'):
                if other._log_path:
                    claimed_logs.add(other._log_path)

        for log in logs:
            if log not in claimed_logs:
                return log

        return logs[0] if logs else None

    def _rejoin_loop(self, instance: RobloxInstance):
        """Auto-rejoin loop for a single instance."""
        # Wait for Roblox to start
        waited = 0
        while instance.rejoin_enabled and waited < 30:
            if instance.pid and is_pid_alive(instance.pid):
                break
            time.sleep(1)
            waited += 1

        # Find log and seek to end
        log_path = self._find_log_for_instance(instance)
        instance._log_path = log_path
        log_pos = 0
        if log_path and log_path.exists():
            log_pos = log_path.stat().st_size

        while instance.rejoin_enabled:
            # Interruptible sleep
            for _ in range(LOG_POLL_INTERVAL):
                if not instance.rejoin_enabled:
                    return
                time.sleep(1)

            if instance.place_id is None:
                continue

            triggered = False
            reason = ""

            # Check 1: process died
            if instance.pid and not is_pid_alive(instance.pid):
                triggered = True
                reason = "Process exited"

            # Check 2: log disconnect patterns
            if not triggered and log_path and log_path.exists():
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
                        log_pos = size
                except OSError:
                    pass

            if not triggered:
                continue

            # Disconnect detected — rejoin
            instance.status = "disconnected"
            self.console.print(
                f"\n[yellow][{instance.account_name}] Disconnect ({reason}) — "
                f"rejoining in {DEFAULT_REJOIN_DELAY}s...[/]"
            )

            # Interruptible delay
            for _ in range(DEFAULT_REJOIN_DELAY):
                if not instance.rejoin_enabled:
                    return
                time.sleep(1)

            if not instance.rejoin_enabled:
                return

            # Kill stale process
            if instance.pid and is_pid_alive(instance.pid):
                self.console.print(f"[dim][{instance.account_name}] Closing stale process...[/]")
                kill_roblox_process(instance.pid)
                time.sleep(3)

            # Close singleton handles in all running Roblox processes before relaunch
            if find_roblox_pids():
                close_roblox_singleton_in_processes()
                time.sleep(2)

            # Get new auth ticket and relaunch
            ticket = instance.api.get_auth_ticket()
            if ticket is None:
                self.console.print(
                    f"[red][{instance.account_name}] Failed to get auth ticket for rejoin.[/]"
                )
                continue

            protocol_uri = build_protocol_uri(ticket, instance.place_id, instance.game_id)
            pids_before = find_roblox_pids()

            self.console.print(
                f"[cyan][{instance.account_name}] Rejoining place {instance.place_id}...[/]"
            )

            if instance.sandbox and instance.sandbox.is_active():
                instance.sandbox.launch(protocol_uri)
            else:
                try:
                    _open_uri(protocol_uri)
                except OSError:
                    continue

            # Detect new PID
            new_pid = self._wait_for_new_pid(pids_before, timeout=20)
            if new_pid:
                instance.pid = new_pid
                instance.status = "running"
                time.sleep(3)
                instance.hwnd = get_window_handle_for_pid(new_pid)
            else:
                instance.status = "launching"

            # Reset log tracking
            time.sleep(5)
            log_path = self._find_log_for_instance(instance)
            instance._log_path = log_path
            if log_path and log_path.exists():
                log_pos = log_path.stat().st_size

    # ── per-instance anti-AFK ──────────────────────────────────────────────

    def _start_afk(self, instance: RobloxInstance):
        if instance.afk_enabled:
            return
        instance.afk_enabled = True
        instance.afk_thread = threading.Thread(
            target=self._afk_loop,
            args=(instance,),
            daemon=True,
        )
        instance.afk_thread.start()

    def _stop_afk(self, instance: RobloxInstance):
        instance.afk_enabled = False
        if instance.afk_thread:
            instance.afk_thread.join(timeout=5)
            instance.afk_thread = None

    def toggle_afk(self, account_id: str):
        instance = self._instances.get(account_id)
        if instance is None:
            return
        if instance.afk_enabled:
            self._stop_afk(instance)
            self.console.print(f"[yellow]Anti-AFK disabled for {instance.account_name}.[/]")
        else:
            self._start_afk(instance)
            self.console.print(f"[green]Anti-AFK enabled for {instance.account_name}.[/]")

    def toggle_afk_all(self):
        for instance in self._instances.values():
            if not instance.afk_enabled:
                self._start_afk(instance)
        self.console.print("[green]Anti-AFK enabled for all instances.[/]")

    def _afk_loop(self, instance: RobloxInstance):
        """Anti-AFK loop for a single instance."""
        interval = 60  # seconds

        while instance.afk_enabled:
            for _ in range(interval):
                if not instance.afk_enabled:
                    return
                time.sleep(1)

            # Refresh HWND if needed
            if instance.pid and (not instance.hwnd or not is_pid_alive(instance.pid)):
                if is_pid_alive(instance.pid):
                    instance.hwnd = get_window_handle_for_pid(instance.pid)

            vk = random.choice(AFK_KEYS)

            # Sandbox mode
            if instance.sandbox and instance.sandbox.is_active():
                try:
                    instance.sandbox.send_key(vk)
                    size = instance.sandbox.get_window_size()
                    if size:
                        w, h = size
                        cx, cy = w // 2, h // 2
                        jitter = random.randint(-20, 20)
                        instance.sandbox.send_click(cx + jitter, cy + jitter)
                except Exception:
                    pass
                continue

            # Normal mode: PostMessage to specific HWND
            hwnd = instance.hwnd
            if hwnd is None:
                continue

            try:
                send_key(hwnd, vk, hold=0.05)
                try:
                    w, h = get_window_size(hwnd)
                    cx, cy = w // 2, h // 2
                    jitter = random.randint(-20, 20)
                    send_click(hwnd, cx + jitter, cy + jitter)
                except Exception:
                    pass
            except Exception:
                pass

    # ── status & queries ───────────────────────────────────────────────────

    def get_instance(self, account_id: str) -> RobloxInstance | None:
        return self._instances.get(account_id)

    def get_all(self) -> list[RobloxInstance]:
        return list(self._instances.values())

    def get_running(self) -> list[RobloxInstance]:
        return [i for i in self._instances.values() if i.status == "running"]

    def has_instances(self) -> bool:
        return len(self._instances) > 0

    def print_dashboard(self):
        """Print a status table of all running instances."""
        instances = self.get_all()
        if not instances:
            self.console.print("[dim]No instances running.[/]")
            return

        table = Table(title="Running Instances")
        table.add_column("#", style="bold")
        table.add_column("Account")
        table.add_column("Place ID", justify="right")
        table.add_column("Status")
        table.add_column("PID", justify="right", style="dim")
        table.add_column("Rejoin")
        table.add_column("Anti-AFK")

        for i, inst in enumerate(instances, 1):
            # Refresh status
            if inst.pid and not is_pid_alive(inst.pid):
                inst.status = "disconnected"

            status_style = {
                "running": "[green]Running[/]",
                "launching": "[yellow]Launching[/]",
                "disconnected": "[red]Disconnected[/]",
                "stopped": "[dim]Stopped[/]",
                "idle": "[dim]Idle[/]",
            }.get(inst.status, inst.status)

            table.add_row(
                str(i),
                inst.account_name,
                str(inst.place_id or "-"),
                status_style,
                str(inst.pid or "-"),
                "[green]On[/]" if inst.rejoin_enabled else "[dim]Off[/]",
                "[green]On[/]" if inst.afk_enabled else "[dim]Off[/]",
            )
        self.console.print(table)
