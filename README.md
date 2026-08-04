# Infovox 230 → NVDA 2026.1 add-on

Reviving the long-abandoned **Infovox 230** text-to-speech engine (Telia
Promotor / Babel-Infovox, both defunct; the engine is public domain) as a
**self-contained synthesizer add-on for the NVDA screen reader** — **60 voices
across 12 languages**, with no hardware dongle, no CrypKey, no 16-bit license
manager, and no administrator rights required.

Languages: American & British English, German, French, Italian, Castilian
Spanish, Dutch, Danish, Norwegian, Swedish, Finnish, Icelandic — each with five
formant voices (Male, Female, Giant, Child, Zombie).

## Download & install

Grab the ready-to-install `infovox230-0.1.nvda-addon` from the
[**Releases**](../../releases) page, then in NVDA: **Tools → Add-on Store →
Install from external source**, and restart when prompted. Full instructions are
in [`nvda-infovox230/README.md`](nvda-infovox230/README.md).

## How it works

NVDA is 64-bit and cannot load the 32-bit Infovox SAPI4 engine in-process, which
is why these voices went silent. The add-on bridges that gap: the 64-bit NVDA
driver launches a bundled 32-bit host that hosts the engine and streams audio +
index marks back over a localhost socket. The engine binary is patched to run
free of its original dongle and license manager. The full reverse-engineering
write-up — including the exact binary patch offsets — is in
[`nvda-infovox230/ARCHITECTURE.md`](nvda-infovox230/ARCHITECTURE.md).

## Repository layout

- **`nvda-infovox230/`** — the add-on and its complete source: the NVDA driver,
  the 32-bit host, the bundled engine and rule sets, the 32-bit Python runtime,
  the Sx32w dongle-emulator stub, build/test tooling, `ARCHITECTURE.md`, and the
  built `infovox230-0.1.nvda-addon`.
- **Top-level files** — the original **Infovox 230 v2.2 installer**
  (`Infovox230v2_2complete.exe`), its extracted contents (`data1/`, `data2/`,
  the `*.IVX` rule sets, the original `*.exe` tools), and runtime DLLs. These are
  preserved for reproducibility so the patches can be re-derived from the
  originals. The same installer is also mirrored on the Internet Archive.

## Licensing

Mixed — see [`LICENSE`](LICENSE) for details. In short: the add-on code is
GPLv2; the Infovox engine, rule sets, and voice data are public domain and
included with permission; and the third-party components inside the original
installer (Microsoft runtimes, CrypKey, InstallShield) remain under their own
licenses and are included only as original installer materials.

## Credits

Original engine and voices by Telia Promotor / Babel-Infovox AB (defunct).
Revival, 64↔32-bit bridge, and NVDA add-on by the repository maintainer.
