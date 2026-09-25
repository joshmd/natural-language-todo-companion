"""Polls Todoist for the projects this entry is set up for."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TodoistAuthError, TodoistClient, TodoistError
from .const import (
    CONF_PROJECTS,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_COMPLETED,
    CONF_SOURCE,
    CONF_TODOIST_ENTRY_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SOURCE_TODOIST_ENTRY,
)

_LOGGER = logging.getLogger(__name__)

TODOIST_DOMAIN = "todoist"


class TokenUnavailable(ConfigEntryAuthFailed):
    """The token this entry relies on can't be found."""


def token_getter(hass: HomeAssistant, entry: ConfigEntry):
    """Return an async function that reads the token when it is needed.

    With SOURCE_TODOIST_ENTRY the token is read from the core Todoist
    integration's entry each time, never copied into this entry.
    """

    async def get_token() -> str:
        if entry.data.get(CONF_SOURCE) == SOURCE_TODOIST_ENTRY:
            core = hass.config_entries.async_get_entry(entry.data.get(CONF_TODOIST_ENTRY_ID, ""))
            if core is None or core.domain != TODOIST_DOMAIN or not core.data.get(CONF_TOKEN):
                raise TokenUnavailable(
                    "The Todoist integration this uses has been removed. Enter an API token instead."
                )
            return core.data[CONF_TOKEN]
        token = entry.data.get(CONF_TOKEN)
        if not token:
            raise TokenUnavailable("No Todoist API token is set.")
        return token

    return get_token


def make_client(hass: HomeAssistant, entry: ConfigEntry) -> TodoistClient:
    return TodoistClient(async_get_clientsession(hass), token_getter(hass, entry))


# Only the fields the card needs leave this integration.
def _task(t: dict[str, Any], completed: bool = False) -> dict[str, Any]:
    due = t.get("due") or None
    return {
        "id": str(t.get("id") or t.get("task_id") or ""),
        "content": t.get("content", ""),
        "section_id": str(t["section_id"]) if t.get("section_id") else None,
        "parent_id": str(t["parent_id"]) if t.get("parent_id") else None,
        "order": t.get("child_order"),
        "due": {
            "date": due.get("date"),
            "datetime": due.get("datetime"),
            "string": due.get("string"),
            "is_recurring": bool(due.get("is_recurring")),
        }
        if due
        else None,
        "completed_at": t.get("completed_at") if completed else None,
    }


@dataclass
class ProjectData:
    id: str
    name: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    completed: list[dict[str, Any]] = field(default_factory=list)

    def as_message(self) -> dict[str, Any]:
        return {
            "project": {"id": self.id, "name": self.name},
            "sections": self.sections,
            "tasks": self.tasks,
            "completed": self.completed,
        }

    def has_task(self, task_id: str) -> bool:
        return any(t["id"] == task_id for t in self.tasks) or any(t["id"] == task_id for t in self.completed)

    def has_section(self, section_id: str) -> bool:
        return any(s["id"] == section_id for s in self.sections)


class NLTodoCoordinator(DataUpdateCoordinator[dict[str, ProjectData]]):
    """Keeps the ticked projects up to date."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = make_client(hass, entry)
        self.project_ids: list[str] = [str(p) for p in entry.options.get(CONF_PROJECTS, [])]
        self.show_completed: bool = bool(entry.options.get(CONF_SHOW_COMPLETED, True))
        self.project_names: dict[str, str] = {}

    async def _async_update_data(self) -> dict[str, ProjectData]:
        try:
            if not self.project_names or any(p not in self.project_names for p in self.project_ids):
                self.project_names = {str(p["id"]): p.get("name", "") for p in await self.client.projects()}
            results = await asyncio.gather(*(self._project(pid) for pid in self.project_ids if pid in self.project_names))
        except TodoistAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TodoistError as err:
            raise UpdateFailed(str(err)) from err
        return {p.id: p for p in results}

    async def _project(self, project_id: str) -> ProjectData:
        sections, tasks = await asyncio.gather(self.client.sections(project_id), self.client.tasks(project_id))
        completed = await self.client.completed(project_id) if self.show_completed else []
        order = lambda s: s.get("section_order", s.get("order", 0)) or 0  # noqa: E731
        return ProjectData(
            id=project_id,
            name=self.project_names.get(project_id, project_id),
            sections=[
                {"id": str(s["id"]), "name": s.get("name", "")}
                for s in sorted(sections, key=order)
                if not s.get("is_archived") and not s.get("is_deleted")
            ],
            tasks=[_task(t) for t in tasks if str(t.get("project_id")) == project_id],
            completed=[_task(t, True) for t in completed if str(t.get("project_id")) == project_id],
        )
