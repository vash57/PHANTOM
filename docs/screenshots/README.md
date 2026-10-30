# Screenshots

This directory is reserved for real terminal captures. The project does not
ship fabricated screenshots or mocked benchmark output.

Capture these on your own machine after the app is running:

| File | What to show |
| --- | --- |
| `boot.png` | The boot sequence and the large PHANTOM ASCII logo. |
| `chat.png` | A streamed answer that includes a fenced code block. |
| `presences.png` | The `/ghost` table with all four presences. |
| `memory.png` | `/memory list` with at least two saved sessions. |
| `status.png` | `/status` and `/scan` with Ollama offline and local rituals working. |

Suggested capture flow:

```bash
python phantom.py
```

Then run `/ghost`, `/memory list`, `/status`, and `/scan`, and take a terminal
screenshot for each. Use a dark terminal profile; the default palette is
Phosphor (deep black, phosphor green, purple accent).

Keep images reasonably small (under 2 MB) and avoid showing personal paths,
tokens, or private conversation content.
