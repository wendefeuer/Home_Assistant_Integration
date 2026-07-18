"""Runtime registry and routing for multiple OpenEPaperLink access points."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import Hub

_LOGGER: Final = logging.getLogger(__name__)

HUB_MANAGER_KEY = "hub_manager"
AP_IDENTIFIER_PREFIX = "ap_"


def normalize_tag_mac(tag_mac: str) -> str:
    """Return the canonical tag MAC representation used by the integration."""
    return tag_mac.upper()


def ap_identifier(entry_id: str) -> str:
    """Return the unique device-registry identifier for an AP config entry."""
    return f"{AP_IDENTIFIER_PREFIX}{entry_id}"


class MultiHubManager:
    """Track loaded AP hubs and route a logical tag to the correct AP."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._hubs: dict[str, Hub] = {}
        self._tag_owners: dict[str, str] = {}

    @property
    def hubs(self) -> tuple[Hub, ...]:
        """Return all registered AP hubs."""
        return tuple(self._hubs.values())

    def register_hub(self, hub: Hub) -> None:
        """Register or replace the runtime hub for a config entry."""
        self._hubs[hub.entry.entry_id] = hub
        _LOGGER.debug(
            "Registered OpenEPaperLink AP %s for entry %s",
            hub.host,
            hub.entry.entry_id,
        )

    def unregister_hub(self, entry_id: str) -> None:
        """Remove an unloaded AP hub from routing."""
        hub = self._hubs.pop(entry_id, None)
        self._tag_owners = {
            tag_mac: owner
            for tag_mac, owner in self._tag_owners.items()
            if owner != entry_id
        }
        if hub:
            _LOGGER.debug(
                "Unregistered OpenEPaperLink AP %s for entry %s",
                hub.host,
                entry_id,
            )

    def get_hub_for_entry(self, entry_id: str) -> Hub:
        """Return the AP hub for an integration config entry."""
        hub = self._hubs.get(entry_id)
        if hub is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="ap_entry_not_loaded",
                translation_placeholders={"entry_id": entry_id},
            )
        return hub

    @staticmethod
    def _tag_last_seen(hub: Hub, tag_mac: str) -> float:
        value = hub.get_tag_data(tag_mac).get("last_seen", 0)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _tag_is_external(hub: Hub, tag_mac: str) -> bool:
        """Return whether the AP only knows a replicated copy of the tag."""
        return hub.get_tag_data(tag_mac).get("is_external") is True

    def hubs_for_tag(self, tag_mac: str) -> list[Hub]:
        """Return hubs that currently know an unblacklisted tag."""
        tag_mac = normalize_tag_mac(tag_mac)
        return [
            hub
            for hub in self._hubs.values()
            if tag_mac in {normalize_tag_mac(mac) for mac in hub.tags}
            and tag_mac
            not in {normalize_tag_mac(mac) for mac in hub.get_blacklisted_tags()}
        ]

    def resolve_tag_hub(self, tag_mac: str, *, require_online: bool = True) -> Hub:
        """Resolve a logical tag to its active AP.

        Only an AP with a local, online tag may receive write operations.
        Replicated ``is_external`` database entries cannot deliver data to the
        physical tag and are therefore excluded from active routing. If more
        than one local AP reports the tag online, the freshest ``last_seen``
        wins. Read-only callers may set ``require_online=False`` and receive
        the freshest local, online, or cached candidate.
        """
        tag_mac = normalize_tag_mac(tag_mac)
        candidates = self.hubs_for_tag(tag_mac)
        local_candidates = [
            hub
            for hub in candidates
            if not self._tag_is_external(hub, tag_mac)
        ]
        active = [
            hub
            for hub in local_candidates
            if hub.online and hub.is_tag_online(tag_mac)
        ]

        if require_online:
            selectable = active
        else:
            selectable = (
                active
                or [hub for hub in local_candidates if hub.online]
                or local_candidates
                or [hub for hub in candidates if hub.online]
                or candidates
            )

        if not selectable:
            candidate_hosts = ", ".join(sorted(hub.host for hub in candidates)) or "none"
            _LOGGER.debug(
                "No routable AP for tag %s (candidates: %s)",
                tag_mac,
                candidate_hosts,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=(
                    "tag_no_online_ap"
                    if candidates
                    else "tag_not_registered_any_ap"
                ),
                translation_placeholders={
                    "tag_mac": tag_mac,
                    "candidate_hosts": candidate_hosts,
                },
            )

        selected = max(
            selectable,
            key=lambda hub: (self._tag_last_seen(hub, tag_mac), hub.entry.entry_id),
        )
        _LOGGER.debug(
            "Resolved tag %s to AP %s; candidates=%s; reason=%s",
            tag_mac,
            selected.host,
            [
                {
                    "host": hub.host,
                    "online": hub.online,
                    "tag_online": hub.is_tag_online(tag_mac) if hub.online else False,
                    "last_seen": self._tag_last_seen(hub, tag_mac),
                    "is_external": self._tag_is_external(hub, tag_mac),
                }
                for hub in candidates
            ],
            "freshest active last_seen" if active else "freshest cached data",
        )
        return selected

    def get_tag_data(self, tag_mac: str) -> dict[str, Any]:
        """Return the freshest available data for a logical tag."""
        try:
            return self.resolve_tag_hub(tag_mac, require_online=False).get_tag_data(
                normalize_tag_mac(tag_mac)
            )
        except HomeAssistantError:
            return {}

    def is_tag_available(self, tag_mac: str) -> bool:
        """Return whether any loaded AP currently owns the live tag connection."""
        try:
            self.resolve_tag_hub(tag_mac, require_online=True)
        except HomeAssistantError:
            return False
        return True

    def tag_exists_elsewhere(self, tag_mac: str, *, exclude_entry_id: str) -> bool:
        """Return whether another AP still exposes an unblacklisted tag."""
        return any(
            hub.entry.entry_id != exclude_entry_id
            for hub in self.hubs_for_tag(tag_mac)
        )

    def is_tag_entity_owner(self, entry_id: str, tag_mac: str) -> bool:
        """Choose one config entry to create the shared tag entities.

        Existing entity-registry ownership wins so entity IDs and automation
        references stay stable across upgrades and restarts.
        """
        tag_mac = normalize_tag_mac(tag_mac)
        owner = self._tag_owners.get(tag_mac)
        if owner is None:
            entity_registry = er.async_get(self.hass)
            prefix = f"{tag_mac}_"
            existing_owners = {
                entity.config_entry_id
                for entity in entity_registry.entities.values()
                if entity.platform == DOMAIN
                and entity.unique_id
                and entity.unique_id.upper().startswith(prefix)
                and entity.config_entry_id
            }
            owner = sorted(existing_owners)[0] if existing_owners else entry_id
            self._tag_owners[tag_mac] = owner
            _LOGGER.debug("Logical tag %s entity owner is %s", tag_mac, owner)
        return owner == entry_id

    def resolve_ap_device(self, device_id: str) -> Hub:
        """Resolve a selected HA AP device to its exact hub."""
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device_id": device_id},
            )

        identifier = next(
            (
                value
                for domain, value in device.identifiers
                if domain == DOMAIN and value.startswith(AP_IDENTIFIER_PREFIX)
            ),
            None,
        )
        if identifier is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_ap",
                translation_placeholders={"device_id": device_id},
            )
        return self.get_hub_for_entry(identifier[len(AP_IDENTIFIER_PREFIX):])


def get_hub_manager(hass: HomeAssistant) -> MultiHubManager:
    """Return the integration-wide multi-hub manager."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = domain_data.get(HUB_MANAGER_KEY)
    if manager is None:
        manager = MultiHubManager(hass)
        domain_data[HUB_MANAGER_KEY] = manager
    return manager
