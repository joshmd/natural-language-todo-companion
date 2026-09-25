"""Diagnostics download. Token removed; counts only, no task text."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from . import NLTodoConfigEntry

TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: NLTodoConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": dict(entry.options)},
        "last_update_success": coordinator.last_update_success,
        "projects": {
            pid: {"sections": len(p.sections), "tasks": len(p.tasks), "completed": len(p.completed)}
            for pid, p in (coordinator.data or {}).items()
        },
    }
