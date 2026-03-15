# HomeKit TV Remote

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Control your TV directly over HAP — the same protocol Apple devices use — giving you a native HA remote entity and the full iOS/iPadOS remote widget in Control Center.

---

## What It Does

- **Full remote control over HAP** — D-pad, back, home, play/pause, volume, mute, and input switching, all sent directly over the HomeKit Accessory Protocol. No vendor app, no IP remote — just the same channel Apple devices use, with the priority that comes with it.
- **iOS/iPadOS remote widget with input cycling** — your TV appears as a Television accessory in Apple Home, unlocking the native remote widget in Control Center. The ⓘ Info button cycles through your saved inputs in order. You control exactly which inputs are visible in Apple Home and which are included in the cycle — per input, with a simple toggle.
- **Any input, any integration** — save HDMI and CEC inputs directly via HAP, or connect any third-party remote or media player entity (Bravia, Apple TV, and others) to switch sources and launch apps from the same unified list.
- **Test before saving** — fire any command from the configuration fields before committing it, so you know it works before it goes into your setup.

---

## Requirements

- Home Assistant 2026.3 or later
- TV already paired via the [HomeKit Device](https://www.home-assistant.io/integrations/homekit_controller/) integration
- HomeKit Bridge integration configured in HA

---

## Installation

**HACS:** Add this repo as a custom repository (category: Integration), install, restart HA, then go to **Settings → Devices & Services → Add Integration → HomeKit TV Remote**.

**Manual:** Copy `custom_components/homekit_tv_remote/` into your `config/custom_components/` directory and restart.

---

## Setup

1. Select your TV's HomeKit Device `media_player` entity and give it a name (e.g. `Sony TV` → entities become `remote.sony_tv`, `media_player.sony_tv`)

2. Expose the integration's `media_player` to HomeKit Bridge **in accessory mode** — this is what enables the iOS remote widget. Replace `Your TV Name` and `your_tv_name` with the name you entered during setup:

```yaml
homekit:
  - name: Your TV Name
    mode: accessory
    filter:
      include_entities:
        - media_player.your_tv_name
```

Restart HA and pair the new accessory in Apple Home.


---

## Adding Inputs

Everything is in the **Configuration section** of the device page. The workflow is:

1. Fill in the fields for your input
2. Press **1f. Test Command** to verify it works
3. Press **1g. Save Input**
4. Turn ON the **Include: \<name\>** switch to make it appear in HomeKit and the input cycle

| Field | Purpose |
|---|---|
| **1a. Input Name** | Display name shown in HomeKit and HA |
| **1b. Command** | HAP command (e.g. `input_9`) or vendor remote command (e.g. `Hdmi2`) |
| **1c. App Name** | App name for media player launches (e.g. `Netflix`) |
| **1d. Input Type** | `hap`, a `remote.*` entity, or a `media_player.*` entity |
| **1e. HAP Identifier** | The number your TV reports for this input — read it from **1i. Current Identifier** while the input is active |
| **1f. Test Command** | Fires the command immediately without saving — works for all input types |
| **1g. Save Input** | Saves the input |
| **1h. Delete Last Input** | Removes the last saved input |
| **1i. Current Identifier** | Live read-out of the TV's current input and its HAP number |
| **Include: \<name\>** | Controls whether this input appears in HomeKit and the cycle |
| **Next Saved Input** | Cycles to the next enabled input — same as the iOS ⓘ Info button |
| **Reload HomeKit YAML** | Re-registers the TV with HomeKit Bridge after adding/removing inputs. After reloading, force-close and reopen the Apple Home app on your iPhone/iPad for the changes to appear. |

### Apple TV specifics

The Apple TV integration works differently from other media players — it only supports `select_source` for launching apps, not `play_media`. Two switches handle this automatically when saving an Apple TV input:

**1. Apple TV App** — turn this ON before saving. It tells the integration to use `select_source` instead of `play_media`. Without it, app launching will silently do nothing.

**1. Apple TV Input** — optional. Turn this ON if you also want the TV to automatically switch its HDMI input to the Apple TV port before launching the app. For this to work, fill in **1e. HAP Identifier** with the number your TV reports for the Apple TV HDMI port — you can read it from **1i. Current Identifier** while that input is active on your TV.

Both switches reset to OFF on every reload — they are per-save toggles, not persistent settings.

> App names are case-sensitive and must match exactly. The easiest way to find them: **Developer Tools → Actions → `media_player.select_source`** → pick your Apple TV entity — the source dropdown lists every installed app with the exact string to use.

---

## Input Examples

**HDMI / CEC input**
Switch to the input on your TV, read its number from **1i. Current Identifier**, then fill in:
`1b. Command` = `input_9` · `1d. Input Type` = `hap`

**Third-party remote (e.g. Bravia)**
`1b. Command` = `Hdmi2` · `1d. Input Type` = `remote.bravia_kd_55xg9505` · `1e. HAP Identifier` = `3`

**App from a third-party media player (e.g. Bravia Netflix)**
`1c. App Name` = `Netflix` · `1d. Input Type` = `media_player.bravia_kd_55xg9505`

**App from Apple TV — app only**
Use this when the TV is already on the Apple TV input, or you handle input switching separately.
`1. Apple TV App` = On · `1c. App Name` = `Netflix` · `1d. Input Type` = `media_player.ng_apple_tv`

**App from Apple TV — with automatic HDMI input switching**
Use this to switch the TV to the Apple TV HDMI port and launch the app in one step. Set **1e. HAP Identifier** to the number your TV reports for the Apple TV port (read from **1i. Current Identifier** while on that input).
`1. Apple TV App` = On · `1. Apple TV Input` = On · `1c. App Name` = `Netflix` · `1d. Input Type` = `media_player.ng_apple_tv` · `1e. HAP Identifier` = `8`

> Apple TV app names are case-sensitive. The easiest way to find them: **Developer Tools → Actions → `media_player.select_source`** → pick your Apple TV entity — the source list shows every installed app with the exact string.

### Third-party integrations

When using a `remote.*` or `media_player.*` entity as the input type, this integration sends the command but relies entirely on the third-party integration to carry it out. The exact command strings, app names, and entity IDs vary between integrations — and what works on one brand may not work on another.

Before saving an input that uses a third-party entity, check that integration's own documentation for:
- The correct command or app name format it expects
- Any pairing or configuration requirements (e.g. Companion protocol for Apple TV, network discovery for Bravia)
- Known limitations — some integrations do not support certain services like `play_media` or `select_source`

If a test command does nothing or throws an error, the issue is almost always with the third-party integration rather than this one.

---

## iOS Remote Widget Buttons

| Button | Action |
|---|---|
| D-pad | Navigate |
| Select | OK |
| Back | Back |
| Play/Pause | Play/Pause |
| **ⓘ Info** | Cycle to next enabled input |

---

## HAP Commands Reference

| Command | Function |
|---|---|
| `4` `5` `6` `7` | D-pad Up / Down / Left / Right |
| `8` | Select / OK |
| `9` | Back |
| `10` | Exit |
| `11` | Play/Pause |
| `16` | TV Home |
| `14` | TV Settings |
| `volume_up` / `volume_down` | Volume |
| `input_N` | Switch to input N |

---

## YAML Examples

```yaml
# Power
- action: remote.turn_on
  target:
    entity_id: remote.sony_tv

# Volume
- action: remote.send_command
  target:
    entity_id: remote.sony_tv
  data:
    command: "volume_up"

# Input switch
- action: remote.send_command
  target:
    entity_id: remote.sony_tv
  data:
    command: "input_9"

# Long press
- action: remote.send_command
  target:
    entity_id: remote.sony_tv
  data:
    command: "14"
    hold_secs: 1.5
```

---

## Debug

Two switches in the Diagnostics section let you turn on detailed logging without restarting:

- **Debug Listen** — logs everything received from the TV (`HOMEKIT_TV_LISTEN`)
- **Debug Send** — logs every command sent to the TV (`HOMEKIT_TV_SEND`)

---

## Tested With

- Sony KD-55XG9505
- Home Assistant 2026.3
- iOS 26.3 / iPadOS 26.3

---

## Say Thank You

If this integration saves you time or just makes your setup a little better, a small donation is always appreciated — it helps keep the project going.

[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-0070ba?logo=paypal&logoColor=white)](https://www.paypal.com/donate?business=nikfam86%40gmail.com&item_name=HomeKit+TV+Remote)
