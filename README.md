# Headless Roblox

A desktop app for managing multiple Roblox accounts and running them simultaneously with auto-rejoin, anti-AFK, headless rendering, macros, and more.

Built with Python and CustomTkinter.

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20(partial)-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

### Multi-Account Manager
- Store unlimited Roblox accounts with encrypted `.ROBLOSECURITY` cookies
- Add accounts by pasting cookies or logging in via browser (Playwright)
- Set a target game (Place ID) per account
- Validate cookies to check which are still active
- Rename accounts with custom nicknames

### Multi-Instance Launching
- Launch multiple Roblox instances at once — one per account
- Automatically bypasses the Roblox singleton mutex/event that normally prevents multiple instances
- Server browser to pick specific servers by player count, FPS, and ping
- Join a friend's game directly from the friends list
- Configurable delay between launches for stability

### Auto-Rejoin
- Per-instance auto-rejoin that monitors for disconnects
- Detects disconnects via Roblox log file scanning and process monitoring
- Automatically re-authenticates and rejoins the same server
- Handles singleton bypass on rejoin when other instances are still running

### Anti-AFK
- Per-instance anti-AFK that sends background input to keep each account alive
- Sends randomized key presses and mouse clicks at configurable intervals
- Works via Win32 PostMessage (no focus stealing)

### Headless Mode (FFlags)
- **Potato Mode** — applies only Roblox-allowlisted FFlags for minimal rendering (recommended)
- **Legacy Mode** — aggressive FFlags including disabled shadows, wind, terrain, and forced voxel rendering
- Automatically manages `ClientAppSettings.json` with backup/restore

### Macros
- **Record from Roblox** — captures mouse clicks and key presses while Roblox is focused (press F6 to stop)
- **Build manually** — step-by-step macro builder with friendly key names and a "Pick from Screen" coordinate picker
- **Play** macros on demand or **schedule** them to repeat on an interval
- Supports click (left/right), key press (19 common Roblox keys), and wait steps

### Bot Scripts
- Image-recognition bots that find and click UI elements on screen
- Create bots from image folders (`bot_recognition_images/`) or JSON definitions
- Run once or schedule to repeat
- Requires sandbox mode for screenshot capture

### Sandbox Mode (Windows only)
- Runs Roblox on a hidden Windows desktop
- Full input works (WASD, jumping, mouse, camera) without touching your main desktop
- Anti-AFK and macros use SendInput on the hidden desktop

### Live Logs
- Real-time log stream showing all background activity
- Color-coded by severity (errors, warnings, success, info)
- Auto-scrolling with 500-line buffer

---

## Installation

### Requirements
- Python 3.12+
- Windows 10/11 (full features) or Linux (partial — see below)

### Setup

```bash
git clone https://github.com/yourusername/Headless-roblox-Cli.git
cd Headless-roblox-Cli
pip install -r requirements.txt
```

For browser login support (optional):
```bash
playwright install chromium
```

### Run

```bash
python run_gui.py
```

---

## Quick Start

1. **Add an account** — Go to the Accounts tab, paste your `.ROBLOSECURITY` cookie, and click Add
2. **Set a game** — Click "Set Game" on the account and enter the Place ID
3. **Launch** — Go to the Launch tab, select your accounts, and click "Launch Selected" (or use "Launch All" on the Dashboard)
4. **Enable protections** — Toggle Auto-Rejoin and Anti-AFK per instance from the Dashboard

---

## Getting Your Cookie

1. Open Roblox in your browser and log in
2. Open DevTools (F12) → Application → Cookies → `https://www.roblox.com`
3. Find `.ROBLOSECURITY` and copy the value
4. Paste it into the Accounts tab

Or use the **Browser Login** button which opens a Chromium window and captures the cookie automatically.

---

## Platform Support

| Feature | Windows | Linux |
|---------|---------|-------|
| GUI (all tabs) | Yes | Yes |
| Account management | Yes | Yes |
| Roblox launching | Yes | Yes (via xdg-open) |
| Multi-instance (mutex bypass) | Yes | No |
| Auto-rejoin | Yes | Partial (no HWND) |
| Anti-AFK | Yes | No |
| Sandbox (hidden desktop) | Yes | No |
| Macro recording | Yes | No |
| Macro builder + playback | Yes | Partial |
| Bot scripts | Yes | No |
| Headless FFlags | Yes | Yes |
| Pick from Screen (coords) | Yes | No |

On Linux, the app launches and all management features work. Windows-only features gracefully show a message or no-op instead of crashing.

---

## Project Structure

```
Headless-roblox-Cli/
├── run_gui.py              # Entry point
├── requirements.txt        # Dependencies
├── config.json             # Encrypted accounts + settings
├── .key                    # Encryption key (auto-generated)
│
├── gui/                    # CustomTkinter desktop app
│   ├── app.py              # Main window with all tabs
│   ├── console_bridge.py   # Redirects Rich console output to GUI
│   └── manager.py          # Backend manager singleton
│
├── account_manager.py      # Multi-account CRUD + encrypted storage
├── instance_manager.py     # Multi-instance orchestration + rejoin + AFK
├── launcher.py             # Roblox protocol URI builder
├── auth.py                 # Cookie + browser login
├── roblox_api.py           # Roblox web API wrapper
├── config.py               # JSON config + Fernet encryption
├── constants.py            # API endpoints, FFlag profiles, Win32 constants
├── utils.py                # Process, window, and mutex utilities
│
├── anti_afk.py             # Background input to prevent AFK kicks
├── background_input.py     # Win32 PostMessage-based input
├── sandbox.py              # Hidden desktop sandbox
├── headless.py             # FFlag profile management
├── macro.py                # Macro record, play, schedule
├── bot.py                  # Image-recognition bot scripts
└── vision.py               # Screenshot capture + template matching
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `customtkinter` | Modern dark-themed GUI |
| `requests` | Roblox API calls |
| `psutil` | Process management |
| `cryptography` | Cookie encryption (Fernet) |
| `pynput` | Macro recording (keyboard/mouse capture) |
| `opencv-python` | Bot image recognition |
| `numpy` | Image processing |
| `Pillow` | Image handling |
| `playwright` | Browser-based login (optional) |
| `pywin32` | Win32 API (Windows only) |
| `rich` | Console output formatting |

---

## How Multi-Instance Works

Roblox normally prevents multiple instances using two named kernel objects:
- `ROBLOX_singletonMutex`
- `ROBLOX_singletonEvent`

When a second Roblox tries to start, it sees these already exist and exits.

This tool bypasses it by:
1. Launching the first Roblox instance normally
2. Enumerating all handles in the Roblox process using `NtQuerySystemInformation`
3. Finding and closing the singleton handles via `DuplicateHandle` with `DUPLICATE_CLOSE_SOURCE`
4. Launching the next instance (which creates fresh singletons)
5. Repeating for each additional account

Each instance gets its own auth ticket, PID tracking, window handle, rejoin thread, and anti-AFK thread.

---

## Disclaimer

This tool is for educational and personal use. Use at your own risk. Automating Roblox may violate their Terms of Service. The authors are not responsible for any account actions taken by Roblox.
