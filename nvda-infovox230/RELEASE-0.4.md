# Infovox 230 for NVDA — v0.4

Brings the classic **Infovox 230** (Telia Promotor / Babel-Infovox, 2002) SAPI 4
speech synthesizer to **NVDA 2026.1** on 64-bit Windows 11, with all 60 voices
across 12 languages.

NVDA 2026.1 is 64-bit and cannot load a 32-bit SAPI 4 engine in-process, which
is why these voices went silent. This add-on bridges that gap with a bundled
32-bit host process that runs the engine and streams audio back to NVDA.

## Install

1. Download `infovox230-0.4.nvda-addon` below.
2. Open it (or NVDA menu → Tools → Add-on store → Install from external source).
3. Restart NVDA when prompted.
4. NVDA menu → Preferences → Settings → Speech → set **Synthesizer** to
   **Infovox 230 (Telia Promotor)**.

Nothing else is required: no dongle, no separate SAPI 4 runtime, no registry
changes, no administrator rights, and no separate Python install.

Upgrading from 0.3 is just installing this over it; your voice and rate / pitch
/ volume settings are kept.

## What's fixed in this release

**No more silent failure on machines with mandatory ASLR.** On systems where
Exploit Protection's *Force randomization for images* (`ForceRelocateImages`) is
enabled — the default in some hardened, managed and enterprise configurations —
the synthesizer would install and appear in the list but never speak, and the
32-bit host died with an access violation (`0xC0000005`) the moment NVDA asked
for audio.

The cause is in the engine, not the add-on. `Ivx230nt.dll` stores absolute
addresses that its own relocation table does not describe, so it is only correct
when Windows maps it at its preferred base of `0x10000000`. Mandatory ASLR moves
it anyway, after which the engine reads through stale pointers and crashes on
the first synthesis call.

The bundled engine now has its base relocations stripped — five bytes in the PE
headers, no code touched — which makes the image unmovable: the loader must
honour the preferred base or refuse the load outright. The host also checks
where the module actually landed and reports a clear error instead of crashing
if it is ever anywhere else. Machines that were already working are unaffected.

For anyone auditing the binary, the patch is documented and reproducible from
the pristine installer copy in the repository root:

```
python nvda-infovox230/tools/strip_engine_relocs.py Ivx230nt.dll
```

which regenerates the shipped engine byte-for-byte (md5
`0f1ed1289088c3fdad810c71eb0d5d3c`). Details are in `ARCHITECTURE.md` §4.

**Packaging fix.** The builder skipped `*.hive` and `*.log` runtime artefacts,
but the registry hive's transaction logs are named `infovox230.hive.LOG1` /
`.LOG2` and matched neither pattern, so they could be packaged into a build made
from a tree that had been run in place. They are now excluded from both the
package and the repository.

## Also in 0.3, if you are coming from 0.1

Language-filter crash on unmapped voices, a volume slider that did nothing, the
engine going silent after a few minutes from leaked notification sinks, and
writes into the real Windows registry — all fixed. See
[`RELEASE-0.3.md`](RELEASE-0.3.md).

## Notes

- Requires NVDA 2026.1 or later (64-bit).
- Removing the add-on removes every trace of it.
- Source, architecture notes and reverse-engineering write-up:
  https://github.com/joshknnd1982/infovox
