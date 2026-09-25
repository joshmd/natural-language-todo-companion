"""Fixtures: a fake Todoist API that records every request."""

from __future__ import annotations

import re
from typing import Any

import pytest
from yarl import URL

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.natural_language_todo.const import (
    CONF_ADMIN_ONLY,
    CONF_PROJECTS,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_COMPLETED,
    CONF_SOURCE,
    CONF_TODOIST_ENTRY_ID,
    DOMAIN,
    SOURCE_TODOIST_ENTRY,
)

pytest_plugins = "pytest_homeassistant_custom_component"

SHOP = "6Jf8VQXxpwv59GRH"
WORK = "6QvgPQ78mV9wCp7j"  # never ticked: must never be fetched


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeTodoist:
    def __init__(self) -> None:
        self.valid_tokens = {"core-token", "new-token"}
        self.user = {"id": "4242", "full_name": "Test"}
        self.projects = [{"id": SHOP, "name": "Shopping"}, {"id": WORK, "name": "Work"}]
        self.sections = {
            SHOP: [
                {"id": "sec2", "project_id": SHOP, "name": "Bakery", "section_order": 2},
                {"id": "sec1", "project_id": SHOP, "name": "Fruit", "section_order": 1},
                {"id": "gone", "project_id": SHOP, "name": "Old", "section_order": 3, "is_archived": True},
            ],
            WORK: [{"id": "w1", "project_id": WORK, "name": "Secret"}],
        }
        self.tasks = {
            SHOP: [
                {
                    "id": "t1", "project_id": SHOP, "section_id": "sec1", "content": "Bananas", "child_order": 1,
                    "description": "private notes", "responsible_uid": "99",
                    "due": {"date": "2026-09-26", "string": "sat", "is_recurring": False},
                },
                {"id": "t2", "project_id": SHOP, "section_id": None, "content": "Milk", "child_order": 2, "due": None},
            ],
            WORK: [{"id": "w9", "project_id": WORK, "content": "Secret work task"}],
        }
        self.completed = {
            SHOP: [{"id": "c1", "project_id": SHOP, "content": "Eggs", "completed_at": "2026-09-24T10:00:00Z"}],
        }
        self.calls: list[tuple[str, str, Any, str | None]] = []
        self.fail_move = False
        self.next_id = 100

    async def respond(self, method: str, url: URL, data: Any, headers: dict | None) -> AiohttpClientMockResponse:
        auth = (headers or {}).get("Authorization", "")
        self.calls.append((method.upper(), url.path, data, auth))
        token = auth.removeprefix("Bearer ")

        def reply(status: int = 200, json: Any = None) -> AiohttpClientMockResponse:
            return AiohttpClientMockResponse(method, url, status=status, json=json)

        if token not in self.valid_tokens:
            return reply(401, {"error": "unauthorized"})
        path = url.path.removeprefix("/api/v1")
        q = url.query
        if method.upper() == "GET":
            if path == "/user":
                return reply(json=self.user)
            if path == "/projects":
                return reply(json={"results": self.projects, "next_cursor": None})
            if path == "/sections":
                return reply(json={"results": self.sections.get(q["project_id"], []), "next_cursor": None})
            if path == "/tasks":
                items = self.tasks.get(q["project_id"], [])
                # Two pages, to exercise the cursor loop.
                if "cursor" not in q and len(items) > 1:
                    return reply(json={"results": items[:1], "next_cursor": "page2"})
                return reply(json={"results": items[1:] if "cursor" in q else items, "next_cursor": None})
            if path == "/tasks/completed/by_completion_date":
                return reply(json={"items": self.completed.get(q["project_id"], []), "next_cursor": None})
        if method.upper() == "POST":
            if path == "/tasks/quick":
                self.next_id += 1
                task = {"id": f"n{self.next_id}", "content": data["text"], "project_id": "inbox", "due": {"string": "tomorrow"}}
                return reply(json=task)
            if m := re.fullmatch(r"/tasks/([^/]+)/(move|close|reopen)", path):
                if m.group(2) == "move" and self.fail_move:
                    return reply(500, {})
                return reply(204)
        return reply(404, {})


@pytest.fixture
def todoist(aioclient_mock) -> FakeTodoist:
    fake = FakeTodoist()
    # Route api.todoist.com through the fake, keeping request headers.
    orig = aioclient_mock.match_request

    async def match_request(method, url, *, params=None, headers=None, json=None, data=None, **kwargs):
        u = URL(url)
        if params:
            u = u.with_query(params)
        if u.host == "api.todoist.com":
            return await fake.respond(method, u, json or data, headers)
        return await orig(method, url, params=params, headers=headers, json=json, data=data, **kwargs)

    aioclient_mock.match_request = match_request
    return fake


@pytest.fixture
def core_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain="todoist", data={CONF_TOKEN: "core-token"}, title="Todoist", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def entry(hass, core_entry) -> MockConfigEntry:
    e = MockConfigEntry(
        domain=DOMAIN,
        title="Todoist",
        unique_id="4242",
        data={CONF_SOURCE: SOURCE_TODOIST_ENTRY, CONF_TODOIST_ENTRY_ID: core_entry.entry_id},
        options={CONF_PROJECTS: [SHOP], CONF_SHOW_COMPLETED: True, CONF_ADMIN_ONLY: False, CONF_SCAN_INTERVAL: 60},
    )
    e.add_to_hass(hass)
    return e


@pytest.fixture
async def loaded(hass, entry, todoist) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry
