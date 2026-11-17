# bridge

A voice-controlled orchestrator for Claude Code in tmux. You talk to one Claude Code session. It runs the other agents.

The listener is always on. It transcribes everything it hears, in Hindi, English and Hinglish, into a daily transcript file. Every 3 hours the orchestrator starts a summarizer that turns the transcript into action items in your daily note. It runs as a systemd user service, keeps the machine awake and restarts after a crash. There is no app to open and no button to press.

Voice processing is local. Speech-to-text (faster-whisper and AI4Bharat IndicConformer) and spoken replies (Piper) run on the machine. No audio is uploaded, and the listener works offline. Only transcript text reaches Claude, when the 3-hourly summarizer reads it.

This repository contains the listener, the voice, instructions for the orchestrator session, and a script that closes idle agents.

```
  you
   │  speak (local whisper)  or  type
   ▼
┌──────────────────────────────┐
│ tmux window "orchestrator"   │  one Claude Code session
│  routes work, checks it,     │
│  asks you only for decisions │
└──────┬───────────┬───────────┘
       │ send-keys │ capture-pane
       ▼           ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│ agent     │ │ agent     │ │ agent     │  one Claude session per window
└─────┬─────┘ └─────┬─────┘ └─────┬─────┘
      └──── results ┴─────────────┘
                    │
                    ▼
        orchestrator reviews them, returns
        incomplete work, then reports:
        "Bug fixed and tested. Merge it?"
              (spoken by hud-say, local Piper TTS)
```

## What it does

