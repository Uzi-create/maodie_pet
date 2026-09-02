#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  /usr/bin/python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt pyinstaller

ICONSET="build/MaodiePet.iconset"
mkdir -p "$ICONSET"
SOURCE_ICON="assets/idle-sprite-v4.png"
for SIZE in 16 32 128 256 512; do
  sips -z "$SIZE" "$SIZE" "$SOURCE_ICON" --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
  DOUBLE=$((SIZE * 2))
  sips -z "$DOUBLE" "$DOUBLE" "$SOURCE_ICON" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "build/MaodiePet.icns"

.venv/bin/pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "圆头耄耋" \
  --osx-bundle-identifier "com.uzicreate.maodiepet" \
  --icon "build/MaodiePet.icns" \
  --add-data "assets:assets" \
  app.py

echo "完成：$SCRIPT_DIR/dist/圆头耄耋.app"
