# Contributing

Thanks for your interest in improving the Infovox 230 NVDA add-on. Contributions
of all kinds — bug fixes, new features, documentation, and testing — are
welcome.

## License

The code written for this project is **MIT** (see [`LICENSE`](LICENSE)). By
contributing, you agree that your contributions are licensed under the same
terms. The exceptions are the files derived from NVDA (the driver, the host and
the SAPI 4 interface file, listed in [`NOTICE.md`](NOTICE.md)), which stay under
the **GPL v2**; changes to those files are under the GPL v2. The Infovox
engine is included with its maintainer's permission; the third-party binaries preserved from the
original installer keep their own licenses.

## How to contribute

1. **Fork** the repository on GitHub.
2. Create a branch: `git checkout -b my-fix`.
3. Make your change and test it in NVDA (see [`BUILDING.md`](BUILDING.md)).
4. Commit and push to your fork.
5. Open a **pull request** describing what you changed and how you tested it
   (which NVDA version, which voices/languages).

Found a bug but not ready to fix it? Open an **issue** — a clear report with
your NVDA version and steps to reproduce is a real contribution on its own.

## Project layout

See [`README.md`](README.md) for the overview and
[`nvda-infovox230/ARCHITECTURE.md`](nvda-infovox230/ARCHITECTURE.md) for how the
64↔32-bit bridge and the engine patches work. In short:

- `nvda-infovox230/addon/synthDrivers/infovox230.py` — the 64-bit driver NVDA
  loads.
- `nvda-infovox230/host/infovox_host.py` — the 32-bit host that drives the SAPI4
  engine.
- The two communicate over a small localhost socket protocol. **If you change
  one side of the protocol, change the other to match.**

## Building and testing

[`BUILDING.md`](BUILDING.md) has the full steps. The short version: edit under
`nvda-infovox230/`, run `python build.py` from that folder, install the
resulting `.nvda-addon` in NVDA, and try speech, say-all, capitals, and a few
voices before opening a PR.

## A few notes

- Keep the driver 64-bit-safe and the host 32-bit-safe (it uses `comtypes`
  against the 32-bit engine).
- Match the existing code style and keep the license headers intact.
- Please don't commit rebuilt copies of the bundled binaries unless the change
  is intentional and explained in the PR.
