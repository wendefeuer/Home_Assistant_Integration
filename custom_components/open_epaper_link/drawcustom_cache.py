"""Persistent upload fingerprint cache for the drawcustom action."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER: Final = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_drawcustom_cache"
STORAGE_VERSION = 1
CACHE_DATA_KEY = "drawcustom_cache"


@dataclass(frozen=True, slots=True)
class UploadReservation:
    """Identify one scheduled upload for cache bookkeeping."""

    target_key: str
    fingerprint: str
    sequence: int


@dataclass(frozen=True, slots=True)
class ReplayPayload:
    """Last successfully uploaded AP image and its effective parameters."""

    image_data: bytes
    parameters: dict[str, Any]
    fingerprint: str


def build_upload_fingerprint(image_data: bytes, parameters: dict[str, Any]) -> str:
    """Return a stable fingerprint for rendered content and effective settings."""
    digest = hashlib.sha256()
    digest.update(image_data)
    digest.update(b"\0")
    digest.update(
        json.dumps(
            parameters,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()


class DrawCustomUploadCache:
    """Track the last requested and successfully uploaded image per display."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the persistent cache."""
        self._store: Store[dict[str, dict[str, str]]] = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY,
            private=True,
            atomic_writes=True,
        )
        self._successful: dict[str, str] = {}
        self._replay_payloads: dict[str, ReplayPayload] = {}
        self._resend_enabled: set[str] = set()
        self._tail: dict[str, tuple[str, int]] = {}
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Restore fingerprints saved by an earlier Home Assistant run."""
        try:
            stored = await self._store.async_load()
        except Exception as err:  # pragma: no cover - storage helper owns I/O
            _LOGGER.warning("Unable to load drawcustom upload cache: %s", err)
            return

        fingerprints = stored.get("fingerprints", {}) if stored else {}
        if not isinstance(fingerprints, dict):
            _LOGGER.warning("Ignoring invalid drawcustom upload cache data")
            return

        self._successful = {
            str(target_key): fingerprint
            for target_key, fingerprint in fingerprints.items()
            if isinstance(fingerprint, str)
        }
        self._tail = {
            target_key: (fingerprint, 0)
            for target_key, fingerprint in self._successful.items()
        }

        replay_payloads = stored.get("replay_payloads", {}) if stored else {}
        if isinstance(replay_payloads, dict):
            for target_key, payload in replay_payloads.items():
                if not isinstance(payload, dict):
                    continue
                fingerprint = payload.get("fingerprint")
                encoded_image = payload.get("image")
                parameters = payload.get("parameters")
                if not (
                    isinstance(fingerprint, str)
                    and isinstance(encoded_image, str)
                    and isinstance(parameters, dict)
                ):
                    continue
                try:
                    image_data = base64.b64decode(encoded_image, validate=True)
                except (binascii.Error, ValueError, TypeError):
                    continue
                self._replay_payloads[str(target_key)] = ReplayPayload(
                    image_data=image_data,
                    parameters=dict(parameters),
                    fingerprint=fingerprint,
                )

        resend_enabled = stored.get("resend_enabled", []) if stored else []
        if isinstance(resend_enabled, list):
            self._resend_enabled = {
                str(target_key)
                for target_key in resend_enabled
                if isinstance(target_key, str)
            }

    async def async_reserve(
        self,
        target_key: str,
        fingerprint: str,
        *,
        only_if_changed: bool,
    ) -> UploadReservation | None:
        """Reserve an upload, or skip an unchanged opt-in request."""
        async with self._lock:
            tail = self._tail.get(target_key)
            if only_if_changed and tail and tail[0] == fingerprint:
                return None

            self._sequence += 1
            reservation = UploadReservation(
                target_key=target_key,
                fingerprint=fingerprint,
                sequence=self._sequence,
            )
            self._tail[target_key] = (fingerprint, reservation.sequence)
            return reservation

    async def async_mark_success(
        self,
        reservation: UploadReservation,
        replay_payload: ReplayPayload | None = None,
    ) -> None:
        """Record a successfully uploaded fingerprint and persist it."""
        async with self._lock:
            self._successful[reservation.target_key] = reservation.fingerprint
            if replay_payload is not None:
                self._replay_payloads[reservation.target_key] = replay_payload

            tail = self._tail.get(reservation.target_key)
            if tail == (reservation.fingerprint, reservation.sequence):
                self._tail[reservation.target_key] = (reservation.fingerprint, 0)

            await self._async_save_locked()

    async def async_mark_failure(self, reservation: UploadReservation) -> None:
        """Release a failed tail reservation so the request can be retried."""
        async with self._lock:
            tail = self._tail.get(reservation.target_key)
            if tail != (reservation.fingerprint, reservation.sequence):
                return

            successful = self._successful.get(reservation.target_key)
            if successful is None:
                self._tail.pop(reservation.target_key, None)
            else:
                self._tail[reservation.target_key] = (successful, 0)

    async def async_set_resend_enabled(
        self, target_key: str, enabled: bool
    ) -> None:
        """Persist whether reboot recovery is enabled for an AP display."""
        async with self._lock:
            if enabled:
                self._resend_enabled.add(target_key)
            else:
                self._resend_enabled.discard(target_key)
            await self._async_save_locked()

    def is_resend_enabled(self, target_key: str) -> bool:
        """Return the stored reboot-recovery setting for a display."""
        return target_key in self._resend_enabled

    async def async_reserve_replay(
        self, target_key: str
    ) -> tuple[UploadReservation, ReplayPayload] | None:
        """Reserve the last successful image unless newer work is pending."""
        async with self._lock:
            if target_key not in self._resend_enabled:
                return None

            replay_payload = self._replay_payloads.get(target_key)
            if replay_payload is None:
                return None

            tail = self._tail.get(target_key)
            if tail is not None and tail[1] != 0:
                return None

            self._sequence += 1
            reservation = UploadReservation(
                target_key=target_key,
                fingerprint=replay_payload.fingerprint,
                sequence=self._sequence,
            )
            self._tail[target_key] = (
                replay_payload.fingerprint,
                reservation.sequence,
            )
            return reservation, replay_payload

    async def _async_save_locked(self) -> None:
        """Persist fingerprints, replay payloads, and switch settings."""
        data = {
            "fingerprints": dict(self._successful),
            "replay_payloads": {
                target_key: {
                    "fingerprint": payload.fingerprint,
                    "image": base64.b64encode(payload.image_data).decode("ascii"),
                    "parameters": dict(payload.parameters),
                }
                for target_key, payload in self._replay_payloads.items()
            },
            "resend_enabled": sorted(self._resend_enabled),
        }
        try:
            await self._store.async_save(data)
        except Exception as err:  # pragma: no cover - storage helper owns I/O
            _LOGGER.warning("Unable to save drawcustom upload cache: %s", err)


def get_drawcustom_cache(hass: HomeAssistant) -> DrawCustomUploadCache:
    """Return the integration-wide drawcustom cache instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    cache = domain_data.get(CACHE_DATA_KEY)
    if cache is None:
        cache = DrawCustomUploadCache(hass)
        domain_data[CACHE_DATA_KEY] = cache
    return cache
