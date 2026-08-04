#!/usr/bin/env python3
"""Assemble infovox230-<ver>.nvda-addon from the addon/ tree + engine payload.

Stages, under addon/synthDrivers/infovox230/:
    engine/   Ivx230nt.dll, every *.IVX rule file, darules.dll, Sx32w.dll (emulator)
    host/     infovox_host.py, _sapi4.py
    python32/ (only if already fetched; otherwise the driver falls back to py -3-32)
then zips the addon/ contents (manifest.ini at the root) into the .nvda-addon.
"""
import os, sys, shutil, zipfile, glob, configparser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # nvda-infovox230
PROJ = os.path.dirname(ROOT)                                         # project root (engine files)
ADDON = os.path.join(ROOT, "addon")
PKG = os.path.join(ADDON, "synthDrivers", "infovox230")
ENGINE = os.path.join(PKG, "engine")
HOSTD = os.path.join(PKG, "host")

def stage():
    os.makedirs(ENGINE, exist_ok=True)
    os.makedirs(HOSTD, exist_ok=True)
    # engine DLL (prefer project root, else the unpacked installer tree)
    dll = os.path.join(PROJ, "Ivx230nt.dll")
    if not os.path.exists(dll):
        alt = os.path.join(PROJ, "data1", "Infovox_230_TTS_Engine_Files_NT", "Ivx230nt.dll")
        dll = alt if os.path.exists(alt) else dll
    shutil.copy2(dll, os.path.join(ENGINE, "Ivx230nt.dll"))
    # every rule file
    n = 0
    for pat in ("*.IVX", "*.ivx"):
        for f in glob.glob(os.path.join(PROJ, pat)):
            shutil.copy2(f, os.path.join(ENGINE, os.path.basename(f))); n += 1
    # danish helper dll, if present
    dar = os.path.join(PROJ, "darules.dll")
    if os.path.exists(dar):
        shutil.copy2(dar, os.path.join(ENGINE, "darules.dll"))
    # dongle emulator (validated), under both casings the loader might request
    emu = os.path.join(ROOT, "sx32w_stub", "sx32w.dll")
    for name in ("Sx32w.dll",):
        shutil.copy2(emu, os.path.join(ENGINE, name))
    # host scripts
    for f in ("infovox_host.py", "_sapi4.py"):
        shutil.copy2(os.path.join(ROOT, "host", f), os.path.join(HOSTD, f))
    print("staged engine: %s (%d rule files)" % (ENGINE, n))

def version():
    cp = configparser.ConfigParser()
    # manifest.ini isn't strict ini (has triple-quoted desc); read version line
    ver = "0.1"
    for line in open(os.path.join(ADDON, "manifest.ini"), encoding="utf-8"):
        if line.strip().startswith("version"):
            ver = line.split("=", 1)[1].strip()
            break
    return ver

def build():
    stage()
    ver = version()
    out = os.path.join(ROOT, "infovox230-%s.nvda-addon" % ver)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(ADDON):
            for fn in files:
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, ADDON)   # manifest.ini at zip root
                z.write(full, rel)
    mb = os.path.getsize(out) / 1e6
    print("wrote %s (%.1f MB)" % (out, mb))
    return out

if __name__ == "__main__":
    build()
