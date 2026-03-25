# ── API Endpoints ──────────────────────────────────────────────────────────────
AUTH_URL = "https://auth.roblox.com"
AUTH_TICKET_URL = "https://auth.roblox.com/v1/authentication-ticket"
USERS_URL = "https://users.roblox.com/v1/users/authenticated"
GAMES_URL = "https://games.roblox.com/v1/games"
SERVERS_URL = "https://games.roblox.com/v1/games/{place_id}/servers/{server_type}"
PRESENCE_URL = "https://presence.roblox.com/v1/presence/users"
FRIENDS_URL = "https://friends.roblox.com/v1/users/{user_id}/friends"
PLACE_DETAILS_URL = "https://games.roblox.com/v1/games/multiget-place-details"
THUMBNAILS_URL = "https://thumbnails.roblox.com/v1/places/gameicons"
ASSET_GAME_URL = "https://assetgame.roblox.com/game/PlaceLauncher.ashx"
NEGOTIATE_URL = "https://www.roblox.com/Login/Negotiate.ashx"

# ── Roblox Paths ──────────────────────────────────────────────────────────────
PLAYER_EXE = "RobloxPlayerBeta.exe"
CLIENT_SETTINGS_DIR = "ClientSettings"
CLIENT_APP_SETTINGS_FILE = "ClientAppSettings.json"

# ── FFlag Profiles ────────────────────────────────────────────────────────────
# Potato Mode: only flags on the Roblox allowlist (as of March 2026)
FFLAG_POTATO_MODE = {
    "DFIntDebugFRMQualityLevelOverride": 1,
    "DFFlagTextureQualityOverrideEnabled": True,
    "DFIntTextureQualityOverride": 0,
    "FIntDebugForceMSAASamples": 0,
    "FIntFRMMaxGrassDistance": 0,
    "FIntFRMMinGrassDistance": 0,
    "DFFlagDebugPauseVoxelizer": True,
    "FFlagDebugSkyGray": True,
    "DFIntCSGLevelOfDetailSwitchingDistance": 50,
    "DFIntCSGLevelOfDetailSwitchingDistanceL12": 100,
    "DFIntCSGLevelOfDetailSwitchingDistanceL23": 150,
    "DFIntCSGLevelOfDetailSwitchingDistanceL34": 200,
    "FIntGrassMovementReducedMotionFactor": 999,
}

# Legacy Headless: includes non-allowlisted flags (likely ignored on current Roblox)
FFLAG_LEGACY_HEADLESS = {
    **FFLAG_POTATO_MODE,
    "DFIntTaskSchedulerTargetFps": 9999999,
    "FFlagDebugGraphicsPreferVulkan": False,
    "FFlagDebugGraphicsPreferD3D11FL10": False,
    "FFlagDebugGraphicsPreferD3D11": False,
    "FIntRenderGrassDetailStrands": 0,
    "DFFlagDebugRenderForceTechnologyVoxel": True,
    "FFlagDisableNewIGMinDUA": True,
    "FIntTerrainOctreeMaxCells": 0,
    "FIntRenderShadowIntensity": 0,
    "FFlagGlobalWindRendering": False,
    "FIntRenderLocalLightUpdatesMax": 0,
    "FIntRenderLocalLightUpdatesMin": 0,
}

# ── Win32 Constants ───────────────────────────────────────────────────────────
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_SPACE = 0x20
VK_E = 0x45
VK_W = 0x57
VK_A = 0x41
VK_S = 0x53
VK_D = 0x44

AFK_KEYS = [VK_SPACE, VK_W, VK_A, VK_S, VK_D]

# ── Anti-AFK Defaults ────────────────────────────────────────────────────────
DEFAULT_AFK_INTERVAL = 60  # seconds
MIN_AFK_INTERVAL = 10
MAX_AFK_INTERVAL = 600

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_FILE = "config.json"
KEY_FILE = ".key"
BACKUP_SUFFIX = ".backup"
