from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = ROOT / ".session.json"
SESSION_KEY = "northstar.session"
API_BASE_URL = os.getenv("NORTHSTAR_API_URL", "http://127.0.0.1:8000").rstrip("/")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class Api:
    def __init__(self, storage=None):
        self.storage = storage
        self.token: str | None = None
        self.refresh_token: str | None = None
        self.user: dict | None = None
        self._load()

    def _load(self):
        data = self.storage.get(SESSION_KEY) if self.storage is not None else None
        if not data and SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if self.storage is not None:
                self.storage.set(SESSION_KEY, data)
        if data:
            self.token = data.get("token")
            self.refresh_token = data.get("refresh_token")
            self.user = data.get("user")

    def _save(self):
        data = {
            "token": self.token,
            "refresh_token": self.refresh_token,
            "user": self.user,
        }
        if self.storage is not None:
            if not self.storage.set(SESSION_KEY, data):
                raise RuntimeError("Could not save your NorthStar login on this device.")
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
            return
        SESSION_FILE.write_text(json.dumps(data), encoding="utf-8")

    def clear(self):
        self.token = None
        self.refresh_token = None
        self.user = None
        if self.storage is not None:
            self.storage.remove(SESSION_KEY)
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()

    def _headers(self) -> dict:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            with httpx.Client(base_url=API_BASE_URL, timeout=60) as client:
                return client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.ConnectError as exc:
            raise ApiError("Cannot reach the NorthStar server. Start the backend first.") from exc

    @staticmethod
    def _response_error(res: httpx.Response) -> ApiError:
        detail = "Request failed."
        try:
            payload = res.json()
            detail = payload.get("detail", detail)
            if isinstance(detail, list):
                detail = "; ".join(
                    item.get("msg", str(item)) if isinstance(item, dict) else str(item)
                    for item in detail
                )
        except ValueError:
            detail = res.text[:300]
        return ApiError(detail, res.status_code)

    def _refresh(self):
        if not self.refresh_token:
            raise ApiError("Your saved login has expired. Please log in again.", 401)
        try:
            with httpx.Client(base_url=API_BASE_URL, timeout=60) as client:
                res = client.post(
                    "/auth/refresh",
                    json={"refresh_token": self.refresh_token},
                )
        except httpx.ConnectError as exc:
            raise ApiError("Cannot reach the NorthStar server. Start the backend first.") from exc
        if res.status_code >= 400:
            self.clear()
            raise self._response_error(res)
        data = res.json()
        self.token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user = data["user"]
        self._save()

    def request(self, method: str, path: str, **kwargs):
        res = self._send(method, path, **kwargs)
        if (
            res.status_code == 401
            and self.refresh_token
            and path not in {"/auth/login", "/auth/register", "/auth/refresh"}
        ):
            self._refresh()
            res = self._send(method, path, **kwargs)
        if res.status_code >= 400:
            raise self._response_error(res)
        if res.headers.get("content-type", "").startswith("application/json"):
            return res.json()
        return res.content

    def logout(self):
        error = None
        if self.refresh_token:
            try:
                with httpx.Client(base_url=BASE, timeout=10) as client:
                    res = client.post(
                        "/auth/logout",
                        json={"refresh_token": self.refresh_token},
                    )
                if res.status_code >= 400:
                    error = self._response_error(res)
            except httpx.ConnectError as exc:
                error = ApiError("Could not reach the server to revoke this login.")
                error.__cause__ = exc
        self.clear()
        if error:
            raise error

    def register(self, payload: dict) -> dict:
        data = self.request("POST", "/auth/register", json=payload)
        self.token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user = data["user"]
        self._save()
        return data

    def login(self, username: str, password: str) -> dict:
        data = self.request("POST", "/auth/login", json={"username": username, "password": password})
        self.token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user = data["user"]
        self._save()
        return data

    def establish_session(self):
        data = self.request("POST", "/auth/session")
        self.token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user = data["user"]
        self._save()

    def me(self) -> dict:
        self.user = self.request("GET", "/users/me")
        self._save()
        return self.user
