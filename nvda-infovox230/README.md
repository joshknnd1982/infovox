# Infovox 230 → NVDA 2026.1 add-on

Brings the long-abandoned **Infovox 230** text-to-speech engine (Telia Promotor
/ Babel-Infovox, both defunct; the engine is public domain) back to life as a
**self-contained synthesizer add-on for NVDA 2026.1** — **60 voices across 12
languages**, no hardware dongle, no CrypKey, no 16-bit license manager, and **no
administrator rights** required.

Languages: American & British English, German, French, Italian, Castilian
Spanish, Dutch, Danish, Norwegian, Swedish, Finnish, Icelandic — each with five
formant voices (Male, Female, Giant, Child, Zombie).

## Install

1. In NVDA: **NVDA menu → Tools → Add-on Store → Install from external source**,
   and choose `infovox230-0.1.nvda-addon`.
2. Restart NVDA when prompted.
3. **NVDA menu → Preferences → Settings → Speech**, set **Synthesizer** to
   **Infovox 230 (Telia Promotor)**, then pick a voice and adjust rate / pitch /
   volume.

The first time you select the synthesizer it builds its voice table and starts
the engine — this takes a few seconds once; afterwards it is immediate. No UAC
prompt appears.

**Nothing is written to the Windows registry.** The engine insists on reading
its configuration from `HKCU\Software\Babel-Infovox AB\Infovox 230`, so the host
loads a private hive file (`infovox230.hive`, inside the add-on folder) with
`RegLoadAppKey` and points *its own process's* `HKEY_CURRENT_USER` at it with
`RegOverridePredefKey`. The engine's registry reads land in that file; your real
registry is never read or written, and the redirection disappears when the host
process exits. Removing the add-on folder removes every trace. Keys written by
earlier versions of this add-on are deleted automatically on first run.

## How it works

NVDA 2026.1 is 64-bit and cannot load the 32-bit Infovox SAPI4 engine in-process
— which is exactly why every SAPI4 voice went silent in 2026.1. The add-on
bridges that gap:

```
 NVDA 2026.1 (64-bit)                          bundled host (32-bit Python)
 ┌───────────────────────────┐   127.0.0.1 TCP  ┌────────────────────────────┐
 │ synthDrivers/infovox230.py │ ───────────────► │ host/infovox_host.py       │
 │  • lists 60 voices         │  control frames  │  • voice table→private hive│
 │  • builds tagged text      │                  │  • LoadLibrary Ivx230nt.dll│
 │  • nvwave.WavePlayer        │ ◄─────────────── │  • ITTSCentral.TextData     │
 │  • fires index / done       │  PCM + marks     │  • captures PCM (IAudioDest)│
 └───────────────────────────┘                  └────────────────────────────┘
```

Everything is bundled inside the add-on: the engine and its 12 rule sets, a
32-bit Python with `comtypes`, the host, the 64-bit driver, and a tiny emulated
`Sx32w.dll`. See `ARCHITECTURE.md` for the full reverse-engineering write-up.

## Licensing defeated + engine fixes (all in `Ivx230nt.dll`)

The engine ran on Windows 95/98/XP only and was gated by a Rainbow Sentinel
SuperPro **hardware dongle** + CrypKey, with a 16-bit license manager that will
not run on Windows 11. Four minimal, surgical binary patches (documented in
`ARCHITECTURE.md`, and reproducible from the originals) make it run free and
self-contained on Windows 11:

| Offset | What | Fix |
|--------|------|-----|
| `0x15b50` | Rainbow SuperPro dongle check | always report authorized |
| `0x0a4c9` | `GetUlexInstance` treats missing user lexicon as fatal | make it non-fatal (lexicon is optional) |
| `0x09dec` | `Init` rejects mode unless licence-type 1/2/3 | accept and proceed |
| 10 sites | engine reads config/voices/lexicon from `HKLM` | read per-user `HKCU` (no admin), which the host then redirects into a private hive file so the real registry is untouched |

The voice definitions themselves come from the engine's own trial installer,
which does run on Windows 11 and supplied the correct speaker/formant data.

## Folder contents

```
nvda-infovox230/
  infovox230-0.1.nvda-addon      the installable add-on  ← install this
  README.md                      this file
  ARCHITECTURE.md                how it works + reverse-engineering notes
  addon/                         the add-on source tree (engine, host, driver, python32, modes.json)
  host/                          host + SAPI4 interface source (mirrors addon/…/host)
  sx32w_stub/                    the dongle emulator + its generator
  tools/                         diagnostics + the test harnesses used to bring it up
  _run/                          proof WAVs and logs from bring-up (first_speech.wav, all_voices.wav, …)
```

## Status

Working end to end: the engine loads on Windows 11, all 60 voices enumerate and
synthesize (verified as clean 16 kHz speech), the licensing is fully bypassed,
and the 64↔32-bit bridge is validated over the exact protocol NVDA uses. The
only step that runs on your machine is installing the `.nvda-addon` and choosing
the synthesizer.
