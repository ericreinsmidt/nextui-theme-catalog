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
import subprocess
import sys
import tempfile
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


def validate_zip(zip_path, work_dir):
    """Validate theme zip contents. Returns (entry_data, errors)."""
    errors = []

    # Unzip
    result = run(["unzip", "-o", "-q", str(zip_path), "-d", str(work_dir)])
    if result.returncode != 0:
        return None, ["Could not extract zip file."]

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
        return None, ["Missing `manifest.json` in zip root."]

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return None, [f"Invalid manifest.json: {e}"]

    for field in ["name", "author", "version"]:
        if field not in manifest or not manifest[field]:
            errors.append(f"manifest.json missing required field: `{field}`")

    if errors:
        return None, errors

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

    # Detect wallpaper mode
    wallpaper_mode = "none"
    if has_wallpapers:
        if (work_dir / "wallpapers" / "wallpaper.png").exists():
            wallpaper_mode = "universal"
        elif (work_dir / "wallpapers" / "systems").is_dir() or \
             (work_dir / "wallpapers" / "root.png").exists():
            wallpaper_mode = "per_system"
        else:
            errors.append("`wallpapers/` exists but has no recognizable content "
                          "(need `wallpaper.png` for universal, or `systems/` or `root.png` for per-system).")

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
        return None, errors

    # Spot-check PNGs
    for png in work_dir.rglob("*.png"):
        if png.name == "preview.png":
            continue
        result = run(["file", str(png)])
        if "PNG" not in result.stdout and "image" not in result.stdout:
            errors.append(f"`{png.relative_to(work_dir)}` is not a valid image.")
            break

    if errors:
        return None, errors

    # Count assets
    wallpaper_count = 0
    if has_wallpapers:
        wallpaper_count = len(list((work_dir / "wallpapers").rglob("*.png")))

    icon_count = 0
    if has_icons:
        icon_count = len(list((work_dir / "icons").rglob("*.png")))

    # Enumerate system tags
    systems = set()
    for png in work_dir.rglob("systems/*.png"):
        systems.add(png.stem)
    systems = sorted(systems)

    # Find representative wallpaper image path (for browse background)
    wallpaper_sample = None
    if has_wallpapers:
        wp_dir = work_dir / "wallpapers"
        # Prefer root.png, then wallpaper.png (universal), then first system wallpaper
        for candidate in [wp_dir / "root.png", wp_dir / "wallpaper.png"]:
            if candidate.exists():
                wallpaper_sample = candidate
                break
        if not wallpaper_sample:
            sys_dir = wp_dir / "systems"
            if sys_dir.is_dir():
                pngs = sorted(sys_dir.glob("*.png"))
                if pngs:
                    wallpaper_sample = pngs[0]

    # Find representative icon image path (for icon browse)
    icon_sample = None
    if has_icons:
        ic_sys_dir = work_dir / "icons" / "systems"
        if ic_sys_dir.is_dir():
            pngs = sorted(ic_sys_dir.glob("*.png"))
            if pngs:
                icon_sample = pngs[0]

    entry = {
        "id": "",  # filled in by caller
        "name": manifest["name"],
        "author": manifest["author"],
        "version": manifest["version"],
        "description": manifest.get("description", ""),
        "has_wallpapers": has_wallpapers,
        "wallpaper_mode": wallpaper_mode,
        "has_icons": has_icons,
        "wallpaper_count": wallpaper_count,
        "icon_count": icon_count,
        "systems": systems,
        "url": "",
        "preview_url": "",
        "wallpaper_preview_url": "",
        "icon_preview_url": "",
        "_wallpaper_sample": str(wallpaper_sample) if wallpaper_sample else "",
        "_icon_sample": str(icon_sample) if icon_sample else "",
    }

    return entry, []


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
        entry, errors = validate_zip(zip_path, work_dir)

        if errors:
            error_list = "\n".join(f"- {e}" for e in errors)
            fail(f"Theme validation failed:\n\n{error_list}")

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

        # Upload wallpaper sample (for browse background)
        wp_sample_path = entry.pop("_wallpaper_sample", "")
        if wp_sample_path and Path(wp_sample_path).exists():
            wp_dest = tmpdir / f"{eid}.wallpaper.png"
            shutil.copy2(wp_sample_path, wp_dest)
            result = run(["gh", "release", "upload", "assets", str(wp_dest), "--clobber"])
            if result.returncode == 0:
                entry["wallpaper_preview_url"] = f"https://github.com/{REPO}/releases/download/assets/{eid}.wallpaper.png"
                print(f"Uploaded wallpaper sample: {Path(wp_sample_path).name}")
        else:
            entry.pop("_wallpaper_sample", None)

        # Upload icon sample (for icon browse)
        ic_sample_path = entry.pop("_icon_sample", "")
        if ic_sample_path and Path(ic_sample_path).exists():
            ic_dest = tmpdir / f"{eid}.icon.png"
            shutil.copy2(ic_sample_path, ic_dest)
            result = run(["gh", "release", "upload", "assets", str(ic_dest), "--clobber"])
            if result.returncode == 0:
                entry["icon_preview_url"] = f"https://github.com/{REPO}/releases/download/assets/{eid}.icon.png"
                print(f"Uploaded icon sample: {Path(ic_sample_path).name}")
        else:
            entry.pop("_icon_sample", None)

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

    pr_body = (
        f"## {action} Theme: {theme_name}\n\n"
        f"Submitted in #{ISSUE_NUMBER}\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Name | {entry['name']} |\n"
        f"| Author | {entry['author']} |\n"
        f"| Version | {entry['version']} |\n"
        f"| Wallpapers | {entry['wallpaper_mode']} ({entry['wallpaper_count']} files) |\n"
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
    comment_on_issue(
        f"## Validation Passed!\n\n"
        f"Theme **{theme_name}** has been validated and assets uploaded.\n\n"
        f"A PR has been created to update the catalog. "
        f"Once a maintainer merges it, the theme will be available in the app.\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| ID | `{eid}` |\n"
        f"| Wallpapers | {entry['wallpaper_mode']} ({entry['wallpaper_count']} files) |\n"
        f"| Icons | {entry['icon_count']} files |\n"
        f"| Systems | {', '.join(entry['systems']) or 'N/A'} |"
    )

    print(f"Done! {action}d theme: {theme_name} (id: {eid})")


if __name__ == "__main__":
    main()
