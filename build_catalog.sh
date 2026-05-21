#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY_DIR="$SCRIPT_DIR/registry"
OUTPUT="$SCRIPT_DIR/catalog.json"

errors=0
entries=""

for reg_file in "$REGISTRY_DIR"/*.json; do
    [ -f "$reg_file" ] || continue
    id=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$reg_file")
    url=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['url'])" "$reg_file")

    echo "--- Processing: $id ---"

    # Resolve source directory (local file:// or future GitHub)
    if [[ "$url" == file://* ]]; then
        source_dir="$SCRIPT_DIR/${url#file://}"
    else
        echo "  SKIP: non-local URLs not yet supported"
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

    # Validate preview exists
    if [ ! -f "$source_dir/preview.png" ]; then
        echo "  FAIL: missing preview.png"
        errors=$((errors + 1))
        continue
    fi

    # Validate preview is a real PNG
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
    systems=$(find "$source_dir" -path "*/systems/*.png" -exec basename {} .png \; 2>/dev/null | sort -u | python3 -c "import sys,json; print(json.dumps(sorted(set(l.strip() for l in sys.stdin))))")

    echo "  OK: wallpapers=$has_wallpapers ($wallpaper_mode, $wallpaper_count files) icons=$has_icons ($icon_count files)"
    echo "  Systems: $systems"

    # Build catalog entry JSON
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
    'url': sys.argv[9]
}
print(json.dumps(entry))
" "$manifest" "$id" "$has_wallpapers" "$wallpaper_mode" "$has_icons" "$wallpaper_count" "$icon_count" "$systems" "$url")

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
echo "Errors: $errors"
[ "$errors" -eq 0 ] || exit 1
