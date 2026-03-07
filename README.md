
# Headless Roblox CLI

A lightweight **Python CLI tool for launching and managing Roblox sessions** with features like:

* Headless / minimal rendering mode
* Anti-AFK automation
* Auto-rejoin on disconnect
* Server browser
* Join friends automatically
* Secure Roblox authentication

This tool is designed for **AFK farming, automation, and low-resource Roblox sessions**.

---

# Features

### Headless / Potato Mode

Runs Roblox with minimal graphics settings using Roblox FastFlags to reduce rendering overhead.

* Lower GPU usage
* Reduced CPU load
* Ideal for AFK sessions

The tool applies optimized settings automatically and restores them when disabled. 

---

### Anti-AFK System

Prevents Roblox from kicking you for being idle by periodically sending simulated key presses. 

Configurable:

* Keypress interval
* Sending strategy
* Background operation

---

### Auto-Rejoin

Automatically rejoins your game if:

* You disconnect
* The server closes
* Roblox crashes
* You get kicked

It monitors Roblox logs to detect disconnect events. 

---

### Game Launching

Join games multiple ways:

* By **Place ID**
* By **server browser**
* Join **friends**
* Via **deep links**

Uses the Roblox authentication ticket system to launch sessions programmatically. 

---

### Secure Login

Login methods:

* `.ROBLOSECURITY` cookie
* Browser login via Playwright

Cookies are encrypted locally before being stored. 

---

# Requirements

* Windows
* Python **3.10+**
* Roblox installed

Dependencies:

```
requests
psutil
rich
pywin32
pyautogui
cryptography
playwright
```

From `requirements.txt`: 

---

# Installation

Clone the repository:

```
git clone https://github.com/YOURNAME/headless-roblox-cli.git
cd headless-roblox-cli
```

Install dependencies:

```
pip install -r requirements.txt
```

Install Playwright browser (required for browser login):

```
playwright install chromium
```

---

# Running the Tool

Start the CLI:

```
python main.py
```

You will see a menu like:

```
Main Menu
1 Login
2 Join Game
3 Toggle Headless Mode
4 Toggle Anti-AFK
5 Settings
6 Status
7 Toggle Auto-Rejoin
8 Kill Roblox
0 Exit
```

---

# Usage

### 1. Login

Choose:

* Cookie login
* Browser login

### 2. Join a Game

Options:

* Join by **Place ID**
* Browse servers
* Join friends
* Deep link join

### 3. Enable Headless Mode

Two profiles:

| Profile | Description                                      |
| ------- | ------------------------------------------------ |
| potato  | Safe minimal graphics                            |
| legacy  | More aggressive flags (may be ignored by Roblox) |

---

### 4. Anti-AFK

Prevents idle kick by sending movement keys.

Default interval:

```
60 seconds
```

Adjustable in settings.

---

### 5. Auto-Rejoin

Automatically reconnects to the same place if you disconnect.

Useful for:

* AFK grinding
* unstable servers
* long sessions

---

# Project Structure

```
main.py
auth.py
launcher.py
anti_afk.py
headless.py
roblox_api.py
config.py
constants.py
utils.py
requirements.txt
```

Core components:

| File          | Purpose                      |
| ------------- | ---------------------------- |
| main.py       | CLI interface                |
| auth.py       | Roblox login system          |
| launcher.py   | Game launching & auto-rejoin |
| anti_afk.py   | Anti-idle system             |
| headless.py   | FastFlag graphics control    |
| roblox_api.py | Roblox API wrapper           |

---

# Security Notes

* Cookies are **encrypted locally**
* No credentials are sent anywhere except Roblox APIs
* This tool runs **locally only**

---

# Disclaimer

This project is **not affiliated with Roblox Corporation**.

Use at your own risk.
Automation tools may violate Roblox Terms of Service.

---

# License

MIT License

You are free to:

* Use
* Modify

But **credit must remain in the project**.

---
