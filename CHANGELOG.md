# Changelog

## Unreleased

### Features

* add HA-managed, content-mode-independent event groups for **Button 1**, **Button 2**, and **NFC**, each with a persistent counter, last-activation timestamp, and counter reset button
* add the optional `drawcustom.only_if_changed` setting, including a persistent per-display cache, to avoid uploading an unchanged rendered image and unchanged effective upload settings ([#345](https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues/345))
* add an opt-in **Resend Image After Reboot** configuration switch per AP display; after `BOOT`, `FIRSTBOOT`, or `WDT_RESET`, it requeues the last successful `drawcustom` image through the normal Multi-AP upload route ([#204](https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues/204))

### Bug Fixes

* create battery entities from usable battery telemetry instead of suppressing them solely because a synchronized Multi-AP record is marked `is_external`
* ignore replicated `is_external` button/NFC records when emitting events and updating counters, preventing duplicate Multi-AP actions
* count distinct local tag reboot events correctly instead of comparing translated wakeup-reason text with numeric firmware codes

### Upgrade Notes / Hinweise zum Update

* Restart Home Assistant once after installing this version so the new entity platforms are loaded. / Home Assistant nach der Installation einmal neu starten, damit die neuen Entitätsplattformen geladen werden.
* The former #330 AP Timestamp configuration entities are removed automatically. The replacement values do not require the AP's **Time Stamp** content mode and work in **Home Assistant**, **Remote content**, and other display modes.
* The new entity names deliberately use the shared prefixes **Event Button 1**, **Event Button 2**, and **Event NFC** (German: **Ereignis ...**) so each counter, last-activation timestamp, and reset control is recognizable as one group.
* All nine event entities are disabled by default because display capabilities vary. Enable only the required groups on the HA device page. Existing entity-registry choices are preserved on update, and events continue to be recorded while their entities are disabled.
* Event counters start at `0` and persist across Home Assistant restarts. A last-activation sensor is **Unknown / Unbekannt** until the corresponding event is received for the first time; displays without that hardware keep the unused group at `0` and unknown.
* Reset controls clear only their counter; the last-activation timestamp remains available. Device triggers remain the recommended input for automations.
* With `drawcustom.only_if_changed`, only a successful upload updates the persistent comparison cache. Dry runs always render a preview without changing the cache. Calling `drawcustom` once without the option forces an upload and refreshes the cached result.
* **Resend Image After Reboot / Bild nach Neustart erneut senden** is a visible per-display configuration switch and defaults to off. It requires at least one successful `drawcustom` upload made after this update; older images, dry runs, and failed uploads do not provide or replace the recovery image.
* Automatic reboot recovery runs only in Home Assistant content mode (`25`). It does not overwrite Timestamp, Remote content, or other AP-managed modes, and replicated Multi-AP records cannot trigger it.

### Validation

* 37 focused tests cover Multi-AP routing, disabled-by-default and persistent Button 1/Button 2/NFC values, the `drawcustom` comparison cache, and reboot image recovery
* live Home Assistant 2026.7.2 validation registered all nine grouped event entities for both test displays; all seven integration entries loaded, counters started at `0`, timestamps started at `Unknown`, the superseded #330 entities were removed, and no OpenEPaperLink system-log errors occurred
* the 27 pre-existing image snapshot deviations remain unrelated to these changes

## [3.0.3](https://github.com/wendefeuer/Home_Assistant_Integration/compare/3.0.2...3.0.3) (2026-07-18)

### Bug Fixes

* exclude replicated `is_external` tag records from write routing
* prefer the AP that owns the physical tag even when synchronized AP databases report identical `last_seen` values
* fail closed when only a replicated tag record is available instead of queueing an update on the wrong AP

### Validation

* twelve focused Multi-AP tests passed on Python 3.14.5 with Home Assistant 2026.7.2
* live image delivery was verified with the shared test display `OeP Datum`
* an existing shopping-list display resumed receiving updates after the fix
* the 27 pre-existing image snapshot deviations remain unrelated to this routing change

## [3.0.2](https://github.com/wendefeuer/Home_Assistant_Integration/compare/3.0.1...3.0.2) (2026-07-14)

### Bug Fixes

* point the HACS installation button to `wendefeuer/Home_Assistant_Integration`
* point release, issue, manual-download, documentation, and issue-tracker links to the public fork
* publish the validated Multi-AP implementation on the fork's default `main` branch

### Validation

* no functional integration code changes compared with `3.0.1`
* nine focused Multi-AP tests passed
* Python 3.12 compilation, JSON/translation validation, and repository secret scanning passed

## [3.0.1](https://github.com/wendefeuer/Home_Assistant_Integration/compare/3.0.1-multi-ap.1...3.0.1) (2026-07-14)

### Release

* promote the validated Multi-AP beta to the stable `3.0.1` fork release
* no functional code changes compared with `3.0.1-multi-ap.1`
* retain the backup, rollback, known-limitations, and sanitized issue-reporting guidance

### Validation

* nine focused Multi-AP tests passed
* Python 3.12 compilation and JSON/translation validation passed
* live validation passed on Home Assistant Core 2026.7.2 with two APs and shared tags
* AP fallback/recovery, separate AP reboot, and unchanged BLE operation were verified

## [3.0.1-multi-ap.1](https://github.com/wendefeuer/Home_Assistant_Integration/compare/3.0.0...3.0.1-multi-ap.1) (2026-07-14)

> **Pre-release:** Test version for broader Multi-AP validation. Back up Home Assistant and the existing integration folder before installation.

### Features

* allow multiple AP config entries while continuing to reject duplicate hosts
* keep one logical Home Assistant device per physical tag across multiple APs
* route tag state and actions to an online AP, preferring the freshest `last_seen`
* create unique AP device identifiers and separate per-entry tag stores
* add debug logging for routing candidates, the selected AP, and the selection reason

### Bug Fixes

* retain a shared tag when it is deleted or blacklisted on only one AP
* route `reboot_ap` to the explicitly selected AP device
* treat an accepted AP reboot followed by the expected connection loss as successful

### Validation

* nine focused Multi-AP tests passed
* Python compilation and JSON/translation validation passed
* live validation passed on Home Assistant Core 2026.7.2 with two APs and shared tags
* AP fallback/recovery, separate AP reboot, and unchanged BLE operation were verified
* 27 existing image snapshot differences were reproduced unchanged on the upstream code in the same Windows/Pillow environment and are not caused by this beta

### Known limitations

* pre-release from a public fork; not yet merged into the upstream stable release
* Multi-AP routing covers AP-based tags; BLE paths are intentionally unchanged
* the selected AP can change when connectivity or tag `last_seen` data changes
* broader field testing with other AP counts, firmware combinations, and Home Assistant versions is still required

## [3.0.0](https://github.com/OpenEPaperLink/Home_Assistant_Integration/compare/2.8.0...3.0.0) (2026-03-27)


### ⚠ BREAKING CHANGES

* remove OpenDisplay (OEPL BLE) support

### Features

* remove OpenDisplay (OEPL BLE) support ([96af68a](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/96af68a600d205fdab59a2212e094495414779fe))


### Bug Fixes

* add green and blue to named colors ([00c33fb](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/00c33fba79dfbcfb23b716161e61af485c62d597))

## [2.8.0](https://github.com/OpenEPaperLink/Home_Assistant_Integration/compare/v2.7.0...2.8.0) (2025-12-22)


### Features

* **config-flow:** add DHCP discovery for AP devices ([c107abb](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/c107abb6cfcd1988a22ea85ec806f15646db1deb))
* **upload:** add refresh_type parameter to support partial refresh ([a72c2bc](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/a72c2bc56c78ee1bcfd1b3616dadf34b46d641b0))
* **upload:** add refresh_type parameter to support partial refresh ([864cc87](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/864cc87f6510b52064d9d7a6a5148379307e1277))


### Bug Fixes

* **ci:** correct include-v-in-tag to boolean value ([46be136](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/46be13604b98ea873a421f3bd657df7a90c106a4))
* properly set name on discovery of BLE devices ([b2148fb](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/b2148fb04e91bcab46885fd0e902ed65c7d21b5d))

## [2.7.0](https://github.com/OpenEPaperLink/Home_Assistant_Integration/compare/2.6.0...v2.7.0) (2025-12-17)


### Features

* **text:** add multiline support to parse_colors with proper anchor handling ([1be0e77](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/1be0e77f49062248dc8bab090a0ccbd46c1cedf9))


### Bug Fixes

* **multiline:** parse percentage coordinates properly ([3a7ceb0](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/3a7ceb0b7977fea64ffc808e1a27e901e860b47d))
* **text:** allow color tags to span multiple lines in text elements ([c894eb0](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/c894eb0d387462a98c74664fb4bf946c8e3f5b25))
* **text:** correct anchor alignment when using parse_colors ([36a346d](https://github.com/OpenEPaperLink/Home_Assistant_Integration/commit/36a346d52756ec1947191f36b940258ab5aea612)), closes [#242](https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues/242)
