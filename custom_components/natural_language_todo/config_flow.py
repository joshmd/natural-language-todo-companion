"""Set up in Settings > Devices & services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TodoistAuthError, TodoistClient, TodoistError
from .const import (
    CONF_ADMIN_ONLY,
    CONF_PROJECTS,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_COMPLETED,
    CONF_SOURCE,
    CONF_TODOIST_ENTRY_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SOURCE_TODOIST_ENTRY,
    SOURCE_TOKEN,
)
from .coordinator import TODOIST_DOMAIN

DEFAULT_OPTIONS = {
    CONF_SHOW_COMPLETED: True,
    CONF_ADMIN_ONLY: False,
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
}


def _todoist_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        e
        for e in hass.config_entries.async_entries(TODOIST_DOMAIN)
        if e.state is ConfigEntryState.LOADED and e.data.get(CONF_TOKEN)
    ]


def _client(hass: HomeAssistant, token: str) -> TodoistClient:
    async def get_token() -> str:
        return token

    return TodoistClient(async_get_clientsession(hass), get_token)


def _project_selector(projects: list[dict]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=str(p["id"]), label=p.get("name") or str(p["id"])) for p in projects],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


class NLTodoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._projects: list[dict] = []

    # ---- choosing where the token comes from -----------------------------

    def _source_schema(self) -> vol.Schema:
        options = [
            SelectOptionDict(value=e.entry_id, label=f"Use my Todoist integration ({e.title})")
            for e in _todoist_entries(self.hass)
        ]
        options.append(SelectOptionDict(value=SOURCE_TOKEN, label="Enter a Todoist API token"))
        return vol.Schema(
            {
                vol.Required(CONF_SOURCE, default=options[0]["value"]): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )

    def _token_schema(self) -> vol.Schema:
        return vol.Schema({vol.Required(CONF_TOKEN): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))})

    async def _connect(self, data: dict[str, Any]) -> tuple[dict | None, str | None]:
        """Check the token works. Returns (user, error key)."""
        if data[CONF_SOURCE] == SOURCE_TODOIST_ENTRY:
            core = self.hass.config_entries.async_get_entry(data[CONF_TODOIST_ENTRY_ID])
            token = core.data.get(CONF_TOKEN) if core else None
        else:
            token = data.get(CONF_TOKEN)
        if not token:
            return None, "invalid_auth"
        client = _client(self.hass, token)
        try:
            user = await client.user()
            self._projects = await client.projects()
        except TodoistAuthError:
            return None, "invalid_auth"
        except TodoistError:
            return None, "cannot_connect"
        return user, None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not _todoist_entries(self.hass):
            return await self.async_step_token()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_SOURCE] == SOURCE_TOKEN:
                return await self.async_step_token()
            data = {CONF_SOURCE: SOURCE_TODOIST_ENTRY, CONF_TODOIST_ENTRY_ID: user_input[CONF_SOURCE]}
            result = await self._linked(data, errors)
            if result:
                return result
        return self.async_show_form(step_id="user", data_schema=self._source_schema(), errors=errors)

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_SOURCE: SOURCE_TOKEN, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
            result = await self._linked(data, errors)
            if result:
                return result
        return self.async_show_form(step_id="token", data_schema=self._token_schema(), errors=errors)

    async def _linked(self, data: dict[str, Any], errors: dict[str, str]) -> ConfigFlowResult | None:
        user, error = await self._connect(data)
        if error:
            errors["base"] = error
            return None
        await self.async_set_unique_id(str(user.get("id", "")))
        if self.source == "reauth":
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        self._abort_if_unique_id_configured()
        self._data = data
        return await self.async_step_projects()

    # ---- choosing projects -------------------------------------------------

    async def async_step_projects(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_PROJECTS):
                errors["base"] = "no_projects"
            else:
                return self.async_create_entry(
                    title="Todoist",
                    data=self._data,
                    options={**DEFAULT_OPTIONS, CONF_PROJECTS: user_input[CONF_PROJECTS]},
                )
        schema = vol.Schema({vol.Required(CONF_PROJECTS, default=[]): _project_selector(self._projects)})
        return self.async_show_form(step_id="projects", data_schema=schema, errors=errors)

    # ---- reauthentication ----------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_SOURCE] == SOURCE_TOKEN:
                return await self.async_step_token()
            data = {CONF_SOURCE: SOURCE_TODOIST_ENTRY, CONF_TODOIST_ENTRY_ID: user_input[CONF_SOURCE]}
            result = await self._linked(data, errors)
            if result:
                return result
        return self.async_show_form(step_id="reauth_confirm", data_schema=self._source_schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NLTodoOptionsFlow:
        return NLTodoOptionsFlow()


class NLTodoOptionsFlow(OptionsFlowWithReload):
    """Configure: projects and behaviour. Reloads the entry on save."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opts = {**DEFAULT_OPTIONS, **self.config_entry.options}
        if user_input is not None:
            if not user_input.get(CONF_PROJECTS):
                errors["base"] = "no_projects"
            else:
                return self.async_create_entry(data={**opts, **user_input})
        try:
            projects = await self.config_entry.runtime_data.client.projects()
        except Exception:  # noqa: BLE001 - fall back to what is already chosen
            projects = [{"id": p, "name": p} for p in opts.get(CONF_PROJECTS, [])]
        schema = vol.Schema(
            {
                vol.Required(CONF_PROJECTS, default=opts.get(CONF_PROJECTS, [])): _project_selector(projects),
                vol.Required(CONF_SHOW_COMPLETED, default=opts[CONF_SHOW_COMPLETED]): BooleanSelector(),
                vol.Required(CONF_ADMIN_ONLY, default=opts[CONF_ADMIN_ONLY]): BooleanSelector(),
                vol.Required(CONF_SCAN_INTERVAL, default=opts[CONF_SCAN_INTERVAL]): vol.All(
                    NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Coerce(int),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
