# HomeKit TV Remote

The first Home Assistant integration to control a TV directly over the HomeKit Accessory Protocol (HAP). Rather than relying on vendor-specific IP remote protocols, it communicates with the TV the same way Apple devices do — over HAP, using the existing HomeKit pairing. This gives you a native remote entity, full iOS/iPadOS remote widget support, and flexible input and app switching with per-input HomeKit visibility control.

---

## How It Works

The integration sits between two existing HA integrations:

```
TV  ←——HAP——→  HomeKit Device integration  (pairs the TV into HA)
                        ↓
               HomeKit TV Remote  (this integration — adds remote entity)
                        ↓
               HomeKit Bridge in accessory mode  (exposes it back to Apple Home)
                        ↓
              iOS / iPadOS remote widget
```

1. **HomeKit Device** pairs your TV into HA and creates a `media_player` entity — but no remote entity, so the iOS remote widget is unavailable.
2. **HomeKit TV Remote** reads the existing pairing and creates a `remote` entity that communicates directly with the TV over HAP. This is faster than vendor-specific protocols because HAP commands are processed at a higher priority by the TV firmware.
3. **HomeKit Bridge** re-exposes the integration's `media_player` entity back to Apple Home. It **must be configured in accessory mode** for a single entity — this is what produces the Television accessory type that enables the remote widget. Standard bridge mode (multiple entities) does not work for this purpose.

---

## Features

### 1. HAP-Native Remote Control

All remote commands are sent directly over HAP, bypassing the TV's vendor IP protocol entirely.

| Command | Function | Notes |
|---|---|---|
| `0` | Rewind | |
| `1` | Fast Forward | |
| `2` | Next Track | |
| `3` | Previous Track | |
| `4` | D-pad Up | |
| `5` | D-pad Down | |
| `6` | D-pad Left | |
| `7` | D-pad Right | |
| `8` | Select / OK | |
| `9` | Back | |
| `10` | Exit | |
| `11` | Play/Pause | Standard |
| `12` | Play/Pause | Apple TV variant |
| `14` | TV Settings | |
| `15` | Info | |
| `16` | TV Home | |
| `volume_up` | Volume Up | |
| `volume_down` | Volume Down | |
| `input_N` | Switch to input N | e.g. `input_9` |

The `input_N` number is assigned by the TV's HAP layer and does not necessarily match the physical port number. Switch to an input manually and read its number from the **1c. Current Identifier** entity on the device page.

All commands confirmed on Sony KD-55XG9505. Results may vary on other manufacturers.

---

### 2. Custom Input & App Switching

Save named inputs that appear in the HomeKit source list and HA media player card, in the order they were saved. Four input types are supported:

| Type | How it works |
|---|---|
| `hap` | Writes `ActiveIdentifier` directly to the TV — fastest, works for all HDMI and CEC inputs |
| `remote` | Sends a vendor command via a third-party `remote.*` entity (e.g. Sony Bravia) |
| `media_player` | Launches an app via `media_player.play_media` on a third-party media player entity |
| `media_player_source` | Launches an app via `media_player.select_source` — **required for Apple TV**, which does not support `play_media` for app launching |

Each saved input has an **Include** switch on the device page. Only inputs with Include ON appear in the HomeKit source list and are cycled by the iOS remote Info button. Inputs with Include OFF are still saved and can be triggered from HA automations, but are invisible to HomeKit.

---

### 3. iOS / iPadOS Remote Widget

When the integration's `media_player` entity is exposed to HomeKit Bridge **in accessory mode**, the TV appears as a Television accessory in Apple Home and the full remote widget becomes available in Control Center.

| iOS Button | HAP Command |
|---|---|
| D-pad Up | `4` |
| D-pad Down | `5` |
| D-pad Left | `6` |
| D-pad Right | `7` |
| Select | `8` |
| Back | `9` |
| Play / Pause | `11` |
| **ⓘ Info** | Cycles to the next enabled input |

The **ⓘ Info button** steps through enabled inputs in the order they were saved, wrapping back to the first after the last. The **Next Saved Input** button on the device page does the same thing and shares the same position counter — useful for dashboards and automations.

---

## Requirements

