#!/usr/bin/env bash
# Optional: keep your tmux server (and every agent in it) alive across desktop logouts and crashes.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin"
install -m 755 "$here/tmux-keep" "$HOME/.local/bin/tmux-keep"
echo "Installed tmux-keep."
echo "  Start your session with:   tmux-keep work      (instead of: tmux new -s work)"
echo "  Protect one already running: tmux-keep --adopt"
loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes \
  || echo "  To survive a full logout too, run once: loginctl enable-linger \"$USER\""
