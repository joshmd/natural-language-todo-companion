"""Constants for the Natural Language To-do companion."""

from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "natural_language_todo"

API_BASE: Final = "https://api.todoist.com/api/v1"

# How the entry gets its Todoist token.
CONF_SOURCE: Final = "source"
SOURCE_TODOIST_ENTRY: Final = "todoist_entry"  # reuse the core Todoist integration
SOURCE_TOKEN: Final = "token"  # token entered in this integration
CONF_TODOIST_ENTRY_ID: Final = "todoist_entry_id"

# Options.
CONF_PROJECTS: Final = "projects"
CONF_SHOW_COMPLETED: Final = "show_completed"
CONF_ADMIN_ONLY: Final = "admin_only"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 3600
COMPLETED_DAYS: Final = 7
PAGE_LIMIT: Final = 200
MAX_PAGES: Final = 25  # 5,000 items per list is plenty for a dashboard card

# Todoist IDs are letters, digits, "_" and "-". Anything else is refused
# before it gets near a URL.
ID_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

SERVICE_ADD_TASK: Final = "add_task"
SERVICE_SET_DONE: Final = "set_done"

WS_PROJECTS: Final = f"{DOMAIN}/projects"
WS_SUBSCRIBE: Final = f"{DOMAIN}/subscribe"


def signal_project_updated(project_id: str) -> str:
    """Dispatcher signal sent whenever a project's data is refreshed."""
    return f"{DOMAIN}_project_updated_{project_id}"
