# NextUI Theme Catalog

Community theme repository for [TheyTheMeRollin](https://github.com/ericreinsmidt/nextui-theythemerollin), the theme manager for NextUI on TrimUI handhelds.

Themes are wallpaper and icon packs that change the look of your device. Browse and install them directly from the app.

---

## Submitting a Theme

1. Create your theme zip (see below)
2. [Open a submission issue](https://github.com/ericreinsmidt/nextui-theme-catalog/issues/new?template=submit-theme.yml)
3. Fill in the details and drag your zip file into the form
4. A bot will validate your theme and create a PR automatically
5. Once approved and merged, your theme appears in the app

## Creating a Theme

### Zip Structure

Your zip file should contain these files at the root:

```
manifest.json           required
preview.png             required — screenshot of your theme
wallpapers/             optional — include if your theme has wallpapers
  wallpaper.png         for universal mode (one image for all screens)
  root.png              for per-system mode (fallback/main menu wallpaper)
  systems/
    (GB).png            per-system wallpapers
    (GBA).png
    (SFC).png
    ...
  lists/
    (GB).png            per-system list wallpapers
    (GBA).png
    ...
icons/                  optional — include if your theme has icons
  systems/
    (GB).png            system icons
    (GBA).png
    ...
  collections.png       Collections folder icon
  recently_played.png   Recently Played icon
  tools.png             Tools icon
```

### manifest.json

```json
{
  "name": "My Theme",
  "author": "Your Name",
  "version": "1.0",
  "description": "A brief description of your theme",
  "wallpapers": {
    "mode": "per_system"
  },
  "icons": true
}
```

**Required fields:** `name`, `author`, `version`

**Wallpaper mode** must match your file structure:
- `"universal"` — single `wallpapers/wallpaper.png` applied everywhere
- `"per_system"` — `wallpapers/systems/` with per-console images, optional `root.png` as fallback

Omit the `wallpapers` field if your theme has no wallpapers (icons only).

### System Tags

Use these tags for system-specific wallpapers and icons:

| Tag | System |
|-----|--------|
| (FC) | Famicom / NES |
| (SFC) | Super Famicom / SNES |
| (GB) | Game Boy |
| (GBC) | Game Boy Color |
| (GBA) | Game Boy Advance |
| (MD) | Mega Drive / Genesis |
| (PS) | PlayStation |
| (N64) | Nintendo 64 |
| (NDS) | Nintendo DS |
| (PSP) | PSP |
| (MAME) | Arcade / MAME |
| (PCE) | PC Engine / TurboGrafx |
| (NGP) | Neo Geo Pocket |
| (WS) | WonderSwan |
| (MSX) | MSX |
| (PICO8) | PICO-8 |

You only need to include the systems your theme supports. Missing systems keep their existing wallpaper/icon.

### Preview Image

`preview.png` should be a screenshot showing your theme in action — the main menu or a system list. This is what users see when browsing themes in the app. Recommended resolution: 1024x768 (Brick native).

---

## For Maintainers

### Approving a Theme
Merge the auto-generated PR. The catalog updates immediately.

### Removing a Theme
```bash
# Remove from catalog.json
# Then delete the release assets:
gh release delete-asset assets <id>.zip
gh release delete-asset assets <id>.preview.png
```
