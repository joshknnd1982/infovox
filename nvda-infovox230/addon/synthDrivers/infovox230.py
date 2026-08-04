# infovox230.py -- NVDA synth driver (64-bit client side of the bridge).
#
# NVDA 2026.1 runs 64-bit and cannot load the 32-bit Infovox 230 SAPI4 engine
# in-process. This driver launches a bundled 32-bit host process
# (host/infovox_host.py under a bundled 32-bit Python) which hosts the engine
# and streams PCM + index marks back over a localhost socket. Audio is played
# here through NVDA's own nvwave.WavePlayer.
#
# Exposes every enumerated voice/language and the rate, pitch and volume
# parameters the selected voice supports.
#
# GPL v2 (NVDA add-on). The engine it drives is public domain.

import os
import json
import queue
import struct
import socket
import threading
import subprocess
from collections import OrderedDict, deque

import config
import nvwave
from logHandler import log
from synthDriverHandler import (
    SynthDriver,
    VoiceInfo,
    synthIndexReached,
    synthDoneSpeaking,
)
from speech.commands import (
    IndexCommand,
    CharacterModeCommand,
    BreakCommand,
    PitchCommand,
    RateCommand,
    VolumeCommand,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(BASE_DIR, "infovox230")          # bundled payload
ENGINE_DIR = os.path.join(PKG_DIR, "engine")            # engine DLLs + rules + sx32w.dll
HOST_SCRIPT = os.path.join(PKG_DIR, "host", "infovox_host.py")
PY32 = os.path.join(PKG_DIR, "python32", "python.exe")  # bundled 32-bit python
PORT = 8765


def _find_python32():
    if os.path.exists(PY32):
        return [PY32]
    # developer fallback (a machine with the 32-bit launcher/interpreter)
    return ["py", "-3-32"]


class _HostLink:
    """Owns the host subprocess and the control/audio socket. All socket reads
    are done by the driver's single reader thread."""

    def __init__(self):
        self.proc = None
        self.sock = None
        self._wlock = threading.Lock()

    def start(self):
        args = _find_python32() + [
            HOST_SCRIPT, "--engine-dir", ENGINE_DIR,
            "--log", os.path.join(PKG_DIR, "host.log"),
            "serve", "--port", str(PORT),
        ]
        log.info("infovox230: launching host: %r", args)
        self.proc = subprocess.Popen(
            args, cwd=ENGINE_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        ready = False
        for _ in range(400):
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.decode("utf-8", "replace").strip()
            if line:
                log.debug("infovox230 host: %s", line)
            if line.startswith("READY"):
                ready = True
                break
        if not ready:
            raise RuntimeError("Infovox host failed to start (see infovox230/host.log)")
        self.sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    def send(self, t, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        with self._wlock:
            self.sock.sendall(t.encode("ascii") + struct.pack("<I", len(payload)) + payload)

    def recv_frame(self):
        hdr = self._recv_exact(5)
        if not hdr:
            return None, None
        t = hdr[0:1].decode("ascii")
        (ln,) = struct.unpack("<I", hdr[1:5])
        payload = self._recv_exact(ln) if ln else b""
        return t, payload

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def stop(self):
        try:
            if self.sock:
                self.send("Q")
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        try:
            if self.proc:
                self.proc.terminate()
        except Exception:
            pass


class SynthDriver(SynthDriver):
    name = "infovox230"
    description = "Infovox 230 (Telia Promotor)"

    supportedSettings = (
        SynthDriver.VoiceSetting(),
        SynthDriver.RateSetting(),
        SynthDriver.PitchSetting(),
        SynthDriver.VolumeSetting(),
    )
    supportedCommands = {IndexCommand, CharacterModeCommand, BreakCommand,
                         RateCommand, PitchCommand, VolumeCommand}
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        return os.path.isdir(ENGINE_DIR) and os.path.exists(
            os.path.join(ENGINE_DIR, "Ivx230nt.dll"))

    def __init__(self):
        self._link = _HostLink()
        self._link.start()
        self._ctrl = queue.Queue()       # control responses: (type, payload)
        self._rate = 40      # default reading speed (0-100); calmer than mid
        self._pitch = 40     # default pitch lowered from mid (voices ran high)
        self._volume = 100
        self._player = None
        self._fmt = None
        self._playedBytes = 0
        self._pendingMarks = deque()     # (byteOffset, markNum)
        self._utteranceIndexes = []      # every index this utterance must fire
        self._speaking = False
        # Per-utterance generation tags. speak() bumps _gen and sets _playGen;
        # the host echoes the id in 'B'/'D' frames so the reader can drop audio
        # belonging to a cancelled/superseded utterance instead of bleeding or
        # cutting into the next one.
        self._gen = 0
        self._playGen = -1               # generation we currently want to hear
        self._inGen = -1                 # generation of frames arriving now
        self._fedBytes = 0               # bytes fed to the player this utterance
        self._doneGen = None             # gen for which 'D' (end) has arrived
        # Dedicated audio thread. All WavePlayer.feed() calls happen here, and it
        # periodically flushes the player so its "chunk finished" callbacks fire
        # (NVDA's WavePlayer only checks them when fed) — that is what makes
        # synthDoneSpeaking / synthIndexReached fire reliably (needed for say-all).
        self._audioQ = deque()           # ('A', gen, chunk) | ('D', gen)
        self._audioCond = threading.Condition()
        self._audioAlive = True
        self._audioThread = threading.Thread(target=self._audioThreadFunc,
                                            name="infovox230Audio", daemon=True)
        self._audioThread.start()
        # single reader thread owns all socket reads
        self._readerAlive = True
        self._reader = threading.Thread(target=self._readerLoop,
                                        name="infovox230Reader", daemon=True)
        self._reader.start()
        self._voices = self._loadVoices()
        if not self._voices:
            raise RuntimeError("Infovox engine enumerated no voices (licensing gate?)")
        self._voice = list(self._voices.keys())[0]
        self._selectVoice(self._voice)

    def terminate(self):
        self._readerAlive = False
        self._audioAlive = False
        with self._audioCond:
            self._audioCond.notify()
        try:
            if self._player:
                self._player.stop()
        except Exception:
            pass
        self._link.stop()

    # ---- request/response over the control queue ----
    def _request(self, t, payload=b"", expect=("K", "E", "V"), timeout=15):
        self._link.send(t, payload)
        try:
            rt, rp = self._ctrl.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("infovox230: timed out waiting for %r response" % t)
        return rt, rp

    # ---- voices ----
    def _loadVoices(self):
        rt, rp = self._request("L")
        if rt != "V":
            raise RuntimeError("expected voice list, got %r" % rt)
        arr = json.loads(rp.decode("utf-8"))
        import locale
        voices = OrderedDict()
        for v in arr:
            vid = v["id"]
            name = v["name"] or v["product"] or vid
            if v.get("speaker") and v["speaker"] not in name:
                name = "%s (%s)" % (name, v["speaker"])
            language = None
            try:
                language = locale.windows_locale.get(v.get("langid"))
            except Exception:
                pass
            voices[vid] = VoiceInfo(vid, name, language)
        log.info("infovox230: %d voices enumerated", len(voices))
        return voices

    def _getAvailableVoices(self):
        return self._voices

    def _get_voice(self):
        return self._voice

    def _set_voice(self, value):
        if value not in self._voices:
            return
        self._voice = value
        self._selectVoice(value)

    def _selectVoice(self, vid):
        rt, rp = self._request("S", vid)
        if rt == "K":
            info = json.loads(rp.decode("utf-8") or "{}")
            fmt = info.get("format") or {}
            # The engine often only reports its wave format at synthesis time,
            # so this may be rate 0 here; if so we defer player creation until
            # the host sends an 'F' frame during the first utterance.
            if fmt.get("rate"):
                self._fmt = fmt
                self._initPlayer()
            # re-apply current parameters to the new voice
            self._pushParams()
        elif rt == "E":
            log.error("infovox230: select failed: %s", rp.decode("utf-8", "replace"))

    def _initPlayer(self):
        if not self._fmt or not self._fmt.get("rate"):
            return
        try:
            if self._player:
                self._player.close()
        except Exception:
            pass
        self._player = nvwave.WavePlayer(
            channels=self._fmt.get("channels", 1),
            samplesPerSec=self._fmt.get("rate", 16000),
            bitsPerSample=self._fmt.get("bits", 16),
            outputDevice=config.conf["audio"]["outputDevice"],
        )

    def _onFormat(self, payload):
        try:
            fmt = json.loads(payload.decode("utf-8"))
        except Exception:
            return
        # (Re)create the player only if the format actually changed.
        if fmt.get("rate") and fmt != self._fmt:
            self._fmt = fmt
            self._initPlayer()

    # ---- parameters (0..100) ----
    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        self._rate = max(0, min(100, value))
        self._request("P", json.dumps({"rate": self._rate}))

    def _get_pitch(self):
        return self._pitch

    def _set_pitch(self, value):
        self._pitch = max(0, min(100, value))
        self._request("P", json.dumps({"pitch": self._pitch}))

    def _get_volume(self):
        return self._volume

    def _set_volume(self, value):
        self._volume = max(0, min(100, value))
        self._request("P", json.dumps({"volume": self._volume}))

    def _pushParams(self):
        self._request("P", json.dumps(
            {"rate": self._rate, "pitch": self._pitch, "volume": self._volume}))

    # ---- speaking ----
    def speak(self, speechSequence):
        tagged = self._buildTagged(speechSequence)
        self._gen += 1
        gen = self._gen
        self._playGen = gen
        self._playedBytes = 0
        self._fedBytes = 0
        self._doneGen = None
        self._pendingMarks.clear()
        # Every index in this utterance must fire exactly once: normally when
        # the engine reports its bookmark at the right audio position (see
        # _fireMarks), but any the engine never reports are fired when the
        # utterance finishes (_checkDone). NVDA say-all emits bare index-only
        # chunks with no surrounding audio, and the engine won't emit a
        # bookmark for those -- without this fallback say-all blocks forever
        # waiting for a lineReached callback that never arrives.
        self._utteranceIndexes = [it.index for it in speechSequence
                                  if isinstance(it, IndexCommand)]
        self._speaking = True
        # make sure the player is ready to accept a fresh utterance
        try:
            if self._player:
                self._player.pause(False)
        except Exception:
            pass
        self._link.send("T", json.dumps({"text": tagged, "tagged": True, "id": gen}))

    def _buildTagged(self, speechSequence):
        parts = []
        for item in speechSequence:
            if isinstance(item, str):
                parts.append(item.replace("\\", "\\\\"))
            elif isinstance(item, IndexCommand):
                parts.append("\\mrk=%d\\" % item.index)
            elif isinstance(item, CharacterModeCommand):
                parts.append("\\RmS=1\\" if item.state else "\\RmS=0\\")
            elif isinstance(item, BreakCommand):
                parts.append("\\Pau=%d\\" % item.time)
            elif isinstance(item, RateCommand):
                parts.append("\\Spd=%d\\" % self._scale(item.newValue, 0, 1000))
            elif isinstance(item, PitchCommand):
                parts.append("\\Pit=%d\\" % self._scale(item.newValue, 0, 0xFFFF))
            elif isinstance(item, VolumeCommand):
                v = self._scale(item.newValue, 0, 0xFFFF)
                parts.append("\\Vol=%d\\" % (v | (v << 16)))
        parts.append("\\Pau=1\\")
        return "".join(parts)

    @staticmethod
    def _scale(percent, lo, hi):
        return int(lo + (hi - lo) * (max(0, min(100, percent)) / 100.0))

    def cancel(self):
        # Invalidate the current utterance first so any in-flight audio frames
        # are dropped by the reader, then stop playback immediately (this also
        # unblocks a reader thread that is waiting inside WavePlayer.feed, which
        # is what makes interruption feel instant).
        self._playGen = -1
        self._speaking = False
        self._pendingMarks.clear()
        self._utteranceIndexes = []
        with self._audioCond:
            self._audioQ.clear()
            self._audioCond.notify()
        try:
            if self._player:
                self._player.stop()
        except Exception:
            pass
        try:
            self._link.send("X")
        except Exception:
            pass

    def pause(self, switch):
        try:
            if self._player:
                self._player.pause(switch)
        except Exception:
            pass

    # ---- reader thread: hand audio to the audio thread, control inline ----
    def _readerLoop(self):
        while self._readerAlive:
            try:
                t, payload = self._link.recv_frame()
                if t is None:
                    break
                if t == "A":
                    with self._audioCond:
                        self._audioQ.append(("A", self._inGen, payload))
                        self._audioCond.notify()
                elif t == "B":               # begin utterance <id>
                    (self._inGen,) = struct.unpack("<I", payload)
                elif t == "F":
                    if self._inGen == self._playGen:
                        self._onFormat(payload)
                elif t == "M":
                    if self._inGen == self._playGen:
                        off, num = struct.unpack("<II", payload)
                        self._pendingMarks.append((off, num))
                elif t == "D":               # end utterance <id>
                    (did,) = struct.unpack("<I", payload) if payload else (self._inGen,)
                    with self._audioCond:
                        self._audioQ.append(("D", did))
                        self._audioCond.notify()
                else:  # 'V', 'K', 'E' -> control responses
                    self._ctrl.put((t, payload))
            except Exception:
                log.exception("infovox230 reader error (continuing)")

    # ---- audio thread: the ONLY place WavePlayer.feed() is called ----
    def _audioThreadFunc(self):
        while self._audioAlive:
            item = None
            with self._audioCond:
                if self._audioQ:
                    item = self._audioQ.popleft()
                else:
                    self._audioCond.wait(0.02)
            if item is None:
                # idle: flush so chunk-finished callbacks fire, then see if the
                # current utterance has fully drained.
                if self._player and (self._fedBytes > self._playedBytes
                                     or self._doneGen is not None):
                    try:
                        self._player.feed(None, 0, None)
                    except Exception:
                        pass
                self._checkDone()
                continue
            try:
                if item[0] == "A":
                    _, gen, chunk = item
                    if gen == self._playGen and self._player and chunk:
                        size = len(chunk)
                        self._fedBytes += size
                        self._player.feed(chunk, size,
                                          lambda s=size: self._onChunkPlayed(s))
                elif item[0] == "D":
                    _, gen = item
                    if gen == self._playGen:
                        self._doneGen = gen
                        self._checkDone()
            except Exception:
                log.exception("infovox230 audio error (continuing)")

    def _onChunkPlayed(self, size):
        # Called by WavePlayer when a chunk finishes; updates progress + marks.
        self._playedBytes += size
        self._fireMarks()

    def _fireMarks(self):
        while self._pendingMarks and self._pendingMarks[0][0] <= self._playedBytes:
            _off, num = self._pendingMarks.popleft()
            synthIndexReached.notify(synth=self, index=num)
            try:
                self._utteranceIndexes.remove(num)
            except ValueError:
                pass

    def _checkDone(self):
        # Fire synthDoneSpeaking once the utterance's audio has all played.
        if (self._doneGen is not None and self._doneGen == self._playGen
                and self._playedBytes >= self._fedBytes):
            self._doneGen = None
            self._fireMarks()
            # drain any engine bookmarks not yet reached by playback...
            while self._pendingMarks:
                _off, num = self._pendingMarks.popleft()
                synthIndexReached.notify(synth=self, index=num)
                try:
                    self._utteranceIndexes.remove(num)
                except ValueError:
                    pass
            # ...then fire any indexes the engine never bookmarked at all
            # (e.g. say-all's audio-less callback chunks), in order, so NVDA's
            # lineReached callbacks always advance and say-all never stalls.
            for num in self._utteranceIndexes:
                synthIndexReached.notify(synth=self, index=num)
            self._utteranceIndexes = []
            self._speaking = False
            synthDoneSpeaking.notify(synth=self)
