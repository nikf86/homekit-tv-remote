# Brand images

Home Assistant does not read an integration's icon from the integration folder.
The frontend loads it from `brands.home-assistant.io`, which is why the
integration page shows "icon not available" until the images are submitted.

## What is here

| File | Size | Notes |
|---|---|---|
| `custom_integrations/homekit_tv_remote/icon.png` | 256 × 256 | trimmed edge to edge |
| `custom_integrations/homekit_tv_remote/icon@2x.png` | 512 × 512 | trimmed edge to edge |

Both are nikfam's artwork, cropped to remove the transparent border the source
files carried (23 px on the 512, 10 px on the 256) and rescaled to the exact
sizes the brands repo requires. The repo rejects images with empty margins.

No `dark_icon` variants are needed: the artwork carries its own dark rounded
square, so it reads correctly on light and dark themes alike.

No `logo.png` is included. It is optional, and Home Assistant falls back to the
icon. A logo is a wordmark rather than a scaled-up icon, so it is worth drawing
deliberately rather than deriving.

## How to submit

1. Fork <https://github.com/home-assistant/brands>.
2. Copy `custom_integrations/homekit_tv_remote/` from here into the fork, same path.
3. Open a pull request.

Two rules that get custom integrations rejected: no Home Assistant branding in
the artwork (it implies an official integration), and no symlinks in the
`custom_integrations` folder.

Once the PR is merged the icon appears automatically — in the integration page,
the Add Integration dialog, and HACS. Nothing in this repository needs changing.

## A note on small sizes

Home Assistant renders this icon at roughly 24–96 px. "HAP" stays legible all
the way down; the "by nikfam" line and the remote's button colours turn to mush
below about 64 px. That is normal for a detailed icon and costs nothing
functionally — but if you want it sharper in the integration list, the change
worth making is dropping the byline and enlarging the wordmark in a
small-size-specific variant.
