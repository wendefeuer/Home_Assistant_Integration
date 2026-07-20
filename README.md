# OpenEPaperLink integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/wendefeuer/Home_Assistant_Integration?style=for-the-badge)](https://github.com/wendefeuer/Home_Assistant_Integration/releases)
[![GitHub issues](https://img.shields.io/github/issues/wendefeuer/Home_Assistant_Integration?style=for-the-badge)](https://github.com/wendefeuer/Home_Assistant_Integration/issues)

[//]: # (Server Widget has to be enabled first)
[//]: # (![Discord]&#40;https://img.shields.io/discord/717057001594683422?style=flat-square&#41;)



Home Assistant Integration for the [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink) project, enabling control and monitoring of electronic shelf labels (ESLs) through Home Assistant.

## Multi-AP release / Multi-AP-Version

> [!IMPORTANT]
> **Create a Home Assistant backup and a separate copy of your existing `custom_components/open_epaper_link` folder before installation.** Version `3.1.1` is the stable Multi-AP release of this public fork and has not yet been merged into the upstream project.
>
> **Vor der Installation ein Home-Assistant-Backup und zusätzlich eine Kopie des vorhandenen Ordners `custom_components/open_epaper_link` erstellen.** Version `3.1.1` ist die stabile Multi-AP-Version dieses öffentlichen Forks und noch nicht in das Upstream-Projekt übernommen.

Release version: [`3.1.1`](https://github.com/wendefeuer/Home_Assistant_Integration/releases/tag/3.1.1)

Feedback and bug reports: [GitHub Issues in the fork](https://github.com/wendefeuer/Home_Assistant_Integration/issues/new/choose)

### English Multi-AP installation

This release allows multiple OpenEPaperLink AP config entries in one Home Assistant instance. A physical tag remains one logical Home Assistant device. Tag actions are routed only through an AP that reports a local, non-replicated tag record; if several local APs qualify, the freshest `last_seen` value wins.

1. Create a full Home Assistant backup.
2. Back up the existing `/config/custom_components/open_epaper_link` folder separately.
3. Install the release using one of these methods:
   - **HACS custom repository (recommended):** In HACS, open the three-dot menu, select **Custom repositories**, add `https://github.com/wendefeuer/Home_Assistant_Integration` as type **Integration**, then use **Download** or **Redownload**. Under **Need a different version?**, select `3.1.1` if necessary.
   - **Manual:** Download the source archive from the [`3.1.1` release](https://github.com/wendefeuer/Home_Assistant_Integration/releases/tag/3.1.1), extract it, and copy its `custom_components/open_epaper_link` folder to `/config/custom_components/open_epaper_link`, replacing the integration files.
4. Restart Home Assistant. Do not edit files below `.storage`.
5. Open **Settings → Devices & services → OpenEPaperLink** and add each AP separately. Existing AP entries can remain in place.
6. Verify that every AP has its own device, shared tags appear only once, and a test action reaches the expected online AP.

To roll back, restore the backed-up integration folder or reinstall the latest upstream stable release, restart Home Assistant, and verify the integration and its devices again.

When reporting a problem, use the [fork issue tracker](https://github.com/wendefeuer/Home_Assistant_Integration/issues/new/choose) and include the release version, Home Assistant version, AP count and firmware versions, reproduction steps, and sanitized logs. Remove tokens, passwords, private addresses, tag identifiers, and other personal data before posting.

### Deutsche Multi-AP-Installation

Diese Version erlaubt mehrere OpenEPaperLink-AP-Konfigurationseinträge in einer Home-Assistant-Instanz. Ein physisches Tag bleibt ein logisches Home-Assistant-Gerät. Tag-Aktionen werden nur über einen AP mit einem lokalen, nicht replizierten Tag-Eintrag geleitet; kommen mehrere lokale APs infrage, gewinnt der neueste `last_seen`-Wert.

1. Ein vollständiges Home-Assistant-Backup erstellen.
2. Den vorhandenen Ordner `/config/custom_components/open_epaper_link` zusätzlich separat sichern.
3. Die Version mit einer der folgenden Methoden installieren:
   - **HACS Custom Repository (empfohlen):** In HACS das Drei-Punkte-Menü öffnen, **Benutzerdefinierte Repositories** auswählen, `https://github.com/wendefeuer/Home_Assistant_Integration` mit dem Typ **Integration** hinzufügen und anschließend **Herunterladen** oder **Erneut herunterladen** wählen. Unter **Andere Version benötigt?** bei Bedarf `3.1.1` auswählen.
   - **Manuell:** Das Quellarchiv der [Version `3.1.1`](https://github.com/wendefeuer/Home_Assistant_Integration/releases/tag/3.1.1) herunterladen, entpacken und den enthaltenen Ordner `custom_components/open_epaper_link` nach `/config/custom_components/open_epaper_link` kopieren. Dabei die vorhandenen Integrationsdateien ersetzen.
4. Home Assistant neu starten. Keine Dateien unter `.storage` bearbeiten.
5. Unter **Einstellungen → Geräte & Dienste → OpenEPaperLink** jeden AP einzeln hinzufügen. Vorhandene AP-Einträge können bestehen bleiben.
6. Prüfen, ob jeder AP ein eigenes Gerät besitzt, gemeinsam sichtbare Tags nur einmal erscheinen und eine Testaktion den erwarteten erreichbaren AP erreicht.

Für ein Rollback den gesicherten Integrationsordner wiederherstellen oder die aktuelle stabile Upstream-Version erneut installieren, Home Assistant neu starten und anschließend Integration und Geräte erneut prüfen.

Probleme bitte zentral im [Issue-Tracker des Forks](https://github.com/wendefeuer/Home_Assistant_Integration/issues/new/choose) melden. Dabei Release-Version, Home-Assistant-Version, Anzahl und Firmwarestände der APs, Reproduktionsschritte und bereinigte Logs angeben. Tokens, Passwörter, private Adressen, Tag-Kennungen und andere personenbezogene Daten vor dem Veröffentlichen entfernen.

### Known limitations / Bekannte Einschränkungen

- This is a stable release of a public fork and is not yet part of the upstream project. / Dies ist eine stabile Version eines öffentlichen Forks und noch nicht Teil des Upstream-Projekts.
- Multi-AP routing applies to AP-based tags. Existing BLE behavior is intentionally unchanged. / Das Multi-AP-Routing gilt für AP-basierte Tags. Das bestehende BLE-Verhalten bleibt absichtlich unverändert.
- Write routing requires a local, non-replicated tag record and depends on AP connectivity. If several local APs qualify, the most recent tag `last_seen` data decides. / Schreibzugriffe benötigen einen lokalen, nicht replizierten Tag-Eintrag und hängen von der AP-Erreichbarkeit ab. Kommen mehrere lokale APs infrage, entscheiden die neuesten `last_seen`-Daten des Tags.
- A tag shared by multiple APs is intentionally shown as one HA device and has no permanent parent-AP assignment. / Ein von mehreren APs erfasstes Tag wird absichtlich als ein HA-Gerät angezeigt und besitzt keine dauerhafte Zuordnung zu einem übergeordneten AP.
- A display reported only as a replicated remote record (`is_external: true`) is intentionally hidden from Home Assistant. It appears automatically when any configured AP reports a local record. / Ein Display, das ausschließlich als replizierter Remote-Datensatz (`is_external: true`) gemeldet wird, bleibt in Home Assistant absichtlich ausgeblendet. Es erscheint automatisch, sobald ein eingerichteter AP einen lokalen Datensatz meldet.
- An AP reboot can close the HTTP connection before returning a response; an accepted reboot request followed by that disconnect is treated as successful. / Ein AP-Neustart kann die HTTP-Verbindung schließen, bevor eine Antwort zurückkommt; eine zuvor angenommene Neustartanforderung wird in diesem Fall als erfolgreich behandelt.
- Version `3.1.1` contains the Multi-AP implementation validated with two APs on Home Assistant Core 2026.7.2, including the local-versus-replicated routing and visibility fixes. Other AP counts, firmware combinations, and HA versions have not been validated to the same extent. / Version `3.1.1` enthält die mit zwei APs unter Home Assistant Core 2026.7.2 geprüfte Multi-AP-Implementierung einschließlich der Korrekturen für Routing und Sichtbarkeit lokaler und replizierter Tag-Einträge. Andere AP-Anzahlen, Firmwarekombinationen und HA-Versionen wurden noch nicht im gleichen Umfang validiert.

## Requirements

### Hardware

**AP-Based Setup:**
- OpenEPaperLink Access Point (ESP32-based)
- Compatible Electronic Shelf Labels connected to AP

**BLE-Based Setup (ATC firmware):**
- BLE-compatible Electronic Shelf Labels with ATC BLE firmware
- Home Assistant with Bluetooth adapter or proxy (e.g., ESPHome)
- No separate AP required - direct device communication

**Mixed Setup:**
- Both AP and BLE devices can coexist in the same Home Assistant instance

> **OpenDisplay users:** OpenDisplay (OEPL BLE) devices are no longer supported by this integration. OpenDisplay now has dedicated integrations:
> - [**Core integration**](https://www.home-assistant.io/integrations/opendisplay) — send images to the display via the `upload_image` action
> - [**Custom integration**](https://github.com/OpenDisplay/Home_Assistant_Integration) — full support including the `drawcustom` action

## Features

### 🔌 Device Integration
- Each tag and AP appears as a device in Home Assistant
- Device triggers for buttons, NFC, and GPIO
- Automatic tag discovery and configuration

### ⚙️ Configuration Controls
- AP settings management (WiFi, Bluetooth, language, etc.)
- Tag inventory and blacklist management

### 🔘 Button and NFC events / Button- und NFC-Ereignisse

For every AP-connected display, Home Assistant keeps independent values for **Button 1**, **Button 2**, and **NFC**. They work with every display content mode; the AP's optional **Time Stamp** mode is not required. Each accepted event updates a persistent counter and a last-activation timestamp. Device triggers remain the recommended way to start automations immediately.

Home Assistant führt für jedes am AP angebundene Display eigene Werte für **Button 1**, **Button 2** und **NFC**. Sie funktionieren unabhängig vom Inhaltsmodus des Displays; der optionale AP-Modus **Time Stamp** wird dafür nicht benötigt. Jedes angenommene Ereignis erhöht einen dauerhaft gespeicherten Zähler und aktualisiert den Zeitpunkt der letzten Auslösung. Zum unmittelbaren Starten einer Automation werden weiterhin die Geräteauslöser empfohlen.

> [!IMPORTANT]
> Restart Home Assistant once after installing this version. All nine event entities are **disabled by default**, because many displays have neither two buttons nor NFC. Enable only the required Button 1, Button 2, or NFC group on the display's Home Assistant device page. Existing user-enabled entities keep their current registry setting during an update. Event values continue to be recorded while their entities are disabled.
>
> After enabling a group, its counter initially shows `0` if no event has occurred; a last-activation sensor remains **Unknown / Unbekannt** until that event is received for the first time. This is expected and is not an integration error. The previous #330 timestamp-mode configuration entities are removed automatically during setup.

The related entities deliberately share the prefix **Event Button 1**, **Event Button 2**, or **Event NFC** (German: **Ereignis Button 1**, **Ereignis Button 2**, **Ereignis NFC**) so they are easy to recognize as a group on the device page:

| Entity in each group | Meaning |
| --- | --- |
| **Last activation / Letzte Auslösung** | Timestamp of the most recently accepted event; unknown before the first event. |
| **Count / Anzahl** | Persistent number of accepted events; survives Home Assistant restarts. |
| **Reset count / Zähler zurücksetzen** | Control button that sets only the counter to `0`; the last timestamp is retained. |

The integration applies the configured button/NFC debounce interval before updating these values. Replicated `is_external` records in Multi-AP installations neither increment the counters nor emit duplicate Home Assistant events. A display without Button 2 or NFC still receives the corresponding entities; they simply remain at `0` and **Unknown / Unbekannt**.

Die Integration wendet vor der Aktualisierung die konfigurierte Button-/NFC-Entstörzeit an. Replizierte `is_external`-Datensätze einer Multi-AP-Installation erhöhen weder die Zähler noch erzeugen sie doppelte HA-Ereignisse. Besitzt ein Display keinen zweiten Button oder kein NFC, bleiben die betreffenden Werte einfach bei `0` beziehungsweise **Unbekannt**.

### 🎨 Display Controls

#### drawcustom (Recommended)
The most flexible and powerful service for creating custom displays. Supports:
- Text with multiple fonts and styles
- Shapes (rectangles, circles, lines)
- Icons from Material Design Icons
- QR codes
- Images from URLs
- Plots of Home Assistant sensor data
- Progress bars

[View full drawcustom documentation](docs/drawcustom/supported_types.md)

Set the optional `only_if_changed: true` parameter to upload a rendered image only when its pixels or effective upload settings have changed. The last successful result is retained across Home Assistant restarts. A dry run still creates a preview and never updates this cache. To force a transfer after the display was changed elsewhere, call `drawcustom` once without `only_if_changed`.

Mit dem optionalen Parameter `only_if_changed: true` wird ein gerendertes Bild nur übertragen, wenn sich seine Pixel oder die effektiven Upload-Einstellungen geändert haben. Das letzte erfolgreiche Ergebnis bleibt über HA-Neustarts erhalten. Ein Dry-Run erzeugt weiterhin eine Vorschau und verändert diesen Cache nicht. Wurde das Display außerhalb der Integration geändert, kann die Übertragung durch einen einmaligen `drawcustom`-Aufruf ohne `only_if_changed` erzwungen werden.

#### Automatic resend after a tag reboot / Automatisches Wiederholen nach einem Display-Neustart

Every AP-connected display has a **Resend Image After Reboot** switch under **Configuration**. The switch is visible after the update but is **off by default**. When enabled, the integration reuploads the last successfully transmitted `drawcustom` image after the AP reports `BOOT`, `FIRSTBOOT`, or `WDT_RESET` for that display.

The recovery image becomes available only after a successful `drawcustom` upload made with the new integration version. Images created before the update cannot be recovered automatically until they have been sent again. Dry runs and failed uploads never replace the recovery image. Recovery is limited to tags in **Home Assistant** content mode (`25`), so an old image cannot overwrite Timestamp, Remote content, or another AP-managed mode. In Multi-AP installations, replicated external tag records never trigger a resend.

Jedes am AP angebundene Display erhält unter **Konfiguration** den Schalter **Bild nach Neustart erneut senden**. Die Entität ist nach dem Update sichtbar, der Schalter steht aber standardmäßig auf **aus**. Ist er eingeschaltet, überträgt die Integration das zuletzt erfolgreich gesendete `drawcustom`-Bild erneut, sobald der AP für dieses Display `BOOT`, `FIRSTBOOT` oder `WDT_RESET` meldet.

Ein Wiederherstellungsbild steht erst nach einem erfolgreichen `drawcustom`-Upload mit der neuen Integrationsversion zur Verfügung. Bilder aus der Zeit vor dem Update müssen deshalb einmal erneut gesendet werden. Dry-Runs und fehlgeschlagene Uploads ersetzen das Wiederherstellungsbild nicht. Die Funktion arbeitet ausschließlich im Inhaltsmodus **Home Assistant** (`25`), damit kein altes Bild einen Timestamp-, Remote-content- oder anderen AP-Modus überschreibt. In Multi-AP-Installationen lösen replizierte externe Display-Datensätze keine Übertragung aus.

#### Legacy Services (Deprecated)
The following services have been deprecated in favor of drawcustom:
- **dlimg**: Download and display images from URLs
- **lines5**: Display 5 lines of text (1.54" displays only)
- **lines4**: Display 4 lines of text (2.9" displays only)

These legacy services were removed in the 1.0 release. Please migrate to using drawcustom.

### 🚦 Device Management
- `clear_pending`: Clear pending updates
- `force_refresh`: Force display refresh
- `reboot_tag`: Reboot tag
- `scan_channels`: Initiate channel scan
- `reboot_ap`: Reboot the access point
- Automatic tag detection and configuration
- Support for tag blacklisting to ignore unwanted devices
- Hardware capability detection for buttons, NFC, and GPIO features

### 🔋 Battery Optimization

To maximize tag battery life when using this integration:

- **[Shorten latency during config](https://github.com/OpenEPaperLink/OpenEPaperLink/wiki/Tag-protocol-timing#shorten-latency-during-config) setting**: This setting can be set to `no` either directly on the AP's web interface or through the integration's AP device in Home Assistant.

  If set to `yes`, tags will only sleep for 40 seconds between check-ins instead of using the configured longer sleep periods, reducing battery life.

  This occurs because Home Assistant maintains a constant WebSocket connection to the AP, which the AP interprets as being in configuration mode.

## Installation

### ⚠️ Important: BLE Tag Firmware & Configuration
For the integration to discover and control BLE-based e-paper tags, they **MUST** be running the correct firmware and be properly configured. Tags with their original stock firmware will **not** be discovered by Home Assistant.

#### Step 1: Flash `ATC_BLE_OEPL` Firmware
The flashing method depends on the tag model:
- **For tags previously used with an OpenEPaperLink BLE AP:** The [web-based OTA flasher](https://atc1441.github.io/BLE_EPaper_OTA.html) can likely be used.
- **For other tags:** A manual flash is often required. This video provides a comprehensive guide: [Universal E-Paper Firmware Flashing](https://youtu.be/9oKWkHGI-Yk).

#### Step 2: Set the Device Type
After flashing, the correct device type for the tag model **must** be set.
1.  Connect to the tag using the [ATC_BLE_OEPL Image Upload tool](https://atc1441.github.io/ATC_BLE_OEPL_Image_Upload.html).
2.  Use the "Set Type" dropdown to select the specific tag model (e.g., "`12: 290 Gici BWR SSD`").
3.  Click the "Set Type" button.

#### Getting Help
For any issues, the `#atc_ble_oepl` and `#home_assistant` channel on the [OpenEPaperLink Discord](https://discord.com/invite/eRUHt4u5CZ) is a great resource for community support.

Once flashed and configured, tags are discovered by HA automatically.

### Option 1: HACS Installation (Recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=wendefeuer&repository=Home_Assistant_Integration&category=integration)

If the button does not add the repository, open **HACS → three-dot menu → Custom repositories** and add `https://github.com/wendefeuer/Home_Assistant_Integration` with category **Integration**.

Falls die Schaltfläche das Repository nicht hinzufügt, in **HACS → Drei-Punkte-Menü → Benutzerdefinierte Repositories** die Adresse `https://github.com/wendefeuer/Home_Assistant_Integration` mit der Kategorie **Integration** eintragen.

### Option 2: Manual Installation
1. Download the `open_epaper_link` folder from the [latest release](https://github.com/wendefeuer/Home_Assistant_Integration/releases/latest)
2. Copy it to your [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations)
3. Restart Home Assistant

## Configuration

This step is only needed when using OpenEPaperLink in AP mode. When using a BLE-only setup, the tags will be detected automatically as soon as OpenEPaperLink has been installed.

### Automatic Configuration
Add OpenEPaperLink to your Home Assistant instance using this button:

[![Add Integration](https://user-images.githubusercontent.com/31328123/189550000-6095719b-ca38-4860-b817-926b19de1b32.png)](https://my.home-assistant.io/redirect/config_flow_start?domain=open_epaper_link)

### Manual Configuration
1. Browse to your Home Assistant instance
2. Go to Settings → Devices & Services
3. Click the `Add Integration` button in the bottom right
4. Search for and select "OpenEPaperLink"
5. Follow the on-screen instructions

### Integration Options
After setup, you can configure additional options through the integration's option flow:

#### Tag Management
- **Blacklisted Tags**: Select tags to hide and ignore.
- **Button Debounce Time**: Adjust sensitivity of button triggers (0.0-5.0 seconds)
- **NFC Debounce Time**: Adjust sensitivity of NFC triggers (0.0-5.0 seconds)

#### Device Discovery

**AP Device Configuration:**
- **Automatic Discovery** (recommended): APs are automatically discovered via DHCP when connected to the network
- **Manual Setup** (fallback): Go to Settings → Integrations → Add Integration and enter your AP's IP address
- **Multiple AP hubs supported**: Add every AP separately. A physical tag remains one logical Home Assistant device; actions are routed to the online AP with the freshest tag check-in.
- All tags connected to the AP are automatically discovered

**BLE Device Discovery:**
- Automatic discovery via Bluetooth scanning
- Devices appear when in range and advertising
- Each BLE device creates a separate integration entry
- No limit on number of BLE devices

## Usage Examples

### Basic Text Display
```yaml
- type: "text"
  value: "Hello World!"
  x: 10
  y: 10
  size: 40
  color: "red"
```

### Progress Bar with Icon
```yaml
- type: "progress_bar"
  x_start: 10
  y_start: 10
  x_end: 180
  y_end: 30
  progress: 75
  fill: "red"
  show_percentage: true
- type: "icon"
  value: "mdi:battery-70"
  x: 190
  y: 20
  size: 24
```

### Sensor Display
```yaml
- type: "text"
  value: "Temperature: {{ states('sensor.temperature') }}°C"
  x: 10
  y: 10
  size: 24
  color: "black"
- type: "text"
  value: "Humidity: {{ states('sensor.humidity') }}%"
  x: 10
  y: 40
  size: 24
  color: "black"
```
## Migrating to Version 1.0

### Breaking Changes

1. **Service Changes**
   - `dlimg`, `lines4`, and `lines5` services have been deprecated
   - All image/text display should now use `drawcustom` service
   - Service target now uses device ID instead of entity ID
2. **Entity Changes**
    - Entities for each device have also changed significantly

**To make sure no potential bugs carry over from the old version, please remove the old integration and re-add it. This will ensure that all entities are correctly setup.**



### Service Migration

#### Text Display
Old format (`lines5` service):
```yaml
line1: "Hello"
line2: "World"
```

New format (`drawcustom` payload):
```yaml
- type: "text"
  value: "Hello"
  x: 10
  y: 10
  size: 24
- type: "text"
  value: "World"
  x: 10
  y: 40
  size: 24
```

#### Image Display
Old format (`dlimg` service):
```yaml
url: "https://example.com/image.jpg"
x: 0
y: 0
xsize: 296
ysize: 128
```

New format (`drawcustom` payload):
```yaml
- type: "dlimg"
  url: "https://example.com/image.jpg"
  x: 0
  y: 0
  xsize: 296
  ysize: 128
```

The device selection, background color, rotation, and other options are now configured through dropdown menus in the service UI.

## Contributing
- Feature requests and bug reports are welcome! Please open an issue on GitHub
- Pull requests are encouraged
- Join the [Discord server](https://discord.com/invite/eRUHt4u5CZ) to discuss ideas and get help
