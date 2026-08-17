# Publishing 2.3.2 — click by click

Four apps are involved. Each step says which one you are in.

Nothing you do before step 5 reaches a single user, so there is no rush and no way to break anything for people already running 1.5.0. They are pinned to the `v1.5.0` release until you publish a new one.

---

## 1 — Finder: unzip the release

Double-click `homekit-tv-remote-2.3.2-release.zip`. You get a folder containing:

```
.github/          ← hidden
.gitignore        ← hidden
custom_components/
docs/
CHANGELOG.md   LICENSE   README.md   RELEASE_NOTES.md
UPLOAD.md   WORKFLOWS.md   hacs.json   verify.py   versions.json
```

**Press Cmd+Shift+. (period) now.** Dot-files are hidden in Finder by default. If you do not turn them on you will copy everything except `.github/` and `.gitignore`, silently, and the validation checks will never run. When hidden files are showing, dimmed items appear — that is how you know it worked.

Leave this window open.

---

## 2 — GitHub Desktop: open your repo folder

Top left, **Current Repository** → select **homekit-tv-remote**.

Then menu bar: **Repository → Show in Finder** (Cmd+Shift+F). A second Finder window opens on your local clone. This is the folder that matters — not anything on github.com.

Turn hidden files on here too if the window does not already show them (Cmd+Shift+.). You should see `.git` (dimmed) — that confirms you are in the right place.

---

## 3 — Finder: swap the files

In your **repo** window:

1. Select the folder `custom_components/homekit_tv_remote` and **delete it entirely** (Cmd+Delete). Do not drag the new one on top and choose Merge — merging leaves the old `text.py`, `select.py` and `sensor.py` behind, and those must go.
2. Also delete `custom_components/homekit_tv_remote/versions.json` if it survived — it moves to the repo root in this release.

Now from the **unzipped release** window, select everything (Cmd+A) and drag it into the repo window. When macOS asks about `README.md`, `hacs.json` and `custom_components`, choose **Replace**.

Do not touch the `.git` folder. Ever.

---

## 4 — GitHub Desktop: review, commit, push

Click the **Changes** tab, left-hand side. Read the list before doing anything.

**Three checkpoints. If any fails, stop.**

| Check | What you should see |
|---|---|
| Deletions registered | `custom_components/homekit_tv_remote/text.py`, `select.py` and `sensor.py` each with a red minus icon |
| Hidden files came across | `.github/workflows/validate.yml` and `.gitignore` listed as new |
| Nothing unexpected vanished | no deletions you cannot explain |

If the three `.py` files are **not** shown as deleted, Finder merged instead of replacing. Redo step 3.

Then, bottom left:

- **Summary:** `2.3.2 — rewrite; configuration moves into the options flow`
- **Description** (optional): `See CHANGELOG.md for the full list and migration notes.`
- Click **Commit to main**.
- Top of the window, click **Push origin**.

Your code is now on GitHub. Still nobody has it.

---

## 5 — github.com: wait for the checks

Open <https://github.com/nikf86/homekit-tv-remote> → **Actions** tab.

Two jobs run on your push: **Home Assistant hassfest** and **HACS validation**. Give them a minute.

- Two green ticks → continue.
- Red X → click it, read the failure, fix, commit and push again. Nothing is published yet, so a red run costs you nothing.

---

## 6 — github.com: publish the release

**This is the step that reaches your users.** Everything before it was preparation.

On the repo page, right-hand sidebar → **Releases** → **Draft a new release**.

| Field | What to put |
|---|---|
| **Choose a tag** | type `v2.3.2`, then click **Create new tag: v2.3.2 on publish** |
| **Target** | `main` |
| **Release title** | `2.3.2 — a rewrite` |
| **Describe this release** | open `RELEASE_NOTES.md` from the release folder, copy all of it, paste here |
| Set as pre-release | leave **unticked** |
| Set as the latest release | leave **ticked** |

Click **Publish release**.

HACS shows the five most recent releases and renders that description in the update dialog. It is the only warning most people will ever read, which is why it leads with the migration notes.

---

## 7 — Check it from the other side

Within an hour or so, HACS on your own Home Assistant should offer **2.3.2**. Users on Home Assistant older than 2026.8 will not be offered it at all — `hacs.json` blocks that deliberately, because 2.x uses APIs that do not exist before then.

Update your own install first. You are the only person who can confirm the migration works on a real setup before anyone else runs it.

---

## Optional: the .DS_Store files

Three of them are already tracked in git, so the new `.gitignore` will not untrack them. Harmless, just untidy. To be rid of them:

**GitHub Desktop → Repository → Open in Terminal**, then:

```bash
git rm --cached .DS_Store custom_components/.DS_Store custom_components/homekit_tv_remote/.DS_Store
```

Back in GitHub Desktop they appear as deletions. Commit and push as normal. `.gitignore` keeps them out from now on.

---

## The icon — already handled

No pull request anywhere. Since **Home Assistant 2026.3**, a custom integration
serves its own brand images: ship `custom_components/<domain>/brand/icon.png` and
Home Assistant fetches it from itself, through
`/api/brands/integration/<domain>/icon.png`. Local images take priority over the
CDN and need no configuration.

That folder is in this release — `icon.png` at 256x256 and `icon@2x.png` at
512x512. Installing 2.3.2 is the whole fix.

The `custom_integrations` folder in home-assistant/brands is marked **legacy** in
that repository's own README for exactly this reason. Opening a pull request
there for a custom integration gets it closed unmerged.

If the grey placeholder is still showing after you update: restart Home
Assistant, then hard refresh the browser with Cmd+Shift+R. The proxy caches
images on disk with a stale-while-revalidate strategy, so a fetch that failed
earlier can linger.

---

## If something looks wrong after pushing

You have not published a release yet, so no user is affected. Fix the files, commit, push again. Only step 6 is visible to anyone else — and even a published release can be deleted from the Releases page, which puts HACS back to offering 1.5.0.
