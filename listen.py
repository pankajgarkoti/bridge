#!/usr/bin/env python3
"""Always-on local dictation: mic -> speech detection -> whisper -> the tmux window named "orchestrator".
Audio stays on this machine. Stop it by closing the tmux window it runs in."""
import os

# The model is fetched once by setup.sh; after that, never touch the network on start-up.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import subprocess
import sys
import time
from datetime import datetime

import numpy as np
from faster_whisper import WhisperModel

# Exact session and window name, never a pane id or number: those go stale when panes move.
TARGET = os.environ.get("HUD_TARGET", "")  # e.g. =work:=orchestrator; start-listener.sh sets it
MODEL = os.environ.get("HUD_MODEL", "base.en")  # small.en is more accurate but ~3.6s per 3s clip on a laptop CPU
LOCK = f"/run/user/{os.getuid()}/hud-speaking"
LOG = os.path.expanduser("~/.local/share/hud-listen/heard.log")
RATE = 16000
FRAME = int(RATE * 0.03)
END_SILENCE_S = 1.4
MIN_SPEECH_S = 0.6
MAX_SPEECH_S = 30
# No hotword / initial_prompt list: biasing whisper toward names made it "hear" those
# names in plain room noise. beam_size 2 and 4 CPU threads were the best speed/accuracy
# trade-off when benchmarked on a laptop CPU.
JUNK = {"", "you", "thank you", "thanks", "bye", "okay", "ok", "hmm", "mm", "uh", "um"}


def log(msg):
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def transcribe(model, pcm):
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(
        audio, language="en", beam_size=2, vad_filter=False, condition_on_previous_text=False,
        no_speech_threshold=0.5, log_prob_threshold=-1.0,
    )
    kept = [s.text.strip() for s in segments if s.no_speech_prob < 0.5 and s.avg_logprob > -1.0]
    return " ".join(kept).strip()


def laptop_mic():
    """Default mic: the built-in (ALSA) one, so a Bluetooth headset can stay in
    high-quality A2DP mode. Falls back to the system default source."""
    out = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) > 1 and cols[1].startswith("alsa_input"):
            return cols[1]
    return subprocess.check_output(["pactl", "get-default-source"], text=True).strip()


SOURCE = os.environ.get("HUD_SOURCE") or laptop_mic()


def fail(msg):
    log(f"ERROR: {msg}. Dictation stopped.")
    sys.exit(2)


def resolve_target():
    """Return the pane id for TARGET, or stop. Never falls back to another pane or window.

    Uses list-panes because `display-message -t` silently falls back to the current pane
    when the target doesn't exist. The `:=` requires an exact window name, and tmux rejects
    a name shared by several windows.
    """
    if ":=" not in TARGET:
        fail(f"HUD_TARGET {TARGET!r} must be an exact name like =work:=orchestrator")
    found = subprocess.run(["tmux", "list-panes", "-t", TARGET, "-F", "#{pane_id}"], capture_output=True, text=True)
    panes = found.stdout.split()
    if found.returncode != 0:
        fail(f"tmux target {TARGET!r} not found or not unique: {found.stderr.strip()}")
    if len(panes) != 1:
        fail(f"tmux target {TARGET!r} has {len(panes)} panes, expected 1: {' '.join(panes)}")
    return panes[0]


def deliver(text):
    pane = resolve_target()
    try:
        subprocess.run(["tmux", "send-keys", "-t", pane, "-l", f"[voice] {text}"], check=True)
        time.sleep(0.4)
        subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=True)
    except subprocess.CalledProcessError as e:
        fail(f"could not send to {pane} ({TARGET!r}): {e}")


def main():
    pane = resolve_target()
    log(f"loading {MODEL}")
    try:
        model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=4)
    except Exception as e:
        fail(f"could not load {MODEL} offline ({e}); run setup.sh, or start once with HF_HUB_OFFLINE=0")
    proc = subprocess.Popen(
        ["parec", f"--device={SOURCE}", "--format=s16le", f"--rate={RATE}", "--channels=1", "--raw", "--latency-msec=60"],
        stdout=subprocess.PIPE,
    )
    log(f"listening on {SOURCE}, sending to {TARGET} ({pane})")
    floor = 300.0
    buf = bytearray()
    pre = []
    in_speech = False
    voiced = silent = start_run = 0
    while True:
        chunk = proc.stdout.read(FRAME * 2)
        if not chunk:
            log("mic stream ended")
            sys.exit(1)
        # Don't hear ourselves: drop everything while hud-say is talking.
        if os.path.exists(LOCK):
            buf.clear()
            pre.clear()
            in_speech = False
            voiced = silent = start_run = 0
            continue
        rms = float(np.sqrt(np.mean(np.frombuffer(chunk, dtype=np.int16).astype(np.float32) ** 2)))
        loud = rms > max(floor * 2.0, 220)
        if not in_speech:
            floor = floor * 0.995 + min(rms, floor * 2) * 0.005
            pre = (pre + [chunk])[-15:]
            start_run = start_run + 1 if loud else 0
            if start_run >= 5:
                in_speech = True
                buf = bytearray(b"".join(pre))
                voiced = start_run
                silent = 0
            continue
        buf += chunk
        if loud:
            voiced += 1
            silent = 0
        else:
            silent += 1
        secs = len(buf) / 2 / RATE
        if silent * 0.03 >= END_SILENCE_S or secs >= MAX_SPEECH_S:
            in_speech = False
            start_run = 0
            pcm = bytes(buf)
            buf.clear()
            pre.clear()
            if voiced * 0.03 < MIN_SPEECH_S:
                continue
            text = transcribe(model, pcm)
            if text.lower().strip(" .,!?") in JUNK or len(text.split()) < 2:
                log(f"ignored: {text!r}")
                continue
            log(f"heard: {text}")
            deliver(text)


if __name__ == "__main__":
    main()
