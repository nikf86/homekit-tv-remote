## ⚠️ Read before updating

This is a rewrite. It does the same job, better, but almost everything behind it changed.

**Your setup migrates automatically. Nothing is deleted.**

**Requires Home Assistant 2026.8 or later.** HACS will not offer you this update on anything older.

---

### Configuration moved off the device page

The five text fields, the dropdown, the buttons, the two Apple TV switches and the per-input "Include" switches are gone. Everything is one form now, at **Settings → Devices & Services → HomeKit TV Remote → Configure**.

Those entities are removed from your device page on first start, and cleaned out of the registry so you get no "Unavailable" ghosts. Six entities remain — remote, media player, **Next input**, **Reload HomeKit Bridge**, and the two debug switches — all keeping their IDs and history.

### Three things that were quietly wrong

- **Input identifiers were guessed** as position-in-the-list plus one. HomeKit identifiers are arbitrary integers, so on a TV numbering its inputs 3, 7, 12 this was simply wrong. They are read from the accessory now — which is why the "HAP Identifier" field you used to type into no longer exists.
- **A playing TV read as off.**
- **Mute did a round trip to the TV** before every toggle.

### The Apple TV switches are gone

The integration now checks the target entity's own source list when a shortcut runs, and picks `select_source` or `play_media` accordingly. Right for Apple TV, Bravia, and anything else, with nothing to flag.

### The ⓘ freeze is fixed

After running a shortcut, the Info button and **Next input** used to go dead for a few seconds. They were waiting on the other integration to finish launching an app. They return immediately now.

### After updating, check one thing

Version 1 kept "saved" and "included" as separate ideas; there is one list now. Inputs whose Include switch was off are migrated anyway rather than dropped — remove any you do not want under **Configure → Manage saved inputs**.

**Manual installs:** delete `text.py`, `select.py` and `sensor.py`.

---

### Also new

Friendly command names (`up`, `back`, `home`, `play_pause`, `rewind`…) alongside the raw integers · `input:<name>` to switch input by name · exit / rewind / fast-forward / track buttons on the iOS widget now work · Test buttons on both the TV inputs and shortcut screens · rename and reorder your inputs · a drawn command reference under **Configure → HAP commands**.

Full detail and migration notes: [CHANGELOG.md](https://github.com/nikf86/homekit-tv-remote/blob/main/CHANGELOG.md)
