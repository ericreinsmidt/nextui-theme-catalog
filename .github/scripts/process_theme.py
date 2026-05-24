#!/usr/bin/env python3
"""
Process a theme submission from a GitHub issue.

Reads the issue body, downloads and validates the zip,
uploads assets to the pinned "assets" release, updates
catalog.json, and creates a PR.

Expected env vars: ISSUE_NUMBER, ISSUE_BODY, GITHUB_REPOSITORY
Requires: gh CLI authenticated, unzip, file
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path


REPO = os.environ.get("GITHUB_REPOSITORY", "")
ISSUE_NUMBER = os.environ.get("ISSUE_NUMBER", "")
ISSUE_BODY = os.environ.get("ISSUE_BODY", "")
CATALOG_PATH = Path("catalog.json")


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    comment_on_issue(f"## Validation Failed\n\n{msg}\n\nPlease fix the issue and resubmit.")
    sys.exit(1)


def run(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
    return result


def comment_on_issue(body):
    if not ISSUE_NUMBER:
        return
    run(["gh", "issue", "comment", ISSUE_NUMBER, "--body", body])


def parse_issue_body(body):
    """Extract form fields from GitHub issue form markdown."""
    fields = {}

    # GitHub issue forms produce: ### Label\n\nValue\n\n
    for match in re.finditer(r"### (.+?)\s*\n\s*\n(.*?)(?=\n### |\n\Z)", body, re.DOTALL):
        label = match.group(1).strip()
        value = match.group(2).strip()
        fields[label] = value

    return fields


def extract_zip_url(text):
    """Find a GitHub attachment URL in text."""
    # GitHub user-attachments format
    patterns = [
        r"https://github\.com/user-attachments/assets/[a-f0-9-]+/[^\s\)]+\.zip",
        r"https://github\.com/[^\s\)]+/files/[^\s\)]+\.zip",
        r"https://user-images\.githubusercontent\.com/[^\s\)]+\.zip",
        r"https://github\.com/[^\s\)]+/releases/download/[^\s\)]+\.zip",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def generate_id(name):
    """Generate a URL-safe id from theme name."""
    eid = name.lower().strip()
    eid = re.sub(r"[^a-z0-9\s-]", "", eid)
    eid = re.sub(r"\s+", "-", eid)
    eid = re.sub(r"-+", "-", eid).strip("-")
    return eid


def get_png_dimensions(png_path):
    """Read width and height from a PNG file's IHDR chunk.

    Returns (width, height) or None on failure.
    """
    try:
        with open(png_path, "rb") as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return None
            header = f.read(8)
            if len(header) < 8:
                return None
            length, chunk_type = struct.unpack(">I4s", header)
            if chunk_type != b"IHDR":
                return None
            data = f.read(length)
            width, height = struct.unpack(">II", data[:8])
            return (width, height)
    except Exception:
        return None


def is_blank_png(png_path):
    """Check if a PNG is fully transparent (all pixels have alpha=0).

    Pure-Python implementation — no Pillow dependency required.
    Returns True only for RGBA/greyscale+alpha PNGs where every pixel's
    alpha channel is zero.
    """
    try:
        with open(png_path, "rb") as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return False

            width = height = 0
            color_type = bit_depth = 0
            idat_chunks = []

            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                length, chunk_type = struct.unpack(">I4s", header)
                data = f.read(length)
                f.read(4)  # CRC

                if chunk_type == b"IHDR":
                    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
                elif chunk_type == b"IDAT":
                    idat_chunks.append(data)
                elif chunk_type == b"IEND":
                    break

            # Only check images with an alpha channel (color types 4 and 6)
            if color_type not in (4, 6):
                return False

            raw = zlib.decompress(b"".join(idat_chunks))

            if color_type == 6:  # RGBA
                channels = 4
                bpp = channels * (bit_depth // 8)
                stride = 1 + width * bpp  # filter byte + pixel data
                for y in range(height):
                    row = raw[y * stride + 1:(y + 1) * stride]
                    for x in range(width):
                        alpha = row[x * bpp + 3]
                        if alpha != 0:
                            return False
            elif color_type == 4:  # Greyscale + alpha
                channels = 2
                bpp = channels * (bit_depth // 8)
                stride = 1 + width * bpp
                for y in range(height):
                    row = raw[y * stride + 1:(y + 1) * stride]
                    for x in range(width):
                        alpha = row[x * bpp + 1]
                        if alpha != 0:
                            return False

            return True
    except Exception:
        return False


def validate_zip(zip_path, work_dir):
    """Validate theme zip contents. Returns (entry_data, errors)."""
    errors = []

    # Unzip
    result = run(["unzip", "-o", "-q", str(zip_path), "-d", str(work_dir)])
    if result.returncode != 0:
        return None, ["Could not extract zip file."], []

    # Check for nested directory (zip with single top-level folder)
    contents = list(work_dir.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        # Unwrap: move contents up one level
        nested = contents[0]
        for item in nested.iterdir():
            shutil.move(str(item), str(work_dir / item.name))
        nested.rmdir()

    # Check manifest
    manifest_path = work_dir / "manifest.json"
    if not manifest_path.exists():
        return None, ["Missing `manifest.json` in zip root."], []

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return None, [f"Invalid manifest.json: {e}"], []

    for field in ["name", "author", "version"]:
        if field not in manifest or not manifest[field]:
            errors.append(f"manifest.json missing required field: `{field}`")

    if errors:
        return None, errors, []

    # Check preview
    preview_path = work_dir / "preview.png"
    if not preview_path.exists():
        errors.append("Missing `preview.png` in zip root.")
    else:
        result = run(["file", str(preview_path)])
        if "PNG" not in result.stdout:
            errors.append("`preview.png` is not a valid PNG image.")

    # Check content directories
    has_wallpapers = (work_dir / "wallpapers").is_dir()
    has_icons = (work_dir / "icons").is_dir()

    if not has_wallpapers and not has_icons:
        errors.append("Zip must contain a `wallpapers/` and/or `icons/` directory.")

    # Detect resolution subdirectories under wallpapers/
    # e.g. wallpapers/1024x768/systems/, wallpapers/1024x720/systems/
    wallpaper_resolutions = []
    if has_wallpapers:
        res_pattern = re.compile(r"^(\d+)x(\d+)$")
        for child in sorted((work_dir / "wallpapers").iterdir()):
            if child.is_dir() and res_pattern.match(child.name):
                wallpaper_resolutions.append(child.name)

    # Detect wallpaper mode
    wallpaper_mode = "none"
    if has_wallpapers:
        if wallpaper_resolutions:
            # Multi-resolution: check structure inside resolution folders
            for res_dir_name in wallpaper_resolutions:
                res_dir = work_dir / "wallpapers" / res_dir_name
                has_universal = (res_dir / "wallpaper.png").exists()
                has_per_system = (res_dir / "systems").is_dir() or (res_dir / "root.png").exists()
                if has_universal:
                    detected = "universal"
                elif has_per_system:
                    detected = "per_system"
                else:
                    errors.append(f"`wallpapers/{res_dir_name}/` has no recognizable content "
                                  f"(need `wallpaper.png` for universal, or `systems/` or `root.png` "
                                  f"for per-system).")
                    continue

                if wallpaper_mode == "none":
                    wallpaper_mode = detected
                elif wallpaper_mode != detected:
                    errors.append(f"Inconsistent wallpaper mode across resolution folders: "
                                  f"expected `{wallpaper_mode}` but `wallpapers/{res_dir_name}/` "
                                  f"is `{detected}`.")

            # Validate that PNGs in resolution folders match declared dimensions
            for res_dir_name in wallpaper_resolutions:
                match = res_pattern.match(res_dir_name)
                expected_w, expected_h = int(match.group(1)), int(match.group(2))
                res_dir = work_dir / "wallpapers" / res_dir_name
                checked = 0
                for png in res_dir.rglob("*.png"):
                    dims = get_png_dimensions(png)
                    if dims and dims != (expected_w, expected_h):
                        rel = png.relative_to(work_dir)
                        errors.append(f"`{rel}` is {dims[0]}x{dims[1]} but is in the "
                                      f"`{res_dir_name}` folder (expected {expected_w}x{expected_h}).")
                        break
                    checked += 1
                if checked == 0:
                    errors.append(f"`wallpapers/{res_dir_name}/` contains no PNG files.")
        else:
            # Flat structure (legacy / single resolution)
            if (work_dir / "wallpapers" / "wallpaper.png").exists():
                wallpaper_mode = "universal"
            elif (work_dir / "wallpapers" / "systems").is_dir() or \
                 (work_dir / "wallpapers" / "root.png").exists():
                wallpaper_mode = "per_system"
            else:
                errors.append("`wallpapers/` exists but has no recognizable content "
                              "(need `wallpaper.png` for universal, or `systems/` or `root.png` "
                              "for per-system).")

        # Validate manifest wallpaper mode matches
        manifest_wp = manifest.get("wallpapers", {})
        if isinstance(manifest_wp, dict):
            manifest_mode = manifest_wp.get("mode", "none")
        else:
            manifest_mode = "none"

        if manifest_mode != wallpaper_mode:
            errors.append(f"Manifest declares wallpaper mode `{manifest_mode}` "
                          f"but content structure is `{wallpaper_mode}`.")

    if errors:
        return None, errors, []

    # Spot-check PNGs
    for png in work_dir.rglob("*.png"):
        if png.name == "preview.png":
            continue
        result = run(["file", str(png)])
        if "PNG" not in result.stdout and "image" not in result.stdout:
            errors.append(f"`{png.relative_to(work_dir)}` is not a valid image.")
            break

    if errors:
        return None, errors, []

    # Count assets
    wallpaper_count = 0
    if has_wallpapers:
        wallpaper_count = len(list((work_dir / "wallpapers").rglob("*.png")))

    icon_count = 0
    blank_icon_count = 0
    if has_icons:
        for png in (work_dir / "icons").rglob("*.png"):
            if is_blank_png(png):
                blank_icon_count += 1
            else:
                icon_count += 1
        if blank_icon_count:
            print(f"  Skipped {blank_icon_count} blank/transparent icon(s)")
        if icon_count == 0:
            has_icons = False

    # Enumerate system tags (skip blank icons)
    systems = set()
    if has_wallpapers:
        if wallpaper_resolutions:
            # Multi-res: look inside each resolution folder
            for res_dir_name in wallpaper_resolutions:
                for png in (work_dir / "wallpapers" / res_dir_name).rglob("systems/*.png"):
                    systems.add(png.stem)
        else:
            for png in (work_dir / "wallpapers").rglob("systems/*.png"):
                systems.add(png.stem)
    if has_icons:
        for png in (work_dir / "icons").rglob("systems/*.png"):
            if not is_blank_png(png):
                systems.add(png.stem)
    systems = sorted(systems)

    warnings = []
    if blank_icon_count:
        warnings.append(f"Found {blank_icon_count} fully-transparent icon(s). These are "
                        f"kept in the zip (they hide default icons when applied) but are "
                        f"excluded from the icon count in the catalog.")

    entry = {
        "id": "",  # filled in by caller
        "name": manifest["name"],
        "author": manifest["author"],
        "version": manifest["version"],
        "description": manifest.get("description", ""),
        "has_wallpapers": has_wallpapers,
        "wallpaper_mode": wallpaper_mode,
        "wallpaper_resolutions": wallpaper_resolutions,
        "has_icons": has_icons,
        "wallpaper_count": wallpaper_count,
        "icon_count": icon_count,
        "systems": systems,
        "url": "",
        "preview_url": "",
    }

    return entry, [], warnings


def update_catalog(entry):
    """Add or update entry in catalog.json."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            catalog = json.load(f)
    else:
        catalog = {"version": 1, "themes": [], "wallpapers": [], "icons": []}

    eid = entry["id"]

    # Remove existing entry with same id from all sections
    for section in ["themes", "wallpapers", "icons"]:
        catalog[section] = [e for e in catalog[section] if e["id"] != eid]

    # Add to appropriate sections
    if entry["has_wallpapers"] and entry["has_icons"]:
        catalog["themes"].append(entry)
    if entry["has_wallpapers"]:
        catalog["wallpapers"].append(entry)
    if entry["has_icons"]:
        catalog["icons"].append(entry)

    with open(CATALOG_PATH, "w") as f:
        json.dump(catalog, f, indent=2)
        f.write("\n")


