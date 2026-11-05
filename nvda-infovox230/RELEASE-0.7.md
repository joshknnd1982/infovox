# Infovox 230 for NVDA — v0.7

Follow-up to #10 (v0.5/v0.6): the length-scaled timeout from #10 reduced how
often long text got cut off, but did not remove it, because any fixed
total-time budget for an utterance is wrong for some text — just at a longer
length than before. Investigating a reproduction (one very long sentence with
no internal punctuation) against the add-on's own logs turned up the real
cause: the 32-bit host process was crashing outright, not timing out.
NVDA's log showed the driver reconnecting with an empty failure reason
(`infovox230: restarting host ()`), which only happens when the socket itself
closes — i.e. the host process died — rather than any of the driver's own
named timeout/error paths. `host.log` had nothing in it at the time, which a
native crash explains (nothing Python-level to catch and log) and a timeout
does not (the timeout path always logs first).

## What changed

**Long unbroken runs of text no longer crash the host.** This engine (SAPI4,
late 1990s/early 2000s) evidently has a bounded internal per-sentence buffer;
one long run of text with no sentence-ending punctuation for it to break on
overflows that buffer and brings the whole host process down, losing the
utterance (the add-on's existing self-heal restarts the host afterward, which
is why speech "just stops" for that one utterance and then resumes normally —
no hang, no crash the user sees, just a gap). The driver now inserts a forced,
practically inaudible break (`\Pau=1\`) at the nearest word boundary into any
run of 200+ characters with no sentence-ending punctuation, before the text
ever reaches the engine.

**The host's own synthesis wait is now stall-based, not length-based.**
`Engine.speak()` previously gave up after a fixed, text-length-scaled
deadline (the #10 fix). It now tracks whether the engine is still producing
PCM at all: as long as new audio keeps arriving, however slowly, synthesis is
allowed to continue with no total-time cap; it only gives up after 12s with
*zero new audio*. This is belt-and-suspenders with the break-insertion fix
above (which should prevent the crash that was the actual root cause), but
removes the length-based guessing entirely for whatever's left.

**A user-editable pronunciation dictionary.**
`synthDrivers/infovox230/dictionary.txt`, shipped with commented-out examples.
One `word<TAB>replacement` per line; whole-word, case-insensitive substitution
applied to the text before it reaches the engine — the same idea as eSpeak's
"add word to dictionary" in NVDA, done as plain text substitution since this
bridge exposes no phoneme-level hook into the engine itself.

## Caveat

I could not reproduce or verify any of this on an actual Windows+NVDA
install myself — this was done by analysing the add-on's own logs
(`host.log`, NVDA's log) against the source rather than against a live
repro. The crash theory fits what both logs show, and the fix is a narrow,
low-risk change (only affects very long unbroken runs of text), but it
would help a lot if anyone hitting the original long-text cutoff could
confirm this actually resolves it, or share a `host.log` where it doesn't.