- Home Assistant 2026.02 or later
- TV paired via the **[HomeKit Device](https://www.home-assistant.io/integrations/homekit_controller/)** integration — this integration uses that pairing, it does not pair itself
- **HomeKit Bridge** integration configured in HA

---

## Installation

### HACS
1. Add this repo as a custom repository in HACS (category: Integration)
2. Install **HomeKit TV Remote** and restart HA
3. Go to **Settings → Devices & Services → Add Integration → HomeKit TV Remote**

### Manual
Copy `custom_components/homekit_tv_remote/` into your HA `config/custom_components/` directory and restart.

---

## Setup

### Step 1 — Configure the integration
1. Go to **Settings → Devices & Services → Add Integration → HomeKit TV Remote**
2. Select the HomeKit Device `media_player` entity for your TV
3. Enter a display name — this generates entity IDs (e.g. `Sony TV` → `remote.sony_tv`, `media_player.sony_tv`)

### Step 2 — Expose to HomeKit Bridge in accessory mode

The integration's `media_player` entity must be exposed to Apple Home via HomeKit Bridge **in accessory mode** — not via the standard bridge filter. Add a dedicated entry to your `configuration.yaml`, replacing `<Your TV Name>` and `<your_tv_name>` with the display name you entered during setup (e.g. `Sony TV` → `media_player.sony_tv`):

```yaml
homekit:
  - name: <Your TV Name>
    mode: accessory
    filter:
      include_entities:
        - media_player.<your_tv_name>
```

Restart HA, then pair the new accessory in the Apple Home app.

> **Why accessory mode?** Only accessory mode produces the Television accessory type that enables the iOS remote widget. Standard bridge mode exposes the entity as a generic switch-like accessory without remote widget support.

---

## Adding Inputs

Go to the integration device page (Configuration section), fill in the fields below, then press **1e. Save Input**. After saving, turn ON the **Include: \<input name\>** switch to make it visible in HomeKit and the input cycle.

| Field | Required | Description |
|---|---|---|
| **1. Apple TV App** | Apple TV apps only | Turn ON to use `select_source` instead of `play_media` — required for the Apple TV integration. Resets to OFF on reload. |
| **1. Apple TV Input** | Apple TV apps with auto HDMI switching | Turn ON to also switch the TV's HDMI input to the Apple TV port before launching the app. Requires **1d. HAP Identifier**. Resets to OFF on reload. |
| **1a. Input Name** | Always | Display name shown in HomeKit and HA (e.g. `Apple TV`) |
| **1b. Command** | `hap` / `remote` inputs | HAP command (e.g. `input_9`) or vendor command (e.g. `Hdmi2`) |
| **1c. App Name** | `media_player` inputs | App name passed to `play_media` or `select_source` (e.g. `Netflix`) |
| **1d. Input Type** | Always | `hap`, a `remote.*` entity, or a `media_player.*` entity |
| **1d. HAP Identifier** | `remote` / `media_player` inputs, and when Apple TV Input is ON | Integer the TV reports for this source — read from **1c. Current Identifier**. When Apple TV Input is ON, also used as the HDMI port to switch to. |
| **1e. Save Input** | — | Saves the input |
| **1f. Delete Last Input** | — | Removes the last saved input |
| **Include: \<name\>** | — | Turn ON to include this input in HomeKit and the cycle. OFF by default. Persistent across restarts. |
| **Next Saved Input** | — | Steps to the next enabled input — same as the iOS ⓘ Info button. Entity ID: `button.<your_tv_name>_next_saved_input` |
| **Reload HomeKit YAML** | After adding/removing inputs | Re-registers the TV with HomeKit Bridge so the source list updates |

---

## Input Configuration Examples

Remember to turn ON the **Include** switch after saving each input you want in HomeKit.

---

**Example 1 — HAP Input (HDMI or CEC)**

Switch to the input on your TV first and read its number from **1c. Current Identifier**.

| Field | Value |
|---|---|
| 1. Apple TV App | Off |
| 1. Apple TV Input | Off |
| 1a. Input Name | `Apple TV` |
| 1b. Command | `input_9` |
| 1c. App Name | *(leave empty)* |
| 1d. Input Type | `hap` |
| 1d. HAP Identifier | `9` |

---

**Example 2 — Third-Party Remote Input (e.g. Sony Bravia)**

Use when the TV requires a vendor-specific command that HAP alone can't send.

| Field | Value |
|---|---|
| 1. Apple TV App | Off |
| 1. Apple TV Input | Off |
| 1a. Input Name | `Portal TV` |
| 1b. Command | `Hdmi2` |
| 1c. App Name | *(leave empty)* |
| 1d. Input Type | `remote.bravia_kd_55xg9505` |
| 1d. HAP Identifier | `3` |

---

**Example 3 — TV App via Third-Party Media Player (e.g. Sony Bravia)**

Use for launching apps via a Bravia or similar integration that supports `play_media`.

| Field | Value |
|---|---|
| 1. Apple TV App | Off |
| 1. Apple TV Input | Off |
| 1a. Input Name | `Netflix` |
| 1b. Command | *(leave empty)* |
| 1c. App Name | `Netflix` |
| 1d. Input Type | `media_player.bravia_kd_55xg9505` |
| 1d. HAP Identifier | *(leave empty)* |

---

**Example 4 — Apple TV App**

Requires the Apple TV integration with Companion protocol paired. See [Apple TV App Names](#apple-tv-app-names) for valid app name strings.

Turn **1. Apple TV App** ON — uses `select_source` instead of `play_media`, which is the only working method for the Apple TV integration.

Optionally turn **1. Apple TV Input** ON and set **1d. HAP Identifier** to the number your TV reports for the Apple TV HDMI port (read from **1c. Current Identifier** while that input is active). When ON, the integration switches the TV's HDMI input to the Apple TV port automatically before launching the app. Leave it OFF if you handle input switching separately.

| Field | Value |
|---|---|
| 1. Apple TV App | **On** |
| 1. Apple TV Input | **On** *(or Off to skip automatic HDMI switching)* |
| 1a. Input Name | `Netflix on ATV` |
| 1b. Command | *(leave empty)* |
| 1c. App Name | `Netflix` |
| 1d. Input Type | `media_player.ng_apple_tv` |
| 1d. HAP Identifier | `9` |

---

## Apple TV App Names

App names are case-sensitive and must match exactly what your Apple TV reports. The most reliable way to find them: **Developer Tools → Actions → `media_player.select_source` → select your Apple TV entity** — the source dropdown lists every installed app with the exact string to use.

| App | Name |
|---|---|
| Netflix | `Netflix` |
| YouTube | `YouTube` |
| Prime Video | `Prime Video` |
| Disney+ | `Disney+` |
| Apple TV+ | `TV` |
| Max | `Max` |
| Hulu | `Hulu` |
| Paramount+ | `Paramount+` |
| Peacock | `Peacock` |
| Spotify | `Spotify` |
| Plex | `Plex` |
| Tubi | `Tubi` |
| Crunchyroll | `Crunchyroll` |
| MUBI | `MUBI` |
| Music | `Music` |
| Podcasts | `Podcasts` |
| Settings | `Settings` |

Apps not installed on your Apple TV will silently do nothing when selected.

---

## Debug Switches

Available on the device page under Diagnostics. Toggle live without restarting.

| Switch | Log tag | What it logs |
|---|---|---|
| Debug Listen | `HOMEKIT_TV_LISTEN` | Polls and push notifications received from the TV |
| Debug Send | `HOMEKIT_TV_SEND` | Every HAP command sent to the TV |

---

## YAML Examples

Replace `remote.sony_tv` with your actual remote entity ID.

### Basic Controls

```yaml
button:
  - name: "TV Power On"
    unique_id: sonytv_hap_power_on
    icon: mdi:power
    press:
      - action: remote.turn_on
        target:
          entity_id: remote.sony_tv

  - name: "TV Power Off"
    unique_id: sonytv_hap_power_off
    icon: mdi:power-off
    press:
      - action: remote.turn_off
        target:
          entity_id: remote.sony_tv

  - name: "Volume Up"
    unique_id: sonytv_hap_volume_up
    icon: mdi:volume-plus
    press:
      - action: remote.send_command
        target:
          entity_id: remote.sony_tv
        data:
          command: "volume_up"

  - name: "Volume Down"
    unique_id: sonytv_hap_volume_down
    icon: mdi:volume-minus
    press:
      - action: remote.send_command
        target:
          entity_id: remote.sony_tv
        data:
          command: "volume_down"

  - name: "TV Home"
    unique_id: sonytv_hap_tv_home
    icon: mdi:home
    press:
      - action: remote.send_command
        target:
          entity_id: remote.sony_tv
        data:
          command: "16"
```

### Input Switching

```yaml
button:
  - name: "HDMI 4 CEC"
    unique_id: sonytv_hap_hdmi4_cec
    icon: mdi:hdmi-port
    press:
      - action: remote.send_command
        target:
          entity_id: remote.sony_tv
        data:
          command: "input_9"

  - name: "HDMI 1"
    unique_id: sonytv_hap_hdmi1
    icon: mdi:hdmi-port
    press:
      - action: remote.send_command
        target:
          entity_id: remote.sony_tv
        data:
          command: "input_2"
```

### Long Press

```yaml
button:
  - name: "TV Settings (Hold)"
    unique_id: sonytv_hap_settings_hold
    icon: mdi:cog
    press:
      - action: remote.send_command
        target:
          entity_id: remote.sony_tv
        data:
          command: "14"
          hold_secs: 1.5
```

---

## Tested With

- Sony KD-55XG9505
- Home Assistant 2026.02
- iOS 26.3 / iPadOS 26.3
