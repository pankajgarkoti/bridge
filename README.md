# bridge

A voice-controlled orchestrator for Claude Code in tmux. You talk to one Claude Code session. It runs the other agents.

The listener is always on. It runs in its own tmux window, keeps the machine awake and restarts after a crash. With `tmux-keep`, it also survives a logout. There is no app to open and no button to press.

Voice processing is local. Speech-to-text (faster-whisper) and spoken replies (Piper) run on the machine. No audio is uploaded, and the listener works offline. Only the transcribed text reaches Claude, the same as typed input.

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
- **Local, always listening.** Transcription uses faster-whisper base.en, about one second per sentence on a 2019 laptop CPU. Audio never leaves the machine.

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

`setup.sh` checks the required tools, creates a venv in `~/.local/share/hud-listen/venv`, downloads the voice (about 63 MB) and the speech model (about 150 MB), and installs `hud-say` to `~/.local/bin`. The listener then starts with `HF_HUB_OFFLINE=1`, so it makes no network requests at start-up.

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

3. Open a window called `hud-listen` and start the listener:

   ```bash
   tmux new-window -n hud-listen
   ~/bridge/start-listener.sh '=work:=orchestrator'
   ```

   The target is an exact session and window name; the `=` signs disable tmux's fuzzy matching. Pane IDs are not used, because panes move. If the name does not match exactly one pane, the listener stops.

   Claude may decline to start the listener itself, since that means an agent connecting a microphone to its own input. Start it by hand.

4. Speak. The text appears in the orchestrator as `[voice] ...`.

Typing into the orchestrator also works. Voice is optional.

## Check each part

```bash
hud-say "Testing the voice"                 # should be audible
pactl list sources short                    # microphones; the built-in one is preferred
tail -f ~/.local/share/hud-listen/heard.log # what the listener heard or ignored
```

## Settings

Environment variables for `start-listener.sh`:

| Variable | Default | What it does |
|---|---|---|
| `HUD_SOURCE` | built-in laptop mic | Which microphone, from `pactl list sources short` |
| `HUD_MODEL` | `base.en` | Whisper model. `small.en` is more accurate but took about 3.6 s per 3 s clip on a 2019 laptop CPU |
| `HF_HUB_OFFLINE` | `1` | Set `0` to allow downloading a model not yet fetched |

The laptop microphone is the default on purpose. A Bluetooth headset using its microphone switches to a call profile, which degrades music to phone quality. With the laptop microphone, the headset stays in stereo.

Removed after testing:

- **A hotword list.** With a list of names to listen for, whisper heard those names in fan noise and typed them into the orchestrator.
- **Larger beams.** `beam_size` 2 with 4 CPU threads gave the best speed for the accuracy. Larger values only added latency.

The silence cut-off (`END_SILENCE_S`) and loudness threshold (`220` in `loud = ...`) are at the top of `listen.py`.

## Before you use it

- **It acts on what it hears.** There is no wake word. A video, a podcast or a nearby conversation arrives as an instruction. `ORCHESTRATOR.md` tells it to treat garbled speech as noise and to read back anything hard to undo, but that is a prompt, not a lock. Stop the listener during calls or media.
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
| `listen.py` | Microphone → speech detection → whisper → the orchestrator pane |
| `hud-say` | Pauses Spotify, speaks, resumes |
| `music-ctl.sh` | Play, pause, skip and volume for Spotify over MPRIS, for voice commands |
| `music-mode.sh` | Optional: keep music in full quality and dictate on the laptop microphone |
| `optional/tmux-reap/` | Optional: closes idle Claude sessions on a timer, logging how to resume each |
| `optional/keep-tmux/` | Optional: runs the tmux server in its own systemd scope so agents survive logouts and desktop crashes |
