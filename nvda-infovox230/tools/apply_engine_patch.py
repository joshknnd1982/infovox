#!/usr/bin/env python3
"""Fallback licence bypass: patch Ivx230nt.dll so the SuperPro dongle check
always reports "authorized".

Primary method is the emulated sx32w.dll (drop it next to the engine); use this
only if, on your machine, the engine still refuses to enumerate voices.

The check lives at file offset 0x15b50 (function HwCheck, verified by
disassembly). Original prologue bytes:
    6A FF 68 6B E2 03 10 64      push -1 ; push 0x1003e26b ; ...
We overwrite the first 8 bytes with:
    B8 01 00 00 00 C2 04 00      mov eax,1 ; ret 4
so every language reports authorized without touching the dongle.

Usage:  python apply_engine_patch.py path\\to\\Ivx230nt.dll
Writes Ivx230nt.dll.patched (does not modify the original).
"""
import sys, hashlib, shutil, os

OFFSET = 0x15b50
EXPECTED = bytes.fromhex("6aff686be2031064")
PATCH    = bytes.fromhex("b801000000c20400")
KNOWN_MD5 = "c379f52d1e8191cb3dc1a991d44eb161"  # Ivx230nt.dll v2.2 (Feb 2002)

def main():
    if len(sys.argv) < 2:
        print(__doc__); return 1
    src = sys.argv[1]
    data = bytearray(open(src, "rb").read())
    md5 = hashlib.md5(data).hexdigest()
    print("file      :", src)
    print("md5       :", md5, "(known good)" if md5 == KNOWN_MD5 else "(unrecognized build!)")
    cur = bytes(data[OFFSET:OFFSET+8])
    print("at 0x%05x : %s" % (OFFSET, cur.hex(" ")))
    if cur == PATCH:
        print("Already patched."); return 0
    if cur != EXPECTED:
        print("Bytes do not match the expected prologue; refusing to patch a")
        print("different build. Use the sx32w.dll emulator instead.")
        return 2
    data[OFFSET:OFFSET+8] = PATCH
    out = src + ".patched"
    open(out, "wb").write(data)
    print("wrote     :", out)
    print("Replace Ivx230nt.dll with this file to bypass the dongle in-engine.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
