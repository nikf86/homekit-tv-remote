# Changelog

## 2.4.0 — bug fixes

No new features. Four faults found during a full review, all of which could
silently drop or misreport a command.

### The D-pad disappearing from the iOS remote

An unavailable or unknown HomeKit Device entity was reported as **off**. Sony
sets drop their HAP session routinely, and Home Assistant restarts pass through
unknown, so this happened often. Home Assistant's HomeKit Bridge translated it
to `Active = 0`, and iOS hides the D-pad on an inactive TV accessory — so the
arrows vanished and came back on every blip, or failed to appear until the
connection recovered.

Unreachable is no longer treated as off, in either entity. The last known state
is held and corrects itself when the connection returns.

The same blip also cleared the remembered input, because the `source` attribute
is absent while unavailable and that read as "the TV moved somewhere else".
Fixed alongside.

### Failed writes recorded as successes

`_press` wrapped `try/except` around *creating* the background task, not around
the write. Any exception inside `put_characteristics` — timeout, disconnected,
HAP error — was raised inside the task and never reached the error handler,
while `_last_error` was set to `HAP_SUCCESS` regardless. A dropped press
produced no error, no log line and no attribute change.

### No ordering guarantee on rapid presses

One background task per press meant five rapid arrows were five concurrent
writes racing onto the connection, and could arrive reordered.

Both are fixed by a single send queue drained by one worker. Callers still
return immediately, order is preserved, and errors surface. Volume and mute now
use the same queue, so they no longer block on the wire while holding the lock.

### hold_secs did nothing

It wrote the characteristic once and then slept locally, delaying the caller
without reaching the TV — and, as a side effect, disqualified the press from the
fast path. HAP's RemoteKey characteristic is a single write of an enum value:
there is no press/release pair and no duration. It is now accepted and ignored,
with a debug line. Use `delay_secs` to pace a sequence.

### Also

- An unclassified HAP error records `-1` instead of `None`. `None` dropped
  `last_hap_error` from the attributes entirely, making a failure look like
  nothing had happened.
- The send worker starts on demand, so a command issued before
  `async_added_to_hass` is not lost.
- `verify.py` gains section 10, covering all of the above.


## 2.3.0

- Removed the **HAP commands** step. Home Assistant's markdown sanitiser strips almost all of an inline SVG — no `viewBox`, no `fill`, and `circle`/`rect`/`text` are not allowed tags — so the drawing arrived as a couple of stray fragments. It lives in the manual instead, where it renders properly.
- Every title, label and description in the Configure dialog rewritten: shorter and more direct.

## 2.2.0 — superseded

- **HAP commands** entry in Configure: the full command reference, drawn as a remote.
- The same drawing heads the command section of the manual.

## 2.1.0

### The ⓘ / Next input freeze — fixed

After running a shortcut, the ⓘ button on the iOS widget and the **Next input** button went dead for several seconds, then recovered on their own.

The whole chain was waiting on the other integration. `button.press` → cycle → run input → `media_player.select_source(blocking=True)`, and an Apple TV app launch does not return until the app is actually up. For that entire window the button sat disabled and further presses did nothing. Underneath it was a second cause: every press re-read the TV's *reported* input, and a TV mid-switch still reports the old one, so two fast presses handed out the same target twice.

Cycling now picks the next input and returns immediately, dispatching the command in the background, and only re-syncs to the live input after four seconds of quiet.

### Configure

- **Test** on the TV inputs screen — switch the TV to one of its own inputs without saving.
- **Manage** became a submenu: **Rename** (label only; what the input does and its place in the cycle are untouched), **Change the order** (one input at a time, list renumbered each time), **Remove**.
- Every change applies immediately and returns you to the menu, instead of closing the dialog. Renaming three inputs no longer means opening Configure three times.
- **Manual** entry linking to the documentation.

### Other

