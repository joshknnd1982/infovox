# Infovox 230 for NVDA — v0.3

Brings the classic **Infovox 230** (Telia Promotor / Babel-Infovox, 2002) SAPI 4
speech synthesizer to **NVDA 2026.1** on 64-bit Windows 11, with all 60 voices
across 12 languages.

NVDA 2026.1 is 64-bit and cannot load a 32-bit SAPI 4 engine in-process, which
is why these voices went silent. This add-on bridges that gap with a bundled
32-bit host process that runs the engine and streams audio back to NVDA.

## Install

1. Download `infovox230-0.3.nvda-addon` below.
2. Open it (or NVDA menu → Tools → Add-on store → Install from external source).
3. Restart NVDA when prompted.
4. NVDA menu → Preferences → Settings → Speech → set **Synthesizer** to
   **Infovox 230 (Telia Promotor)**.

Nothing else is required: no dongle, no separate SAPI 4 runtime, no registry
changes, no administrator rights, and no separate Python install.

## What's fixed in this release

**Speech no longer crashes NVDA's language filter.** Voices whose Windows LANGID
the driver couldn't map were exposed to NVDA with a `None` language. NVDA 2026.1
calls `normalizeLanguage()` on every entry in a synthesizer's language list
without a null check, so a single unmapped voice raised
`AttributeError: 'NoneType' object has no attribute 'replace'` on *every*
utterance once automatic language switching was on. LANGID mapping is now robust
(neutral sublanguages and bare primary languages both resolve), unknown languages
are never published to NVDA, and the driver's own `languageIsSupported()` can no
longer raise into the speech filter.

**The volume slider works.** It previously did nothing at any setting. In SAPI 4
the engine hands loudness to the *audio device*, and this add-on's device is a
capture sink — which stored the level and ignored it. Volume is now applied to
the captured audio itself: 0% is true silence, 100% is the engine's full-scale
output, linear in between. Inline engine volume changes compose correctly on top.

**No more going silent after a few minutes.** The host handed the engine a new
COM notification sink for every utterance, and the engine never released them
(confirmed from logs: 16 created, 0 released, live object count climbing). After
a few minutes of normal speech the engine's internal tables filled and it went
quiet while still accepting calls — which is why switching synthesizer away and
back was the only cure, and why it kept coming back. The sink is now created once
per voice and reused. On top of that, the add-on now self-heals: a dead, wedged,
or unresponsive host is restarted automatically with your voice and rate/pitch/
volume restored, and NVDA is always released so say-all can't stall. A second,
independent hang was fixed too — the host's output pipe was never drained after
startup, so once it filled the host would block mid-utterance forever.

**The Windows registry is no longer touched.** The engine insists on reading its
configuration from `HKCU\Software\Babel-Infovox AB\Infovox 230`, and earlier
versions satisfied that by writing five paths plus all 60 voice-mode keys into
your real registry on every start, leaving them behind. The host now loads a
private hive **file** inside the add-on with `RegLoadAppKey` and points only its
own process's `HKEY_CURRENT_USER` at it with `RegOverridePredefKey`. The engine's
registry reads land in that file; your registry is never read or written, and the
redirection vanishes when the host exits. Keys left by earlier versions are
removed automatically on first run — and a genuine Infovox installation elsewhere
on the machine is detected and left alone.

## Notes

- Requires NVDA 2026.1 or later (64-bit).
- Removing the add-on now removes every trace of it.
- Source, architecture notes and reverse-engineering write-up:
  https://github.com/joshknnd1982/infovox
