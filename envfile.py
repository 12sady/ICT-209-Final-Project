"""
envfile.py
----------
Reads AI settings (and any other KEY=VALUE lines) from a `.env` file next to
app.py, so they don't have to be typed into the terminal every time. Works the
same on Windows and Mac. No extra package needed.

  - `.env` is git-ignored: the real key never gets uploaded. `.env.example`
    shows the format and is safe to share.
  - A setting already in the environment (typed in the terminal, or saved with
    setx) wins over the file.
  - Blank lines and lines starting with # are ignored; "export KEY=..." and
    quoted values ("..." or '...') are accepted, so ai-key.sh lines work too.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def parse(text):
    out = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")          # Windows Notepad may add a BOM
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or not key.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load(path=None):
    """Put .env settings into os.environ (without overriding ones already set).
    Returns the names that were loaded (never the values)."""
    path = path or os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as f:
            values = parse(f.read())
    except (FileNotFoundError, UnicodeDecodeError):
        return []
    loaded = []
    for key, value in values.items():
        if key not in os.environ and value:
            os.environ[key] = value
            loaded.append(key)
    return loaded
