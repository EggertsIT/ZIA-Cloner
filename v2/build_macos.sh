#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ZIA-Backup-Restore"
BUNDLE_ID="com.ziabackuprestore.app"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script must be run on macOS."
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$PROJECT_ROOT/.build-venv"
export PYINSTALLER_CONFIG_DIR="$PROJECT_ROOT/.pyinstaller"
PYINSTALLER_ARCH_ARGS=()
PYINSTALLER_SIGN_ARGS=()

if [[ -n "${PYINSTALLER_TARGET_ARCH:-}" ]]; then
  PYINSTALLER_ARCH_ARGS=(--target-architecture "$PYINSTALLER_TARGET_ARCH")
fi

if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  PYINSTALLER_SIGN_ARGS=(--codesign-identity "$SIGN_IDENTITY")
fi

if [[ -n "${NOTARY_PROFILE:-}" && -z "${SIGN_IDENTITY:-}" ]]; then
  echo "NOTARY_PROFILE requires SIGN_IDENTITY with a Developer ID Application certificate."
  exit 1
fi

if [[ "${1:-}" == "--clean" ]]; then
  rm -rf "$PROJECT_ROOT/build" "$PROJECT_ROOT/dist" "$PROJECT_ROOT/$APP_NAME.spec" "$VENV_DIR" "$PYINSTALLER_CONFIG_DIR"
fi

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or later is required to build this app.")

try:
    import tkinter  # noqa: F401
except Exception as exc:
    raise SystemExit(
        "The selected Python cannot import tkinter. Install/use a Python build "
        "with Tk support, then rerun with PYTHON_BIN=/path/to/python3. "
        f"Original error: {exc}"
    )
PY

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

python - <<'PY'
try:
    import tkinter  # noqa: F401
except Exception as exc:
    raise SystemExit(f"The build virtualenv cannot import tkinter: {exc}")
PY

if python - <<'PY'
import PyInstaller  # noqa: F401
PY
then
  echo "Using installed PyInstaller: $(python -m PyInstaller --version)"
else
  python -m pip install --upgrade pip pyinstaller
fi

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  "${PYINSTALLER_ARCH_ARGS[@]}" \
  "${PYINSTALLER_SIGN_ARGS[@]}" \
  zia_cloner_app.py

APP_BUNDLE="$PROJECT_ROOT/dist/$APP_NAME.app"
if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Expected app bundle was not created: $APP_BUNDLE"
  exit 1
fi

if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
  spctl --assess --type execute --verbose=2 "$APP_BUNDLE" || true
else
  if codesign --force --deep --sign - "$APP_BUNDLE"; then
    echo "Ad-hoc signed: $APP_BUNDLE"
  else
    echo "Warning: ad-hoc codesign failed; continuing with unsigned bundle."
  fi
fi

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
  NOTARY_ZIP="$PROJECT_ROOT/dist/$APP_NAME-notary-upload.zip"
  rm -f "$NOTARY_ZIP"
  ditto -c -k --keepParent "$APP_BUNDLE" "$NOTARY_ZIP"
  xcrun notarytool submit "$NOTARY_ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_BUNDLE"
  xcrun stapler validate "$APP_BUNDLE"
  rm -f "$NOTARY_ZIP"
fi

PACKAGE_DIR="$PROJECT_ROOT/dist/ZIA-Backup-Restore-macOS"
ZIP_PATH="$PROJECT_ROOT/dist/ZIA-Backup-Restore-macOS.zip"
rm -rf "$PACKAGE_DIR" "$ZIP_PATH"
mkdir -p "$PACKAGE_DIR"
cp -R "$APP_BUNDLE" "$PACKAGE_DIR/"
cp "$PROJECT_ROOT/MACOS_USER_GUIDE.txt" "$PACKAGE_DIR/README.txt"
ditto -c -k --sequesterRsrc --keepParent "$PACKAGE_DIR" "$ZIP_PATH"

echo
echo "Built: $APP_BUNDLE"
echo "Package: $ZIP_PATH"
