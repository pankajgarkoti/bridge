#!/usr/bin/env bash
# Installs the listener (Hindi + English transcription), the voice and the 3-hourly voice digest. Safe to run again.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
home_dir="$HOME/.local/share/hud-listen"
voice=en_US-hfc_female-medium
voice_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium"

missing=()
for tool in tmux python3 pactl parec paplay curl; do
  command -v "$tool" >/dev/null || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "Missing: ${missing[*]}. Install them, then run this again." >&2
  exit 1
fi
command -v gdbus >/dev/null || echo "Note: gdbus not found, so music won't pause during speech."

mkdir -p "$home_dir/voices" "$home_dir/models/indicconformer-hi" "$HOME/.local/bin" "$HOME/.local/state/voice/transcripts"
cp "$here/listen.py" "$home_dir/listen.py"
install -m 755 "$here/hud-say" "$HOME/.local/bin/hud-say"
install -m 755 "$here/voice-digest" "$HOME/.local/bin/voice-digest"
ln -sf voice-digest "$HOME/.local/bin/voice-digest-run"
ln -sf voice-digest "$HOME/.local/bin/voice-digest-nudge"

[ -d "$home_dir/venv" ] || python3 -m venv "$home_dir/venv"
"$home_dir/venv/bin/pip" install -q --upgrade pip
"$home_dir/venv/bin/pip" install -q numpy faster-whisper piper-tts sherpa-onnx

for f in "$voice.onnx" "$voice.onnx.json"; do
  [ -s "$home_dir/voices/$f" ] || curl -fsSL -o "$home_dir/voices/$f" "$voice_url/$f"
done

# Fetch the speech models now, so the listener can always start with HF_HUB_OFFLINE=1:
# base.en (English), base (language ID only), about 150 MB each.
for model in "${HUD_MODEL:-base.en}" "${HUD_LID_MODEL:-base}"; do
  echo "Fetching the $model whisper model..."
  HF_HUB_OFFLINE=0 "$home_dir/venv/bin/python" -c \
    "import sys; from faster_whisper import WhisperModel; WhisperModel(sys.argv[1], device='cpu', compute_type='int8')" "$model"
done

# Hindi / Hinglish: AI4Bharat IndicConformer (MIT), sherpa-onnx int8 export, about 190 MB.
# Pinned to a revision and checked, because it is a community conversion.
hi_dir="$home_dir/models/indicconformer-hi"
hi_url="https://huggingface.co/meetsync/indic-conformer-onnx-sherpa/resolve/e19ba0d2f49c243fe4ce79ae3334526a03e753ae"
for f in model.int8.onnx tokens.txt; do
  [ -s "$hi_dir/$f" ] || { echo "Fetching IndicConformer $f..."; curl -fsSL -o "$hi_dir/$f" "$hi_url/$f"; }
done
( cd "$hi_dir" && sha256sum -c --quiet - <<'SUMS'
b99a01834cd1a72cd9be682a0b9543df6b152ef7dfceba88d3dbf59fbb77075d  model.int8.onnx
743aeb755c4489bc734a6705578552b072ffb45055aeeb5db19ae7761a424882  tokens.txt
SUMS
) || { echo "IndicConformer checksum mismatch; delete $hi_dir and run again." >&2; exit 1; }

# systemd user units: the listener and the 3-hourly digest timer (enable them yourself).
if command -v systemctl >/dev/null; then
  mkdir -p "$HOME/.config/systemd/user"
  cp "$here"/systemd/{hud-listen.service,voice-digest.service,voice-digest.timer} "$HOME/.config/systemd/user/"
  systemctl --user daemon-reload
  echo "Units installed. Start with: systemctl --user enable --now hud-listen.service voice-digest.timer"
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Add ~/.local/bin to your PATH so agents can run hud-say." ;;
esac

echo "Done. Test the voice with: hud-say \"Testing the voice\""
echo "Then follow 'Start it' in the README."
echo "Optional: optional/tmux-reap/install.sh closes idle agent sessions automatically."
