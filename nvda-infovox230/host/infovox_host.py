#!/usr/bin/env python3
# infovox_host.py -- 32-bit host process for the Infovox 230 SAPI4 engine.
#
# Runs under 32-bit CPython. Loads the (public-domain) Infovox 230 SAPI4 engine
# in-process, drives it with the same call flow NVDA's own sapi4 driver uses,
# and captures synthesized PCM through a custom IAudio/IAudioDest sink instead
# of sending it to a sound card.
#
# Two modes:
#   python infovox_host.py selftest "Hello world" out.wav [--voice <GUID>]
#       -> loads engine, lists voices, synthesizes to a .wav file. This is the
#          "does it speak at all" proof.
#   python infovox_host.py serve --port 8765
#       -> line/binary protocol server used by the 64-bit NVDA add-on
#          (see PROTOCOL below).
#
# The dongle is defeated by dropping the emulated sx32w.dll next to the engine
# (see sx32w_stub/). No CrypKey, no hardware, no registration required for the
# direct-load path.
#
# Copyright: engine is public domain (Telia Promotor / Babel-Infovox, defunct).
# This host and the _sapi4 interface glue are GPL v2 (derived from NVDA).

import os
import sys
import time
import json
import struct
import logging
import threading
import argparse
from collections import deque
from ctypes import (
    windll, byref, cast, c_void_p, c_ulong, c_ulonglong, c_wchar, POINTER,
    string_at, sizeof, create_string_buffer, memmove, addressof, WINFUNCTYPE,
    HRESULT, c_int,
)
from ctypes.wintypes import DWORD, WORD, BOOL, FILETIME

# comtypes provides the COM machinery. It must be importable by the 32-bit
# Python this runs under (bringup installs it).
from comtypes import (
    GUID, IUnknown, COMObject, STDMETHOD, CoInitialize, CoUninitialize,
    CoCreateInstance, COMError, hresult, ReturnHRESULT,
)


# Minimal, explicit IClassFactory so we don't depend on comtypes' high-level
# CreateInstance wrapper (its signature has varied across versions).
class IClassFactory(IUnknown):
    _iid_ = GUID("{00000001-0000-0000-C000-000000000046}")
    _methods_ = [
        STDMETHOD(HRESULT, "CreateInstance",
                  [POINTER(IUnknown), POINTER(GUID), POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "LockServer", [c_int]),
    ]


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _sapi4 import (  # noqa: E402
    TTSMODEINFOW, TTSMODEINFO, SDATA, TextSDATA, VOICECHARSET,
    ITTSEnumW, ITTSCentralW, ITTSAttributesW, ITTSNotifySinkW, ITTSBufNotifySink,
    IAudio, IAudioDest, IAudioDestNotifySink,
    TTSDATAFLAG_TAGGED, TTSFEATURE_PITCH, TTSFEATURE_SPEED, TTSFEATURE_VOLUME,
    TTSATTR_MINPITCH, TTSATTR_MAXPITCH, TTSATTR_MINSPEED, TTSATTR_MAXSPEED,
    TTSATTR_MINVOLUME, TTSATTR_MAXVOLUME, CLSID_TTSEnumerator,
)

# The engine's own class id, extracted from Ivx230nt.dll's class-object
# dispatch (the CLSID its DllGetClassObject accepts). Lets us instantiate the
# engine directly by path, with no SAPI4 runtime and no regsvr32.
CLSID_INFOVOX_ENGINE = GUID("{C9C5EDA0-7C89-11D0-0100-000000000000}")

log = logging.getLogger("infovox.host")

# ---------------------------------------------------------------------------
# WAVEFORMATEX (SAPI4 hands us one of these via IAudio::WaveFormatSet)
# ---------------------------------------------------------------------------
from ctypes import Structure  # noqa: E402


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", WORD),
        ("nChannels", WORD),
        ("nSamplesPerSec", DWORD),
        ("nAvgBytesPerSec", DWORD),
        ("nBlockAlign", WORD),
        ("wBitsPerSample", WORD),
        ("cbSize", WORD),
    ]


WAVE_FORMAT_PCM = 1


