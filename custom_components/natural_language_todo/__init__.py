"""Natural Language To-do companion.

Syncs chosen Todoist projects, with their sections, for the Natural
Language To-do Card. Reuses the core Todoist integration's connection, or
a token entered here.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, signal_project_updated
from .coordinator import NLTodoCoordinator
from .services import async_setup_services
from .websocket import async_setup_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS: list[Platform] = [Platform.SENSOR]

type NLTodoConfigEntry = ConfigEntry[NLTodoCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    async_setup_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NLTodoConfigEntry) -> bool:
    coordinator = NLTodoCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _sync_devices(hass, entry, coordinator)

    # Cards subscribe by project, not to this coordinator, so an open
    # dashboard keeps updating when the entry reloads after Configure.
    @callback
    def announce() -> None:
        for project_id, project in (coordinator.data or {}).items():
            async_dispatcher_send(hass, signal_project_updated(project_id), project)

    entry.async_on_unload(coordinator.async_add_listener(announce))
    announce()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NLTodoConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def project_device(entry: ConfigEntry, project_id: str, name: str) -> dr.DeviceInfo:
    return dr.DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{project_id}")},
        name=name,
        manufacturer="Todoist",
        model="Project",
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=f"https://app.todoist.com/app/project/{project_id}",
    )


def _sync_devices(hass: HomeAssistant, entry: ConfigEntry, coordinator: NLTodoCoordinator) -> None:
    """One device per ticked project; remove devices for unticked ones."""
    registry = dr.async_get(hass)
    wanted = set()
    for project in coordinator.data.values():
        info = project_device(entry, project.id, project.name)
        registry.async_get_or_create(config_entry_id=entry.entry_id, **info)
        wanted |= info["identifiers"]
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & wanted:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
