#!/usr/bin/env bash
# Usage: start-listener.sh <exact tmux target, e.g. =work:=orchestrator>
# Run it in its own tmux window. Ctrl+C stops it.
#
# The target is an exact session and window NAME (the "=" prefixes stop tmux
# from prefix-matching). Pane ids and window numbers go stale when windows move
# or close, and a stale target could type your words into the wrong terminal.
set -u

[ $# -eq 1 ] || { echo "Usage: $0 =<session>:=<window>   (e.g. =work:=orchestrator)" >&2; exit 2; }
export HUD_TARGET="$1"
# HUD_SOURCE unset = listen.py picks the built-in laptop mic (see README).
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
cd "$HOME/.local/share/hud-listen" || { echo "Run setup.sh first." >&2; exit 1; }

keep_awake=()
command -v systemd-inhibit >/dev/null &&
  keep_awake=(systemd-inhibit --what=idle:sleep:handle-lid-switch --who=hud-listen --why=listening)

echo "Mic: ${HUD_SOURCE:-laptop mic}. Sending to: $HUD_TARGET"
while true; do
  "${keep_awake[@]}" ./venv/bin/python listen.py
  echo "Listener stopped, restarting in 3 seconds. Ctrl+C to quit."
  sleep 3
done
