#!/usr/bin/env python3
"""Launch the Headless Roblox CustomTkinter GUI."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import HeadlessRobloxApp


def main():
    app = HeadlessRobloxApp()
    app.mainloop()


if __name__ == "__main__":
    main()
