#!/usr/bin/env python3
"""Always-on local transcription: mic -> speech detection -> language ID -> STT -> transcript file.

Hindi, English and Hinglish. Everything runs on this machine; no audio or text leaves it.

  speech gate (energy, then Silero VAD)
    -> whisper `base` language ID (en vs hi/ur)
    -> English:          faster-whisper base.en
    -> Hindi / Hinglish: AI4Bharat IndicConformer (sherpa-onnx, int8)
    -> ~/.local/state/voice/transcripts/YYYY-MM-DD.jsonl  (+ a readable .md)

Typing each utterance into the tmux window "orchestrator" (the old behaviour) is off by
default; set HUD_TYPE_TO_ORCH=1 and HUD_TARGET to turn it back on.
"""
import os

# Models are fetched once by setup.sh; after that, never touch the network on start-up.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import json
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

HOME = os.path.expanduser("~/.local/share/hud-listen")
IST = ZoneInfo("Asia/Kolkata")
OUT_DIR = os.path.expanduser(os.environ.get("HUD_TRANSCRIPTS", "~/.local/state/voice/transcripts"))
TYPE_TO_ORCH = os.environ.get("HUD_TYPE_TO_ORCH", "0") == "1"
# Exact session and window name, never a pane id or number: those go stale when panes move.
TARGET = os.environ.get("HUD_TARGET", "")  # e.g. =work:=orchestrator; only used with HUD_TYPE_TO_ORCH=1
STT = os.environ.get("HUD_STT", "hybrid")  # hybrid (en+hi) | en (base.en only, the old behaviour)
EN_MODEL = os.environ.get("HUD_MODEL", "base.en")
LID_MODEL = os.environ.get("HUD_LID_MODEL", "base")
HI_MODEL_DIR = os.environ.get("HUD_HI_MODEL", f"{HOME}/models/indicconformer-hi")
THREADS = int(os.environ.get("HUD_THREADS", "4"))
LOCK = f"/run/user/{os.getuid()}/hud-speaking"
LOG = f"{HOME}/heard.log"
RATE = 16000
FRAME = int(RATE * 0.03)
END_SILENCE_S = 1.0
MIN_SPEECH_S = 0.6
MAX_SPEECH_S = 30
MIN_VAD_SPEECH_S = 0.5  # Silero must find at least this much speech, or the piece is dropped
EN_MIN_P = 0.5  # English language-ID below this goes to the Hindi model instead (see Recognizer)
PIECE_MAX_S = 12 # continuous talk is split at pauses into pieces this long, each with its own language ID
# No hotword / initial_prompt list: biasing whisper toward names made it "hear" those
# names in plain room noise. beam_size 2 was the best speed/accuracy trade-off here.
JUNK = {"", "you", "thank you", "thanks", "bye", "okay", "ok", "hmm", "mm", "uh", "um",
        "धन्यवाद", "हम्म", "हाँ", "हां", "अं"}


def log(msg):
    line = f"{datetime.now(IST):%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def fail(msg):
    log(f"ERROR: {msg}. Listener stopped.")
    sys.exit(2)


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


# ---------- speech to text ----------
class Recognizer:
    def __init__(self):
        try:
            self.en = WhisperModel(EN_MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS)
            self.lid = self.hi = None
            if STT == "hybrid":
                import sherpa_onnx
                self.lid = WhisperModel(LID_MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS)
                self.hi = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                    model=f"{HI_MODEL_DIR}/model.int8.onnx", tokens=f"{HI_MODEL_DIR}/tokens.txt", num_threads=THREADS)
        except Exception as e:
            fail(f"could not load models offline ({e}); run setup.sh, or start once with HF_HUB_OFFLINE=0")

    def language(self, audio):
        """'en' or 'hi'. Urdu counts as Hindi: same spoken language, whisper often confuses them."""
        if self.lid is None:
            return "en", 1.0
        _, _, probs = self.lid.detect_language(audio)
        p = dict(probs)
        hi, en = p.get("hi", 0) + p.get("ur", 0), p.get("en", 0)
        return ("hi", hi) if hi > en else ("en", en)

    def english(self, audio):
        segments, _ = self.en.transcribe(
            audio, language="en", beam_size=2, vad_filter=False, condition_on_previous_text=False,
            no_speech_threshold=0.5, log_prob_threshold=-1.0)
        kept = [s.text.strip() for s in segments if s.no_speech_prob < 0.5 and s.avg_logprob > -1.0]
        return " ".join(kept).strip()

    def hindi(self, audio):
        s = self.hi.create_stream()
        s.accept_waveform(RATE, audio)
        self.hi.decode_stream(s)
        return s.result.text.strip()

    def __call__(self, audio):
        lang, p = self.language(audio)
        # Unsure English (most probability on neither en nor hi) is usually Hindi talk or noise, and
        # base.en hallucinates on it ("that's you, that's you"). IndicConformer doesn't; English
        # comes out of it phonetically in Devanagari, which is still readable.
        if lang == "en" and p < EN_MIN_P and self.hi is not None:
            lang = "hi?"
        text = self.english(audio) if lang == "en" else self.hindi(audio)
        return lang, p, text


