# Bundled font

One WOFF2 file ships inside the bundle so numerals, paths and log lines render
identically with no network and regardless of what the machine has installed
(ADR-0001). UI text itself uses the Windows system faces named in
`design.css` (Segoe UI Variable / Microsoft YaHei UI), so nothing else ships.

| File | Source face | Used for |
|---|---|---|
| `llama-mono.woff2` | Cascadia Code | values, paths, log lines, counters |

The file is a subset: `charset.txt` lists the characters collected from the
design layer's string table, the field metadata, the shell fallback table and
Rust's i18n/field/copy tables. Anything outside that set — a service name in
an unusual script, a path with CJK, a preset the user names — falls through to
the system family named after the bundled one in `design.css`.

Regenerate after changing any copy:

```powershell
python frontend/scripts/subset-fonts.py
```

Requires `pip install fonttools brotli`. The generated file is committed, so a
normal `npm run build` needs neither.

License: SIL Open Font License 1.1 — full text in `OFL.txt`.
