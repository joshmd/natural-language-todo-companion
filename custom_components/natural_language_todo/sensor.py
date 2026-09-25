"""Open-task count per project. The count only: no task text in states."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NLTodoConfigEntry, project_device
from .coordinator import NLTodoCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: NLTodoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(OpenTasksSensor(coordinator, pid) for pid in coordinator.data)


class OpenTasksSensor(CoordinatorEntity[NLTodoCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "open_tasks"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:checkbox-marked-circle-outline"

    def __init__(self, coordinator: NLTodoCoordinator, project_id: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._project_id = project_id
        self._attr_unique_id = f"{entry.entry_id}_{project_id}_open_tasks"
        self._attr_device_info = project_device(entry, project_id, coordinator.data[project_id].name)

    @property
    def available(self) -> bool:
        return super().available and self._project_id in (self.coordinator.data or {})

    @property
    def native_value(self) -> int | None:
        project = (self.coordinator.data or {}).get(self._project_id)
        return len(project.tasks) if project else None