def split_long(audio, s, e, max_s):
    """Cut a stretch longer than max_s at its quietest 100 ms between 40% and 100% of max_s."""
    out = []
    win = RATE // 10
    while (e - s) / RATE > max_s:
        lo, hi = s + int(0.4 * max_s * RATE), s + int(max_s * RATE)
        frames = audio[lo:hi][: (hi - lo) // win * win].reshape(-1, win)
        cut = lo + int(np.argmin((frames ** 2).mean(axis=1))) * win + win // 2
        out.append((s, cut))
        s = cut
    return out + [(s, e)]


def speech_pieces(audio, max_s=PIECE_MAX_S, min_lid_s=2.0, gap_s=0.8):
    """Silero VAD (bundled with faster-whisper) over one gated chunk. Drops fans, clicks and taps
    the energy gate let through, and splits continuous talk at every pause (>= 200 ms) into pieces
    of at most max_s, so each piece gets its own language ID (one speaker in Hindi, then someone in
    English). A piece shorter than min_lid_s absorbs the next one: too short for a reliable language ID."""
    ts = get_speech_timestamps(audio, VadOptions(threshold=0.5, min_silence_duration_ms=200, speech_pad_ms=100))
    merged = []
    for t in ts:
        s, e = t["start"], t["end"]
        if (merged and (merged[-1][1] - merged[-1][0]) / RATE < min_lid_s
                and (s - merged[-1][1]) / RATE <= gap_s and (e - merged[-1][0]) / RATE <= max_s):
            merged[-1][1] = e
        else:
            merged.append([s, e])
    pieces = [p for s, e in merged for p in split_long(audio, s, e, max_s)]
    return [(s, e) for s, e in pieces if (e - s) / RATE >= MIN_VAD_SPEECH_S]


def speech_seconds(audio):
    return sum(e - s for s, e in speech_pieces(audio)) / RATE


# ---------- output ----------
def append_transcript(start, dur, lang, p, text):
    os.makedirs(OUT_DIR, exist_ok=True)
    day = start.strftime("%Y-%m-%d")
    rec = {"ts": start.isoformat(timespec="seconds"), "dur": round(dur, 1), "lang": lang, "lid_p": round(p, 2), "text": text}
    with open(f"{OUT_DIR}/{day}.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    md = f"{OUT_DIR}/{day}.md"
    new = not os.path.exists(md)
    with open(md, "a") as f:
        if new:
            f.write(f"# Voice transcript {day} (IST)\n\n")
        f.write(f"- **{start:%H:%M:%S}** `{lang}` {text}\n")


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


# ---------- worker: transcribes off the mic thread so the mic never stalls ----------
def worker(rec, jobs):
    while True:
        start, pcm = jobs.get()
        chunk = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        for s, e in speech_pieces(chunk):
            audio = chunk[s:e]
            dur = len(audio) / RATE
            t0 = time.time()
            lang, p, text = rec(audio)
            took = time.time() - t0
            if text.lower().strip(" .,!?।") in JUNK or len(text.split()) < 2:
                log(f"ignored [{lang}]: {text!r}")
                continue
            log(f"heard [{lang} {p:.2f}] ({dur:.1f}s audio, {took:.1f}s): {text}")
            append_transcript(start + timedelta(seconds=s / RATE), dur, lang, p, text)
            if TYPE_TO_ORCH:
                deliver(text)


def main():
    if TYPE_TO_ORCH:
        resolve_target()
    log(f"loading models (stt={STT}, en={EN_MODEL}" + (f", lid={LID_MODEL}, hi={HI_MODEL_DIR})" if STT == "hybrid" else ")"))
    rec = Recognizer()
    jobs = queue.Queue(maxsize=20)
    threading.Thread(target=worker, args=(rec, jobs), daemon=True).start()
    proc = subprocess.Popen(
        ["parec", f"--device={SOURCE}", "--format=s16le", f"--rate={RATE}", "--channels=1", "--raw", "--latency-msec=60"],
        stdout=subprocess.PIPE,
    )
    log(f"listening on {SOURCE}, writing to {OUT_DIR}" + (f", typing into {TARGET}" if TYPE_TO_ORCH else ""))
    floor = 300.0
    buf = bytearray()
    pre = []
    in_speech = False
    voiced = silent = start_run = 0
    started = None
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
                started = datetime.now(IST)
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
            try:
                jobs.put_nowait((started, pcm))
            except queue.Full:
                log("transcriber is behind; dropped an utterance")


if __name__ == "__main__":
    main()