# ---------------------------------------------------------------------------
# Capturing audio sink: implements IAudio + IAudioDest. Instead of playing,
# it accumulates PCM and records the wave format and bookmark byte offsets.
# Modelled on NVDA's SynthDriverAudio but synchronous and non-playing.
# ---------------------------------------------------------------------------
class CaptureAudio(COMObject):
    _com_interfaces_ = [IAudio, IAudioDest]

    def __init__(self, on_pcm=None):
        super().__init__()
        self.wfx = None
        self.pcm = bytearray()
        self.written = 0
        self.free = 1 << 20
        self._notify = None          # IAudioDestNotifySink*
        self._level = 0xFFFFFFFF
        self._claimed = False
        self._started = False
        self.on_pcm = on_pcm         # optional streaming callback(bytes)
        self.on_format = None        # optional callback(wfx) on WaveFormatSet
        self.marks = []              # (byteOffset, markID) from IAudioDest.BookMark

    # ---- IAudio ----
    def IAudio_Flush(self):
        return

    def IAudio_LevelGet(self):
        return self._level

    def IAudio_LevelSet(self, dwLevel):
        self._level = dwLevel
        return

    def IAudio_PassNotify(self, pNotifyInterface, IIDNotifyInterface):
        if pNotifyInterface:
            self._notify = cast(pNotifyInterface, POINTER(IAudioDestNotifySink))
        else:
            self._notify = None
        return

    def IAudio_PosnGet(self):
        # Report everything written as already played so bookmarks fire promptly.
        return self.written

    def IAudio_Claim(self):
        self._claimed = True
        if self._notify:
            try:
                self._notify.AudioStart()
            except COMError:
                pass
        return

    def IAudio_UnClaim(self):
        self._claimed = False
        if self._notify:
            try:
                self._notify.AudioStop(0)
            except COMError:
                pass
        return

    def IAudio_Start(self):
        self._started = True
        return

    def IAudio_Stop(self):
        self._started = False
        return

    def IAudio_TotalGet(self):
        return self.written

    def IAudio_ToFileTime(self, pqWord):
        return FILETIME(0, 0)

    def IAudio_WaveFormatGet(self):
        if not self.wfx:
            raise ReturnHRESULT(hresult.E_FAIL, None)
        size = sizeof(WAVEFORMATEX)
        ptr = windll.ole32.CoTaskMemAlloc(size)
        memmove(ptr, addressof(self.wfx), size)
        return SDATA(ptr, size)

    def IAudio_WaveFormatSet(self, dWFEX):
        wfx = WAVEFORMATEX()
        n = min(dWFEX.dwSize, sizeof(WAVEFORMATEX))
        memmove(addressof(wfx), dWFEX.pData, n)
        self.wfx = wfx
        log.info("WaveFormatSet: %d Hz, %d ch, %d bit (tag=%d)",
                 wfx.nSamplesPerSec, wfx.nChannels, wfx.wBitsPerSample, wfx.wFormatTag)
        self.free = max(wfx.nAvgBytesPerSec * 4, 1 << 20)
        if self.on_format:
            try:
                self.on_format(wfx)
            except Exception:
                pass
        return

    # ---- IAudioDest ----
    def IAudioDest_FreeSpace(self):
        return (self.free, 0)

    def IAudioDest_DataSet(self, pBuffer, dwSize):
        if pBuffer and dwSize:
            chunk = string_at(pBuffer, dwSize)
            self.pcm += chunk
            self.written += dwSize
            if self.on_pcm:
                self.on_pcm(chunk)
        return

    def IAudioDest_BookMark(self, dwMarkID):
        # The engine registers an audio-position mark here (internal sequential
        # id). Since we "play" instantly, immediately tell the engine the mark
        # was reached; for our \mrk=N\ marks the engine then fires
        # ITTSBufNotifySink::BookMark with the real N (see BufNotifySink), which
        # is what NVDA needs. Internal (word) marks don't reach that sink.
        if self._notify:
            try:
                self._notify.BookMark(int(dwMarkID), 0)
            except COMError:
                pass
        return


# ---------------------------------------------------------------------------
# TTS notify sink (utterance-level) and buffer notify sink (bookmarks/done)
# ---------------------------------------------------------------------------
class TTSNotifySink(COMObject):
    _com_interfaces_ = [ITTSNotifySinkW]

    def ITTSNotifySinkW_AttribChanged(self, this, dwAttribute):
        return

    def ITTSNotifySinkW_AudioStart(self, this, qTimeStamp):
        return

    def ITTSNotifySinkW_AudioStop(self, this, qTimeStamp):
        return

    def ITTSNotifySinkW_Visual(self, this, qTimeStamp, cIPAPhoneme, cEnginePhoneme,
                               dwHints, pTTSMouth):
        return


class BufNotifySink(COMObject):
    _com_interfaces_ = [ITTSBufNotifySink]

    def __init__(self, audio=None):
        super().__init__()
        self.done = threading.Event()
        self.audio = audio            # CaptureAudio, to read the byte position
        self.mark_offsets = []        # (byteOffset, markNum) in synthesis order

    def ITTSBufNotifySink_TextDataDone(self, this, qTimeStamp, dwFlags):
        self.done.set()
        return

    def ITTSBufNotifySink_TextDataStarted(self, this, qTimeStamp):
        return

    def ITTSBufNotifySink_BookMark(self, this, qTimeStamp, dwMarkNum):
        # Record the PCM byte position at which this user \mrk=N\ occurs, so the
        # 64-bit side can fire synthIndexReached in sync with playback.
        off = self.audio.written if self.audio else 0
        log.debug("mark N=%d at byte %d", int(dwMarkNum), off)
        self.mark_offsets.append((off, int(dwMarkNum)))
        return

    def ITTSBufNotifySink_WordPosition(self, this, qTimeStamp, dwByteOffset):
        return


