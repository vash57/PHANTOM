# Contributing to PHANTOM.exe

Thanks for helping the ghost learn a few more tricks. This project is small on
purpose: the terminal is the interface, Ollama is the brain, and every other
piece should stay understandable in one sitting.

## Ground rules

- Keep the project local-first. Do not add telemetry, accounts, cloud API keys,
  or silent network calls.
- Never execute AI output. Commands in this project must not run shell
  commands on the user's behalf.
- Do not add fake AI responses, fake command output, or invented benchmark
  numbers.
- Preserve the offline experience. `/help`, `/status`, `/scan`, `/memory`,
  `/theme`, `/ghost`, and `/effects` must work without Ollama.
- Prefer the standard library. Ask before adding a runtime dependency.
- Keep accessibility working: `--no-animation`, `--plain`, `--no-color`,
  `NO_COLOR`, and non-TTY output must remain usable.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Run the terminal:

```bash
python phantom.py --no-animation
```

## Tests

```bash
python -m pytest
```

The test suite must pass without an Ollama server. Use fake HTTP responses and
temporary memory directories. Do not require a model download in tests.

## Style

- Python 3.11+, `from __future__ import annotations` where useful.
- Type hints for public functions and dataclasses for structured data.
- No comments that merely restate the code. Explain *why* when it matters.
- Keep terminal output concise, readable, and safe for narrow terminals.
- No shell execution, no `eval`, no `pickle`, no secrets in logs.

## Adding a personality

1. Add a prompt and a `Personality` entry in `src/personality.py`.
2. Give it a distinct greeting, farewell, glyph, and UI style.
3. Add it to the tests in `tests/test_personality.py`.
4. Check that `/ghost <name>` works and that the shared safety contract still
   applies.

## Adding a developer ritual

1. Add a `Tool` entry in `src/toolkit.py`.
2. Add an alias only if it is genuinely obvious.
3. Keep the instruction focused and the prompt-injection wrapper intact.
4. Add a test in `tests/test_toolkit.py`.

## Reporting a security issue

Do not open a public issue for a vulnerability. Describe the problem to the
maintainers privately and include a minimal reproduction. Please do not include
real credentials or private conversation data.
