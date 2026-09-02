#!/usr/bin/env python3
"""Strip the base-relocation table from Ivx230nt.dll so Windows is forced to
load the engine at its preferred image base, 0x10000000.

Why this is needed
------------------
The engine stores absolute addresses that its own relocation table does not
cover, so it is only correct when it lands at 0x10000000. Windows will happily
relocate it somewhere else -- and on machines with mandatory ASLR (Exploit
Protection's "Force randomization for images" / ForceRelocateImages, which is
on by default in some hardened and managed configurations) it always does. The
engine then reads through stale absolute pointers and the 32-bit host dies with
an access violation, 0xC0000005, on the very first synthesis call.

A PE with IMAGE_FILE_RELOCS_STRIPPED set cannot be moved: the loader must map
it at its preferred base or fail the load outright. Failing loudly is exactly
what we want, and the host checks for it (see Engine.load in host/infovox_host.py,
which refuses to run if the module lands anywhere but 0x10000000).

What it changes
---------------
Two fields, five bytes total, both in the PE headers -- no code is touched:

  * COFF Characteristics  |= 0x0001 (IMAGE_FILE_RELOCS_STRIPPED)
  * Data directory 5 (IMAGE_DIRECTORY_ENTRY_BASERELOC) RVA and Size -> 0

The .reloc section data is deliberately left in the file. Nothing reads it once
the directory entry is cleared, and leaving it keeps every other RVA, file
offset and section boundary in the image unchanged -- including the dongle
patch offset used by apply_engine_patch.py.

This is independent of, and composes with, the dongle bypass: the emulated
sx32w.dll (sx32w_stub/) or apply_engine_patch.py handle the licence check;
this handles image placement.

Usage:  python strip_engine_relocs.py path\to\Ivx230nt.dll
Writes Ivx230nt.dll.norelocs (does not modify the original).
"""
import sys
import struct
import hashlib

IMAGE_FILE_RELOCS_STRIPPED = 0x0001
# Ivx230nt.dll v2.2 (Feb 2002), as shipped in Infovox230v2_2complete.exe.
KNOWN_MD5_ORIGINAL = "a57c1ef2757d412fd92b8077ba399613"
# The same file after this script has run; this is what the add-on ships.
KNOWN_MD5_STRIPPED = "0f1ed1289088c3fdad810c71eb0d5d3c"
REQUIRED_BASE = 0x10000000


def strip(data):
    """Return (patched bytes, list of human-readable changes)."""
    data = bytearray(data)
    if data[:2] != b"MZ":
        raise ValueError("not an MZ image")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise ValueError("no PE signature at e_lfanew")

    # COFF header: 4-byte signature, then Machine, NumberOfSections, ...,
    # SizeOfOptionalHeader (2), Characteristics (2) at +18.
    off_chars = e_lfanew + 4 + 18
    chars = struct.unpack_from("<H", data, off_chars)[0]

    # Optional header starts right after the 20-byte COFF header.
    opt = e_lfanew + 4 + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x10B:
        raise ValueError("expected a PE32 (0x10B) image, got 0x%X" % magic)
    base = struct.unpack_from("<I", data, opt + 28)[0]  # ImageBase
    # PE32 data directories begin at optional-header offset 96;
    # entry 5 is IMAGE_DIRECTORY_ENTRY_BASERELOC, 8 bytes (RVA, Size).
    off_reloc_dir = opt + 96 + 5 * 8
    rva, size = struct.unpack_from("<II", data, off_reloc_dir)

    changes = []
    if base != REQUIRED_BASE:
        raise ValueError("ImageBase is 0x%08X, expected 0x%08X" % (base, REQUIRED_BASE))
    if not (chars & IMAGE_FILE_RELOCS_STRIPPED):
        struct.pack_into("<H", data, off_chars, chars | IMAGE_FILE_RELOCS_STRIPPED)
        changes.append("Characteristics 0x%04X -> 0x%04X at file offset 0x%X"
                       % (chars, chars | IMAGE_FILE_RELOCS_STRIPPED, off_chars))
    if rva or size:
        struct.pack_into("<II", data, off_reloc_dir, 0, 0)
        changes.append("BASERELOC directory RVA=0x%X size=0x%X -> 0/0 at file offset 0x%X"
                       % (rva, size, off_reloc_dir))
    return bytes(data), changes


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    original = open(src, "rb").read()
    md5 = hashlib.md5(original).hexdigest()
    print("file      :", src)
    if md5 == KNOWN_MD5_ORIGINAL:
        print("md5       :", md5, "(known original)")
    elif md5 == KNOWN_MD5_STRIPPED:
        print("md5       :", md5, "(already stripped)")
    else:
        print("md5       :", md5, "(unrecognized build!)")

    patched, changes = strip(original)
    if not changes:
        print("Already stripped; nothing to do.")
        return 0
    for c in changes:
        print("changed   :", c)

    out = src + ".norelocs"
    with open(out, "wb") as f:
        f.write(patched)
    got = hashlib.md5(patched).hexdigest()
    print("wrote     :", out)
    print("result md5:", got,
          "(matches the shipped engine)" if got == KNOWN_MD5_STRIPPED else "")
    print("Replace Ivx230nt.dll with this file; it must then load at 0x%08X."
          % REQUIRED_BASE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
