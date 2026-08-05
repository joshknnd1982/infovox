# Building the Infovox 230 add-on from source

## What you need

- **Windows** — the engine and the 32-bit host are Windows binaries.
- **NVDA 2026.1 or newer (64-bit)** to install and test.
- **Python 3** to run the build script. You do **not** need a separate 32-bit
  Python: a 32-bit Python with `comtypes` is bundled inside the add-on.

## Where things live

All buildable source is under `nvda-infovox230/`:

- `addon/` — everything that goes into the `.nvda-addon`; this whole folder is
  zipped, with `manifest.ini` at its root.
- `addon/synthDrivers/infovox230.py` — the **64-bit NVDA driver** (runs inside
  NVDA).
- `host/infovox_host.py` — the **32-bit host** that loads the SAPI4 engine. This
  is the canonical copy; the build copies it into
  `addon/synthDrivers/infovox230/host/` for you so the two never drift.
- `sx32w_stub/` — the dongle-emulator stub source.
- `tools/` — bring-up and test scripts.
- `ARCHITECTURE.md` — how the bridge works and the exact engine binary patches.

## Build

From the `nvda-infovox230/` directory:

```
cd nvda-infovox230
python build.py
```

This re-syncs the bundled host and produces `infovox230-<version>.nvda-addon`,
where `<version>` is read from `addon/manifest.ini`.

## Install and test

1. In NVDA: **Tools → Add-on Store → Install from external source**, choose the
   `.nvda-addon`, and restart NVDA.
2. **Preferences → Settings → Speech**, set **Synthesizer** to Infovox 230 and
   pick a voice.
3. Smoke test: read some text, run a say-all (NVDA+Down Arrow), arrow across a
   capital letter, and switch between a couple of voices and languages.

## About the engine binary

The bundled `Ivx230nt.dll` is already patched to run without the original
hardware dongle and license manager (offsets are documented in
`ARCHITECTURE.md`) — you normally never touch it. If you ever need to re-derive
the patches from a clean original, the source installer
(`Infovox230v2_2complete.exe`) is preserved at the repo root and is also mirrored
on the Internet Archive.

## Releasing a new version

1. Bump `version` in `addon/manifest.ini` (and `lastTestedNVDAVersion` if you
   tested against a newer NVDA).
2. `python build.py`.
3. Create a GitHub release and attach the new `.nvda-addon`, e.g.
   `gh release create vX.Y "nvda-infovox230/infovox230-X.Y.nvda-addon" --title "..." --notes "..."`.
