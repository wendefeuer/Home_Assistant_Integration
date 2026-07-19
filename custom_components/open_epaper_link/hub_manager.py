"""Runtime registry and routing for multiple OpenEPaperLink access points."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import Hub

_LOGGER: Final = logging.getLogger(__name__)

HUB_MANAGER_KEY = "hub_manager"
AP_IDENTIFIER_PREFIX = "ap_"
TAG_EVENT_STORAGE_KEY = f"{DOMAIN}_tag_events"
TAG_EVENT_STORAGE_VERSION = 1
TRACKED_TAG_EVENTS = ("BUTTON1", "BUTTON2", "NFC")


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
        self._tag_event_store: Store[dict[str, Any]] | None = None
        self._tag_event_stats: dict[str, dict[str, dict[str, Any]]] = {}
        self._tag_event_lock = asyncio.Lock()
        self._tag_events_loaded = False

    async def async_load_tag_events(self) -> None:
        """Load persistent button and NFC statistics once for all APs."""
        async with self._tag_event_lock:
            if self._tag_events_loaded:
                return
            self._tag_event_store = Store[dict[str, Any]](
                self.hass,
                TAG_EVENT_STORAGE_VERSION,
                TAG_EVENT_STORAGE_KEY,
                private=True,
                atomic_writes=True,
            )
            stored = await self._tag_event_store.async_load() or {}
            tags = stored.get("tags", {})
            self._tag_event_stats = tags if isinstance(tags, dict) else {}
            self._tag_events_loaded = True

    def get_tag_event_stats(self, tag_mac: str) -> dict[str, dict[str, Any]]:
        """Return a defensive copy of the HA-managed event values for a tag."""
        stats = self._tag_event_stats.get(normalize_tag_mac(tag_mac), {})
        return {
            event_type: dict(values)
            for event_type, values in stats.items()
            if isinstance(values, dict)
        }

    async def async_record_tag_event(
        self, tag_mac: str, event_type: str, occurred_at: float
    ) -> None:
        """Persist one accepted button or NFC event for a logical tag."""
        if event_type not in TRACKED_TAG_EVENTS:
            return
        await self.async_load_tag_events()
        tag_mac = normalize_tag_mac(tag_mac)
        async with self._tag_event_lock:
            tag_stats = self._tag_event_stats.setdefault(tag_mac, {})
            event_stats = tag_stats.setdefault(event_type, {})
            event_stats["count"] = int(event_stats.get("count", 0)) + 1
            event_stats["last"] = occurred_at
            await self._tag_event_store.async_save(
                {"tags": self._tag_event_stats}
            )

    async def async_reset_tag_event_count(
        self, tag_mac: str, event_type: str
    ) -> None:
        """Reset one persistent event counter without clearing its timestamp."""
        if event_type not in TRACKED_TAG_EVENTS:
            return
        await self.async_load_tag_events()
        tag_mac = normalize_tag_mac(tag_mac)
        async with self._tag_event_lock:
            tag_stats = self._tag_event_stats.setdefault(tag_mac, {})
            event_stats = tag_stats.setdefault(event_type, {})
            event_stats["count"] = 0
            await self._tag_event_store.async_save(
                {"tags": self._tag_event_stats}
            )

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

        A replicated ``is_external`` record must never own the shared entities.
        When a tag moved between APs, migrate its existing registry entries to
        the freshest local owner while preserving entity IDs and unique IDs.
        """
        tag_mac = normalize_tag_mac(tag_mac)
        local_candidates = [
            hub
            for hub in self.hubs_for_tag(tag_mac)
            if not self._tag_is_external(hub, tag_mac)
        ]
        if not local_candidates:
            self._tag_owners.pop(tag_mac, None)
            _LOGGER.debug(
                "No local entity owner for tag %s; replicated records are ignored",
                tag_mac,
            )
            return False

        selected = max(
            local_candidates,
            key=lambda hub: (self._tag_last_seen(hub, tag_mac), hub.entry.entry_id),
        )
        owner = selected.entry.entry_id
        previous_owner = self._tag_owners.get(tag_mac)
        self._tag_owners[tag_mac] = owner

        if previous_owner != owner:
            self._migrate_tag_registry_owner(tag_mac, owner)
            _LOGGER.info(
                "Logical tag %s entity owner is local AP %s (entry %s)",
                tag_mac,
                selected.host,
                owner,
            )
        return owner == entry_id

    def _migrate_tag_registry_owner(self, tag_mac: str, owner: str) -> None:
        """Move existing tag registry records to the selected local AP entry."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        prefix = f"{tag_mac}_"
        tag_entities = [
            entity
            for entity in entity_registry.entities.values()
            if entity.platform == DOMAIN
            and entity.unique_id
            and entity.unique_id.upper().startswith(prefix)
        ]
        stale_owners = {
            entity.config_entry_id
            for entity in tag_entities
            if entity.config_entry_id and entity.config_entry_id != owner
        }
        device_ids = {
            entity.device_id for entity in tag_entities if entity.device_id
        }

        for entity in tag_entities:
            if entity.config_entry_id != owner:
                entity_registry.async_update_entity(
                    entity.entity_id,
                    config_entry_id=owner,
                )

        tag_device = device_registry.async_get_device(
            identifiers={(DOMAIN, tag_mac)}
        )
        if tag_device is not None:
            device_ids.add(tag_device.id)

        for device_id in device_ids:
            device = device_registry.async_get(device_id)
            if device is None:
                continue
            if owner not in device.config_entries:
                device_registry.async_update_device(
                    device_id,
                    add_config_entry_id=owner,
                )
            for stale_owner in stale_owners:
                if stale_owner not in device.config_entries:
                    continue
                still_used = any(
                    entity.device_id == device_id
                    and entity.config_entry_id == stale_owner
                    for entity in entity_registry.entities.values()
                )
                if not still_used:
                    device_registry.async_update_device(
                        device_id,
                        remove_config_entry_id=stale_owner,
                    )

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
