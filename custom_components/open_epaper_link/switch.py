from __future__ import annotations

PARALLEL_UPDATES = 1

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .drawcustom_cache import get_drawcustom_cache
from .entity import OpenEPaperLinkAPEntity, OpenEPaperLinkTagEntity
from .hub_manager import get_hub_manager
from .runtime_data import OpenEPaperLinkConfigEntry

import logging

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class OpenEPaperLinkSwitchDescription(SwitchEntityDescription):
    """Switch description with explicit default enable flag."""

    description: str
    entity_registry_enabled_default: bool = False


# Define switch configurations
SWITCH_ENTITIES: tuple[OpenEPaperLinkSwitchDescription, ...] = (
    OpenEPaperLinkSwitchDescription(
        key="preview",
        translation_key="preview",
        name="Preview Images",
        description="Enable/disable preview images on the AP",
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSwitchDescription(
        key="ble",
        translation_key="ble",
        name="Bluetooth",
        description="Enable/disable Bluetooth",
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSwitchDescription(
        key="nightlyreboot",
        translation_key="nightlyreboot",
        name="Nightly Reboot",
        description="Enable/disable automatic nightly reboot of the AP",
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSwitchDescription(
        key="showtimestamp",
        translation_key="showtimestamp",
        name="Show Timestamp",
        description="Enable/disable showing timestamps on ESLs",
        entity_registry_enabled_default=True,
    ),
)
"""Configuration for all switch entities to create for the AP."""


class APConfigSwitch(OpenEPaperLinkAPEntity, SwitchEntity):
    """Switch entity for AP configuration."""

    entity_description: OpenEPaperLinkSwitchDescription

    def __init__(self, hub, description: OpenEPaperLinkSwitchDescription) -> None:
        """Initialize the switch entity."""
        super().__init__(hub)
        self.entity_description = description
        self._key = description.key
        self._attr_unique_id = f"{hub.entry.entry_id}_{description.key}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_translation_key = description.translation_key or description.key
        self._description = description.description
        self._attr_device_class = SwitchDeviceClass.SWITCH
        self._attr_entity_registry_enabled_default = description.entity_registry_enabled_default

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._hub.online and self._key in self._hub.ap_config

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        if not self.available:
            return None
        return bool(int(self._hub.ap_config.get(self._key, 0)))

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the entity on."""
        await self._hub.set_ap_config_item(self._key, 1)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        await self._hub.set_ap_config_item(self._key, 0)

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_ap_config_update",
                self._handle_update,
            )
        )


class TagResendImageAfterRebootSwitch(OpenEPaperLinkTagEntity, SwitchEntity):
    """Enable automatic replay of the last successful drawcustom image."""

    _attr_entity_registry_enabled_default = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, hub, tag_mac: str) -> None:
        """Initialize the per-display reboot recovery switch."""
        super().__init__(hub, tag_mac)
        self._cache = get_drawcustom_cache(hub.hass)
        self._target_key = f"ap:{tag_mac.upper()}"
        self._attr_unique_id = f"{tag_mac}_resend_image_after_reboot"
        self._attr_translation_key = "resend_image_after_reboot"

    @property
    def is_on(self) -> bool:
        """Return the persisted reboot recovery setting."""
        return self._cache.is_resend_enabled(self._target_key)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable automatic image replay for this display."""
        await self._cache.async_set_resend_enabled(self._target_key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable automatic image replay for this display."""
        await self._cache.async_set_resend_enabled(self._target_key, False)
        self.async_write_ha_state()


async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up switch entities for AP configuration.

    Creates switch entities for all defined AP configuration options
    based on the SWITCH_ENTITIES definition list.

    For each defined switch:

    1. Creates an APConfigSwitch instance with appropriate configuration
    2. Ensures the AP configuration is loaded before creating entities
    3. Adds all created entities to Home Assistant

    Args:
        hass: Home Assistant instance
        entry: Configuration entry
        async_add_entities: Callback to register new entities
    """
    hub = entry.runtime_data
    hub_manager = get_hub_manager(hass)

    # Wait for initial AP config to be loaded
    if not hub.ap_config:
        await hub.async_update_ap_config()

    entities = []

    # Create switch entities from configuration
    for description in SWITCH_ENTITIES:
        entities.append(APConfigSwitch(hub, description))

    added_tag_switches: set[str] = set()
    for tag_mac in hub.tags:
        if hub_manager.is_tag_entity_owner(entry.entry_id, tag_mac):
            entities.append(TagResendImageAfterRebootSwitch(hub, tag_mac))
            added_tag_switches.add(tag_mac)

    async_add_entities(entities)

    @callback
    def async_add_tag_switch(tag_mac: str) -> None:
        """Add the reboot recovery switch for a newly discovered tag."""
        if (
            tag_mac not in added_tag_switches
            and hub_manager.is_tag_entity_owner(entry.entry_id, tag_mac)
        ):
            added_tag_switches.add(tag_mac)
            async_add_entities([TagResendImageAfterRebootSwitch(hub, tag_mac)])

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, f"{DOMAIN}_tag_discovered", async_add_tag_switch
        )
    )