# ---------------------------------------------------------------------------
# Engine loading + a single Engine wrapper
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self, engine_dir, keep_registry=False, modes_json=None):
        self.engine_dir = os.path.abspath(engine_dir)
        self.keep_registry = keep_registry
        self.modes_json = modes_json
        self.enum = None
        self.central = None
        self.attrs = None
        self.audio = None
        self.sink = None
        self.sinkPtr = None
        self.sinkKey = DWORD()
        self.modes = []          # list of TTSMODEINFOW
        self.features = 0
        self.rate_min = self.rate_max = self.rate_def = None
        self.pitch_min = self.pitch_max = self.pitch_def = None
        self.vol_min = self.vol_max = self.vol_def = None
        # last base rate/pitch/volume (0-100) set by the client; re-applied
        # before every utterance so an inline \Pit= change (e.g. NVDA's capital
        # pitch bump) doesn't persist into later utterances.
        self._base = {}

    # -- load the engine and obtain an ITTSEnum --
    def load(self):
        # Make the engine find its rule files / DLLs relative to engine_dir.
        os.environ["PATH"] = self.engine_dir + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(self.engine_dir)
        except Exception:
            pass
        os.chdir(self.engine_dir)
        if not self.keep_registry:
            self._seed_registry()
            if self.modes_json and os.path.exists(self.modes_json):
                self._write_modes(self.modes_json)
        else:
            log.info("keep-registry: using existing engine registry config as-is")

        # Preferred: direct in-process load by path (no SAPI4 runtime needed).
        try:
            self.enum = self._load_direct()
            log.info("Engine loaded via direct DllGetClassObject.")
            return
        except Exception as e:
            log.warning("Direct load failed (%s); trying SAPI4 enumerator.", e)

        # Fallback: the SAPI4 runtime's system enumerator (needs spchapi + the
        # engine registered with regsvr32 SysWOW64).
        self.enum = CoCreateInstance(CLSID_TTSEnumerator, interface=ITTSEnumW)
        log.info("Engine reached via CLSID_TTSEnumerator.")

    def _seed_registry(self):
        """Best-effort: point the engine at our engine_dir for its rule files,
        lexicons and licence dir. Old Infovox installs read these from
        HKLM\\Software\\Babel-Infovox AB\\Infovox 230. We write HKCU (no admin)
        and try HKLM too. Harmless if the engine ignores them."""
        try:
            import winreg
        except Exception:
            return
        d = self.engine_dir
        values = {
            "LanguageDir": d, "LicenseDir": d, "LexiconDir": d,
            "LanguageDirectory": d, "Path": d,
        }
        subkey = r"Software\Babel-Infovox AB\Infovox 230"
        for root, name in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                           (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            try:
                k = winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_WRITE)
                for vn, vv in values.items():
                    winreg.SetValueEx(k, vn, 0, winreg.REG_SZ, vv)
                winreg.CloseKey(k)
                log.info("seeded engine paths in %s\\%s", name, subkey)
            except Exception as e:
                log.debug("could not seed %s registry (%s)", name, e)

    def _write_modes(self, modes_json_path):
        """Write the voice table (60 modes) into HKCU so the HKCU-patched engine
        enumerates them. LanguageFile stays relative and resolves under
        LanguageDir (= engine_dir). No admin required."""
        try:
            import winreg
            modes = json.load(open(modes_json_path, "r"))
        except Exception as e:
            log.warning("could not load modes.json (%s)", e)
            return
        root = winreg.HKEY_CURRENT_USER
        base = r"Software\Babel-Infovox AB\Infovox 230\Modes"
        try:
            winreg.CreateKeyEx(root, base, 0, winreg.KEY_WRITE).Close()
        except Exception:
            pass
        n = 0
        for m in modes:
            name = m.get("_name")
            if not name:
                continue
            try:
                k = winreg.CreateKeyEx(root, base + "\\" + name, 0, winreg.KEY_WRITE)
                for vn, vv in m.items():
                    if vn.startswith("_"):
                        continue
                    winreg.SetValueEx(k, vn, 0, winreg.REG_SZ, str(vv))
                winreg.CloseKey(k)
                n += 1
            except Exception as e:
                log.debug("mode write failed for %s (%s)", name, e)
        log.info("wrote %d voice modes to HKCU\\%s", n, base)

    def _load_direct(self):
        dllpath = None
        for cand in ("Ivx230nt.dll", "Ivx230.dll"):
            p = os.path.join(self.engine_dir, cand)
            if os.path.exists(p):
                dllpath = p
                break
        if not dllpath:
            raise FileNotFoundError("Ivx230nt.dll not found in %s" % self.engine_dir)
        self._hmod = windll.kernel32.LoadLibraryW(dllpath)
        if not self._hmod:
            raise OSError("LoadLibrary failed: %d" % windll.kernel32.GetLastError())
        proc = windll.kernel32.GetProcAddress(self._hmod, b"DllGetClassObject")
        if not proc:
            raise OSError("DllGetClassObject not exported")
        proto = WINFUNCTYPE(HRESULT, POINTER(GUID), POINTER(GUID), POINTER(c_void_p))
        DllGetClassObject = proto(proc)
        pcf = c_void_p()
        hr = DllGetClassObject(byref(CLSID_INFOVOX_ENGINE),
                               byref(IClassFactory._iid_), byref(pcf))
        if hr != 0 or not pcf:
            raise COMError(hr, "DllGetClassObject", None)
        factory = cast(pcf, POINTER(IClassFactory))
        # Ask the factory for the engine's mode enumerator.
        pv = c_void_p()
        factory.CreateInstance(None, byref(ITTSEnumW._iid_), byref(pv))
        if not pv:
            raise COMError(-1, "CreateInstance returned NULL", None)
        return cast(pv, POINTER(ITTSEnumW))

    # -- enumerate modes (voices/languages) --
    def list_modes(self):
        self.modes = []
        self.enum.Reset()
        while True:
            mode = TTSMODEINFOW()
            fetched = c_ulong(0)
            try:
                self.enum.Next(1, byref(mode), byref(fetched))
            except COMError as e:
                log.error("Next() failed: %s", e)
                break
            if fetched.value == 0:
                break
            self.modes.append(mode)
            log.info("mode: name=%r product=%r speaker=%r langID=0x%04x gModeID=%s "
                     "gender=%d age=%d features=0x%x",
                     mode.szModeName, mode.szProductName, mode.szSpeaker,
                     mode.language.LanguageID, str(mode.gModeID),
                     mode.wGender, mode.wAge, mode.dwFeatures)
        return self.modes

    # -- release the current central/audio (some engines allow only one) --
    def release_current(self):
        try:
            if self.central is not None:
                try:
                    self.central.UnRegister(self.sinkKey)
                except Exception:
                    pass
        except Exception:
            pass
        self.attrs = None
        self.central = None
        self.sinkPtr = None
        self.sink = None
        self.audio = None

    # -- select a mode by gModeID GUID (string or GUID) --
    def select(self, mode_guid):
        if isinstance(mode_guid, str):
            mode_guid = GUID(mode_guid)
        # Some SAPI4 engines allow only one ITTSCentral at a time; release the
        # previous one before selecting the next.
        self.release_current()
        # find features for this mode
        self.features = 0
        for m in self.modes:
            if m.gModeID == mode_guid:
                self.features = m.dwFeatures
                break
        self.audio = CaptureAudio()
        self.central = POINTER(ITTSCentralW)()
        self.enum.Select(mode_guid, byref(self.central), self.audio)
        # register a notify sink
        self.sink = TTSNotifySink()
        self.sinkPtr = self.sink.QueryInterface(ITTSNotifySinkW)
        try:
            self.central.Register(cast(self.sinkPtr, c_void_p),
                                  ITTSNotifySinkW._iid_, byref(self.sinkKey))
        except COMError as e:
            log.warning("Register() failed (non-fatal): %s", e)
        # attributes (rate/pitch/volume)
        try:
            self.attrs = self.central.QueryInterface(ITTSAttributesW)
        except COMError:
            self.attrs = None
        self._query_ranges()
        log.info("Selected mode %s (features=0x%x)", str(mode_guid), self.features)

    def _query_ranges(self):
        """Discover the engine's *real* rate/pitch/volume ranges (as NVDA's own
        sapi4 driver does): set the API min/max sentinels and read back the
        value the engine actually clamps to. NVDA's 0..100% then maps onto that
        range instead of onto the raw 0..0xFFFFFFFF sentinel domain."""
        self.rate_min = self.rate_max = self.rate_def = None
        self.pitch_min = self.pitch_max = self.pitch_def = None
        self.vol_min = self.vol_max = self.vol_def = None
        if not self.attrs:
            return
        if self.features & TTSFEATURE_SPEED:
            try:
                v = DWORD(); self.attrs.SpeedGet(byref(v)); self.rate_def = v.value
                self.attrs.SpeedSet(TTSATTR_MINSPEED); self.attrs.SpeedGet(byref(v)); self.rate_min = v.value
                self.attrs.SpeedSet(TTSATTR_MAXSPEED); self.attrs.SpeedGet(byref(v))
                self.rate_max = max(v.value - 1, self.rate_min + 1)
                self.attrs.SpeedSet(self.rate_def if self.rate_def is not None
                                    else (self.rate_min + self.rate_max) // 2)
            except COMError:
                self.rate_min = self.rate_max = None
        if self.features & TTSFEATURE_PITCH:
            try:
                v = WORD(); self.attrs.PitchGet(byref(v)); self.pitch_def = v.value
                self.attrs.PitchSet(TTSATTR_MINPITCH); self.attrs.PitchGet(byref(v)); self.pitch_min = v.value
                self.attrs.PitchSet(TTSATTR_MAXPITCH); self.attrs.PitchGet(byref(v)); self.pitch_max = v.value
                self.attrs.PitchSet(self.pitch_def)
            except COMError:
                self.pitch_min = self.pitch_max = None
        if self.features & TTSFEATURE_VOLUME:
            try:
                v = DWORD(); self.attrs.VolumeGet(byref(v)); self.vol_def = v.value & 0xFFFF
                self.attrs.VolumeSet(TTSATTR_MINVOLUME); self.attrs.VolumeGet(byref(v)); self.vol_min = v.value & 0xFFFF
                self.attrs.VolumeSet(TTSATTR_MAXVOLUME); self.attrs.VolumeGet(byref(v)); self.vol_max = v.value & 0xFFFF
            except COMError:
                self.vol_min = self.vol_max = None
        log.info("ranges rate[%s..%s def %s] pitch[%s..%s] vol[%s..%s]",
                 self.rate_min, self.rate_max, self.rate_def,
                 self.pitch_min, self.pitch_max, self.vol_min, self.vol_max)

    # -- set speech parameters directly (0..100 percent) --
    def set_param(self, which, percent, remember=True):
        if not self.attrs:
            return
        percent = max(0, min(100, int(percent)))
        if remember:
            self._base[which] = percent

        def scale(lo, hi):
            return int(lo + (hi - lo) * percent / 100.0)
        try:
            if which == "rate" and self.rate_min is not None and self.rate_max is not None:
                self.attrs.SpeedSet(scale(self.rate_min, self.rate_max))
            elif which == "pitch" and self.pitch_min is not None and self.pitch_max is not None:
                self.attrs.PitchSet(scale(self.pitch_min, self.pitch_max))
            elif which == "volume" and self.vol_min is not None and self.vol_max is not None:
                v = scale(self.vol_min, self.vol_max) & 0xFFFF
                self.attrs.VolumeSet(v | (v << 16))
        except COMError as e:
            log.warning("set_param %s failed: %s", which, e)

    # -- speak tagged text, block until done, return (pcm, wfx, marks) --
    def speak(self, tagged_text, pump, timeout=30.0, cancel_check=None):
        self.audio.pcm = bytearray()
        self.audio.written = 0
        self.audio.marks = []
        # Re-establish the base rate/pitch/volume so a persisted inline change
        # (e.g. the pitch bump on a capital letter) is cleared before this
        # utterance; inline tags within the text still override for this one.
        for _k, _v in list(self._base.items()):
            self.set_param(_k, _v, remember=False)
        buf = BufNotifySink(self.audio)
        bufPtr = buf.QueryInterface(ITTSBufNotifySink)
        self.central.TextData(
            VOICECHARSET.CHARSET_TEXT,
            TTSDATAFLAG_TAGGED,
            TextSDATA(tagged_text),
            cast(bufPtr, c_void_p),
            ITTSBufNotifySink._iid_,
        )
        # pump the message queue until the engine signals TextDataDone, the
        # client requests cancel, or we time out.
        deadline = time.time() + timeout
        cancelled = False
        while not buf.done.is_set() and time.time() < deadline:
            pump()
            if cancel_check and cancel_check():
                cancelled = True
                try:
                    self.central.AudioReset()
                except COMError:
                    pass
                break
            time.sleep(0.002)
        if not cancelled and not buf.done.is_set():
            log.warning("TextData timed out after %.1fs (no TextDataDone).", timeout)
        wfx = self.audio.wfx
        # Prefer the audio-sink marks (correct byte offsets); fall back to the
        # buffer-sink marks if the engine used that channel instead.
        marks = self.audio.marks if self.audio.marks else buf.mark_offsets
        return bytes(self.audio.pcm), wfx, list(marks)


def _pct_to_range(pct, lo, hi):
    return int(lo + (hi - lo) * (pct / 100.0))


# ---------------------------------------------------------------------------
# Message pump. SAPI4 delivers callbacks via the thread message queue, so we
# must pump it while waiting. (See NVDA's _ComThread.)
# ---------------------------------------------------------------------------
def make_pump():
    from ctypes import wintypes
    user32 = windll.user32
    msg = wintypes.MSG()
    PM_REMOVE = 1

    def pump():
        while user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
    return pump


# ---------------------------------------------------------------------------
# Tag builder: turn plain text + params into Infovox/SAPI4 control-tagged text.
# ---------------------------------------------------------------------------
def build_tagged(text, rate=None, pitch=None, volume=None, marks=None):
    out = []
    if rate is not None:
        out.append("\\Spd=%d\\" % _pct_to_range(rate, TTSATTR_MINSPEED, min(TTSATTR_MAXSPEED, 1000)))
    if pitch is not None:
        out.append("\\Pit=%d\\" % _pct_to_range(pitch, TTSATTR_MINPITCH, TTSATTR_MAXPITCH))
    if volume is not None:
        v = _pct_to_range(volume, 0, 0xFFFF)
        out.append("\\Vol=%d\\" % (v | (v << 16)))
    out.append(text.replace("\\", "\\\\"))
    out.append("\\Pau=1\\")
    return "".join(out)


def write_wav(path, pcm, wfx):
    import wave
    ch = wfx.nChannels if wfx else 1
    sr = wfx.nSamplesPerSec if wfx else 11025
    bits = wfx.wBitsPerSample if wfx else 16
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(bits // 8)
        w.setframerate(sr)
        w.writeframes(pcm)


# ---------------------------------------------------------------------------
# selftest mode -- the "prove it speaks" path
# ---------------------------------------------------------------------------
def cmd_selftest(args):
    CoInitialize()
    pump = make_pump()
    eng = Engine(args.engine_dir, keep_registry=getattr(args, "keep_registry", False), modes_json=getattr(args, "modes", None))
    eng.load()
    modes = eng.list_modes()
    if not modes:
        log.error("NO VOICES ENUMERATED. If the log shows the engine loaded but "
                  "zero modes, a licensing gate (dongle/CrypKey) is still active. "
                  "Confirm sx32w.dll (the emulator) sits next to Ivx230nt.dll.")
        return 2
    print("Voices found: %d" % len(modes))
    for i, m in enumerate(modes):
        print("  [%d] %s | %s | lang 0x%04x | %s"
              % (i, m.szModeName, m.szProductName, m.language.LanguageID, str(m.gModeID)))
    voice = args.voice or str(modes[0].gModeID)
    eng.select(voice)
    tagged = build_tagged(args.text)
    pcm, wfx, marks = eng.speak(tagged, pump)
    if not pcm:
        log.error("Engine produced 0 bytes of audio. Voice selected but silent -- "
                  "likely a second (CrypKey) gate or an audio-format rejection. "
                  "See log above for WaveFormatSet / DataSet lines.")
        return 3
    write_wav(args.out, pcm, wfx)
    dur = len(pcm) / float(wfx.nAvgBytesPerSec if wfx else 22050)
    print("OK: wrote %s  (%d bytes PCM, ~%.2fs)" % (args.out, len(pcm), dur))
    return 0


# ---------------------------------------------------------------------------
# serve mode -- binary protocol for the 64-bit NVDA add-on.
#
# PROTOCOL (all little-endian). Frames: <1 byte type><4 byte len><payload>.
#   client -> host:
#     'L'  list voices     (payload: none)          -> host 'V'
#     'S'  select voice    (payload: utf8 GUID)      -> host 'K'
#     'P'  set params      (payload: json {rate,pitch,volume})
#     'T'  speak           (payload: json {text, index?, rate?, pitch?, volume?})
#                          -> host streams 'A' pcm frames, 'M' marks, then 'D'
#     'X'  cancel          (payload: none)
#     'Q'  quit
#   host -> client:
#     'V'  voices json  [{id,name,langid,gender,age,features}, ...]
#     'K'  ack (payload: json {format:{rate,channels,bits}})
#     'A'  pcm chunk (raw bytes)
#     'M'  mark reached at byte offset (payload: <4 byte offset><4 byte mark>)
#     'D'  utterance done (payload: none)
#     'E'  error (payload: utf8 message)
# ---------------------------------------------------------------------------
def _send(sock, t, payload=b""):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    sock.sendall(t.encode("ascii") + struct.pack("<I", len(payload)) + payload)


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_frame(sock):
    hdr = _recv_exact(sock, 5)
    if not hdr:
        return None, None
    t = hdr[0:1].decode("ascii")
    (ln,) = struct.unpack("<I", hdr[1:5])
    payload = _recv_exact(sock, ln) if ln else b""
    return t, payload


def cmd_serve(args):
    import socket
    CoInitialize()
    pump = make_pump()
    eng = Engine(args.engine_dir, keep_registry=getattr(args, "keep_registry", False), modes_json=getattr(args, "modes", None))
    eng.load()
    eng.list_modes()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(1)
    print("READY %d" % args.port, flush=True)
    log.info("listening on 127.0.0.1:%d", args.port)
    conn, _ = srv.accept()
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass
    log.info("client connected")

    # Background reader: feeds a queue and flags cancels so we can abort a
    # synthesis in progress (NVDA needs speech to stop the instant a key is hit).
    import queue as _queue
    frames = _queue.Queue()
    cancel_evt = threading.Event()
    stop_evt = threading.Event()

    def reader():
        while not stop_evt.is_set():
            t, payload = _recv_frame(conn)
            if t is None:
                frames.put((None, None))
                break
            if t == "X":
                cancel_evt.set()          # abort any in-progress speak
            frames.put((t, payload))
    rt = threading.Thread(target=reader, name="ivxServeReader", daemon=True)
    rt.start()

    def voices_payload():
        arr = []
        for m in eng.modes:
            arr.append({
                "id": str(m.gModeID),
                "name": (m.szModeName or "").strip(),
                "product": (m.szProductName or "").strip(),
                "speaker": (m.szSpeaker or "").strip(),
                "langid": m.language.LanguageID,
                "gender": m.wGender,
                "age": m.wAge,
                "features": m.dwFeatures,
            })
        return json.dumps(arr)

    try:
        while True:
            t, payload = frames.get()
            if t is None or t == "Q":
                break
            if t == "L":
                _send(conn, "V", voices_payload())
            elif t == "S":
                try:
                    eng.select(payload.decode("utf-8"))
                    fmt = {"rate": eng.audio.wfx.nSamplesPerSec if eng.audio.wfx else 0,
                           "channels": eng.audio.wfx.nChannels if eng.audio.wfx else 1,
                           "bits": eng.audio.wfx.wBitsPerSample if eng.audio.wfx else 16}
                    _send(conn, "K", json.dumps({"format": fmt}))
                except Exception as e:
                    _send(conn, "E", str(e))
            elif t == "P":
                try:
                    p = json.loads(payload or b"{}")
                    for k in ("rate", "pitch", "volume"):
                        if k in p:
                            eng.set_param(k, p[k])
                    _send(conn, "K", "{}")
                except Exception as e:
                    _send(conn, "E", str(e))
            elif t == "T":
                try:
                    p = json.loads(payload or b"{}")
                    uid = int(p.get("id", 0)) & 0xFFFFFFFF
                    _send(conn, "B", struct.pack("<I", uid))  # begin utterance
                    for k in ("rate", "pitch", "volume"):
                        if k in p and p[k] is not None:
                            eng.set_param(k, p[k])
                    tagged = _tagged_from_request(p)
                    # stream PCM as it arrives; announce the wave format the
                    # moment the engine sets it (before any audio) so the client
                    # can open its player with the right rate.
                    def on_pcm(chunk, _c=conn):
                        _send(_c, "A", chunk)

                    def on_format(wfx, _c=conn):
                        _send(_c, "F", json.dumps({
                            "rate": wfx.nSamplesPerSec, "channels": wfx.nChannels,
                            "bits": wfx.wBitsPerSample}))
                    eng.audio.on_pcm = on_pcm
                    eng.audio.on_format = on_format
                    if eng.audio.wfx:  # already known from a prior utterance
                        on_format(eng.audio.wfx)
                    cancel_evt.clear()
                    _pcm, wfx, marks = eng.speak(tagged, pump,
                                                 cancel_check=cancel_evt.is_set)
                    if not cancel_evt.is_set():
                        for off, num in marks:
                            _send(conn, "M", struct.pack("<II", off, num & 0xFFFFFFFF))
                    _send(conn, "D", struct.pack("<I", uid))  # end utterance
                except Exception as e:
                    log.exception("speak failed")
                    _send(conn, "E", str(e))
            elif t == "X":
                # cancel already handled by the reader (cancel_evt); if idle,
                # reset audio just in case.
                try:
                    if eng.central is not None:
                        eng.central.AudioReset()
                except Exception:
                    pass
            else:
                _send(conn, "E", "unknown frame %r" % t)
    finally:
        stop_evt.set()
        try:
            conn.close()
        except Exception:
            pass
        CoUninitialize()
    return 0


# ---------------------------------------------------------------------------
# speakmany mode -- a longer demo exercising many languages and voices.
# Writes one combined WAV plus one WAV per clip.
# ---------------------------------------------------------------------------
# (voice-name substring to match, text to speak)
DEMO_CLIPS = [
    ("American English Male",   "Hello. This is the American English male voice on Infovox two thirty."),
    ("American English Female", "And this is the American English female voice."),
    ("American English Child",  "This is the child voice."),
    ("American English Giant",  "This is the giant voice."),
    ("American English Zombie", "This is the zombie voice."),
    ("British English Male",    "Good day. This is British English."),
    ("German Male",             "Guten Tag. Dies ist die deutsche Stimme von Infovox."),
    ("French Male",             "Bonjour. Ceci est la voix francaise de Infovox."),
    ("Italian Male",            "Buongiorno. Questa e la voce italiana."),
    ("Castilian Spanish Male",  "Hola. Esta es la voz en castellano."),
    ("Dutch Male",              "Hallo. Dit is de Nederlandse stem."),
    ("Danish Male",             "Goddag. Dette er den danske stemme."),
    ("Norwegian Male",          "God dag. Dette er den norske stemmen."),
    ("Swedish Male",            "God dag. Det haer aer den svenska roesten."),
    ("Finnish Male",            "Hyvaa paivaa. Tama on suomen kieli."),
    ("Icelandic Male",          "Godan dag. Thetta er islenska roeddin."),
]


def cmd_speakmany(args):
    CoInitialize()
    pump = make_pump()
    eng = Engine(args.engine_dir, keep_registry=getattr(args, "keep_registry", False), modes_json=getattr(args, "modes", None))
    eng.load()
    modes = eng.list_modes()
    if not modes:
        log.error("No voices enumerated.")
        return 2
    outdir = args.outdir
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    def find_mode(name):
        name = name.lower()
        for m in modes:
            if (m.szModeName or "").strip().lower() == name:
                return m
        for m in modes:
            if name in (m.szModeName or "").strip().lower():
                return m
        return None

    combined = bytearray()
    combined_wfx = None
    n_ok = 0
    for i, (voice, text) in enumerate(DEMO_CLIPS):
        m = find_mode(voice)
        if not m:
            log.warning("voice not found: %s", voice)
            continue
        try:
            eng.select(str(m.gModeID))
            pcm, wfx, _marks = eng.speak(build_tagged(text), pump, timeout=30)
        except Exception:
            log.exception("clip failed: %s", voice)
            continue
        if not pcm:
            log.warning("clip produced no audio: %s", voice)
            continue
        safe = voice.replace(" ", "_")
        path = os.path.join(outdir, "%02d_%s.wav" % (i, safe))
        write_wav(path, pcm, wfx)
        n_ok += 1
        print("  wrote %s (%d bytes, %.1fs)" % (
            os.path.basename(path), len(pcm),
            len(pcm) / float(wfx.nAvgBytesPerSec if wfx else 22050)))
        # accumulate into the combined track (assume a shared format across voices)
        if combined_wfx is None:
            combined_wfx = wfx
        if wfx and combined_wfx and wfx.nSamplesPerSec == combined_wfx.nSamplesPerSec \
                and wfx.wBitsPerSample == combined_wfx.wBitsPerSample \
                and wfx.nChannels == combined_wfx.nChannels:
            combined += pcm
            # ~0.4s of silence between clips
            combined += b"\x00" * int(combined_wfx.nAvgBytesPerSec * 0.4)
    if combined and combined_wfx:
        allpath = os.path.join(outdir, "all_voices.wav")
        write_wav(allpath, bytes(combined), combined_wfx)
        dur = len(combined) / float(combined_wfx.nAvgBytesPerSec)
        print("OK: wrote %s  (%d clips, %d bytes, ~%.1fs)" % (allpath, n_ok, len(combined), dur))
    else:
        print("OK: wrote %d individual clips to %s" % (n_ok, outdir))
    return 0 if n_ok else 3


def _tagged_from_request(p):
    text = p.get("text", "")
    if p.get("tagged"):
        # client already built the full control-tagged string
        return text
    parts = []
    if p.get("index") is not None:
        parts.append("\\mrk=%d\\" % int(p["index"]))
    parts.append(text.replace("\\", "\\\\"))
    parts.append("\\Pau=1\\")
    return "".join(parts)


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Infovox 230 SAPI4 host (32-bit)")
    ap.add_argument("--engine-dir", default=os.path.dirname(os.path.abspath(__file__)),
                    help="folder containing Ivx230nt.dll, the .IVX rule files and sx32w.dll")
    ap.add_argument("--log", default=None, help="log file path")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--keep-registry", action="store_true",
                    help="use the existing engine registry config as-is (don't reseed paths)")
    _defmodes = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modes.json")
    ap.add_argument("--modes", default=_defmodes if os.path.exists(_defmodes) else None,
                    help="path to modes.json; written to HKCU so the engine enumerates the voices")
    sub = ap.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("selftest")
    st.add_argument("text")
    st.add_argument("out")
    st.add_argument("--voice", default=None)

    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8765)

    dm = sub.add_parser("speakmany")
    dm.add_argument("outdir")

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log, "w", "utf-8")] if args.log
        else [logging.StreamHandler(sys.stderr)],
    )
    if args.cmd == "selftest":
        return cmd_selftest(args)
    elif args.cmd == "serve":
        return cmd_serve(args)
    elif args.cmd == "speakmany":
        return cmd_speakmany(args)


if __name__ == "__main__":
    sys.exit(main())
