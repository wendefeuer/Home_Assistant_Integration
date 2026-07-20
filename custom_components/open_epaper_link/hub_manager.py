"""Runtime registry and routing for multiple OpenEPaperLink access points."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
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


def is_tag_identifier(identifier: str) -> bool:
    """Return whether a registry identifier is an AP-connected tag MAC."""
    normalized = normalize_tag_mac(identifier)
    return len(normalized) == 16 and all(
        character in "0123456789ABCDEF" for character in normalized
    )


def ap_identifier(entry_id: str) -> str:
    """Return the unique device-registry identifier for an AP config entry."""
    return f"{AP_IDENTIFIER_PREFIX}{entry_id}"


class MultiHubManager:
    """Track loaded AP hubs and route a logical tag to the correct AP."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._hubs: dict[str, Hub] = {}
        self._tag_owners: dict[str, str] = {}
        self._visible_tags: set[str] = set()
        self._hidden_external_tags: set[str] = set()
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

    def is_hub_registered(self, entry_id: str) -> bool:
        """Return whether an AP config entry currently has a runtime hub."""
        return entry_id in self._hubs

    def _all_enabled_ap_entries_loaded(self) -> bool:
        """Return whether every enabled AP entry has a registered hub.

        Cleanup must wait because an unavailable AP may own the local copy of
        an otherwise external tag.
        """
        config_entries = getattr(self.hass, "config_entries", None)
        if config_entries is None:
            return False

        configured_ap_entries = {
            entry.entry_id
            for entry in config_entries.async_entries(DOMAIN)
            if entry.data.get("device_type") != "ble"
            and entry.disabled_by is None
        }
        return configured_ap_entries.issubset(self._hubs)

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

    def local_hubs_for_tag(self, tag_mac: str) -> list[Hub]:
        """Return hubs that expose a local, non-replicated tag record."""
        tag_mac = normalize_tag_mac(tag_mac)
        return [
            hub
            for hub in self.hubs_for_tag(tag_mac)
            if not self._tag_is_external(hub, tag_mac)
        ]

    def is_tag_visible(self, tag_mac: str) -> bool:
        """Return whether a tag should be represented in Home Assistant."""
        return bool(self.local_hubs_for_tag(tag_mac))

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
        local_candidates = self.local_hubs_for_tag(tag_mac)
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
        local_candidates = self.local_hubs_for_tag(tag_mac)
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
        self._visible_tags.add(tag_mac)

        if previous_owner != owner:
            self._migrate_tag_registry_owner(tag_mac, owner)
            _LOGGER.info(
                "Logical tag %s entity owner is local AP %s (entry %s)",
                tag_mac,
                selected.host,
                owner,
            )
        return owner == entry_id

    async def async_reconcile_tag_visibility(self, tag_mac: str) -> bool:
        """Reconcile one tag's HA registry state with all loaded AP records."""
        tag_mac = normalize_tag_mac(tag_mac)
        local_candidates = self.local_hubs_for_tag(tag_mac)
        if local_candidates:
            was_visible = tag_mac in self._visible_tags
            self._hidden_external_tags.discard(tag_mac)
            selected = max(
                local_candidates,
                key=lambda hub: (
                    self._tag_last_seen(hub, tag_mac),
                    hub.entry.entry_id,
                ),
            )
            self.is_tag_entity_owner(selected.entry.entry_id, tag_mac)
            if not was_visible:
                _LOGGER.info(
                    "Local tag %s became visible in Home Assistant", tag_mac
                )
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_tag_discovered", tag_mac
                )
            return True

        self._tag_owners.pop(tag_mac, None)
        if not self._all_enabled_ap_entries_loaded():
            _LOGGER.debug(
                "Deferring cleanup for non-local tag %s until all AP entries load",
                tag_mac,
            )
            return False

        self._visible_tags.discard(tag_mac)
        if tag_mac not in self._hidden_external_tags:
            self._remove_tag_registry_entries(tag_mac)
            self._hidden_external_tags.add(tag_mac)
        return False

    async def async_reconcile_all_tag_visibility(self) -> bool:
        """Reconcile all runtime and registered tags after AP setup."""
        if not self._all_enabled_ap_entries_loaded():
            _LOGGER.debug(
                "Deferring tag visibility reconciliation until all AP entries load"
            )
            return False

        tag_macs = {
            normalize_tag_mac(tag_mac)
            for hub in self._hubs.values()
            for tag_mac in hub.tags
        }
        device_registry = dr.async_get(self.hass)
        tag_macs.update(
            normalize_tag_mac(identifier[1])
            for device in device_registry.devices.values()
            for identifier in device.identifiers
            if len(identifier) == 2
            and identifier[0] == DOMAIN
            and is_tag_identifier(identifier[1])
        )

        for tag_mac in sorted(tag_macs):
            await self.async_reconcile_tag_visibility(tag_mac)
        return True

    def _remove_tag_registry_entries(self, tag_mac: str) -> None:
        """Remove entities and device for a tag that has no local AP owner."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        prefix = f"{tag_mac}_"
        entity_ids = [
            entity.entity_id
            for entity in entity_registry.entities.values()
            if entity.platform == DOMAIN
            and entity.unique_id
            and entity.unique_id.upper().startswith(prefix)
        ]
        for entity_id in entity_ids:
            entity_registry.async_remove(entity_id)

        tag_device = device_registry.async_get_device(
            identifiers={(DOMAIN, tag_mac)}
        )
        if tag_device is not None:
            device_registry.async_remove_device(tag_device.id)

        if entity_ids or tag_device is not None:
            _LOGGER.info(
                "Removed external-only tag %s from Home Assistant (%d entities)",
                tag_mac,
                len(entity_ids),
            )

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
            device_stale_owners = stale_owners | {
                entry_id
                for entry_id in device.config_entries
                if entry_id in self._hubs and entry_id != owner
            }
            if owner not in device.config_entries:
                device_registry.async_update_device(
                    device_id,
                    add_config_entry_id=owner,
                )
            for stale_owner in device_stale_owners:
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
