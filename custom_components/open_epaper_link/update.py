"""Firmware update status for OpenEPaperLink access points."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

import aiohttp
from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import Hub
from .entity import OpenEPaperLinkAPEntity
from .firmware import (
    DEFAULT_FIRMWARE_REPOSITORY,
    FirmwareRelease,
    async_get_latest_firmware_release,
)
from .runtime_data import OpenEPaperLinkConfigEntry
from .util import is_ble_entry

_LOGGER: Final = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(hours=6)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenEPaperLinkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the firmware update entity for an AP config entry."""
    entry_data = entry.runtime_data
    if is_ble_entry(entry_data):
        return

    async_add_entities([OpenEPaperLinkAPFirmwareUpdate(entry_data)], True)


class OpenEPaperLinkAPFirmwareUpdate(OpenEPaperLinkAPEntity, UpdateEntity):
    """Report firmware updates without offering installation."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_registry_enabled_default = True
    _attr_translation_key = "firmware"
    _attr_title = "OpenEPaperLink AP"

    def __init__(self, hub: Hub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.entry.entry_id}_firmware"
        self._release: FirmwareRelease | None = None

    @property
    def installed_version(self) -> str | None:
        """Return the firmware version reported by the AP."""
        return self._hub.ap_build_version

    @property
    def latest_version(self) -> str | None:
        """Return the latest compatible stable firmware version."""
        return self._release.version if self._release else None

    @property
    def release_url(self) -> str | None:
        """Return the GitHub release page for the offered version."""
        return self._release.release_url if self._release else None

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Match the AP web UI's release/build-time comparison semantics."""
        if latest_version == installed_version:
            return False

        if (
            self._release is not None
            and self._release.published_at is not None
            and self._hub.ap_build_time is not None
            and self._hub.ap_build_time
            > self._release.published_at + timedelta(minutes=30)
        ):
            return False

        return True

    async def async_update(self) -> None:
        """Refresh installed and latest compatible firmware metadata."""
        try:
            await self._hub.async_update_ap_info()
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as err:
            _LOGGER.debug(
                "Unable to refresh firmware information from AP %s: %s",
                self._hub.host,
                err,
            )

        if not self._hub.ap_config:
            await self._hub.async_update_ap_config()

        repository = (
            self._hub.ap_config.get("repo") or DEFAULT_FIRMWARE_REPOSITORY
        )
        self._release = await async_get_latest_firmware_release(
            self.hass,
            repository,
            self._hub.ap_env,
        )
