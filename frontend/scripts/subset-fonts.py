#!/usr/bin/env python3
"""Build the bundled font subset (ADR-0001: no remote fonts, nothing fetched).

The app ships one WOFF2 file under ``frontend/src/assets/fonts``:

  llama-mono.woff2  Cascadia Code — values, paths, log lines, counters

UI text uses the Windows system faces (Segoe UI Variable / Microsoft YaHei UI)
named in ``design.css``; only the mono face is bundled, so numerals render
identically offline. It is cut down to the characters the interface can show.
The character set is collected from every file that carries user-visible copy:

  * the design layer's own string table and the field metadata;
  * the shell's fallback table;
  * Rust's i18n table, field labels and command copy.

Anything outside the subset (a service name in an unusual script, a path with
CJK in it, a preset the user names themselves) falls back to the system font
through the CSS stack, which is why the bundled family is listed *first* and
the system families are still named as fallbacks.

Regenerate after changing any copy:

    python frontend/scripts/subset-fonts.py

Requires: ``pip install fonttools brotli``. The generated files are committed so
the normal build needs neither.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "src" / "assets" / "fonts"

# Every file whose text can end up on screen. The Rust half is every source
# file: the strings live in i18n.rs / fields.rs / copy.rs, but status lines and
# updater sentences also sit in params/service/updater/update_files, and a
# missing glyph renders as tofu — so the scan is deliberately greedy.
SOURCES = [
    ROOT / "frontend" / "src" / "design" / "copy.js",
    ROOT / "frontend" / "src" / "api" / "field-copy.js",
    ROOT / "frontend" / "src" / "api" / "shell-copy.js",
] + sorted(
    p
    for p in (ROOT / "src-tauri").rglob("*.rs")
    if "target" not in p.parts
)

# Punctuation and symbols that show up in dynamic text (paths, unit suffixes,
# the separators the shell draws), even when no copy file spells them out.
EXTRA = "…—–·•「」『』（）【】《》〈〉、。，：；！？“”‘’％＃＠＆℃±×÷≈≤≥→←↑↓●○■□◆◇★☆▪▸⌘⇧⌥⌃⤢⋯✕✓⚠"

# The one bundled face, and the family name the stylesheet asks for.
FACES = [
    {
        "source": Path(r"C:\Windows\Fonts\CascadiaCode.ttf"),
        "out": "llama-mono.woff2",
        "features": "ccmp,locl,kern,liga,calt,zero,ss01,ss02",
    },
]


def charset() -> str:
    chars = {chr(c) for c in range(0x20, 0x7F)}  # printable ASCII, always
    chars.update(EXTRA)
    for path in SOURCES:
        if not path.exists():
            raise SystemExit(f"missing copy source: {path}")
        chars.update(ch for ch in path.read_text(encoding="utf-8") if ord(ch) > 0x7E)
    # No control characters, and drop the ones that would confuse a text file.
    chars.discard("\n")
    chars.discard("\t")
    return "".join(sorted(chars))


def subset(chars_file: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for face in FACES:
        if not face["source"].exists():
            raise SystemExit(f"missing font: {face['source']}")
        target = OUT / face["out"]
        cmd = [
            sys.executable,
            "-m",
            "fontTools.subset",
            str(face["source"]),
            f"--text-file={chars_file}",
            f"--output-file={target}",
            "--flavor=woff2",
            f"--layout-features={face['features']}",
            "--name-IDs=1,2,3,4,5,6",
            "--notdef-outline",
            "--recalc-bounds",
            "--drop-tables+=DSIG",
        ]
        print("+", " ".join(cmd[3:]))
        subprocess.run(cmd, check=True)
        print(f"  {face['out']}: {target.stat().st_size / 1024:.1f} KB")


def main() -> None:
    text = charset()
    OUT.mkdir(parents=True, exist_ok=True)
    chars_file = OUT / "charset.txt"
    chars_file.write_text(text, encoding="utf-8")
    print(f"charset: {len(text)} characters")
    subset(chars_file)
    print("done — commit the .woff2 files, charset.txt is the receipt")


if __name__ == "__main__":
    main()
