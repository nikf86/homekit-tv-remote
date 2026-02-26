# HomeKit TV Remote

A Home Assistant custom integration that creates a native HAP remote entity for HomeKit-compatible TVs, enabling full iOS/iPadOS remote widget support and flexible input switching beyond what the HomeKit Device integration provides.

> **Note:** HomeKit TV accessories expose only a `media_player` entity via the HomeKit Device integration — no remote entity is available. This integration creates one by connecting directly to the TV over HAP using the existing pairing.

---

## Features

### 1. HAP-Native Remote Control

Communicates directly with the TV over HAP, bypassing traditional IP remote protocols. HAP commands are typically prioritized higher by the TV firmware, resulting in noticeably faster response times.

All commands confirmed on Sony KD-55XG9505. Results may vary on other manufacturers.

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
| `input_9` | HDMI CEC — HDMI 4 | |
| `input_10` | HDMI CEC — HDMI 1 | |
| `input_8` | HDMI CEC — HDMI 2 | |
| `input_6` | HDMI 4 | |
| `input_2` | HDMI 1 | |
| `input_3` | HDMI 2 | |

Both HDMI and HDMI CEC inputs are supported. The `input_N` number is assigned by the TV's HAP layer and may not match the physical port number. Switch to an input manually and read the active number from the **1c. Current Identifier** entity on the device page.

---

### 2. Custom Input & App Switching

Save inputs that appear as a source list in HomeKit and the HA media player card. Three command types are supported:

| Type | How it works |
|---|---|
| `hap` | Sends `ActiveIdentifier` directly to the TV — fastest, works for HDMI and CEC |
| `remote` | Routes a command through a third-party remote entity (e.g. Bravia) |
| `media_player` | Launches an app via `play_media` on a third-party media player entity |

---

### 3. iOS / iPadOS Remote Widget

The TV is exposed as a Television accessory in Apple Home, enabling the full remote widget in Control Center.

| iOS Button | Command |
|---|---|
| D-pad Up | `4` |
| D-pad Down | `5` |
| D-pad Left | `6` |
| D-pad Right | `7` |
| Select | `8` |
| Back | `9` |
| Play / Pause | `11` |

The **ⓘ Info button** cycles through saved inputs in order, wrapping back to the first after the last. All three input types can be mixed in the cycle.

---

## Requirements

> ⚠️ Your TV must be paired with HA via the **[HomeKit Device](https://www.home-assistant.io/integrations/homekit_controller/)** integration before installing. This integration uses the existing pairing — it does not pair itself.

- Home Assistant 2026.02 or later
- TV paired via the HomeKit Device integration
- HomeKit Bridge integration configured in HA

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

1. Select the HomeKit Device media player entity for your TV
2. Enter a display name — this generates the entity IDs (e.g. `Sony TV` → `remote.sony_tv`)
3. Expose `media_player.<your_tv>` to HomeKit via the **HomeKit Bridge integration in accessory mode** — this enables the iOS/iPadOS remote widget

---

## Adding Inputs

Go to the integration device page and fill in the fields below, then press **1e. Save Input**.

| Field | Required | Description |
|---|---|---|
| **1a. Input Name** | Always | Display name shown in HomeKit source list (e.g. `Apple TV`) |
| **1b. Command** | For `hap` / `remote` | HAP command (e.g. `input_9`) or vendor command (e.g. `Hdmi2`) |
| **1c. App Name** | For `media_player` | App name passed to `play_media` (e.g. `Netflix`) |
| **1d. Input Type** | Always | `hap`, a `remote.*` entity, or a `media_player.*` entity |
| **1d. HAP Identifier** | For `remote` / `media_player` | Integer the TV reports for this source — read from **1c. Current Identifier** |
| **1e. Save Input** | — | Saves the input |
| **1f. Delete Last Input** | — | Removes the last saved input |
| **Reload HomeKit YAML** | After changes | Re-registers the TV with HomeKit Bridge |

---

## Debug Switches

Available on the device page under Diagnostics. Can be toggled live without restarting.

| Switch | Log tag | What it logs |
|---|---|---|
| Debug Listen | `HOMEKIT_TV_LISTEN` | Polls and push notifications from the TV |
| Debug Send | `HOMEKIT_TV_SEND` | Every HAP command sent to the TV |

---

## Tested With

- Sony KD-55XG9505
- Home Assistant 2026.02
- iOS 26.3 / iPadOS 26.3

---

## YAML Button Examples

Replace `remote.homekit_tv` with your actual remote entity ID if you used a different name during setup.

### Basic Controls

```yaml
button:
  - name: "TV Power On"
    unique_id: sonytv_hap_power_on
    icon: mdi:power
    press:
      - action: remote.turn_on
        target:
          entity_id: remote.homekit_tv

  - name: "TV Power Off"
    unique_id: sonytv_hap_power_off
    icon: mdi:power-off
    press:
      - action: remote.turn_off
        target:
          entity_id: remote.homekit_tv

  - name: "Volume Up"
    unique_id: sonytv_hap_volume_up
    icon: mdi:volume-plus
    press:
      - action: remote.send_command
        target:
          entity_id: remote.homekit_tv
        data:
          command: "volume_up"

  - name: "Volume Down"
    unique_id: sonytv_hap_volume_down
    icon: mdi:volume-minus
    press:
      - action: remote.send_command
        target:
          entity_id: remote.homekit_tv
        data:
          command: "volume_down"

  - name: "TV Home"
    unique_id: sonytv_hap_tv_home
    icon: mdi:home
    press:
      - action: remote.send_command
        target:
          entity_id: remote.homekit_tv
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
          entity_id: remote.homekit_tv
        data:
          command: "input_9"

  - name: "HDMI 1"
    unique_id: sonytv_hap_hdmi1
    icon: mdi:hdmi-port
    press:
      - action: remote.send_command
        target:
          entity_id: remote.homekit_tv
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
          entity_id: remote.homekit_tv
        data:
          command: "14"
          hold_secs: 1.5
```
