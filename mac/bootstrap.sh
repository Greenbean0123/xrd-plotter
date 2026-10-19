#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
MODE="${1:-start}"
mkdir -p logs
LOG="$ROOT/logs/${MODE}-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
pause() { if [ -t 0 ]; then read -r -p 'Press Return to close... ' || true; fi; }
on_error() {
    status=$?
    trap - ERR
    echo ""
    echo "Operation failed (exit $status). Please send the logs folder."
    echo "Log: $LOG"
    pause
    exit "$status"
}
trap on_error ERR
echo 'XRD Plotter - automatic Mac setup'
echo "Mode: $MODE"
if [ "$(uname -s)" != Darwin ]; then
    echo 'This launcher must be run on macOS.'
    exit 1
fi
case "$MODE" in start|repair|build|diagnose) ;; *) echo 'Unknown mode'; exit 1 ;; esac
sw_vers
uname -m
echo "Rosetta translation: $(sysctl -in sysctl.proc_translated 2>/dev/null || echo 0)"

check_python() {
    [ -x "$1" ] || return 1
    "$1" -I -c 'import sys, tkinter, venv, ensurepip; assert (3,11) <= sys.version_info[:2] <= (3,13); assert "t" not in sys.abiflags; r=tkinter.Tk(); r.withdraw(); r.update(); r.destroy()' >/dev/null 2>&1
}
# Do not invoke Apple's /usr/bin/python3 developer-tools placeholder.
PYTHON=''
for candidate in "$ROOT/.venv/bin/python" \
    /Library/Frameworks/Python.framework/Versions/{3.13,3.12,3.11}/bin/python3 \
    /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
    /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if check_python "$candidate"; then PYTHON="$candidate"; break; fi
done

if [ "$MODE" = diagnose ]; then
    echo "Usable Python: ${PYTHON:-not found}"
    if [ -n "$PYTHON" ]; then
        "$PYTHON" -I "$ROOT/mac/check_environment.py" || true
        "$PYTHON" -m pip list || true
    fi
    echo "Diagnostic report: $LOG"
    pause
    exit 0
fi

if [ -z "$PYTHON" ]; then
    echo 'No compatible Python with a working Tkinter window was found.'
    echo 'Downloading Python 3.13.16 from python.org (Intel + Apple Silicon).'
    mkdir -p .runtime
    PKG="$ROOT/.runtime/python-3.13.16-macos11.pkg"
    curl --fail --location --retry 3 --connect-timeout 30 --proto '=https' --tlsv1.2 \
        https://www.python.org/ftp/python/3.13.16/python-3.13.16-macos11.pkg -o "$PKG"
    echo "30666509020b4da0dd8bc2e773255f34d76b7bb80b66960a928d5f6daa0192d7  $PKG" | shasum -a 256 -c -
    pkgutil --check-signature "$PKG"
    echo 'The standard macOS Python installer will open. Complete it, then return here.'
    open -W -a Installer "$PKG"
    PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
    if ! check_python "$PYTHON"; then
        echo 'Python installation was cancelled or Tkinter did not pass its window check.'
        false
    fi
    CERTS='/Applications/Python 3.13/Install Certificates.command'
    if [ -f "$CERTS" ]; then bash "$CERTS"; fi
fi

echo "Selected Python: $PYTHON"
"$PYTHON" -I -c 'import sys, platform; print(sys.version); print(platform.machine()); print(sys.executable)'
if ! check_python "$ROOT/.venv/bin/python"; then
    # Preserve a broken/moved virtual environment for diagnosis instead of deleting it.
    if [ -e .venv ]; then mv .venv ".venv-backup-$(date +%Y%m%d-%H%M%S)-$$"; fi
    "$PYTHON" -m venv .venv
fi
PYTHON="$ROOT/.venv/bin/python"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONNOUSERSITE=1
if [ "$MODE" = repair ] || ! "$PYTHON" -I "$ROOT/mac/check_environment.py"; then
    "$PYTHON" -m pip install --index-url https://pypi.org/simple --upgrade pip
    "$PYTHON" -m pip install --index-url https://pypi.org/simple --only-binary=:all: \
        --upgrade -r "$ROOT/mac/requirements.txt"
fi
"$PYTHON" -I "$ROOT/mac/check_environment.py"
if [ "$MODE" = build ]; then
    "$PYTHON" -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
    "$PYTHON" build.py
    open "$ROOT/dist"
    echo 'Build complete. The .app and .dmg are in dist/.'
    pause
else
    echo 'Starting XRD Plotter...'
    "$PYTHON" "$ROOT/src/startup.py"
fi
