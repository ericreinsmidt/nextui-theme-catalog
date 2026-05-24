# NextUI Theme Catalog

Community themes for [Bling](https://github.com/ericreinsmidt/nextui-bling), a theme manager for NextUI on TrimUI handhelds (Brick, Smart Pro, Smart Pro S).

Themes can include **wallpapers** (menu backgrounds), **icons** (system icons), or both.

---

## Submitting a Theme

Submitting is simple — no git knowledge required.

### Step 1: Create Your Theme

Organize your files into this folder structure, then zip them:

```
my-theme/
  manifest.json        <- required (theme info)
  preview.png          <- required (screenshot of your theme)
  wallpapers/          <- optional
    ...
  icons/               <- optional
    ...
```

Details on each part below.

### Step 2: Submit

1. Go to the **[Submit a Theme](https://github.com/ericreinsmidt/nextui-theme-catalog/issues/new?template=submit-theme.yml)** page
2. Fill in the theme name, your name, and a short description
3. Drag your `.zip` file into the upload box
4. Check the boxes and submit

A bot will automatically validate your zip. If something's wrong, it'll tell you exactly what to fix. If everything passes, a PR is created and a maintainer will merge it. Your theme will then appear in the app for everyone to download.

---

## Theme Structure

### manifest.json

Every theme needs a `manifest.json` at the root of the zip:

```json
{
  "name": "My Theme",
  "author": "Your Name",
  "version": "1.0",
  "description": "A short description of your theme"
}
```

If your theme includes wallpapers, add a `wallpapers` field:

```json
{
  "name": "My Theme",
  "author": "Your Name",
  "version": "1.0",
  "description": "A short description of your theme",
  "wallpapers": {
    "mode": "per_system"
  }
}
```

**Wallpaper modes:**
- `"universal"` — one wallpaper used for every screen
- `"per_system"` — different wallpapers per console

If your theme is icons-only, just leave out the `wallpapers` field entirely.

### preview.png

A screenshot showing what your theme looks like in action. This is what people see when browsing in the app.

- **Resolution:** 1024x768 (Brick native) recommended
- **Content:** Main menu or a system list showing your wallpaper/icons
- **Format:** PNG

### Wallpapers

Put your wallpaper images in a `wallpapers/` folder.

**Universal mode** (one wallpaper everywhere):

```
wallpapers/
  wallpaper.png        <- this image is used for all screens
```

**Per-system mode** (different per console):

```
wallpapers/
  root.png             <- main menu background (also used as fallback)
  systems/
    (GB).png           <- Game Boy menu background
    (SFC).png          <- SNES menu background
    ...
  lists/
    (GB).png           <- Game Boy game list background
    (SFC).png          <- SNES game list background
    ...
```

- `root.png` is the main menu wallpaper and the fallback for any system you don't include
- `systems/` wallpapers appear on the system's menu screen
- `lists/` wallpapers appear on the game list screen
- You don't need every system — only include the ones you want to customize

### Icons

Put your icon images in an `icons/` folder:

```
icons/
  systems/
    (GB).png           <- Game Boy icon
    (SFC).png          <- SNES icon
    ...
  collections.png      <- Collections folder icon (optional)
  recently_played.png  <- Recently Played icon (optional)
  tools.png            <- Tools icon (optional)
```

Icons appear on the main menu next to each system name. You only need to include the systems you want to customize.

---

## System Tags

Use these tags for filenames. The tag is the part in parentheses from the system's folder name on the device.

| Tag | System |
|-----|--------|
| `(FC)` | Nintendo Entertainment System / Famicom |
| `(FDS)` | Famicom Disk System |
| `(SFC)` | Super Nintendo / SNES |
| `(GB)` | Game Boy |
| `(GBC)` | Game Boy Color |
| `(GBA)` | Game Boy Advance |
| `(N64)` | Nintendo 64 |
| `(MD)` | Sega Genesis / Mega Drive |
| `(SMS)` | Sega Master System |
| `(GG)` | Sega Game Gear |
| `(SEGACD)` | Sega CD |
| `(32X)` | Sega 32X |
| `(PS)` | Sony PlayStation |
| `(PSP)` | Sony PSP |
| `(PCE)` | TurboGrafx-16 / PC Engine |
| `(NEOGEO)` | Neo Geo |
| `(NGP)` | Neo Geo Pocket |
| `(NGPC)` | Neo Geo Pocket Color |
| `(MAME)` | Arcade (MAME) |
| `(FBN)` | Arcade (FinalBurn Neo) |
| `(MSX)` | Microsoft MSX |
| `(LYNX)` | Atari Lynx |
| `(A2600)` | Atari 2600 |
| `(A5200)` | Atari 5200 |
| `(A7800)` | Atari 7800 |
| `(COLECO)` | ColecoVision |
| `(VB)` | Virtual Boy |
| `(P8)` | Pico-8 |
| `(PKM)` | Pokemon mini |
| `(CPC)` | Amstrad CPC |
| `(C64)` | Commodore 64 |
| `(PRBOOM)` | Doom |
| `(SGB)` | Super Game Boy |

You only need to include the systems your theme supports. Any system you skip keeps its current wallpaper/icon.

---

## Examples

### Full theme (wallpapers + icons, per-system)

```
manifest.json
preview.png
wallpapers/
  root.png
  systems/
    (GB).png
    (GBA).png
    (SFC).png
    (MD).png
    (PS).png
  lists/
    (GB).png
    (GBA).png
    (SFC).png
    (MD).png
    (PS).png
icons/
  systems/
    (GB).png
    (GBA).png
    (SFC).png
    (MD).png
    (PS).png
  collections.png
  recently_played.png
  tools.png
```

### Universal wallpaper (one image for all screens)

```
manifest.json
preview.png
wallpapers/
  wallpaper.png
```

### Icons only

```
manifest.json
preview.png
icons/
  systems/
    (GB).png
    (GBA).png
    (SFC).png
```

---

## Updating a Theme

Submit a new issue with the same theme name. The bot will replace the old version with the new one.

## For Maintainers

### Approving a theme
Merge the auto-generated PR. The issue closes automatically.

### Removing a theme
Edit `catalog.json` to remove the entry, then delete the release assets:
```bash
gh release delete-asset assets <id>.zip
gh release delete-asset assets <id>.preview.png
```
