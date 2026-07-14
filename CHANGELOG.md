# Changelog

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
