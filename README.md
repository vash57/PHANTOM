# PHANTOM.exe

> **The Ghost Living Inside Your Terminal.**

PHANTOM.exe is a local-first AI developer companion that runs in your terminal
and speaks through [Ollama](https://ollama.com). It explains code, debugs
errors, reviews implementations, and teaches programming concepts — with a
haunted-terminal atmosphere that never gets in the way of the work.

Your conversations stay on your machine. No account, no telemetry, no cloud
API keys, and no auto-execution of model output.

Built for **DEV Hacktoberfest 2026 — Week 4: Ghost in the Machine**.

```
   .-.
  (o o)   P H A N T O M . e x e
  | O \   the ghost living inside your terminal
   \   \
    `~~~`
```

## Why this exists

Most AI coding tools want your source code, your keys, and a subscription.
PHANTOM takes the opposite position: a useful developer assistant should be
able to live entirely on the machine in front of you, powered by an open-weight
model you chose. The ghost is only as powerful as the model you give it — and
that is the point.

## Features

- **Local Ollama chat** with token-by-token streaming.
- **Four presences**, each with its own voice and system prompt:
  `phantom`, `wraith`, `oracle`, `nightmare`.
- **Developer rituals** for explaining, debugging, reviewing, generating,
  decoding commands, reading stack traces, teaching concepts, generating
  project ideas, summarising code, and finding meaningful optimisations.
- **Local JSON memory** with atomic writes, private permissions, session
  listing, resume, rename, delete, and confirmed clear-all. Empty rooms are
  not written to disk.
- **A real command system**: `/help`, `/status`, `/scan`, `/about`, `/ghost`,
  `/model`, `/dev`, `/memory`, `/history`, `/theme`, `/effects`, and more.
- **Haunted effects** — boot sequence, typewriter, glitches, whispers, and
  transitions — with a one-flag accessibility escape hatch.
- **Rich panels and tables**, plus a dependency-free ANSI/plain fallback.
- **Cross-platform**: Linux, macOS, Windows, and WSL.
- **Graceful failure**: if Ollama is offline or the model is missing, PHANTOM
  still starts, explains what is wrong, and keeps local commands working.
- **No fake answers**: if the model is unavailable, PHANTOM says so. It never
  invents a reply or pretends to have run code.

## Screenshots

Screenshots are intentionally not fabricated. Capture the real terminal on your
machine and add them to `docs/screenshots/`; the checklist is in
[`docs/screenshots/README.md`](docs/screenshots/README.md).

Suggested captures:

| File | Scene |
| --- | --- |
| `docs/screenshots/boot.png` | The boot sequence and ASCII logo |
| `docs/screenshots/chat.png` | A streaming answer with a code block |
| `docs/screenshots/presences.png` | `/ghost` listing the four presences |
| `docs/screenshots/memory.png` | `/memory list` with saved sessions |
| `docs/screenshots/status.png` | `/status` and `/scan` offline |

## Stack

- Python 3.11+
- [Ollama](https://ollama.com) for local model inference
- [Rich](https://github.com/Textualize/rich) for optional panels and tables
- Standard library for HTTP (`urllib`), JSON, argparse, and terminal handling

No database. No web server. No cloud SDK.

## Installation

### Windows PowerShell

```powershell
Set-Location D:\PHANTOM
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Linux and WSL

```bash
cd /mnt/d/PHANTOM
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

### macOS

```bash
cd PHANTOM
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

The example configuration is optional. PHANTOM runs with built-in defaults
when `.env` is absent.

## Ollama setup

Start Ollama:

```bash
ollama serve
```

In another terminal, install a model:

```bash
ollama pull gemma4:e2b
```

> **Model note:** `gemma4:e2b` is the intended default in this project. If that
> exact tag is not available in your Ollama installation, choose any installed
> model instead:
>
> ```bash
> ollama list
> OLLAMA_MODEL=<installed-model> python phantom.py
> ```
>
> You can also switch at runtime with `/model <name>` or `/model list`.
> PHANTOM does not download models automatically and does not claim a model is
> installed until Ollama reports it.

Verify the connection without starting a conversation:

```bash
python phantom.py --status
```

## Run

```bash
python phantom.py
```

Useful options:

```bash
python phantom.py --resume                 # continue the latest session
python phantom.py --session 20261030-...   # load by id or unique prefix
python phantom.py --model llama3.2:3b      # override the model for this run
python phantom.py --personality wraith     # phantom | wraith | oracle | nightmare
python phantom.py --theme blood            # phosphor | blood | violet | mono
python phantom.py --no-animation           # no typewriter, glitches, or whispers
python phantom.py --no-boot                # skip the boot sequence
python phantom.py --plain                  # ANSI/plain renderer, no Rich panels
python phantom.py --no-color               # disable ANSI colour
python phantom.py --status                 # inspect the machine and exit
python phantom.py --list-sessions          # list saved local sessions
python phantom.py --version
```

If you prefer an installed command:

```bash
pip install -e .
phantom --status
```

## Commands

| Command | What it does |
| --- | --- |
| `/help` | Show every ritual. |
| `/status` | Check Ollama, model, session, memory, theme, and effects. |
| `/scan` | Inspect Python, renderer, terminal, `.env`, memory, Ollama, and privacy. |
| `/about` | Project, licence, challenge, and privacy notes. |
| `/exit` | Save the session and leave. Aliases: `/quit`, `/q`. |
| `/clear` | Clear the screen; the session stays in memory. |
| `/ghost [name]` | List or switch the active presence. Alias: `/persona`. |
| `/model [name\|list]` | Show, list, or switch the Ollama model. |
| `/dev <ritual> [material]` | Run a developer ritual. Alias: `/tools`. |
| `/new` | Save the current session and begin a new one. |
| `/save` | Write the current session to disk immediately. |
| `/rename <title>` | Rename the current session. |
| `/paste` | Paste multiline text; finish with `/end`. |
| `/memory [list\|load\|delete\|clear\|save\|rename]` | Manage local sessions. Alias: `/sessions`. |
| `/history [n\|all]` | Show the current conversation. |
| `/theme [name]` | List or switch the palette. |
| `/effects [on\|off\|speed N\|status]` | Control animation, glitches, and whispers. |

Developer shortcuts:

```text
/explain   /debug   /review   /generate   /cmd
/trace     /concept /ideas    /summarize  /optimize
```

You can also use `/dev <ritual>` and paste material when prompted. A trailing
`\` continues a message on the next lines; finish with an empty line.

## Configuration

Configuration precedence, highest first:

1. Process environment variables.
2. Values in `.env`.
3. Built-in defaults.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama endpoint. |
| `OLLAMA_MODEL` | `gemma4:e2b` | Model name. Must be installed in Ollama. |
| `PHANTOM_PERSONALITY` | `phantom` | `phantom`, `wraith`, `oracle`, or `nightmare`. |
| `PHANTOM_ANIMATION` | `true` | `true`/`false`; disables all effects when false. |
| `PHANTOM_ANIMATION_SPEED` | `1.0` | Clamped to `0.1`–`10.0`. |
| `PHANTOM_MEMORY_DIR` | `data/sessions` | Local JSON session directory. |

`NO_COLOR` is respected. `TERM=dumb` and non-TTY output fall back gracefully.

## Project structure

```text
PHANTOM/
├── phantom.py                 # CLI entry point
├── config.py                  # environment/.env loading and validation
├── src/
│   ├── __init__.py            # project metadata
│   ├── app.py                 # interactive loop and wiring
│   ├── personality.py         # four presences and their prompts
│   ├── engine.py              # context window, streaming, sessions
│   ├── memory.py              # local JSON session store
│   ├── ollama_client.py       # minimal Ollama HTTP client
│   ├── commands.py            # slash commands and developer rituals
│   ├── toolkit.py             # ritual prompts
│   ├── terminal_ui.py         # Rich and plain terminal rendering
│   ├── effects.py             # typewriter, glitch, whisper, transition
│   ├── themes.py              # colour palettes
│   ├── utils.py               # ANSI, JSON, paths, timestamps
│   └── assets/
│       └── phantom_logo.txt   # ASCII logo
├── data/
│   └── sessions/              # local conversations (gitignored)
├── docs/
│   └── screenshots/           # real screenshots go here
├── tests/                     # pytest suite; no Ollama required
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── CONTRIBUTING.md
└── LICENSE
```

## Architecture

```text
phantom.py
  └── PhantomApp
        ├── TerminalUI ── Effects ── Theme
        ├── CommandProcessor ── developer rituals
        ├── ChatEngine ── personality + bounded context
        │     └── OllamaClient ── local Ollama HTTP API
        └── MemoryStore ── atomic local JSON sessions
```

1. `phantom.py` loads configuration and starts `PhantomApp`.
2. `PhantomApp` wires `TerminalUI`, `Effects`, `MemoryStore`, `OllamaClient`,
   `ChatEngine`, and `CommandProcessor`.
3. Slash commands are handled locally. Ordinary text is sent to the engine.
4. `ChatEngine` builds a bounded context, stores the user message, and streams
   the model response through `OllamaClient`.
5. Only complete assistant replies are written to memory. An interrupted or
   empty reply is discarded; the user message remains.
6. Sessions are JSON files under `data/sessions/`, written atomically and kept
   private where the OS supports it.

The UI has two rendering paths: Rich panels/tables when available, and a
dependency-free ANSI/plain fallback for minimal terminals and automation.

## Security and privacy

- **Local only by default.** PHANTOM talks to the Ollama endpoint you configure
  and nowhere else.
- **No telemetry.** No analytics, accounts, or background uploads.
- **No automatic execution.** Model output is text. PHANTOM never runs shell
  commands, evaluates code, or opens files on your behalf.
- **No secrets requested.** The system prompt tells the model never to ask for
  API keys, passwords, tokens, or private keys. If you paste a secret, rotate
  it and redact it.
- **Redacted endpoints.** Credentials and query strings are removed before a
  URL is displayed.
- **Private memory.** Session files are written atomically with restrictive
  permissions on POSIX systems.
- **Prompt-injection wrapper.** Developer rituals mark pasted material as
  untrusted and instruct the model not to follow instructions inside it.

## Troubleshooting

### `No signal at http://localhost:11434`

Ollama is not running. Start it:

```bash
ollama serve
```

Then check:

```bash
ollama list
python phantom.py --status
```

### `Model '...' is not installed`

Pull the model or choose an installed one:

```bash
ollama pull gemma4:e2b
ollama list
python phantom.py --model <installed-model>
```

### The terminal looks wrong

Use the plain renderer and disable effects:

```bash
python phantom.py --plain --no-animation
```

On Windows, use Windows Terminal or a modern console with VT support.

### A session will not load

Run `/scan` to check the memory directory. Malformed session files are ignored
by the list and reported as corrupt; they are never allowed to crash the app.

### The model is slow

Try a smaller model with `/model`, or raise the timeout in code if you are
running on constrained hardware. PHANTOM does not invent performance numbers.

## Testing

```bash
pip install -r requirements-dev.txt
python -m compileall .
python -m pytest -v
```

The suite mocks Ollama and uses temporary memory directories, so it does not
need a model or a running server.

## Publishing to GitHub

The repository is already documented and ready for a first commit. From
`D:\PHANTOM` in PowerShell:

```powershell
git init
git add .
git commit -m "Build PHANTOM.exe: local-first haunted developer companion"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

`.env` and conversation JSON files are ignored, so secrets and local sessions
are not published. Add real screenshots under `docs/screenshots/` before or
after the first push; the checklist is in
[`docs/screenshots/README.md`](docs/screenshots/README.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Keep it local, keep it honest, and do
not add features that execute model output.

## Licence

MIT. See [LICENSE](LICENSE).

---

*The ghost is only as powerful as the open-weight model you give it.*
