#!/usr/bin/env python3
"""Rebuild the Infovox 230 .nvda-addon from the addon/ tree.

An NVDA add-on is simply a zip of the add-on folder with manifest.ini at its
root. This script packages nvda-infovox230/addon/ into
    infovox230-<version>.nvda-addon
where <version> is read from addon/manifest.ini.

Usage (from the nvda-infovox230/ directory):
    python build.py

It also keeps the bundled 32-bit host in sync: host/infovox_host.py is the
canonical copy you edit, and it is copied into
addon/synthDrivers/infovox230/host/ before packaging so the two never drift.

Requires only Python 3 (standard library). You do NOT need a separate 32-bit
Python to build or run the add-on -- one is bundled inside addon/.
"""
import os
import re
import sys
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, "addon")


def main():
    if not os.path.isdir(ADDON):
        sys.exit("error: addon/ not found -- run this from nvda-infovox230/")

    # Keep the bundled host copy identical to the canonical source in host/.
    canonical = os.path.join(HERE, "host", "infovox_host.py")
    bundled = os.path.join(ADDON, "synthDrivers", "infovox230", "host",
                           "infovox_host.py")
    if os.path.exists(canonical):
        os.makedirs(os.path.dirname(bundled), exist_ok=True)
        shutil.copyfile(canonical, bundled)
        print("synced host -> %s" % os.path.relpath(bundled, HERE))

    # Read the add-on version from the manifest.
    version = "0.1"
    with open(os.path.join(ADDON, "manifest.ini"), encoding="utf-8") as f:
        m = re.search(r"^\s*version\s*=\s*(.+)$", f.read(), re.MULTILINE)
        if m:
            version = m.group(1).strip().strip('"')

    out = os.path.join(HERE, "infovox230-%s.nvda-addon" % version)
    if os.path.exists(out):
        os.remove(out)

    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(ADDON):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, ADDON))
                count += 1

    print("built %s (%d files, %.1f MB)"
          % (os.path.relpath(out, HERE), count, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
