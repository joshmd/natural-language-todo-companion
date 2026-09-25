"""Tests for the companion: setup, data minimisation, actions and security."""

from __future__ import annotations

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.natural_language_todo.const import (
    CONF_ADMIN_ONLY,
    CONF_PROJECTS,
    CONF_SOURCE,
    CONF_TODOIST_ENTRY_ID,
    DOMAIN,
    SOURCE_TODOIST_ENTRY,
    SOURCE_TOKEN,
)

from .conftest import SHOP, WORK


def paths(todoist):
    return [c[1] for c in todoist.calls]


# ---- config flow -------------------------------------------------------------


async def test_flow_reuses_core_todoist_connection(hass: HomeAssistant, core_entry, todoist):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: core_entry.entry_id})
    assert result["step_id"] == "projects"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PROJECTS: [SHOP]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SOURCE: SOURCE_TODOIST_ENTRY, CONF_TODOIST_ENTRY_ID: core_entry.entry_id}
    assert CONF_TOKEN not in result["data"], "token is not copied"
    assert result["options"][CONF_PROJECTS] == [SHOP]
    assert result["options"][CONF_ADMIN_ONLY] is False
    assert result["result"].unique_id == "4242"


async def test_flow_with_token_and_bad_token(hass: HomeAssistant, todoist):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "token", "no core Todoist entry: straight to the token"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: " new-token "})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PROJECTS: []})
    assert result["errors"] == {"base": "no_projects"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PROJECTS: [SHOP]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SOURCE: SOURCE_TOKEN, CONF_TOKEN: "new-token"}


async def test_flow_refuses_same_account_twice(hass: HomeAssistant, entry, core_entry, todoist):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: core_entry.entry_id})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_changes_projects(hass: HomeAssistant, loaded, todoist):
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PROJECTS: [SHOP, WORK], "show_completed": False, CONF_ADMIN_ONLY: True, "scan_interval": 120},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert loaded.options[CONF_PROJECTS] == [SHOP, WORK]
    assert loaded.state is ConfigEntryState.LOADED
    assert set(loaded.runtime_data.data) == {SHOP, WORK}


# ---- setup and data ----------------------------------------------------------


async def test_only_ticked_projects_are_fetched(hass: HomeAssistant, loaded, todoist):
    data = loaded.runtime_data.data
    assert set(data) == {SHOP}
    for _method, path, _, _ in todoist.calls:
        assert WORK not in path
    queried = [c for c in todoist.calls if c[1] in ("/api/v1/tasks", "/api/v1/sections")]
    assert queried, "fetched the ticked project"
    shop = data[SHOP]
    assert [s["name"] for s in shop.sections] == ["Fruit", "Bakery"], "ordered, archived removed"
    assert [t["content"] for t in shop.tasks] == ["Bananas", "Milk"], "both pages fetched"
    assert [t["content"] for t in shop.completed] == ["Eggs"]


async def test_devices_and_count_sensor(hass: HomeAssistant, loaded):
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), loaded.entry_id)
    assert [d.name for d in devices] == ["Shopping"]
    states = [s for s in hass.states.async_all("sensor") if s.entity_id.startswith("sensor.shopping")]
    assert len(states) == 1
    assert states[0].state == "2"
    assert "tasks" not in states[0].attributes and "results" not in states[0].attributes


async def test_token_is_read_from_core_entry_each_time(hass: HomeAssistant, loaded, core_entry, todoist):
    hass.config_entries.async_update_entry(core_entry, data={CONF_TOKEN: "new-token"})
    todoist.calls.clear()
    await loaded.runtime_data.async_refresh()
    assert todoist.calls and all(c[3] == "Bearer new-token" for c in todoist.calls)


async def test_rejected_token_starts_reauth(hass: HomeAssistant, loaded, todoist):
    todoist.valid_tokens = set()
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_removed_core_entry_starts_reauth(hass: HomeAssistant, loaded, core_entry, todoist):
    await hass.config_entries.async_remove(core_entry.entry_id)
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_diagnostics_redacts_token(hass: HomeAssistant, core_entry, todoist):
    from custom_components.natural_language_todo.diagnostics import async_get_config_entry_diagnostics

    e = MockConfigEntry(
        domain=DOMAIN, unique_id="4242", data={CONF_SOURCE: SOURCE_TOKEN, CONF_TOKEN: "new-token"},
        options={CONF_PROJECTS: [SHOP]},
    )
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    diag = await async_get_config_entry_diagnostics(hass, e)
    assert "new-token" not in str(diag)
    assert "Bananas" not in str(diag), "no task text"
    assert diag["projects"][SHOP] == {"sections": 2, "tasks": 2, "completed": 1}


# ---- websocket -----------------------------------------------------------------


async def test_subscribe_sends_minimal_project_data(hass: HomeAssistant, loaded, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe", "project_id": SHOP})
    assert (await client.receive_json())["success"]
    event = (await client.receive_json())["event"]
    assert event["project"] == {"id": SHOP, "name": "Shopping"}
    assert [s["name"] for s in event["sections"]] == ["Fruit", "Bakery"]
    first = event["tasks"][0]
    assert set(first) == {"id", "content", "section_id", "parent_id", "order", "due", "completed_at"}
    assert "private notes" not in str(event) and "responsible_uid" not in str(event)

    await client.send_json_auto_id({"type": f"{DOMAIN}/projects"})
    assert (await client.receive_json())["result"] == {"projects": [{"id": SHOP, "name": "Shopping"}]}


@pytest.mark.parametrize("project_id", [WORK, "../x", "x/../../projects/y"])
async def test_subscribe_refuses_other_projects(hass: HomeAssistant, loaded, hass_ws_client, project_id):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe", "project_id": project_id})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_subscribe_pushes_updates(hass: HomeAssistant, loaded, hass_ws_client, todoist):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe", "project_id": SHOP})
    await client.receive_json()
    await client.receive_json()
    todoist.tasks[SHOP].append({"id": "t3", "project_id": SHOP, "content": "Tea", "child_order": 3})
    await loaded.runtime_data.async_refresh()
    event = (await client.receive_json())["event"]
    assert "Tea" in [t["content"] for t in event["tasks"]]


