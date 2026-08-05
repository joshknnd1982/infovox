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
import time
import locale
import queue
import struct
import socket
import threading
import subprocess
from collections import OrderedDict, deque

import config
import nvwave
import languageHandler
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
#: Ports tried in turn when (re)starting the host. A restarted host must not
#: collide with the previous one still shutting down and holding the old port.
PORT_RANGE = 20
#: Give up on an utterance that has produced nothing for this long and treat
#: the host as wedged. Longer than the host's own 30s TextData timeout so the
#: host gets to self-heal first.
STUCK_TIMEOUT = 35.0


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
        self._port = PORT
        self._drainer = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        last = None
        for attempt in range(PORT_RANGE):
            port = PORT + (self._port - PORT + attempt) % PORT_RANGE
            try:
                self._startOn(port)
                self._port = PORT + (port - PORT + 1) % PORT_RANGE
                return
            except Exception as e:
                last = e
                log.debugWarning("infovox230: host start on port %d failed: %s"
                                 % (port, e))
                self.stop()
        raise RuntimeError("Infovox host failed to start (see infovox230/host.log): %s"
                           % (last,))

    def _startOn(self, port):
        args = _find_python32() + [
            HOST_SCRIPT, "--engine-dir", ENGINE_DIR,
            "--log", os.path.join(PKG_DIR, "host.log"),
            "serve", "--port", str(port),
        ]
        log.info("infovox230: launching host on port %d: %r", port, args)
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
            raise RuntimeError("host did not report READY")
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        # Keep draining the host's stdout/stderr for the rest of its life. The
        # pipe holds only a few KB: once full, the host BLOCKS on its next
        # write -- mid-utterance, forever -- and speech dies with no error
        # anywhere. Reading until READY and then walking away (as this used to)
        # left that hazard armed for every byte the engine or Python wrote
        # afterwards.
        self._drainer = threading.Thread(target=self._drainStdout,
                                         args=(self.proc,),
                                         name="infovox230HostOut", daemon=True)
        self._drainer.start()

    @staticmethod
    def _drainStdout(proc):
        try:
            for line in iter(proc.stdout.readline, b""):
                line = line.decode("utf-8", "replace").rstrip()
                if line:
                    log.debug("infovox230 host: %s", line)
        except Exception:
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass

    def send(self, t, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        with self._wlock:
            sock = self.sock
            if sock is None:
                raise OSError("infovox230: host link is down")
            sock.sendall(t.encode("ascii") + struct.pack("<I", len(payload)) + payload)

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
            sock = self.sock
            if sock is None:
                return None
            try:
                chunk = sock.recv(n - len(buf))
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
        self.sock = None
        proc, self.proc = self.proc, None
        try:
            if proc:
                proc.terminate()
        except Exception:
            pass
        # Reap it, so a wedged host can't linger holding its port or the engine.
        try:
            if proc:
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
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
        # Host recovery state. If the host process dies or wedges, the driver
        # restarts it in place and restores the voice and parameters, so speech
        # comes back on its own instead of needing a manual synth switch.
        self._recoverLock = threading.RLock()
        self._recovering = False
        self._recoverWhy = ""
        self._speakStarted = 0.0         # when the current utterance was sent
        self._lastRecover = 0.0
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

    # ---- host recovery ----------------------------------------------------
    def _requestRecover(self, why):
        """Ask for the host to be restarted. Callable from any thread.

        The restart itself is always performed by the reader thread (it owns
        all socket reads), so this just records the reason and drops the
        socket, which wakes the reader out of recv immediately."""
        with self._recoverLock:
            if self._recovering or not self._readerAlive:
                return
            self._recovering = True
            self._recoverWhy = why
        log.warning("infovox230: host restart requested (%s)", why)
        self._releaseSpeech()             # never leave NVDA waiting on us
        try:
            self._link.stop()             # unblocks the reader thread
        except Exception:
            pass

    def _doRecover(self):
        """Restart the host and put it back exactly where it was: same voice,
        same rate/pitch/volume. This is the in-place equivalent of switching
        synthesizer and switching back -- which is what the user previously had
        to do by hand. READER THREAD ONLY."""
        with self._recoverLock:
            why = getattr(self, "_recoverWhy", "link lost")
            self._recovering = True
        # Never spin: if the host refuses to stay up, back off between tries.
        wait = 3.0 - (time.time() - self._lastRecover)
        if wait > 0:
            time.sleep(wait)
        self._lastRecover = time.time()
        ok = False
        try:
            log.warning("infovox230: restarting host (%s)", why)
            self._playGen = -1
            self._releaseSpeech()
            try:
                self._link.stop()
            except Exception:
                pass
            while True:
                try:
                    self._ctrl.get_nowait()   # discard stale control responses
                except queue.Empty:
                    break
            if not self._readerAlive:
                return False       # terminated while we were tearing down
            self._link.start()
            if not self._readerAlive:
                self._link.stop()  # driver shut down mid-restart; don't orphan it
                return False
            self._selectVoice(self._voice, sync=True)  # re-pushes rate/pitch/volume
            ok = True
            log.info("infovox230: host restarted; speech restored")
        except Exception:
            log.exception("infovox230: host restart failed; will retry")
        finally:
            with self._recoverLock:
                self._recovering = False
        return ok

    def _syncRequest(self, t, payload=b"", timeout=15):
        """Send a control frame and read its reply straight off the socket.
        READER THREAD ONLY -- during recovery the queue-based _request() would
        deadlock, because the thread that feeds that queue is the one doing the
        recovering."""
        self._link.send(t, payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            rt, rp = self._link.recv_frame()
            if rt is None:
                raise RuntimeError("infovox230: link closed during %r" % t)
            if rt in ("K", "E", "V"):
                return rt, rp
            # anything else is leftover audio from the fresh host: drop it
        raise RuntimeError("infovox230: timed out waiting for %r response" % t)

    def _releaseSpeech(self):
        """Unblock NVDA after a lost utterance: fire the indexes it is waiting
        on and then synthDoneSpeaking, otherwise say-all stalls forever."""
        with self._audioCond:
            self._audioQ.clear()
        self._pendingMarks.clear()
        indexes, self._utteranceIndexes = self._utteranceIndexes, []
        self._doneGen = None
        wasSpeaking = self._speaking
        self._speaking = False
        try:
            for num in indexes:
                synthIndexReached.notify(synth=self, index=num)
        except Exception:
            pass
        if wasSpeaking:
            try:
                synthDoneSpeaking.notify(synth=self)
            except Exception:
                pass

    # ---- request/response over the control queue ----
    def _request(self, t, payload=b"", expect=("K", "E", "V"), timeout=15):
        while True:
            try:
                self._ctrl.get_nowait()   # a late reply must not answer this one
            except queue.Empty:
                break
        self._link.send(t, payload)
        try:
            rt, rp = self._ctrl.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("infovox230: timed out waiting for %r response" % t)
        return rt, rp

    # ---- voices ----
    @staticmethod
    def _localeFromLangid(langid):
        """Map a SAPI4 LANGID (a WORD) to a Windows locale name like "sv_SE".
        Old SAPI4 engines are sloppy with sublanguage bits, so unknown ids are
        retried with SUBLANG_DEFAULT and finally reduced to the bare primary
        language ("sv"). Returns None only when the id is missing or truly
        unknown; callers must treat None as "language not known"."""
        try:
            langid = int(langid)
        except (TypeError, ValueError):
            return None
        if langid <= 0:
            return None
        lang = locale.windows_locale.get(langid)
        if lang:
            return lang
        primary = langid & 0x3FF
        # MAKELANGID(primary, SUBLANG_DEFAULT): SUBLANG_DEFAULT (1) << 10
        lang = locale.windows_locale.get(0x0400 | primary)
        if lang:
            return lang
        for lid, name in sorted(locale.windows_locale.items()):
            if lid & 0x3FF == primary:
                return name.split("_")[0]
        return None

    def _loadVoices(self):
        rt, rp = self._request("L")
        if rt != "V":
            raise RuntimeError("expected voice list, got %r" % rt)
        arr = json.loads(rp.decode("utf-8"))
        voices = OrderedDict()
        for v in arr:
            vid = v["id"]
            name = v["name"] or v["product"] or vid
            if v.get("speaker") and v["speaker"] not in name:
                name = "%s (%s)" % (name, v["speaker"])
            language = self._localeFromLangid(v.get("langid"))
            if not language:
                log.debugWarning(
                    "infovox230: no locale for voice %r (langid=%r)"
                    % (name, v.get("langid")))
            voices[vid] = VoiceInfo(vid, name, language)
        log.info("infovox230: %d voices enumerated", len(voices))
        return voices

    def _getAvailableVoices(self):
        return self._voices

    def _get_availableLanguages(self):
        # NVDA 2026.1's SynthDriver.languageIsSupported() calls
        # languageHandler.normalizeLanguage() on every member of this set
        # without a None guard; a single voice whose language is unknown then
        # crashes the getSpeechSequenceWithLangs speech filter on every
        # utterance ("AttributeError: 'NoneType' object has no attribute
        # 'replace'"). Never expose unknown (None/empty) languages.
        return {v.language for v in self._voices.values() if v.language}

    def languageIsSupported(self, lang):
        # Replaces the base implementation, which in NVDA 2026.1 assumes every
        # available language is a normalizable string. This runs inside NVDA's
        # speech filter for every utterance, so it must never raise.
        try:
            if lang is None:
                return True
            normalized = languageHandler.normalizeLanguage(lang)
            if not normalized:
                return False
            available = self.availableLanguages
            if not available:
                # The engine reported no usable language metadata at all;
                # claiming "unsupported" would just make NVDA announce
                # "(not supported)" before most foreign text. Stay quiet.
                return True
            root = normalized.split("_")[0]
            for availableLang in available:
                if not availableLang:
                    continue
                normalizedAvailable = languageHandler.normalizeLanguage(
                    availableLang)
                if not normalizedAvailable:
                    continue
                if (normalized == normalizedAvailable
                        or root == normalizedAvailable.split("_")[0]):
                    return True
            return False
        except Exception:
            log.debugWarning("infovox230: languageIsSupported failed",
                             exc_info=True)
            return True

    def _get_voice(self):
        return self._voice

    def _set_voice(self, value):
        if value not in self._voices:
            return
        self._voice = value
        try:
            self._selectVoice(value)
        except Exception:
            log.warning("infovox230: voice select failed", exc_info=True)
            self._requestRecover("voice select failed")

    def _selectVoice(self, vid, sync=False):
        # sync=True is the recovery path: the reader thread does its own socket
        # reads, because it is the thread that would otherwise be feeding the
        # response queue it is waiting on.
        req = self._syncRequest if sync else self._request
        rt, rp = req("S", vid)
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
            self._pushParams(sync=sync)
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
    def _setParam(self, **kw):
        """Push one parameter. A dead or wedged host must not turn a slider
        nudge into an exception in NVDA's settings UI; ask for a restart and
        carry on, and the value is re-applied once the host is back."""
        try:
            self._request("P", json.dumps(kw))
        except Exception:
            log.warning("infovox230: setting %s failed", ", ".join(kw),
                        exc_info=True)
            self._requestRecover("parameter update failed")

    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        self._rate = max(0, min(100, value))
        self._setParam(rate=self._rate)

    def _get_pitch(self):
        return self._pitch

    def _set_pitch(self, value):
        self._pitch = max(0, min(100, value))
        self._setParam(pitch=self._pitch)

    def _get_volume(self):
        return self._volume

    def _set_volume(self, value):
        self._volume = max(0, min(100, value))
        self._setParam(volume=self._volume)

    def _pushParams(self, sync=False):
        req = self._syncRequest if sync else self._request
        req("P", json.dumps(
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
        self._speakStarted = time.time()
        # make sure the player is ready to accept a fresh utterance
        try:
            if self._player:
                self._player.pause(False)
        except Exception:
            pass
        payload = json.dumps({"text": tagged, "tagged": True, "id": gen})
        try:
            self._link.send("T", payload)
        except Exception:
            # The host died or its socket is gone. Get it restarted; this
            # utterance is lost, but speech resumes by itself from the next one
            # instead of staying dead until the user switches synthesizer.
            self._requestRecover("send failed")

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
        self._speakStarted = 0.0
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
                    # Socket closed: the host exited, was killed, or a wedge was
                    # detected and someone dropped the link on purpose. Bringing
                    # it back here is what stops "it just went silent" from being
                    # permanent -- this loop used to simply break, leaving the
                    # driver alive but deaf until the user switched synths.
                    if not self._readerAlive:
                        break
                    self._doRecover()
                    continue
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
                self._checkStuck()
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

    def _checkStuck(self):
        """Watchdog. If an utterance was sent and the host has neither streamed
        audio nor reported 'D' within STUCK_TIMEOUT, or the host process has
        exited outright, the link is wedged: restart it. This is the backstop
        that makes silence self-correcting no matter what caused it."""
        if not self._speaking or self._recovering:
            return
        started = self._speakStarted
        if not started:
            return
        stalled = (time.time() - started > STUCK_TIMEOUT
                   and self._fedBytes == 0 and self._doneGen is None)
        if stalled:
            self._requestRecover("no audio for %.0fs" % STUCK_TIMEOUT)
        elif not self._link.alive():
            self._requestRecover("host process exited")

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
            self._speakStarted = 0.0
            synthDoneSpeaking.notify(synth=self)
