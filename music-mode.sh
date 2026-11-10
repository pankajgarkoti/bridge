#!/usr/bin/env bash
# Music mode for the voice HUD.
#
#   music-mode.sh on    Spotify keeps playing; the spoken replies do not pause
#                       it; the headset is forced to A2DP (full-quality music,
#                       mic released — no more narrowband call-mode audio).
#                       When the music stops, the headset profile switches back
#                       and the mic returns automatically.
#   music-mode.sh off   Back to the default: pause music around spoken replies,
#                       headset profile free, mic always available.
#
# Settings (environment):
#   HUD_TARGET    exact orchestrator target, e.g. =work:=orchestrator (required)
#   HUD_LISTENER  the listener's window, default: <same session>:hud-listen
#   HUD_CARD      Bluetooth card, default: the first bluez_card in `pactl list cards short`
#   HUD_A2DP / HUD_CALL  card profile names (see `pactl list cards`)
#
set -u
here="$(cd "$(dirname "$0")" && pwd)"
FLAG="$HOME/.local/share/hud-listen/music-mode"
CARD="${HUD_CARD:-$(pactl list cards short | awk '$2 ~ /^bluez_card/ {print $2; exit}')}"
A2DP="${HUD_A2DP:-a2dp-sink-sbc_xq}"
CALL="${HUD_CALL:-headset-head-unit}"
# The listener's pane and its two mics: while music plays (A2DP, mic released)
# dictation rides the LAPTOP mic; with the headset profile it goes back to the
# headset's own mic. Respawn swaps the env only on state changes.
TARGET="${HUD_TARGET:-}"
session="${TARGET%%:*}"; session="${session#=}"
LISTENER="${HUD_LISTENER:-$session:hud-listen}"
if [ "${1:-}" != "" ] && { [ -z "$CARD" ] || [ -z "$TARGET" ]; }; then
  echo "music-mode: need a Bluetooth card (HUD_CARD) and HUD_TARGET=<=session:=window>" >&2
  exit 2
fi
bt_sink()   { pactl list sinks short   | awk -F'\t' '$2 ~ /^bluez_output/ {print $2; exit}'; }
bt_source() { pactl list sources short | awk -F'\t' '$2 ~ /^bluez_input/  {print $2; exit}'; }
mic_for_profile() {
  case "$1" in
    "$A2DP") pactl list sources short | awk -F'\t' '$1 ~ /^[0-9]+$/ && $2 ~ /^alsa_input/ {print $2; exit}' ;;
    *) pactl list sources short | awk -F'\t' '$1 ~ /^[0-9]+$/ && $2 ~ /bluez_input/ {print $2; exit}' ;;
  esac
}
swap_listener() {
  src="$1"
  [ -n "$src" ] || return 0
  tmux respawn-pane -k -t "$LISTENER" \
    "HUD_SOURCE='$src' '$here/start-listener.sh' '$TARGET'" >/dev/null 2>&1 || true
}
dest=org.mpris.MediaPlayer2.spotify
obj=/org/mpris/MediaPlayer2
player=org.mpris.MediaPlayer2.Player

spotify_playing() {
  status=$(gdbus call --session --dest "$dest" --object-path "$obj" \
    --method org.freedesktop.DBus.Properties.Get "$player" PlaybackStatus 2>/dev/null)
  case "$status" in *Playing*) return 0 ;; *) return 1 ;; esac
}

watch() {
  exec 9>"$HOME/.local/share/hud-listen/music-watch.lock"
  flock -n 9 || exit 0  # one watcher only
  local last=""
  while [ -e "$FLAG" ]; do
    local want=""
    if spotify_playing; then want="$A2DP"; else want="$CALL"; fi
    if [ "$want" != "$last" ]; then
      # Flip only on a state change — repeated set-card-profile calls
      # renegotiate the Bluetooth transport and make the music glitch.
      pactl set-card-profile "$CARD" "$want" >/dev/null 2>&1
      sleep 1
      if [ "$want" = "$A2DP" ]; then
        # Route can go stale across a transport switch.
        pactl set-default-sink "$(bt_sink)" >/dev/null 2>&1
      else
        # Mic back: make sure the capture route follows.
        pactl set-default-source "$(bt_source)" >/dev/null 2>&1
      fi
      last="$want"
      # Dictation keeps working in music mode: ride the laptop mic while the
      # headset is in A2DP, back to the headset mic when the call profile
      # returns (each respawn = a fresh whisper load, fine at music stops).
      swap_listener "$(mic_for_profile "$want")"
    fi
    sleep 3
  done
  pactl set-card-profile "$CARD" "$CALL" >/dev/null 2>&1
}

case "${1:-}" in
  on)
    touch "$FLAG"
    HUD_CARD="$CARD" nohup "$0" watch >/dev/null 2>&1 &
    echo ok
    ;;
  off)
    rm -f "$FLAG"
    pactl set-card-profile "$CARD" "$CALL" >/dev/null 2>&1
    pactl set-default-source "$(bt_source)" >/dev/null 2>&1
    swap_listener "$(mic_for_profile "$CALL")"
    echo off
    ;;
  watch)
    watch
    ;;
  *) echo "usage: music-mode.sh on|off|watch" >&2; exit 2 ;;
esac
