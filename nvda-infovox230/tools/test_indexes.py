#!/usr/bin/env python3
"""Unit-test the driver's index/done guarantee WITHOUT NVDA: stub the NVDA
imports, load the real infovox230.py, create a SynthDriver instance without
running __init__, and drive the real _onChunkPlayed / _fireMarks / _checkDone
through the exact situations NVDA say-all produces.

The bug being guarded against: say-all only advances to the next line when the
synth fires synthIndexReached for that line's callback mark. The engine will not
emit a bookmark for an audio-less 'callback-only' chunk, so that index must be
fired as a fallback when the utterance finishes -- otherwise say-all stalls.
"""
import os, sys, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addon", "synthDrivers"))

# ---- record every notification the driver emits ----
FIRED = []           # ("index", n) / ("done",)

def _mk_notifier(kind):
    class _N:
        @staticmethod
        def notify(**kw):
            FIRED.append((kind, kw.get("index")))
    return _N()

# ---- minimal stubs for the NVDA modules the driver imports ----
config = types.ModuleType("config"); config.conf = {}
nvwave = types.ModuleType("nvwave"); nvwave.WavePlayer = object
logHandler = types.ModuleType("logHandler")
logHandler.log = types.SimpleNamespace(
    debug=lambda *a, **k: None, info=lambda *a, **k: None,
    warning=lambda *a, **k: None, error=lambda *a, **k: None,
    exception=lambda *a, **k: None)

sdh = types.ModuleType("synthDriverHandler")
class _Base:
    @staticmethod
    def VoiceSetting(*a, **k): return None
    @staticmethod
    def RateSetting(*a, **k): return None
    @staticmethod
    def PitchSetting(*a, **k): return None
    @staticmethod
    def VolumeSetting(*a, **k): return None
sdh.SynthDriver = _Base
sdh.VoiceInfo = object
sdh.synthIndexReached = _mk_notifier("index")
sdh.synthDoneSpeaking = _mk_notifier("done")

speech = types.ModuleType("speech")
cmds = types.ModuleType("speech.commands")
class IndexCommand:
    def __init__(self, index): self.index = index
for _n in ("CharacterModeCommand", "BreakCommand", "PitchCommand",
           "RateCommand", "VolumeCommand"):
    setattr(cmds, _n, type(_n, (), {}))
cmds.IndexCommand = IndexCommand
speech.commands = cmds

for _m, _o in {"config": config, "nvwave": nvwave, "logHandler": logHandler,
               "synthDriverHandler": sdh, "speech": speech,
               "speech.commands": cmds}.items():
    sys.modules[_m] = _o

import infovox230  # the real driver

Drv = infovox230.SynthDriver
IndexCommand = infovox230.IndexCommand


def fresh():
    """A driver instance with just the fields the audio/done path touches."""
    d = Drv.__new__(Drv)
    from collections import deque
    d._pendingMarks = deque()
    d._utteranceIndexes = []
    d._playedBytes = 0
    d._fedBytes = 0
    d._doneGen = None
    d._playGen = 1
    d._speaking = True
    d._player = True  # truthy; not used on this path
    FIRED.clear()
    return d


def begin(d, seq, fed):
    """Mimic speak(): capture the utterance's indexes and its total byte size."""
    d._utteranceIndexes = [it.index for it in seq if isinstance(it, IndexCommand)]
    d._fedBytes = fed


def play_to(d, byte):
    d._onChunkPlayed(byte - d._playedBytes)  # advances _playedBytes + fires marks


def finish(d):
    d._doneGen = d._playGen
    d._checkDone()


def check(name, expect_indexes):
    idx = [n for k, n in FIRED if k == "index"]
    done = [k for k, _ in FIRED if k == "done"]
    ok = idx == expect_indexes and len(done) == 1
    print(("PASS" if ok else "FAIL"),
          "%-42s fired=%s done=%d expect=%s" % (name, idx, len(done), expect_indexes))
    return ok

allok = True

# A) normal say-all line: engine bookmarks the line-end mark; audio plays past it
d = fresh(); begin(d, ["Hello line.", IndexCommand(5)], fed=100)
d._pendingMarks.append((100, 5))
play_to(d, 100); finish(d)
allok &= check("normal line, engine reports mark", [5])

# B) bare callback-only chunk: NO audio, engine reports NO bookmark -> must still fire
d = fresh(); begin(d, [IndexCommand(7)], fed=0)
finish(d)  # no audio at all
allok &= check("audio-less callback chunk (the stall bug)", [7])

# C) several indexes, engine bookmarks only some -> every one still fires
d = fresh(); begin(d, ["a", IndexCommand(1), "b", IndexCommand(2), "c", IndexCommand(3)], fed=200)
d._pendingMarks.append((50, 1)); d._pendingMarks.append((200, 3))  # 2 never reported
play_to(d, 50); play_to(d, 200); finish(d)
allok &= check("mixed: marks for 1&3, fallback for 2", [1, 3, 2])

# D) a run of say-all lines never stalls: each advances and finishes cleanly
seqs = [(["Para one."], [11]), ([IndexCommand(12)], []), (["Para two."], [13]),
        ([IndexCommand(14)], []), (["Para three."], [15])]
run_ok = True
for text_only, marks in [
        (["Para one.", IndexCommand(11)], [(80, 11)]),
        ([IndexCommand(12)], []),                       # bare callback
        (["Para two.", IndexCommand(13)], [(90, 13)]),
        ([IndexCommand(14)], []),                       # bare callback
        (["Para three.", IndexCommand(15)], [(70, 15)])]:
    d = fresh(); begin(d, text_only, fed=(marks[-1][0] if marks else 0))
    for off, n in marks:
        d._pendingMarks.append((off, n))
        play_to(d, off)
    finish(d)
    got = [n for k, n in FIRED if k == "index"]
    want = [it.index for it in text_only if isinstance(it, IndexCommand)]
    if got != want or not any(k == "done" for k, _ in FIRED):
        run_ok = False; print("  FAIL say-all step", want, "got", got)
print(("PASS" if run_ok else "FAIL"), "say-all run of 5 lines advances every time")
allok &= run_ok

print("\nALL PASS" if allok else "\nFAILURES ABOVE")
sys.exit(0 if allok else 1)