# ---- actions ---------------------------------------------------------------------


async def call(hass, service, data, context=None, response=False):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, context=context, return_response=response
    )


async def test_add_task_quick_adds_then_moves(hass: HomeAssistant, loaded, todoist):
    todoist.calls.clear()
    res = await call(hass, "add_task", {"text": "croissants tomorrow", "project_id": SHOP, "section_id": "sec2"}, response=True)
    assert res == {"id": "n101", "content": "croissants tomorrow", "due": "tomorrow", "moved": True}
    posts = [(c[1], c[2]) for c in todoist.calls if c[0] == "POST"]
    assert posts == [
        ("/api/v1/tasks/quick", {"text": "croissants tomorrow"}),
        ("/api/v1/tasks/n101/move", {"section_id": "sec2"}),
    ]


async def test_add_task_without_section_moves_to_project(hass: HomeAssistant, loaded, todoist):
    todoist.calls.clear()
    await call(hass, "add_task", {"text": "milk", "project_id": SHOP}, response=True)
    assert ("/api/v1/tasks/n101/move", {"project_id": SHOP}) in [(c[1], c[2]) for c in todoist.calls]


async def test_add_task_reports_failed_move(hass: HomeAssistant, loaded, todoist):
    todoist.fail_move = True
    res = await call(hass, "add_task", {"text": "milk", "project_id": SHOP}, response=True)
    assert res["moved"] is False


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"text": "x", "project_id": WORK}, "not set up"),
        ({"text": "x", "project_id": "../../projects"}, "not a valid Todoist ID"),
        ({"text": "x", "project_id": SHOP, "section_id": "w1"}, "not in project"),
        ({"text": "x", "project_id": SHOP, "section_id": "a/b"}, "not a valid Todoist ID"),
    ],
)
async def test_add_task_refuses_bad_input(hass: HomeAssistant, loaded, todoist, data, error):
    todoist.calls.clear()
    with pytest.raises(ServiceValidationError, match=error):
        await call(hass, "add_task", data, response=True)
    assert not [c for c in todoist.calls if c[0] == "POST"], "nothing sent to Todoist"


async def test_set_done_closes_and_reopens(hass: HomeAssistant, loaded, todoist):
    todoist.calls.clear()
    await call(hass, "set_done", {"task_id": "t1", "done": True})
    await call(hass, "set_done", {"task_id": "c1", "done": False})
    posts = [c[1] for c in todoist.calls if c[0] == "POST"]
    assert posts == ["/api/v1/tasks/t1/close", "/api/v1/tasks/c1/reopen"]


@pytest.mark.parametrize("task_id", ["w9", "x/../../projects/6QvgPQ78mV9wCp7j/archive", "t1?x", ""])
async def test_set_done_refuses_tasks_outside_ticked_projects(hass: HomeAssistant, loaded, todoist, task_id):
    todoist.calls.clear()
    with pytest.raises((ServiceValidationError, vol.Invalid)):
        await call(hass, "set_done", {"task_id": task_id, "done": True})
    assert not [c for c in todoist.calls if c[0] == "POST"], "nothing sent to Todoist"


async def test_admin_only(hass: HomeAssistant, loaded, todoist, hass_admin_user, hass_read_only_user):
    hass.config_entries.async_update_entry(loaded, options={**loaded.options, CONF_ADMIN_ONLY: True})
    await hass.async_block_till_done()
    todoist.calls.clear()
    with pytest.raises(Unauthorized):
        await call(hass, "set_done", {"task_id": "t1", "done": True}, context=Context(user_id=hass_read_only_user.id))
    with pytest.raises(Unauthorized):
        await call(hass, "add_task", {"text": "x", "project_id": SHOP}, context=Context(user_id=hass_read_only_user.id), response=True)
    assert not [c for c in todoist.calls if c[0] == "POST"]
    await call(hass, "set_done", {"task_id": "t1", "done": True}, context=Context(user_id=hass_admin_user.id))
    await call(hass, "set_done", {"task_id": "t2", "done": True})  # automations: no user
    assert [c[1] for c in todoist.calls if c[0] == "POST"] == ["/api/v1/tasks/t1/close", "/api/v1/tasks/t2/close"]


async def test_api_errors_become_readable_errors(hass: HomeAssistant, loaded, todoist):
    todoist.valid_tokens = set()
    with pytest.raises(HomeAssistantError, match="rejected the token"):
        await call(hass, "set_done", {"task_id": "t1", "done": True})


async def test_subscription_survives_reload(hass: HomeAssistant, loaded, hass_ws_client, todoist):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe", "project_id": SHOP})
    await client.receive_json()
    await client.receive_json()
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    event = (await client.receive_json())["event"]  # sent by the reloaded entry
    assert event["project"]["id"] == SHOP
    todoist.tasks[SHOP].append({"id": "t4", "project_id": SHOP, "content": "Jam", "child_order": 4})
    await loaded.runtime_data.async_refresh()
    event = (await client.receive_json())["event"]
    assert "Jam" in [t["content"] for t in event["tasks"]]
