"""
Image-recognition bot scripts for Roblox.

Define sequences of actions (find button → click, wait, press key, etc.)
that run against the sandbox desktop. The system captures screenshots,
finds GUI elements via template matching, and clicks them automatically.
"""

import json
import re
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from vision import capture_screenshot, ImageMatcher

BOTS_DIR = Path(__file__).parent / "bots"
BOTS_DIR.mkdir(exist_ok=True)

IMAGE_BOTS_DIR = Path(__file__).parent / "bot_recognition_images"
IMAGE_BOTS_DIR.mkdir(exist_ok=True)


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class BotStep:
    """A single step in a bot script."""
    action: str             # "find_click", "wait", "key", "click"
    # find_click
    image: str = ""         # template image filename (e.g. "play_button.png")
    threshold: float = 0.8  # match confidence threshold
    timeout: float = 10.0   # max seconds to search for image
    # wait
    seconds: float = 0.0
    # key
    vk: int = 0
    duration: float = 0.05
    # click (fixed coordinates)
    x: int = 0
    y: int = 0
    button: str = "left"


# ── save / load ───────────────────────────────────────────────────────────────

def save_bot(name: str, steps: list[BotStep]):
    path = BOTS_DIR / f"{name}.json"
    data = {"name": name, "steps": [asdict(s) for s in steps]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_bot(name: str) -> list[BotStep] | None:
    path = BOTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return [BotStep(**s) for s in data["steps"]]


def list_bots() -> list[str]:
    return sorted(p.stem for p in BOTS_DIR.glob("*.json"))


def delete_bot(name: str) -> bool:
    path = BOTS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ── image-folder bots ────────────────────────────────────────────────────────

def _step_sort_key(path: Path) -> int:
    """Extract the step number from filenames like step_1.png, step_2.png."""
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def list_image_bots() -> list[str]:
    """List bot names from bot_recognition_images/ subfolders."""
    if not IMAGE_BOTS_DIR.exists():
        return []
    return sorted(
        d.name
        for d in IMAGE_BOTS_DIR.iterdir()
        if d.is_dir() and any(d.glob("step_*.png"))
    )


def load_image_bot(name: str) -> list[BotStep] | None:
    """
    Build a bot from bot_recognition_images/<name>/step_N.png files.

    Each step_N image becomes a find_click action. Steps are sorted
    by their number (step_1 before step_2, etc.).  A 1-second wait
    is inserted between clicks so the game has time to react.
    """
    folder = IMAGE_BOTS_DIR / name
    if not folder.is_dir():
        return None

    step_files = sorted(folder.glob("step_*.png"), key=_step_sort_key)
    if not step_files:
        return None

    steps: list[BotStep] = []
    for i, img_path in enumerate(step_files):
        # Use the absolute path so ImageMatcher.load_template finds it
        steps.append(BotStep(
            action="find_click",
            image=str(img_path.resolve()),
            threshold=0.8,
            timeout=10.0,
        ))
        # Add a small wait between clicks (skip after last step)
        if i < len(step_files) - 1:
            steps.append(BotStep(action="wait", seconds=1.0))

    return steps


# ── runner ────────────────────────────────────────────────────────────────────

class BotRunner:
    """Execute a bot script against the sandbox."""

    RETRY_INTERVAL = 1.0  # seconds between screenshot retries

    def __init__(self, sandbox, console=None):
        self.sandbox = sandbox
        self.console = console

    def _log(self, msg: str):
        if self.console:
            self.console.print(msg)

    def run(self, steps: list[BotStep]) -> bool:
        """
        Run all steps sequentially.
        Returns True if every step succeeded, False if any failed.
        """
        for i, step in enumerate(steps, 1):
            if step.action == "wait":
                self._log(f"[dim]  Step {i}: wait {step.seconds}s[/]")
                time.sleep(step.seconds)

            elif step.action == "key":
                self._log(f"[dim]  Step {i}: key 0x{step.vk:02X}[/]")
                self.sandbox.send_key(step.vk, step.duration)

            elif step.action == "click":
                self._log(
                    f"[dim]  Step {i}: click ({step.x}, {step.y})[/]"
                )
                self.sandbox.send_click(step.x, step.y, step.button)

            elif step.action == "find_click":
                self._log(
                    f"[dim]  Step {i}: find_click '{step.image}'[/]"
                )
                if not self._find_and_click(step):
                    return False
            else:
                self._log(f"[red]  Step {i}: unknown action '{step.action}'[/]")

            # Small pause between steps so the game registers input
            time.sleep(0.3)

        return True

    def _find_and_click(self, step: BotStep) -> bool:
        """Search for template on screen and click it. Retries until timeout."""
        template = ImageMatcher.load_template(step.image)
        if template is None:
            self._log(f"[red]  Template '{step.image}' not found in images/[/]")
            return False

        deadline = time.time() + step.timeout
        while time.time() < deadline:
            screenshot = capture_screenshot(self.sandbox)
            if screenshot is None:
                self._log("[yellow]  Screenshot failed, retrying...[/]")
                time.sleep(self.RETRY_INTERVAL)
                continue

            match = ImageMatcher.find(screenshot, template, step.threshold)
            if match:
                cx, cy, conf = match
                self._log(
                    f"[green]  Found '{step.image}' at ({cx}, {cy}) "
                    f"conf={conf:.2f} — clicking[/]"
                )
                self.sandbox.send_click(cx, cy, step.button)
                return True

            time.sleep(self.RETRY_INTERVAL)

        self._log(
            f"[red]  Could not find '{step.image}' "
            f"within {step.timeout}s[/]"
        )
        return False


# ── scheduler ─────────────────────────────────────────────────────────────────

class BotScheduler:
    """Run a bot script on a repeating timer in a background thread."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self.bot_name: str = ""
        self.interval: float = 0.0  # minutes
        self.sandbox = None  # set externally

    def _loop(self, steps: list[BotStep], interval_sec: float):
        while self._running:
            if self.sandbox and self.sandbox.is_active():
                runner = BotRunner(self.sandbox)
                runner.run(steps)

            # interruptible sleep
            for _ in range(int(interval_sec)):
                if not self._running:
                    return
                time.sleep(1)

    def start(
        self,
        bot_name: str,
        steps: list[BotStep],
        interval_minutes: float,
    ):
        if self._running:
            return
        self.bot_name = bot_name
        self.interval = interval_minutes
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(steps, interval_minutes * 60),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.bot_name = ""

    def is_running(self) -> bool:
        return self._running
