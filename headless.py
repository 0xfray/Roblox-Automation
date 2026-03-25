import json
import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

from constants import (
    CLIENT_APP_SETTINGS_FILE,
    BACKUP_SUFFIX,
    FFLAG_POTATO_MODE,
    FFLAG_LEGACY_HEADLESS,
)
from utils import get_client_settings_path


class HeadlessManager:
    """
    Manages Roblox Fast Flags for minimal-rendering mode.

    Since September 2025 Roblox enforces an FFlag allowlist.
    Non-allowlisted flags are silently ignored.

    Profiles
    --------
    potato  – only allowlisted flags (works on current Roblox)
    legacy  – all flags including non-allowlisted (likely ignored)
    """

    PROFILES = {
        "potato": FFLAG_POTATO_MODE,
        "legacy": FFLAG_LEGACY_HEADLESS,
    }

    def __init__(self, console: Console):
        self.console = console
        self._active_profile: str | None = None
        self._detect_leftover()

    def _detect_leftover(self):
        """
        Detect if FFlags from a previous session were left behind.

        Checks two things:
        1. A backup file exists → previous apply wasn't restored.
        2. No backup but the settings file matches a known profile →
           likely applied by us in a session that lost its backup.

        In either case, mark the profile as active so _cleanup()
        will offer to restore on exit.
        """
        sf = self._settings_file()
        bf = self._backup_file()
        if sf is None:
            return

        # Case 1: backup file exists → we definitely applied and never restored
        if bf is not None and bf.exists():
            # Try to figure out which profile it was
            self._active_profile = self._identify_profile(sf)
            if self._active_profile:
                self.console.print(
                    f"[yellow]Detected leftover headless flags "
                    f"({self._active_profile}) from a previous session.[/]"
                )
            return

        # Case 2: no backup, but settings file matches a known profile
        if sf.exists():
            matched = self._identify_profile(sf)
            if matched:
                self._active_profile = matched
                # Re-create the backup so restore() works properly
                if bf is not None:
                    bf.write_text("{}", encoding="utf-8")
                self.console.print(
                    f"[yellow]Detected leftover headless flags "
                    f"({matched}) — will offer to restore on exit.[/]"
                )

    def _identify_profile(self, sf: Path) -> str | None:
        """Check if the settings file matches a known profile."""
        try:
            flags = json.loads(sf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        for name, profile_flags in self.PROFILES.items():
            # If at least half the profile flags are present, it's a match
            matched = sum(1 for k in profile_flags if k in flags)
            if matched >= len(profile_flags) // 2:
                return name
        return None

    # ── paths ─────────────────────────────────────────────────────────────

    def _settings_file(self) -> Path | None:
        cs = get_client_settings_path()
        if cs is None:
            return None
        return cs / CLIENT_APP_SETTINGS_FILE

    def _backup_file(self) -> Path | None:
        sf = self._settings_file()
        if sf is None:
            return None
        return sf.with_suffix(sf.suffix + BACKUP_SUFFIX)

    # ── backup / restore ──────────────────────────────────────────────────

    def _backup(self):
        sf = self._settings_file()
        bf = self._backup_file()
        if sf is None or bf is None:
            return
        if sf.exists():
            shutil.copy2(sf, bf)
        else:
            # mark "no original file existed"
            bf.write_text("{}", encoding="utf-8")

    def restore(self):
        sf = self._settings_file()
        bf = self._backup_file()
        if sf is None or bf is None:
            self.console.print("[red]Cannot locate Roblox installation.[/]")
            return

        if bf.exists():
            content = bf.read_text(encoding="utf-8").strip()
            if content == "{}":
                # no original file existed — remove ours
                if sf.exists():
                    sf.unlink()
            else:
                shutil.copy2(bf, sf)
            bf.unlink()

        self._active_profile = None
        self.console.print("[green]Original settings restored.[/]")

    # ── apply / remove ────────────────────────────────────────────────────

    def apply_profile(self, profile: str = "potato"):
        sf = self._settings_file()
        if sf is None:
            self.console.print("[red]Cannot locate Roblox installation.[/]")
            return

        flags = self.PROFILES.get(profile)
        if flags is None:
            self.console.print(f"[red]Unknown profile: {profile}[/]")
            return

        self._backup()
        sf.write_text(json.dumps(flags, indent=2), encoding="utf-8")
        self._active_profile = profile

        self.console.print(
            f"[green]Applied [bold]{profile}[/bold] profile "
            f"({len(flags)} flags).[/]"
        )
        if profile == "legacy":
            self.console.print(
                "[yellow]Warning: most legacy flags are NOT on the Roblox "
                "allowlist and will likely be ignored.[/]"
            )
        self.console.print(
            "[cyan]Note: Roblox reads FFlags at startup. "
            "Restart Roblox for changes to take effect.[/]"
        )

    def remove_profile(self):
        self.restore()

    # ── status ────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        return self._active_profile is not None

    def get_active_profile(self) -> str | None:
        return self._active_profile

    def show_current_flags(self):
        sf = self._settings_file()
        if sf is None or not sf.exists():
            self.console.print("[yellow]No ClientAppSettings.json found.[/]")
            return

        try:
            flags = json.loads(sf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.console.print("[red]Could not read settings file.[/]")
            return

        table = Table(title="Current FFlags")
        table.add_column("Flag", style="cyan")
        table.add_column("Value", style="green")
        for k, v in flags.items():
            table.add_row(k, str(v))
        self.console.print(table)

    def get_allowlist_status(self) -> dict:
        """Check which currently applied flags are on the allowlist."""
        sf = self._settings_file()
        if sf is None or not sf.exists():
            return {"allowed": [], "blocked": []}

        try:
            flags = json.loads(sf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"allowed": [], "blocked": []}

        allowed_names = set(FFLAG_POTATO_MODE.keys())
        result = {"allowed": [], "blocked": []}
        for name in flags:
            if name in allowed_names:
                result["allowed"].append(name)
            else:
                result["blocked"].append(name)
        return result
