#!/usr/bin/env bash
# Optional: close idle Claude Code sessions in tmux every 10 minutes.
# Try it first with: ./tmux-reap-stale --dry-run
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user"
install -m 755 "$here/tmux-reap-stale" "$HOME/.local/bin/tmux-reap-stale"
install -m 644 "$here/tmux-reap-stale.service" "$here/tmux-reap-stale.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now tmux-reap-stale.timer
echo "Installed. Closed sessions are logged with their resume command in ~/.local/state/tmux-reap/closed.log"
echo "Remove with: systemctl --user disable --now tmux-reap-stale.timer"
