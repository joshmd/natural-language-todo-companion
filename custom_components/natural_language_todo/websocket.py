"""Live data for the card, over Home Assistant's authenticated websocket."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import ID_RE, WS_PROJECTS, WS_SUBSCRIBE, signal_project_updated
from .coordinator import ProjectData
from .services import coordinator_for_project, loaded_coordinators


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_projects)
    websocket_api.async_register_command(hass, ws_subscribe)


@websocket_api.websocket_command({vol.Required("type"): WS_PROJECTS})
@callback
def ws_projects(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Names of the ticked projects, for the card editor."""
    projects = [
        {"id": p.id, "name": p.name}
        for coordinator in loaded_coordinators(hass)
        for p in (coordinator.data or {}).values()
    ]
    connection.send_result(msg["id"], {"projects": projects})


@websocket_api.websocket_command({vol.Required("type"): WS_SUBSCRIBE, vol.Required("project_id"): str})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send one project's sections and tasks now and whenever they change."""
    project_id = msg["project_id"]
    coordinator = coordinator_for_project(hass, project_id) if ID_RE.fullmatch(project_id) else None
    if coordinator is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Project is not set up in the companion")
        return

    @callback
    def send(project: ProjectData) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], project.as_message()))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, signal_project_updated(project_id), send)
    connection.send_result(msg["id"])
    if (project := (coordinator.data or {}).get(project_id)) is not None:
        send(project)
