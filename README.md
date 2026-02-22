# HomeKit TV Remote

A Home Assistant custom integration that enables full native remote control for HomeKit-compatible TVs, with custom input switching and direct iOS/iPadOS remote widget support.

> Tested with a **Sony KD-55XG9505**. HomeKit TV accessories expose only a `media_player` entity — there is no remote entity available from the HomeKit Controller integration. This integration creates one by connecting directly to the TV over HAP.

---

## Core Features

### 1. HAP-Native Remote Control — Faster Than Traditional IP Remotes

This integration communicates with your TV **directly over the HomeKit Accessory Protocol (HAP)**, bypassing the overhead of traditional IP-based remote protocols. Because HAP commands are processed at a lower level and are typically prioritized higher by the TV's firmware, button presses feel **significantly more responsive** — often indistinguishable from using the physical remote.

The following HAP RemoteKey commands have been confirmed working on a Sony TV. What other manufacturers expose via HAP may vary.

| Command Value | Function | Notes |
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
| `volume_up` | Volume Up | Via VolumeSelector characteristic |
| `volume_down` | Volume Down | Via VolumeSelector characteristic |

Input switching supports both **direct HDMI inputs** and **HDMI CEC devices** connected to those inputs. Inputs are addressed by their HAP `ActiveIdentifier` integer (e.g. `input_9`), which may differ from the physical HDMI port number. Both types are fully controllable.

---

### 2. Custom Input & App Switching — HAP and Third-Party Integrations

Save any number of custom inputs to the integration. Each input can use one of three switching methods:

- **HAP** — sends a direct `ActiveIdentifier` command to the TV (e.g. `input_9`). Fastest and most reliable. Works for both physical HDMI ports and CEC-connected devices on those ports.
- **Third-party remote** — routes a command through another HA remote entity (e.g. Sony Bravia integration) for inputs that require vendor-specific commands.
- **App launch** — triggers `media_player.play_media` on a third-party media player entity (e.g. Bravia integration) to open streaming apps like Netflix or Disney+ by name.

All saved inputs appear as a **source list** in HomeKit and the HA media player card, selectable from Apple Home or any automation.

---

### 3. iOS / iPadOS Remote Widget with Full Button Support

Once set up, your TV appears as a **Television accessory** in Apple Home, giving you the full iOS and iPadOS remote widget in Control Center. Every button press is routed through HAP for maximum responsiveness.

Supported remote buttons:

| iOS Remote Button | HAP Command Sent |
|---|---|
| D-pad Up | `4` |
| D-pad Down | `5` |
| D-pad Left | `6` |
| D-pad Right | `7` |
| Select | `8` |
| Back | `9` |
| Play / Pause | `11` |

The **ⓘ Info button** on the iOS/iPadOS remote is repurposed as an **input cycling trigger**. Each press executes the next saved input in your list in order, wrapping back to the first after the last. This lets you cycle through HDMI inputs, CEC devices, and streaming apps with a single button — without opening any app or menu. The cycle supports all three input types mixed in any order.

---

## Requirements

> ⚠️ **Before installing this integration, your TV must already be paired with Home Assistant via the [HomeKit Device](https://www.home-assistant.io/integrations/homekit_controller/) integration.** This integration connects to the existing HAP pairing — it does not handle pairing itself.


- Home Assistant 2023.x or later
- TV already paired via the **HomeKit Controller** integration
- **HomeKit Bridge** integration configured in HA

---

## Installation

### Via HACS
1. Add this repository as a custom repository in HACS (category: Integration)
2. Install **HomeKit TV Remote**
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → HomeKit TV Remote**

### Manual
Copy the `custom_components/homekit_tv_remote/` folder into your HA `config/custom_components/` directory and restart.

---

## Setup

During the setup wizard you will select:
1. The HomeKit Controller media player entity for your TV
2. A display name for the TV (used to generate entity IDs)

---

## Adding Inputs

After setup, the integration creates a device page with text and button entities for managing inputs:

| Entity | Purpose |
|---|---|
| **1a. Input Name** | Display name for the new input |
| **1b. Command** | HAP command (`input_9`) or vendor remote command (`Hdmi2`) |
| **1c. App Name** | App name for media_player launch (alternative to command) |
| **1d. Input Type** | `hap`, a remote entity, or a media_player entity |
| **1d. HAP Identifier** | Integer HAP identifier (required for non-HAP inputs) |
| **1e. Save Input** | Saves the current input configuration |
| **1f. Delete Last Input** | Removes the most recently saved input |
| **Reload HomeKit YAML** | Re-registers the TV with HomeKit Bridge after changes |
| **1c. Current Identifier** | Live read-only display of the TV's current active input |

> After saving or deleting an input, press **Reload HomeKit YAML** to keep the iOS remote widget in sync with your changes.

---

## Debug Switches

Two diagnostic switches are available on the device page for troubleshooting:

- **Debug Listen** — logs every poll and push notification from the TV (`HOMEKIT_TV_LISTEN`)
- **Debug Send** — logs every HAP command sent to the TV (`HOMEKIT_TV_SEND`)

Both can be toggled live without restarting the integration.

---

## Tested With

- Sony KD-55XG9505
- Home Assistant 2026.02
- iOS 26.3 / iPadOS 26.3
