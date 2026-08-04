# Architecture & reverse-engineering notes

## 1. What the engine is

`Ivx230nt.dll` (the Windows NT/2000/XP build; `Ivx230.dll` is the Win9x build)
is an **in-process COM server implementing Microsoft SAPI 4** low-level TTS. It
was built by Babel-Infovox AB, February 2002, version 2.2. Confirmed from the
binary:

- Exports `DllGetClassObject`, `DllCanUnloadNow`, `DllRegisterServer`,
  `DllUnregisterServer` — a standard COM in-proc server.
- Implements the SAPI4 vtables (IIDs found verbatim inside the DLL, and they
  match NVDA's own SAPI4 driver byte-for-byte):
  - `ITTSEnumW`   `{6B837B20-4A47-101B-931A-00AA0047BA4F}` — enumerate/select modes
  - `ITTSCentralW` `{28016060-4A47-101B-931A-00AA0047BA4F}` — `TextData` synthesis
  - `ITTSAttributesW` `{1287A280-4A47-101B-931A-00AA0047BA4F}` — pitch/speed/volume
  - `ITTSNotifySinkW`, `ITTSBufNotifySink` — events, bookmarks, "done"
  - `IAudio` / `IAudioDest` / `IAudioDestNotifySink` — the audio path we capture
- The engine's own coclass CLSID is `{C9C5EDA0-7C89-11D0-0100-000000000000}`
  (the value its `DllGetClassObject` dispatch checks). This lets us instantiate
  it directly by path, with no SAPI4 runtime and no `regsvr32`.
- Speech parameters use SAPI4 inline tags: `\Spd=`, `\Pit=`, `\Vol=`, `\Pau=`,
  `\mrk=` (index bookmarks), `\RmS=` (spell/character mode).
- The 12 bundled `*.IVX` files are the per-language rule sets: American &
  British English, German, French, Italian, Spanish/Castilian, Dutch, Danish,
  Norwegian, Swedish, Finnish, Icelandic. Voices carry gender (Male/Female/
  Neutral) and age (Baby…Elderly) attributes.

## 2. The licence gate (and how it's defeated)

The engine imports four functions from `SX32W.dll` — `RNBOsproFormatPacket`,
`RNBOsproInitialize`, `RNBOsproFindFirstUnit`, `RNBOsproRead` — the **Rainbow
Sentinel SuperPro** hardware-dongle API. A single function inside the engine
(file offset `0x15b50`) drives them:

```
RNBOsproFormatPacket(packet, 0x404)      ; "status 1" on failure
RNBOsproInitialize(packet)               ; "status 2"
RNBOsproFindFirstUnit(packet, 0x7E9E)    ; "status 3"  (0x7E9E = developer ID)
RNBOsproRead(packet, cell, &value)       ; "status 4"
... reads per-language cells (SWE, NOR, ITA, ICE, GER, FRE, FIN, DUT, DAN,
    SPA, ENG ...) and builds an authorization bitmask ...
return (readValue & languageBit) != 0    ; 1 = authorized, 0 = not
```

With no dongle, `Initialize`/`FindFirstUnit` fail, the mask is empty, and the
engine enumerates **zero** voices. CrypKey (the strings `AcquireLicense`,
`init_crypkey`, and the separate 16-bit `IvxLM230.exe`) is the software half of
the same scheme.

**Primary bypass — emulated `Sx32w.dll`** (`sx32w_stub/`). A hand-built 32-bit
DLL exports the same 15 `RNBOspro*` symbols. The four the engine calls return
success (`0`), and `RNBOsproRead` writes `0xFFFF` into the output cell. The
engine's final test `readValue & languageBit` is therefore always non-zero, so
**every language reports authorized** with no hardware. Dropping this DLL next
to `Ivx230nt.dll` is the whole fix; it is reversible and touches nothing else.
The generated PE was validated with `pefile` (valid DLL, 15 sorted exports) and
its four hot functions were disassembled to confirm exact behaviour.

**Fallback — engine patch** (`tools/apply_engine_patch.py`). Overwrites the
8-byte prologue of the gate function at `0x15b50` with `mov eax,1 ; ret 4`, so
it always returns "authorized". Use only if the emulator alone proves
insufficient on your machine (e.g. a residual CrypKey check surfaces).

## 3. The 32↔64-bit bridge

NVDA 2026.1 is 64-bit and cannot load this 32-bit COM DLL in-process, so the
add-on splits into two processes:

```
 NVDA 2026.1 (64-bit)                         host (32-bit CPython)
 ┌───────────────────────────┐   TCP 127.0.0.1  ┌───────────────────────────┐
 │ synthDrivers/infovox230.py│ ───────────────► │ infovox_host.py           │
 │  - enumerates voices      │  control frames  │  - LoadLibrary Ivx230nt   │
 │  - builds \tagged\ text   │                  │  - ITTSEnum → Select       │
 │  - nvwave.WavePlayer       │ ◄─────────────── │  - ITTSCentral.TextData    │
 │  - fires index/done        │  PCM + marks     │  - CaptureAudio sink       │
 └───────────────────────────┘                  └───────────────────────────┘
```

The host reuses the **exact call flow of NVDA's own `synthDrivers/sapi4.py`**
(enumerate modes → `Select(gModeID, &central, audioSink)` → `Register` a notify
sink → `QueryInterface(ITTSAttributes)` → `TextData` with tagged text), but
substitutes a capturing `IAudio`/`IAudioDest` sink (`CaptureAudio`) that
accumulates PCM instead of playing it, and records the byte offset of each
`\mrk=` bookmark so index reporting stays in sync with playback on the NVDA
side. SAPI4 delivers its callbacks through the thread message queue, so the host
pumps messages while a `TextData` call is outstanding.

### Wire protocol (localhost TCP)

Frames are `<1-byte type><4-byte little-endian length><payload>`.

| Dir | Type | Meaning | Payload |
|-----|------|---------|---------|
| C→H | `L` | list voices | — |
| C→H | `S` | select voice | UTF-8 mode GUID |
| C→H | `P` | set params | JSON `{rate,pitch,volume}` (0–100) |
| C→H | `T` | speak | JSON `{text: <tagged>, tagged: true}` |
| C→H | `X` | cancel | — |
| C→H | `Q` | quit | — |
| H→C | `V` | voices | JSON array `{id,name,langid,gender,age,features,…}` |
| H→C | `K` | ack | JSON `{format:{rate,channels,bits}}` |
| H→C | `A` | PCM chunk | raw bytes |
| H→C | `M` | mark reached | `<4-byte byteOffset><4-byte markNum>` |
| H→C | `D` | utterance done | — |
| H→C | `E` | error | UTF-8 message |

The 64-bit driver feeds `A` chunks straight into `nvwave.WavePlayer`, counts
played bytes via feed callbacks, and fires `synthIndexReached` for each `M`
whose offset has been played, then `synthDoneSpeaking` on `D`.

## 4. Engine loading strategy

The host tries, in order:

1. **Direct in-process load** — `LoadLibraryW(Ivx230nt.dll)` →
   `DllGetClassObject({C9C5EDA0-…}, IID_IClassFactory)` →
   `CreateInstance(NULL, IID_ITTSEnumW)`. No SAPI4 runtime, no registration.
   This is preferred because it depends on nothing external.
2. **SAPI4 system enumerator** — `CoCreateInstance(CLSID_TTSEnumerator)`. Needs
   the Microsoft SAPI4 runtime (`spchapi.exe`, included in the installer set)
   and the engine registered via the 32-bit `regsvr32` in `SysWOW64`. Used only
   if the direct load fails on your machine.

The self-test log (`_run/selftest.log`) records which path succeeded and every
voice/mode the engine reported.

## 5. Known unknowns (to confirm on Windows)

- Whether the engine's coclass yields `ITTSEnum` directly (path 1) or requires
  the system enumerator (path 2). The host handles both; the log will tell.
- Whether any residual CrypKey check fires after the dongle is emulated. If it
  does, the log will show the engine loading but producing zero voices or zero
  audio, and the engine-patch fallback (or emulating the CrypKey calls) is the
  next lever.
- The exact default sample rate/format each voice requests (captured live from
  `IAudio::WaveFormatSet`; the driver adapts automatically).