- **One point of contact.** The orchestrator assigns work, opens agent windows as needed and writes each agent a brief.
- **Review.** Work with skipped tests or a partial diagnosis goes back to the agent. You only see the result.
- **Decisions, one line each.** Which agent, what it needs, what to answer.
- **Speech.** Short spoken updates, so you don't need to watch the screen.
- **Cleanup.** Finished agents are closed. An idle Claude session holds a few hundred MB, so leaving a dozen open can push a 16 GB machine into swap.
- **Local, always listening, Hindi + English.** About 1.5 s of CPU per 5 s sentence on a 2019 laptop CPU. Audio never leaves the machine. See [Transcription](#transcription-hindi--english).
- **Action items, every 3 hours.** Into `# Tasks` of the daily note. See [Voice digest](#voice-digest).

## Requirements

- Linux with PipeWire or PulseAudio (`pactl`, `parec`, `paplay`)
- tmux, Python 3, curl
- [Claude Code](https://claude.com/claude-code)
- Optional: `gdbus` and Spotify, to pause music during speech
- Optional: systemd user services, for the session reaper

Tested on Fedora 44. Not tested on a clean machine. Not tested on macOS.

## Setup

```bash
git clone https://github.com/pankajgarkoti/bridge ~/bridge
cd ~/bridge && ./setup.sh
```

`setup.sh` checks the required tools, creates a venv in `~/.local/share/hud-listen/venv`, downloads the voice (about 63 MB) and the speech models (whisper base.en and base, about 150 MB each, and IndicConformer Hindi, about 190 MB, pinned and checksummed), installs `hud-say`, `voice-digest-run` and `voice-digest-nudge` to `~/.local/bin`, and installs the systemd user units. The listener then starts with `HF_HUB_OFFLINE=1`, so it makes no network requests at start-up.

```bash
systemctl --user enable --now hud-listen.service voice-digest.timer
```

Optional: close Claude sessions idle for an hour.

```bash
optional/tmux-reap/tmux-reap-stale --dry-run   # list what it would close
optional/tmux-reap/install.sh                  # every 10 minutes, via a systemd user timer
```

Optional: keep everything running through a logout or desktop crash.

```bash
optional/keep-tmux/install.sh
```

By default the tmux server belongs to the terminal that started it. When the desktop session ends, every agent ends with it. `tmux-keep` starts the server in its own systemd user scope instead, so agents survive a logout or a window-manager switch. Run `loginctl enable-linger $USER` once to survive a full logout. `tmux-keep --adopt` moves an already-running server, and everything in it, into the scope without restarting anything.

## Start it

1. Start a named tmux session: `tmux new -s work`, or `tmux-keep work` if installed.
2. Rename the first window `orchestrator` and start Claude in it:

   ```bash
   tmux rename-window orchestrator
   claude
   ```

   Then send: `Read ~/bridge/ORCHESTRATOR.md and act as my orchestrator.`

3. The listener runs as the `hud-listen` user service (above) and writes transcripts; it does not type into the orchestrator. For the old dictation behaviour, where every utterance is typed into the orchestrator, start it by hand instead:

   ```bash
   tmux new-window -n hud-listen
   HUD_TYPE_TO_ORCH=1 ~/bridge/start-listener.sh '=work:=orchestrator'
   ```

   The target is an exact session and window name; the `=` signs disable tmux's fuzzy matching. Pane IDs are not used, because panes move. If the name does not match exactly one pane, the listener stops.

   Claude may decline to start the listener itself, since that means an agent connecting a microphone to its own input. Start it by hand.

4. Speak. The text appears in `~/.local/state/voice/transcripts/<date>.md` (and in the orchestrator as `[voice] ...` with `HUD_TYPE_TO_ORCH=1`).

Typing into the orchestrator also works. Voice is optional.

## Check each part

```bash
hud-say "Testing the voice"                 # should be audible
pactl list sources short                    # microphones; the built-in one is preferred
tail -f ~/.local/share/hud-listen/heard.log # what the listener heard or ignored, with language and timing
tail -f ~/.local/state/voice/transcripts/$(date +%F).md   # today's transcript
systemctl --user list-timers voice-digest.timer           # next digest
```

## Settings

Environment variables for the listener (a drop-in in `~/.config/systemd/user/hud-listen.service.d/`, or exported before `start-listener.sh`):

| Variable | Default | What it does |
|---|---|---|
| `HUD_SOURCE` | built-in laptop mic | Which microphone, from `pactl list sources short` |
| `HUD_STT` | `hybrid` | `hybrid` = language ID, then English or Hindi model. `en` = base.en only (the old English-only setup) |
| `HUD_MODEL` | `base.en` | Whisper model for English. `small.en` is more accurate but took about 3.6 s per 3 s clip on a 2019 laptop CPU |
| `HUD_LID_MODEL` | `base` | Multilingual whisper model used only for language ID |
| `HUD_HI_MODEL` | `~/.local/share/hud-listen/models/indicconformer-hi` | IndicConformer folder (`model.int8.onnx`, `tokens.txt`) |
| `HUD_THREADS` | `4` | CPU threads per model |
| `HUD_TRANSCRIPTS` | `~/.local/state/voice/transcripts` | Where transcripts go |
| `HUD_TYPE_TO_ORCH` | `0` | `1` = also type each utterance into the orchestrator (needs `HUD_TARGET`) |
| `HUD_TARGET` | none | Exact tmux target, e.g. `=work:=orchestrator`; only with `HUD_TYPE_TO_ORCH=1` |
| `HF_HUB_OFFLINE` | `1` | Set `0` to allow downloading a model not yet fetched |

The laptop microphone is the default on purpose. A Bluetooth headset using its microphone switches to a call profile, which degrades music to phone quality. With the laptop microphone, the headset stays in stereo.

Removed after testing:

- **A hotword list.** With a list of names to listen for, whisper heard those names in fan noise and typed them into the orchestrator.
- **Larger beams.** `beam_size` 2 with 4 CPU threads gave the best speed for the accuracy. Larger values only added latency.

The silence cut-off (`END_SILENCE_S`), the loudness threshold (`220` in `loud = ...`), the piece length (`PIECE_MAX_S`) and the English confidence floor (`EN_MIN_P`) are at the top of `listen.py`.

## Transcription (Hindi + English)

```
mic ─▶ energy gate ─▶ Silero VAD ─▶ split at pauses (≤12 s) ─▶ whisper base: language ID
                       (drops fans,                               ├─ en ─▶ faster-whisper base.en
                        clicks, silence)                          └─ hi / ur / unsure ─▶ IndicConformer (sherpa-onnx int8)
                                                                        ▼
                         ~/.local/state/voice/transcripts/YYYY-MM-DD.jsonl  + .md   (IST timestamps)
```

Each piece gets its own language ID, so one person speaking Hindi and then another speaking English come out as two lines, each in the right model, provided there is a pause between them (a few hundred ms). English language ID below 0.5 goes to IndicConformer, because base.en invents text on unclear audio and IndicConformer doesn't.

A `.jsonl` line: `{"ts": "2026-11-14T16:55:46+05:30", "dur": 4.1, "lang": "hi", "lid_p": 1.0, "text": "परसों सुबह नौ बजे सुरेश को फ़ोन करके तीन हज़ार रुपए भेजने हैं"}`. `lang` is `en`, `hi`, or `hi?` (unsure English sent to the Hindi model).

**Why this setup.** Benchmarked 14 Nov 2026 on this laptop (i5-8365U, 4 cores / 8 threads, no GPU) with 9 clips (3 Hindi, 3 English, 3 Hinglish), clean and with room noise at 12 dB SNR. Test audio was made with local Piper voices (Hindi and English), so real speech will score worse. WER is word error rate, lower is better; RTF is processing time ÷ audio length, below 1 is faster than real time.

| Model | Hindi WER | Hinglish WER | English WER | RTF | RAM |
|---|---|---|---|---|---|
| **Hybrid: whisper base LID → base.en / IndicConformer** | **0.03** | **0.05** | **0.00** | **0.32** | 875 MB |
| IndicConformer alone (hi, int8) | 0.03 | 0.05 | 1.93 (English written in Devanagari) | 0.18 | 360 MB |
| faster-whisper large-v3-turbo, int8, 8 threads | 0.09 | 0.05 | 0.00 | 7.5 | ~2 GB |
| faster-whisper medium, int8 | 0.09 | 0.21 | 0.00 | 8.4 | 2.1 GB |
| faster-whisper small, int8 | 0.23 | 0.36 | 0.00 | 1.6 | 815 MB |
| faster-whisper base.en (old setup) | 0.99 | 0.85 | 0.00 | 0.36 | 500 MB |

- Language ID (whisper base, en vs hi+ur) routed all 18 clips correctly, Hinglish to Hindi.
- Large-v3-turbo and medium are as accurate on Hinglish but 20–40× slower; they can't keep up with continuous speech on this CPU.
- NVIDIA Parakeet: `parakeet-tdt-0.6b-v3` and `canary-1b-v2` cover 25 European languages, not Hindi. No official NVIDIA Hindi Parakeet exists; the community Hinglish fine-tune is a 2.4 GB NeMo checkpoint with no published results, not tested.
- `shunyalabs/zero-stt-hinglish` (a Hinglish whisper-medium fine-tune) would have medium's speed, too slow here.
- Cloud STT (e.g. Sarvam) was ruled out: audio stays on the device.

**CPU and cost.** About 1.2 CPU-core-seconds per second of speech (≈ 15% of the machine while someone is talking, near 0 in silence). One hour of continuous speech costs about 1.2 core-hours. No per-hour fee; nothing is sent anywhere.

## Voice digest

`voice-digest.timer` fires at 00, 03, 06, 09, 12, 15, 18 and 21 IST and runs `voice-digest-nudge`. If anything was transcribed since the last digest (`~/.local/state/voice/last-digest`; first run: the last 3 hours), it types one line into the tmux window `orchestrator` and emits the same line on `orch-bus`:

```
[voice-digest] Summarize voice transcripts 2026-11-14T15:00+05:30–2026-11-14T18:00+05:30: ~/.local/state/voice/transcripts/2026-11-14.jsonl. Spawn a summarizer instance.
```

If nothing was heard, it moves `last-digest` forward and doesn't wake the orchestrator. The orchestrator (see `ORCHESTRATOR.md`) runs the summarizer in its own window:

```bash
voice-digest-run 2026-11-14T15:00+05:30 2026-11-14T18:00+05:30
```

It sends the transcript slice to `claude -p` (no tools), which returns action items only: Hindi summarized in English, names and numbers exact, noise, TV and background chatter skipped. The script, not Claude, then adds them to `~/Desktop/notes/Journal/<YYYY>/<MM>/<YYYY-MM-DD>.md` (created from `templates/daily.md` if missing), at the end of `# Tasks`:

```
## From voice (15:00–18:00)
- [ ] Call Suresh day after tomorrow at 9 AM and send him 3000 rupees (said 16:55)
```

Nothing else in the note is touched. With no real action items it writes nothing. On success it updates `last-digest` and emits `voice-digest done: ...`. A second copy running at the same time exits, and a block whose heading is already in the note isn't added again. `VOICE_DIGEST_MODEL` picks the Claude model; `VOICE_DIGEST_NOTES` the notes folder.

## Before you use it

- **It records everything it hears.** Calls, visitors and TV end up in the transcript files, as text, under `~/.local/state/voice/transcripts`. Stop the listener (`systemctl --user stop hud-listen`) when that isn't wanted, and delete what shouldn't be kept.
- **With `HUD_TYPE_TO_ORCH=1` it acts on what it hears.** There is no wake word. A video, a podcast or a nearby conversation arrives as an instruction. `ORCHESTRATOR.md` tells it to treat garbled speech as noise and to read back anything hard to undo, but that is a prompt, not a lock.
- **Avoid `--dangerously-skip-permissions` on the orchestrator.** An always-on microphone plus agents that never ask permission means any speech in the room can become an unchecked command.
- **Agents can act on your desktop.** The instructions forbid synthetic keystrokes, test windows on the live screen, and probing real devices. Each rule exists because something went wrong without it. Keep them in every brief.
- **Check that new agents started.** Claude asks "Do you trust this folder?" the first time it opens a folder, and an agent can sit on that prompt unnoticed. The orchestrator checks each one about 10 seconds after launch.
- **Sessions can outlive a restart.** Two voices means an older orchestrator is still running. `hud-say` queues speech so voices do not overlap, but both copies still act.

## Cost

It consumes Claude usage. Each time the orchestrator wakes, for a monitor event, a voice message or an agent report, it re-reads the whole conversation. Monitors firing every few minutes can exhaust a weekly limit in a couple of days. To reduce it: no standing monitors unless needed, close finished agents (the reaper does this), and keep check-ins infrequent.

## Related

[MAGI](https://github.com/pankajgarkoti/magi), a Hyprland desktop for Fedora, was built with this setup.

## Files

| File | What it is |
|---|---|
| `ORCHESTRATOR.md` | Instructions for the orchestrator session |
| `setup.sh` | Installs the listener, voice and model |
| `start-listener.sh` | Runs the listener, restarts it after a crash, keeps the machine awake |
| `listen.py` | Microphone → speech detection → language ID → Hindi/English STT → transcript files |
| `voice-digest` | `voice-digest-nudge` (timer) and `voice-digest-run` (summarizer → daily note), by name |
| `systemd/` | `hud-listen.service`, `voice-digest.service`, `voice-digest.timer` |
| `hud-say` | Pauses Spotify, speaks, resumes |
| `music-ctl.sh` | Play, pause, skip and volume for Spotify over MPRIS, for voice commands |
| `music-mode.sh` | Optional: keep music in full quality and dictate on the laptop microphone |
| `optional/tmux-reap/` | Optional: closes idle Claude sessions on a timer, logging how to resume each |
| `optional/keep-tmux/` | Optional: runs the tmux server in its own systemd scope so agents survive logouts and desktop crashes |
