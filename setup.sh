#!/usr/bin/env bash
# Installs the listener and voice. Safe to run again.
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

mkdir -p "$home_dir/voices" "$HOME/.local/bin"
cp "$here/listen.py" "$home_dir/listen.py"
install -m 755 "$here/hud-say" "$HOME/.local/bin/hud-say"

[ -d "$home_dir/venv" ] || python3 -m venv "$home_dir/venv"
"$home_dir/venv/bin/pip" install -q --upgrade pip
"$home_dir/venv/bin/pip" install -q numpy faster-whisper piper-tts

for f in "$voice.onnx" "$voice.onnx.json"; do
  [ -s "$home_dir/voices/$f" ] || curl -fsSL -o "$home_dir/voices/$f" "$voice_url/$f"
done

# Fetch the speech model now, so the listener can always start with HF_HUB_OFFLINE=1.
model="${HUD_MODEL:-base.en}"
echo "Fetching the $model speech model (about 150 MB for base.en)..."
HF_HUB_OFFLINE=0 "$home_dir/venv/bin/python" -c \
  "import sys; from faster_whisper import WhisperModel; WhisperModel(sys.argv[1], device='cpu', compute_type='int8')" "$model"

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Add ~/.local/bin to your PATH so agents can run hud-say." ;;
esac

echo "Done. Test the voice with: hud-say \"Testing the voice\""
echo "Then follow 'Start it' in the README."
echo "Optional: optional/tmux-reap/install.sh closes idle agent sessions automatically."
