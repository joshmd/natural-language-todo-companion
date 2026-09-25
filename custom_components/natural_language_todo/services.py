"""Actions the card uses to add, complete and reopen tasks."""

from __future__ import annotations


import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import config_validation as cv

from .api import TodoistError
from .const import CONF_ADMIN_ONLY, DOMAIN, ID_RE, SERVICE_ADD_TASK, SERVICE_SET_DONE
from .coordinator import NLTodoCoordinator

ADD_SCHEMA = vol.Schema(
    {
        vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=2000)),
        vol.Required("project_id"): cv.string,
        vol.Optional("section_id"): vol.Any(None, cv.string),
    }
)
SET_DONE_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("done"): cv.boolean,
    }
)


def loaded_coordinators(hass: HomeAssistant) -> list[NLTodoCoordinator]:
    return [
        e.runtime_data
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]


def coordinator_for_project(hass: HomeAssistant, project_id: str) -> NLTodoCoordinator | None:
    for coordinator in loaded_coordinators(hass):
        if project_id in coordinator.project_ids:
            return coordinator
    return None


def _valid_id(value: str | None, what: str) -> str:
    if value is None or not ID_RE.fullmatch(str(value)):
        raise ServiceValidationError(f"{what} is not a valid Todoist ID")
    return str(value)


async def _check_allowed(hass: HomeAssistant, call: ServiceCall, coordinator: NLTodoCoordinator) -> None:
    """With "Only administrators can change tasks" on, refuse other users.

    Calls with no user (automations, scripts) are allowed.
    """
    if not coordinator.config_entry.options.get(CONF_ADMIN_ONLY, False):
        return
    user_id = call.context.user_id
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=call.context, permission="admin")


async def _refresh(coordinator: NLTodoCoordinator) -> None:
    await coordinator.async_refresh()


def _api_error(err: Exception) -> HomeAssistantError:
    if isinstance(err, ConfigEntryAuthFailed):
        return HomeAssistantError(f"Todoist connection problem: {err}")
    return HomeAssistantError(str(err))


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_task(call: ServiceCall) -> ServiceResponse:
        project_id = _valid_id(call.data["project_id"], "project_id")
        section_id = call.data.get("section_id") or None
        if section_id is not None:
            section_id = _valid_id(section_id, "section_id")
        coordinator = coordinator_for_project(hass, project_id)
        if coordinator is None:
            raise ServiceValidationError(f"Project {project_id} is not set up in {DOMAIN}")
        await _check_allowed(hass, call, coordinator)
        project = (coordinator.data or {}).get(project_id)
        if section_id and (project is None or not project.has_section(section_id)):
            await _refresh(coordinator)
            project = (coordinator.data or {}).get(project_id)
            if project is None or not project.has_section(section_id):
                raise ServiceValidationError(f"Section {section_id} is not in project {project_id}")

        try:
            created = await coordinator.client.quick_add(call.data["text"])
            task_id = _valid_id(created.get("id"), "Created task")
            moved = True
            try:
                await coordinator.client.move(task_id, project_id=project_id, section_id=section_id)
            except TodoistError:
                moved = False
        except (TodoistError, ConfigEntryAuthFailed) as err:
            raise _api_error(err) from err
        await _refresh(coordinator)
        due = created.get("due") or {}
        return {"id": task_id, "content": created.get("content", ""), "due": due.get("string", ""), "moved": moved}

    async def set_done(call: ServiceCall) -> None:
        task_id = _valid_id(call.data["task_id"], "task_id")
        owner = _owner(hass, task_id)
        if owner is None:
            for coordinator in loaded_coordinators(hass):
                await _refresh(coordinator)
            owner = _owner(hass, task_id)
        if owner is None:
            raise ServiceValidationError(f"Task {task_id} is not in a project set up in {DOMAIN}")
        await _check_allowed(hass, call, owner)
        try:
            if call.data["done"]:
                await owner.client.close(task_id)
            else:
                await owner.client.reopen(task_id)
        except (TodoistError, ConfigEntryAuthFailed) as err:
            raise _api_error(err) from err
        await _refresh(owner)

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TASK, add_task, schema=ADD_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, SERVICE_SET_DONE, set_done, schema=SET_DONE_SCHEMA)


def _owner(hass: HomeAssistant, task_id: str) -> NLTodoCoordinator | None:
    for coordinator in loaded_coordinators(hass):
        for project in (coordinator.data or {}).values():
            if project.has_task(task_id):
                return coordinator
    return None