- Brand icons prepared for the [home-assistant/brands](https://github.com/home-assistant/brands) repository.
- Manual rewritten with worked examples for Apple TV and other integrations, and a table of which TV brands ship HomeKit.
- Removed four dead constants; the stale-entity sweep uses an indexed registry lookup instead of scanning every entity in Home Assistant on each setup.

---

## 2.0.0 — a rewrite

> **Read this before updating.** The integration works the same way from the outside, but almost everything behind it changed. Your setup migrates automatically; nothing is deleted.

### Configuration moved out of the device page

Version 1 held configuration in entities: five text fields, a dropdown, five buttons, two Apple TV switches, and one "Include" switch per saved input. That is why fields were named `1a.`, `1b.`, `1c.` — entities sort alphabetically — and why everything you typed reset on reload.

All of it is now a form, at **Settings → Devices & Services → HomeKit TV Remote → Configure**.

**Those entities are removed from your device page on first start**, and their registry entries are cleaned up so you get no "Unavailable" ghosts. Six entities remain: the remote, the media player, **Next input**, **Reload HomeKit Bridge**, and the two debug switches. All six keep their IDs and their history.

### It stopped asking the TV things

Power state and current input are read from the HomeKit Device entity Home Assistant already keeps up to date, and input identifiers are read from the accessory description already held in memory. Three fixes came out of that:

- **Input identifiers were being guessed.** Version 1 computed them as position-in-the-source-list plus one. HomeKit identifiers are arbitrary integers, not positions — on a TV that numbers its inputs 3, 7 and 12 the maths was silently wrong. They are now read from the accessory's `IDENTIFIER` characteristic. **This is what removed the "HAP Identifier" field you used to have to look up and type in.**
- **A playing TV read as off.** `is_on` compared against the literal string `"on"`, so a TV reporting `playing` or `paused` registered as off.
- **Mute did a round trip to the TV** before every toggle. It is one write now. `mute_on` and `mute_off` were added for automations that need a certain result.

### The Apple TV switches are gone

`1. Apple TV App` and `1. Apple TV Input` no longer exist. When a shortcut targets a media player, the integration checks that entity's own source list when the shortcut runs: if your app name is in it, the app launches with `select_source`, otherwise with `play_media`. Correct for Apple TV, for Bravia, and for anything else, with nothing to flag.

### Your saved inputs

The config entry migrates from version 1 to version 2 on first start. Every saved input is converted — all four old command types.

**One thing to check afterwards.** Version 1 kept "saved" and "included" as separate ideas. Version 2 has one list: being in it means being in Apple Home. Inputs whose Include switch was off are migrated anyway rather than silently dropped, and named in the log. Remove any you do not want under **Configure → Manage saved inputs**.

Inputs migrated from 1.x keep their old numeric identifier and show as `(migrated)`. They keep working. To convert one, remove it and tick the input under **TV inputs**.

### Requirements changed

**Home Assistant 2026.3 or later.** The integration uses `OptionsFlowWithReload`, `AddConfigEntryEntitiesCallback` and `ConfigEntry.runtime_data`, all of which exist well before 2026.3, and it serves its own icon from `brand/`, which needs 2026.3. HACS will not offer this update to anyone on an older release.

*(2.0.0 originally declared 2026.8. That was more conservative than necessary — nothing in the code requires it. Corrected in 2.4.0.)*

### If you installed manually

Delete `text.py`, `select.py` and `sensor.py` from `custom_components/homekit_tv_remote/`. HACS handles this for you.

### Also new

- Friendly command names: `up`, `down`, `left`, `right`, `select`, `back`, `exit`, `home`, `settings`, `play_pause`, `rewind`, `fast_forward`, `next_track`, `previous_track` — alongside the raw integers, which still work.
- `input:<name>` switches the TV to an input by name.
- The iOS widget's exit, rewind, fast-forward and track buttons are handled; version 1 ignored them.
- Input cycling starts from the input the TV is actually on, so ⓘ moves one step from where you are even if you changed input with the TV's own remote.

---

## 1.5.0 and earlier

See the [1.x releases](https://github.com/nikf86/homekit-tv-remote/releases).
