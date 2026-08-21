## 2.4.0 — bug fixes

No new features. Four faults found during a full code review, all of which could silently drop or misreport a command.

**Requires Home Assistant 2026.3 or later.** Tested on 2026.8.

---

### The D-pad disappearing from the iOS remote

If the arrows in Control Center vanished and came back, or took a while to appear at all, this is why.

An unavailable or unknown HomeKit Device entity was being reported as **off**. Sony sets drop their HAP session routinely and Home Assistant restarts pass through unknown, so it happened often. HomeKit Bridge translated that to `Active = 0`, and iOS hides the D-pad on an inactive TV accessory.

Unreachable is no longer treated as off. The last known state is held and corrects itself when the connection returns. The same blip was also clearing the remembered input, which is fixed alongside.

### Failed writes were recorded as successes

The error handling wrapped the *creation* of the background task, not the write itself. Any exception inside `put_characteristics` — timeout, disconnected, HAP error — never reached the handler, and the last-error attribute was set to success regardless. A press that failed produced no error, no log line and no visible change.

### Rapid presses could arrive out of order

One background task per press meant several fast arrows became several concurrent writes racing onto the connection.

Both are fixed by a single send queue drained by one worker. Presses still return immediately, order is preserved, and errors surface. Volume and mute use the same queue, so they no longer block on the wire.

### hold_secs did nothing

It wrote the key once and then slept locally, delaying the caller without reaching the TV. HAP's `RemoteKey` characteristic is a single enum write — no press/release pair, no duration, nothing to hold. It is now accepted and ignored. Use `delay_secs` to pace a sequence.

### Also

- An unclassified HAP error now records `-1` rather than `None`, which used to drop the attribute entirely and make a failure look like nothing had happened.
- The send worker starts on demand, so a command issued before the entity finishes setting up is not lost.
- `verify.py` gains section 10, covering all of the above.

---

### Upgrading from 1.x

If you are coming from 1.5.0, everything in the 2.0.0 notes applies to you as well — configuration moved off the device page into a form, input identifiers are read from the accessory instead of typed in, and the two Apple TV switches are gone. Your setup migrates automatically and nothing is deleted.

Manual installs must delete `text.py`, `select.py` and `sensor.py`.

See [CHANGELOG.md](CHANGELOG.md) for the full history.
