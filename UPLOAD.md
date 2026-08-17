# Publishing 2.2.0

Your repo is currently: `README.md`, `hacs.json`, `custom_components/homekit_tv_remote/`, three committed `.DS_Store` files, and tags up to `v1.5.0`. This release changes enough that the how matters as much as the what.

---

## What HACS actually checks

Two corrections to keep in mind, because they affect the file layout.

**HACS reads the icon from inside your integration.** `custom_components/homekit_tv_remote/brand/icon.png` — you already had it, and it is kept. HACS falls back to the [home-assistant/brands](https://github.com/home-assistant/brands) repository only when that folder is absent.

**Home Assistant itself never reads it from there.** The "icon not available" placeholder on the integration page comes from `brands.home-assistant.io`, and the only way to fill it is a pull request to that repository. That is what `brands/` at the repo root is for. You want both: `brand/` for HACS, the PR for Home Assistant.

**`manifest.json` must define `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version`.** Yours had `documentation` empty and no `issue_tracker` — both now filled in. The HACS validation workflow added in `.github/workflows/` fails on this, so you will see it caught automatically from now on.

---

## Files being removed

| File | Why |
|---|---|
| `custom_components/homekit_tv_remote/text.py` | platform gone — configuration is a form now |
| `custom_components/homekit_tv_remote/select.py` | same |
| `custom_components/homekit_tv_remote/sensor.py` | same |
| `custom_components/homekit_tv_remote/versions.json` | moved to the repo root; it is development metadata and does not belong in every user's install |
| `.DS_Store` × 3 | macOS junk, now in `.gitignore` |

`brand/` stays exactly where it was.

---

## The upload

Work on a branch. If anything looks wrong on GitHub you can delete it without having touched `main`.

```bash
cd /path/to/your/homekit-tv-remote
git checkout main && git pull

# 1. a branch to build the release on
git checkout -b v2

# 2. clear the old integration out, so removed files really are removed
git rm -r --quiet custom_components/homekit_tv_remote
git rm --quiet --cached .DS_Store custom_components/.DS_Store \
       custom_components/homekit_tv_remote/.DS_Store 2>/dev/null || true

# 3. copy the new tree in — everything from the release zip
cp -R /path/to/unzipped/homekit-tv-remote/. .

# 4. check what you are about to commit before you commit it
git add -A
git status
```

`git status` should show the three deleted platform files, the moved `versions.json`, the new `.github/`, `brands/`, `docs/`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, and modifications to everything under `custom_components/`. If it shows deletions you did not expect, stop and look.

```bash
# 5. commit and push
git commit -m "2.2.0 — configuration moves into the options flow

Configuration is a form instead of 15 device-page entities. Input
identifiers are read from the accessory instead of guessed. Fixes the
Info / Next input freeze after running a shortcut. Requires HA 2026.8.

See CHANGELOG.md for the full list and the migration notes."

git push -u origin v2
```

Open the pull request on GitHub, **wait for the two checks to go green** (hassfest and HACS validation), then merge it into `main`.

---

## The release

This is the part users actually see. HACS shows the five most recent releases, and shows the release description in the update dialog — so the release notes are your one chance to warn people before they click update.

**Do not just push a tag.** HACS needs a full GitHub Release.

With the `gh` CLI:

```bash
git checkout main && git pull
gh release create v2.2.0 --title "2.2.0 — a rewrite" --notes-file RELEASE_NOTES.md
```

Or on the website: **Releases → Draft a new release → tag `v2.2.0` → target `main`** → paste `RELEASE_NOTES.md` into the description → **Publish release**.

Tag it `v2.2.0` to match your existing `v1.x` tags.

---

## Why nobody on an old Home Assistant will break

`hacs.json` now says `"homeassistant": "2026.8.0"`. HACS will not offer the update to anyone running older than that. They stay on 1.5.0 until they upgrade Home Assistant, which is exactly what you want given 2.x uses APIs that do not exist before 2026.8 and avoids one that 2026.8 removes.

---

## The brands pull request

Separate from all of the above, and it is what fills in the "icon not available" placeholder on the integration page.

1. Fork <https://github.com/home-assistant/brands>.
2. Copy `brands/custom_integrations/homekit_tv_remote/` from this repo into the fork, at the same path.
3. Open a pull request.

Two rules that get custom integrations rejected: no Home Assistant branding in the artwork, and no symlinks in `custom_integrations`.

---

## One decision left

`LICENSE` is MIT with your name on it. It is a placeholder for a choice only you can make — MIT is the usual pick for HACS integrations and lets anyone reuse the code with attribution. If you want something stricter (GPL-3.0, so derivatives must also stay open) or no license at all, replace the file before you push. Note that a repository with no license is, legally, all-rights-reserved, which sits awkwardly with asking people to install it.