def main():
    if not ISSUE_BODY or not ISSUE_NUMBER:
        print("Missing ISSUE_BODY or ISSUE_NUMBER", file=sys.stderr)
        sys.exit(1)

    # Parse issue
    fields = parse_issue_body(ISSUE_BODY)
    theme_name = fields.get("Theme Name", "").strip()
    author = fields.get("Author", "").strip()
    zip_field = fields.get("Theme Zip File", "")

    if not theme_name:
        fail("Could not find theme name in the issue.")
    if not author:
        fail("Could not find author in the issue.")

    zip_url = extract_zip_url(zip_field)
    if not zip_url:
        fail("Could not find a zip file attachment. "
             "Please drag and drop a `.zip` file into the Theme Zip File field.")

    eid = generate_id(theme_name)
    if not eid:
        fail(f"Could not generate a valid ID from theme name: `{theme_name}`")

    print(f"Processing: {theme_name} (id: {eid}) by {author}")
    print(f"Zip URL: {zip_url}")

    # Check for ID conflict with different author
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            catalog = json.load(f)
        for section in ["themes", "wallpapers", "icons"]:
            for existing in catalog[section]:
                if existing["id"] == eid and existing["author"] != author:
                    fail(f"A theme with ID `{eid}` already exists by a different author "
                         f"(`{existing['author']}`). Please choose a different name.")
                    break

    is_update = CATALOG_PATH.exists() and any(
        e["id"] == eid
        for section in ["themes", "wallpapers", "icons"]
        for e in json.load(open(CATALOG_PATH)).get(section, [])
    )

    # Download zip
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        zip_path = tmpdir / f"{eid}.zip"
        work_dir = tmpdir / "contents"
        work_dir.mkdir()

        print(f"Downloading zip...")
        result = run(["curl", "-sfL", "-o", str(zip_path), zip_url])
        if result.returncode != 0:
            fail("Failed to download the zip file from the attachment URL.")

        # Check size (100MB max)
        zip_size = zip_path.stat().st_size
        if zip_size > 100 * 1024 * 1024:
            fail(f"Zip file is too large ({zip_size // 1024 // 1024}MB). Maximum is 100MB.")

        # Validate
        print("Validating zip contents...")
        entry, errors, warnings = validate_zip(zip_path, work_dir)

        if errors:
            error_list = "\n".join(f"- {e}" for e in errors)
            fail(f"Theme validation failed:\n\n{error_list}")

        for w in warnings:
            print(f"  Warning: {w}")

        entry["id"] = eid
        entry["url"] = f"https://github.com/{REPO}/releases/download/assets/{eid}.zip"
        entry["preview_url"] = f"https://github.com/{REPO}/releases/download/assets/{eid}.preview.png"

        # Upload release assets
        print("Uploading release assets...")

        # Ensure assets release exists
        result = run(["gh", "release", "view", "assets"])
        if result.returncode != 0:
            run(["gh", "release", "create", "assets",
                 "--title", "Theme Assets",
                 "--notes", "Pinned release for theme assets. Do not delete.",
                 "--latest=false"])

        result = run(["gh", "release", "upload", "assets", str(zip_path), "--clobber"])
        if result.returncode != 0:
            fail("Failed to upload zip to release assets.")

        # Upload preview
        preview_src = work_dir / "preview.png"
        preview_dest = tmpdir / f"{eid}.preview.png"
        shutil.copy2(preview_src, preview_dest)
        result = run(["gh", "release", "upload", "assets", str(preview_dest), "--clobber"])
        if result.returncode != 0:
            fail("Failed to upload preview to release assets.")

        # Update catalog.json
        print("Updating catalog.json...")
        update_catalog(entry)

    # Create PR
    action = "Update" if is_update else "Add"
    branch = f"theme/{eid}"

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])

    # Delete old branch if exists
    run(["git", "branch", "-D", branch])
    run(["git", "push", "origin", "--delete", branch])

    run(["git", "checkout", "-b", branch])
    run(["git", "add", "catalog.json"])
    run(["git", "commit", "-m", f"{action} theme: {theme_name}\n\nCloses #{ISSUE_NUMBER}"])
    result = run(["git", "push", "origin", branch, "--force"])
    if result.returncode != 0:
        fail("Failed to push branch.")

    res_info = ""
    if entry["wallpaper_resolutions"]:
        res_info = f" — {', '.join(entry['wallpaper_resolutions'])}"

    pr_body = (
        f"## {action} Theme: {theme_name}\n\n"
        f"Submitted in #{ISSUE_NUMBER}\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Name | {entry['name']} |\n"
        f"| Author | {entry['author']} |\n"
        f"| Version | {entry['version']} |\n"
        f"| Wallpapers | {entry['wallpaper_mode']} ({entry['wallpaper_count']} files){res_info} |\n"
        f"| Icons | {entry['icon_count']} files |\n"
        f"| Systems | {', '.join(entry['systems']) or 'N/A'} |\n\n"
        f"**Preview:**\n\n"
        f"![preview]({entry['preview_url']})\n\n"
        f"Closes #{ISSUE_NUMBER}"
    )

    result = run([
        "gh", "pr", "create",
        "--title", f"[Theme] {action}: {theme_name}",
        "--body", pr_body,
        "--head", branch,
        "--base", "main",
    ])

    if result.returncode != 0:
        # PR might already exist, try to update it
        print("PR may already exist, continuing...")

    # Comment on issue
    warn_section = ""
    if warnings:
        warn_list = "\n".join(f"- ⚠️ {w}" for w in warnings)
        warn_section = f"\n\n### Warnings\n\n{warn_list}\n"

    comment_on_issue(
        f"## Validation Passed!\n\n"
        f"Theme **{theme_name}** has been validated and assets uploaded.\n\n"
        f"A PR has been created to update the catalog. "
        f"Once a maintainer merges it, the theme will be available in the app.\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| ID | `{eid}` |\n"
        f"| Wallpapers | {entry['wallpaper_mode']} ({entry['wallpaper_count']} files){res_info} |\n"
        f"| Icons | {entry['icon_count']} files |\n"
        f"| Systems | {', '.join(entry['systems']) or 'N/A'} |"
        f"{warn_section}"
    )

    print(f"Done! {action}d theme: {theme_name} (id: {eid})")


if __name__ == "__main__":
    main()
