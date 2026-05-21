#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY_DIR="$SCRIPT_DIR/registry"
SAMPLES_DIR="$SCRIPT_DIR/samples"
PREVIEWS_DIR="$SCRIPT_DIR/previews"
OUTPUT="$SCRIPT_DIR/catalog.json"

# Auto-detect GitHub repo from git remote
REPO=$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null \
    | sed -E 's#(git@github\.com:|https://github\.com/)##; s#\.git$##')

if [ -z "$REPO" ]; then
    echo "ERROR: Could not detect GitHub repo from git remote"
    exit 1
fi

BRANCH="${GITHUB_REF_NAME:-main}"
BASE_URL="https://github.com/$REPO/raw/$BRANCH"
RAW_URL="https://raw.githubusercontent.com/$REPO/$BRANCH"

echo "Repo:   $REPO"
echo "Branch: $BRANCH"
echo "Base:   $BASE_URL"
echo ""

mkdir -p "$PREVIEWS_DIR"

errors=0
entries=""

for reg_file in "$REGISTRY_DIR"/*.json; do
    [ -f "$reg_file" ] || continue
    id=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$reg_file")

    echo "--- Processing: $id ---"

    source_dir="$SAMPLES_DIR/$id"
    if [ ! -d "$source_dir" ]; then
        echo "  FAIL: samples/$id/ not found"
        errors=$((errors + 1))
        continue
    fi

    # Validate manifest exists
    manifest="$source_dir/manifest.json"
    if [ ! -f "$manifest" ]; then
        echo "  FAIL: missing manifest.json"
        errors=$((errors + 1))
        continue
    fi

    # Validate manifest has required fields
    valid=$(python3 -c "
import json, sys
m = json.load(open(sys.argv[1]))
required = ['name', 'author', 'version']
missing = [f for f in required if f not in m]
if missing:
    print('MISSING:' + ','.join(missing))
else:
    print('OK')
" "$manifest")

    if [[ "$valid" != "OK" ]]; then
        echo "  FAIL: manifest $valid"
        errors=$((errors + 1))
        continue
    fi

    # Validate preview exists and is a real PNG
    if [ ! -f "$source_dir/preview.png" ]; then
        echo "  FAIL: missing preview.png"
        errors=$((errors + 1))
        continue
    fi

    if ! file "$source_dir/preview.png" | grep -q "PNG"; then
        echo "  FAIL: preview.png is not a valid PNG"
        errors=$((errors + 1))
        continue
    fi

    # Detect content and validate structure
    has_wallpapers=false
    has_icons=false
    wallpaper_mode="none"

    if [ -d "$source_dir/wallpapers" ]; then
        has_wallpapers=true
        if [ -f "$source_dir/wallpapers/wallpaper.png" ]; then
            wallpaper_mode="universal"
        elif [ -d "$source_dir/wallpapers/systems" ] || [ -f "$source_dir/wallpapers/root.png" ]; then
            wallpaper_mode="per_system"
        else
            echo "  FAIL: wallpapers/ exists but has no recognizable content"
            errors=$((errors + 1))
            continue
        fi

        # Validate manifest wallpaper mode matches actual content
        manifest_mode=$(python3 -c "
import json, sys
m = json.load(open(sys.argv[1]))
w = m.get('wallpapers', {})
if isinstance(w, dict):
    print(w.get('mode', 'none'))
else:
    print('none')
" "$manifest")

        if [ "$manifest_mode" != "$wallpaper_mode" ]; then
            echo "  FAIL: manifest says wallpaper mode '$manifest_mode' but content is '$wallpaper_mode'"
            errors=$((errors + 1))
            continue
        fi
    fi

    if [ -d "$source_dir/icons" ]; then
        has_icons=true
    fi

    # Validate at least one content type
    if [ "$has_wallpapers" = false ] && [ "$has_icons" = false ]; then
        echo "  FAIL: no wallpapers/ or icons/ directory"
        errors=$((errors + 1))
        continue
    fi

    # Spot-check that PNGs in the package are real images
    bad_png=false
    while IFS= read -r png; do
        if ! file "$png" | grep -q "PNG\|image"; then
            echo "  FAIL: $png is not a valid image"
            bad_png=true
            break
        fi
    done < <(find "$source_dir" -name "*.png" -not -name "preview.png")

    if [ "$bad_png" = true ]; then
        errors=$((errors + 1))
        continue
    fi

    # Count assets
    if [ "$has_wallpapers" = true ]; then
        wallpaper_count=$(find "$source_dir/wallpapers" -name "*.png" 2>/dev/null | wc -l | tr -d ' ')
    else
        wallpaper_count=0
    fi
    if [ "$has_icons" = true ]; then
        icon_count=$(find "$source_dir/icons" -name "*.png" 2>/dev/null | wc -l | tr -d ' ')
    else
        icon_count=0
    fi

    # Build systems list from filenames
    systems=$(find "$source_dir" -path "*/systems/*.png" -exec basename {} .png \; 2>/dev/null \
        | sort -u \
        | python3 -c "import sys,json; print(json.dumps(sorted(set(l.strip() for l in sys.stdin))))")

    echo "  OK: wallpapers=$has_wallpapers ($wallpaper_mode, $wallpaper_count files) icons=$has_icons ($icon_count files)"
    echo "  Systems: $systems"

    # Build zip from sample dir (exclude preview.png — it's served separately)
    zip_file="$SCRIPT_DIR/$id.zip"
    (cd "$source_dir" && zip -qr "$zip_file" . -x "preview.png")
    echo "  Zip: $id.zip ($(du -h "$zip_file" | cut -f1))"

    # Copy preview to previews/
    cp "$source_dir/preview.png" "$PREVIEWS_DIR/$id.png"

    # Build catalog entry JSON with proper URLs
    download_url="$BASE_URL/$id.zip"
    preview_url="$RAW_URL/previews/$id.png"

    entry=$(python3 -c "
import json, sys

manifest = json.load(open(sys.argv[1]))
entry = {
    'id': sys.argv[2],
    'name': manifest['name'],
    'author': manifest['author'],
    'version': manifest['version'],
    'description': manifest.get('description', ''),
    'has_wallpapers': sys.argv[3] == 'true',
    'wallpaper_mode': sys.argv[4],
    'has_icons': sys.argv[5] == 'true',
    'wallpaper_count': int(sys.argv[6]),
    'icon_count': int(sys.argv[7]),
    'systems': json.loads(sys.argv[8]),
    'url': sys.argv[9],
    'preview_url': sys.argv[10]
}
print(json.dumps(entry))
" "$manifest" "$id" "$has_wallpapers" "$wallpaper_mode" "$has_icons" "$wallpaper_count" "$icon_count" "$systems" "$download_url" "$preview_url")

    if [ -z "$entries" ]; then
        entries="$entry"
    else
        entries="$entries,$entry"
    fi
done

# Write catalog.json
python3 -c "
import json, sys
entries = json.loads('[' + sys.argv[1] + ']')
catalog = {
    'version': 1,
    'themes': [e for e in entries if e['has_wallpapers'] and e['has_icons']],
    'wallpapers': [e for e in entries if e['has_wallpapers']],
    'icons': [e for e in entries if e['has_icons']]
}
print(json.dumps(catalog, indent=2))
" "$entries" > "$OUTPUT"

echo ""
echo "=== Build complete ==="
echo "Output: $OUTPUT"
echo "Themes:     $(python3 -c "import json; print(len(json.load(open('$OUTPUT'))['themes']))")"
echo "Wallpapers: $(python3 -c "import json; print(len(json.load(open('$OUTPUT'))['wallpapers']))")"
echo "Icons:      $(python3 -c "import json; print(len(json.load(open('$OUTPUT'))['icons']))")"
echo "Errors: $errors"
[ "$errors" -eq 0 ] || exit 1
