#!/usr/bin/env python3
"""Generate modes.reg: the Infovox 230 standard voice table, reconstructed from
the engine's ReadMode requirements (BaseGUID + ModeGUID mandatory; language,
speaker, prosody optional) and the installer's language->rule-file mapping.

The engine (32-bit) reads these from HKLM\\SOFTWARE\\Babel-Infovox AB\\Infovox
230\\Modes, which on 64-bit Windows is HKLM\\SOFTWARE\\WOW6432Node\\...
BaseGUID is the engine's sole base GUID found in Ivx230nt.dll.
"""
BASE = "{C9C5EDA0-7C89-11D0-0100-000000000000}"

# (voice name, LCID decimal, rule file, gender[1=male,2=female], speaker)
VOICES = [
    ("American English", 1033, "amrules.ivx", 1, "US English"),
    ("British English",  2057, "blrules.ivx", 1, "British English"),
    ("German",           1031, "gerules.ivx", 1, "Deutsch"),
    ("French",           1036, "frrules.ivx", 1, "Francais"),
    ("Italian",          1040, "itrules.ivx", 1, "Italiano"),
    ("Spanish",          1034, "sprules.ivx", 1, "Espanol"),
    ("Dutch",            1043, "durules.ivx", 1, "Nederlands"),
    ("Danish",           1030, "darules.ivx", 1, "Dansk"),
    ("Norwegian",        1044, "norules.ivx", 1, "Norsk"),
    ("Swedish",          1053, "swrules.ivx", 1, "Svenska"),
    ("Finnish",          1035, "firules.ivx", 1, "Suomi"),
    ("Icelandic",        1039, "icrules.ivx", 1, "Islenska"),
]

def modeguid(n):
    # {C9C5EDA0-7C89-11D0-03NN-000000000000}
    return "{C9C5EDA0-7C89-11D0-03%02X-000000000000}" % n

def emit(hive):
    out = []
    root = r"%s\Babel-Infovox AB\Infovox 230\Modes" % hive
    out.append("[%s]" % root)
    out.append("")
    for i, (name, lcid, rule, gender, speaker) in enumerate(VOICES, start=1):
        out.append("[%s\\%s]" % (root, name))
        out.append('"BaseGUID"="%s"' % BASE)
        out.append('"ModeGUID"="%s"' % modeguid(i))
        out.append('"Name"="%s"' % name)
        out.append('"LanguageID"="%d"' % lcid)
        out.append('"LanguageFile"="%s"' % rule)
        out.append('"Gender"="%d"' % gender)
        out.append('"SpeakerName"="%s"' % speaker)
        out.append('"SpeakerStyle"="Standard"')
        out.append("")
    return "\n".join(out)

reg = "Windows Registry Editor Version 5.00\r\n\r\n"
# write to both the 32-bit (WOW6432Node) view the engine actually reads and the
# plain view, to be safe.
reg += emit(r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node").replace("\n", "\r\n") + "\r\n"
reg += emit(r"HKEY_LOCAL_MACHINE\SOFTWARE").replace("\n", "\r\n") + "\r\n"

open("_run/modes.reg", "w", encoding="utf-16").write(reg)
print("wrote _run/modes.reg with %d voices" % len(VOICES))
