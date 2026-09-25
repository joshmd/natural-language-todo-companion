"""Minimal async client for the Todoist API v1."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import aiohttp

from homeassistant.util.json import json_loads

from .const import API_BASE, COMPLETED_DAYS, ID_RE, MAX_PAGES, PAGE_LIMIT


class TodoistError(Exception):
    """Todoist request failed."""


class TodoistAuthError(TodoistError):
    """Todoist rejected the token."""


def check_id(value: Any) -> str:
    """Return value as a Todoist ID, or raise ValueError."""
    text = str(value)
    if not ID_RE.fullmatch(text):
        raise ValueError(f"not a valid Todoist ID: {text!r}")
    return text


def _path_id(value: Any) -> str:
    """ID for use inside a URL path. Validated, then encoded as well."""
    return quote(check_id(value), safe="")


class TodoistClient:
    """Talks to api.todoist.com with a token fetched on every request.

    get_token is called each time so a token changed in the core Todoist
    integration is picked up without restarting.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        get_token: Callable[[], Awaitable[str]],
    ) -> None:
        self._session = session
        self._get_token = get_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        token = await self._get_token()
        try:
            async with self._session.request(
                method,
                f"{API_BASE}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status in (401, 403):
                    raise TodoistAuthError(f"Todoist rejected the token (HTTP {resp.status})")
                if resp.status >= 400:
                    raise TodoistError(f"Todoist returned HTTP {resp.status}")
                if resp.status == 204:
                    return None
                body = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TodoistError(f"Could not reach Todoist: {err}") from err
        if not body.strip():
            return None
        try:
            return json_loads(body)
        except ValueError as err:
            raise TodoistError("Todoist sent a reply that isn't JSON") from err

    async def _paged(self, path: str, params: dict[str, Any], key: str = "results") -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page_params = {**params, "limit": PAGE_LIMIT}
            if cursor:
                page_params["cursor"] = cursor
            data = await self._request("GET", path, params=page_params) or {}
            items.extend(data.get(key) or [])
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return items

    async def user(self) -> dict:
        return await self._request("GET", "/user") or {}

    async def projects(self) -> list[dict]:
        return await self._paged("/projects", {})

    async def sections(self, project_id: str) -> list[dict]:
        return await self._paged("/sections", {"project_id": check_id(project_id)})

    async def tasks(self, project_id: str) -> list[dict]:
        return await self._paged("/tasks", {"project_id": check_id(project_id)})

    async def completed(self, project_id: str) -> list[dict]:
        until = datetime.now(timezone.utc)
        since = until - timedelta(days=COMPLETED_DAYS)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return await self._paged(
            "/tasks/completed/by_completion_date",
            {"project_id": check_id(project_id), "since": since.strftime(fmt), "until": until.strftime(fmt)},
            key="items",
        )

    async def quick_add(self, text: str) -> dict:
        return await self._request("POST", "/tasks/quick", json={"text": text}) or {}

    async def move(self, task_id: str, *, project_id: str, section_id: str | None) -> None:
        # Todoist takes exactly one destination; a section implies its project.
        body = {"section_id": check_id(section_id)} if section_id else {"project_id": check_id(project_id)}
        await self._request("POST", f"/tasks/{_path_id(task_id)}/move", json=body)

    async def close(self, task_id: str) -> None:
        await self._request("POST", f"/tasks/{_path_id(task_id)}/close")

    async def reopen(self, task_id: str) -> None:
        await self._request("POST", f"/tasks/{_path_id(task_id)}/reopen")
