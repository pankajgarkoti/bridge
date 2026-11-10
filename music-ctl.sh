#!/usr/bin/env bash
# Control the music from the orchestrator (voice commands land here).
#   music-ctl.sh play|pause|toggle|next|prev
#   music-ctl.sh volume        -> prints current level (0-100)
#   music-ctl.sh volume N      -> sets the player volume to N percent
#   music-ctl.sh status        -> one line: state · artist — title · volume
set -u
dest=org.mpris.MediaPlayer2.spotify
obj=/org/mpris/MediaPlayer2
player=org.mpris.MediaPlayer2.Player
call() { gdbus call --session --dest "$dest" --object-path "$obj" --method "$@" 2>/dev/null; }
getq() { call "org.freedesktop.DBus.Properties.Get" "$player" "$1"; }
cmd="${1:-status}"

parse_meta() { # parse_meta <raw metadata string> -> artist line, title line
python3 - "$1" <<'PY'
import re, sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
def g(key):
    m = re.search(rf"'{key}': <(.+?)>,?\s*(?:'mpris|'xesam|\}})", raw) or \
        re.search(rf"'{key}': <(.+?)>", raw)
    if not m: return "?"
    v = m.group(1)
    v = v.replace("[", "'").replace("]", "'").strip(", '")
    return v.strip("' ") or "?"
print(g("xesam:artist"))
print(g("xesam:title"))
PY
}

volume_now() {
python3 <<'PY'
import re, sys, subprocess
raw = subprocess.run(["gdbus","call","--session","--dest","org.mpris.MediaPlayer2.spotify",
  "--object-path","/org/mpris/MediaPlayer2",
  "--method","org.freedesktop.DBus.Properties.Get","org.mpris.MediaPlayer2.Player","Volume"],
  capture_output=True, text=True).stdout
m = re.search(r"([0-9]*\.?[0-9]+)", raw or "")
print(int(round((float(m.group(1)) if m else 0)*100)))
PY
}

case "$cmd" in
  play)  call "$player.Play" >/dev/null ;;
  pause) call "$player.Pause" >/dev/null ;;
  toggle)
      st=$(getq PlaybackStatus)
      case "$st" in *Playing*) exec "$0" pause ;; *) exec "$0" play ;; esac
      ;;
  next)  call "$player.Next" >/dev/null ;;
  prev)  call "$player.Previous" >/dev/null ;;
  volume)
      if [ -n "${2:-}" ]; then
        case "$2" in [0-9]|[1-9][0-9]|100)
          call "org.freedesktop.DBus.Properties.Set" "$player" Volume "<double $(awk "BEGIN{print $2/100}")>" >/dev/null
        ;; esac
      fi
      printf 'volume %d%%\n' "$(volume_now)"
      ;;
  status)
      st=$(getq PlaybackStatus | sed -E 's/.*(Playing|Paused).*/\1/;t;d')
      artist=$(parse_meta "$(getq Metadata)" | head -1)
      title=$(parse_meta "$(getq Metadata)" | tail -1)
      printf '%s · %s — %s · volume %d%%\n' "${st:-stopped}" "$artist" "$title" "$(volume_now)"
      ;;
esac
