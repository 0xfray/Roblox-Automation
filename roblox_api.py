import requests

from constants import (
    AUTH_TICKET_URL,
    USERS_URL,
    SERVERS_URL,
    PRESENCE_URL,
    FRIENDS_URL,
    PLACE_DETAILS_URL,
)


class RobloxAPI:
    """Roblox web-API wrapper with automatic CSRF token handling."""

    def __init__(self, cookie: str):
        self.session = requests.Session()
        self.session.cookies[".ROBLOSECURITY"] = cookie
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.roblox.com",
            "Referer": "https://www.roblox.com/",
        })

    # ── internal ──────────────────────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, url, **kwargs)
        # CSRF rotation: first POST returns 403 with new token
        if resp.status_code == 403:
            token = resp.headers.get("X-CSRF-TOKEN")
            if token:
                self.session.headers["X-CSRF-TOKEN"] = token
                resp = self.session.request(method, url, **kwargs)
        return resp

    # ── user ──────────────────────────────────────────────────────────────

    def get_authenticated_user(self) -> dict | None:
        resp = self._request("GET", USERS_URL)
        if resp.status_code == 200:
            return resp.json()
        return None

    # ── auth ticket ───────────────────────────────────────────────────────

    def get_auth_ticket(self) -> str | None:
        resp = self._request("POST", AUTH_TICKET_URL)
        if resp.status_code == 200:
            return resp.headers.get("rbx-authentication-ticket")
        return None

    # ── servers ───────────────────────────────────────────────────────────

    def get_servers(
        self,
        place_id: int,
        server_type: str = "Public",
        limit: int = 10,
        sort_order: str = "Desc",
        cursor: str | None = None,
    ) -> dict | None:
        url = SERVERS_URL.format(place_id=place_id, server_type=server_type)
        params = {"sortOrder": sort_order, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = self._request("GET", url, params=params)
        if resp.status_code == 200:
            return resp.json()
        return None

    # ── friends & presence ────────────────────────────────────────────────

    def get_friends(self, user_id: int) -> list[dict]:
        url = FRIENDS_URL.format(user_id=user_id)
        resp = self._request("GET", url)
        if resp.status_code == 200:
            return resp.json().get("data", [])
        return []

    def get_user_presence(self, user_ids: list[int]) -> list[dict]:
        resp = self._request("POST", PRESENCE_URL, json={"userIds": user_ids})
        if resp.status_code == 200:
            return resp.json().get("userPresences", [])
        return []

    # ── place details ─────────────────────────────────────────────────────

    def get_place_details(self, place_ids: list[int]) -> list[dict]:
        resp = self._request(
            "GET", PLACE_DETAILS_URL, params={"placeIds": place_ids}
        )
        if resp.status_code == 200:
            return resp.json()
        return []
