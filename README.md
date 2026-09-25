# Natural Language To-do Companion

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=joshmd&repository=natural-language-todo-companion&category=integration)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Validate](https://github.com/joshmd/natural-language-todo-companion/actions/workflows/validate.yml/badge.svg)](https://github.com/joshmd/natural-language-todo-companion/actions/workflows/validate.yml)
[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?logo=buymeacoffee&logoColor=000000)](https://www.buymeacoffee.com/joshmd)

A Home Assistant integration that brings **Todoist sections** to the [Natural Language To-do Card](https://github.com/joshmd/natural-language-Todo).

Home Assistant's own Todoist integration shows each project as a to-do list, but it drops sections. This companion syncs the projects you choose, with their sections, and adds tasks with **Todoist's own Quick Add parser**, so `milk tomorrow 5pm /Bakery @shop p1` works exactly as it does in the Todoist app.

- **Set up in the UI.** Everything is done in **Settings → Devices & services**. There's no YAML to edit.
- **Reuses your Todoist connection.** If the Todoist integration is already set up, the companion uses it, so there's no token to paste.
- **Only syncs what you choose.** Tick the projects you want. Nothing else from your Todoist account comes into Home Assistant.

## Requirements

- Home Assistant **2026.1** or newer (tested on 2026.2 and 2026.9)
- [HACS](https://hacs.xyz)
- The [Natural Language To-do Card](https://github.com/joshmd/natural-language-Todo) **v0.3** or newer
- A Todoist account. The core [Todoist integration](https://www.home-assistant.io/integrations/todoist/) is recommended, but you can enter an API token instead

## Install

1. Click this button to open the repository in HACS:

   [![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=joshmd&repository=natural-language-todo-companion&category=integration)

   <details>
   <summary>If the button does not work</summary>

   1. Open **HACS** in Home Assistant.
   2. Select the three-dot menu (top right) → **Custom repositories**.
   3. Repository: `https://github.com/joshmd/natural-language-todo-companion`
   4. Type: **Integration**
   5. Select **Add**, then search HACS for **Natural Language To-do Companion**.

   </details>

2. Select **Download**, then **Download** again to confirm.
3. **Restart Home Assistant.**

## Set up

1. Go to **Settings → Devices & services → Add integration** and search for **Natural Language To-do Companion**.
2. Choose **Use my Todoist integration**. If you don't have the Todoist integration, paste an API token instead, from Todoist → **Settings → Integrations → Developer**.
3. Tick the projects you want on your dashboard and select **Submit**.

Each project appears as a device, with an **Open tasks** sensor you can use in automations.

To add or remove projects later, open the integration and select **Configure**.

## Use it in the card

Add a **Natural Language To-do Card**, choose **Todoist, with sections** in its editor, and pick a project. In YAML:

```yaml
type: custom:natural-language-todo-card
source: companion
project_id: 6Jf8VQXxpwv59GRH
title: Shopping
sort: due
```

Type `/` and a section's name to add to that section: `croissants tomorrow /Bakery`. Everything else is parsed by Todoist: dates, repeats (`every 2 months`), `@labels` and `p1`–`p4`.

## Options

Open the integration and select **Configure**:

| Option | Default | What it does |
|---|---|---|
| Projects | | The projects synced into Home Assistant |
| Sync completed tasks from the last 7 days | On | Lets the card show a Completed group |
| Only administrators can change tasks | Off | Other users can see lists but can't add, complete or reopen tasks. Automations aren't affected |
| Refresh every | 60 s | How often to check Todoist for changes made elsewhere. Changes made in the card show straight away |

## Actions

You can also use these in automations and scripts:

| Action | Fields |
|---|---|
| `natural_language_todo.add_task` | `text` (natural language), `project_id`, optional `section_id`. Returns the new task's ID, text and due date |
| `natural_language_todo.set_done` | `task_id`, `done` (true to complete, false to reopen) |

Both only work on tasks in projects you've ticked.

## Privacy and security

- **Your token stays on the server.** With **Use my Todoist integration**, the token is read from that integration each time it's needed and never copied. A pasted token is stored like any other integration's credentials. It's never sent to the browser, and the diagnostics download removes it.
- **Only ticked projects are synced.** Other projects are never fetched.
- **Only what the card needs leaves the integration:** task text, section, due date and order. Descriptions, comments and assignees are never sent to dashboards. The sensors hold a count only, so no task text is stored in Home Assistant's history.
- **Changes are limited to ticked projects.** The actions refuse tasks and sections outside them, and only accept well-formed Todoist IDs, so no request can reach another part of the Todoist API.
- **Anyone with a Home Assistant login can change tasks,** unless you turn on **Only administrators can change tasks**.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Reconnect to Todoist" in notifications | Todoist no longer accepts the token, or the Todoist integration was removed. Follow the prompt to choose an account or paste a new token. |
| The card says a project "isn't ticked" | Tick it under **Configure**. |
| The card says the companion is needed | Install this integration, restart, then set it up. |

## Licence

[MIT](LICENSE)

## Support

If this is useful to you, you can buy me a coffee:

<a href="https://www.buymeacoffee.com/joshmd"><img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=&slug=joshmd&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" height="50"></a>
