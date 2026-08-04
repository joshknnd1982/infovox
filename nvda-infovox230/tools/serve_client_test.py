#!/usr/bin/env python3
"""Exercise the host 'serve' protocol exactly as the NVDA driver does (minus
nvwave playback): spawn the host, list voices, select one, speak, collect the
streamed PCM, and write a WAV. Validates the socket bridge before NVDA."""
import os, sys, json, socket, struct, subprocess, time, wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "addon", "synthDrivers", "infovox230", "python32", "python.exe")
HOST = os.path.join(ROOT, "host", "infovox_host.py")
MODES = os.path.join(ROOT, "addon", "synthDrivers", "infovox230", "modes.json")
ENG = sys.argv[1] if len(sys.argv) > 1 else r"C:\infovox230sc"
PORT = 8770
OUT = os.path.join(ROOT, "_run", "serve_test.wav")


def send(s, t, payload=b""):
    if isinstance(payload, str): payload = payload.encode("utf-8")
    s.sendall(t.encode() + struct.pack("<I", len(payload)) + payload)

def recv_exact(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c: return None
        b += c
    return b

def recv_frame(s):
    h = recv_exact(s, 5)
    if not h: return None, None
    t = h[0:1].decode(); (ln,) = struct.unpack("<I", h[1:5])
    return t, (recv_exact(s, ln) if ln else b"")


def main():
    args = [PY, HOST, "--engine-dir", ENG, "--modes", MODES,
            "--log", os.path.join(ROOT, "_run", "serve_host.log"), "--debug",
            "serve", "--port", str(PORT)]
    print("spawning host:", args)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ready = False
    for _ in range(400):
        line = p.stdout.readline()
        if not line: break
        line = line.decode("utf-8", "replace").strip()
        if line: print("host:", line)
        if line.startswith("READY"):
            ready = True; break
    if not ready:
        print("HOST FAILED TO START"); return 2
    s = socket.create_connection(("127.0.0.1", PORT), timeout=15)

    send(s, "L")
    t, pl = recv_frame(s)
    voices = json.loads(pl.decode())
    print("voices:", len(voices))
    vid = voices[3]["id"] if len(voices) > 3 else voices[0]["id"]
    print("selecting:", voices[3]["name"] if len(voices) > 3 else voices[0]["name"])

    send(s, "S", vid)
    t, pl = recv_frame(s)
    print("select ack:", t, pl.decode())

    # apply a moderate rate (25%) to check the mapping isn't extreme
    send(s, "P", json.dumps({"rate": 25, "pitch": 50, "volume": 90}))
    t, pl = recv_frame(s)
    print("param ack:", t)

    send(s, "T", json.dumps({"text": r"\mrk=1\ First sentence. \mrk=2\ Second sentence. \mrk=3\ Third sentence. \Pau=1\ ", "tagged": True, "id": 1}))
    pcm = bytearray(); fmt = None; marks = []
    while True:
        t, pl = recv_frame(s)
        if t is None: break
        if t == "F": fmt = json.loads(pl.decode()); print("format:", fmt)
        elif t == "A": pcm += pl
        elif t == "M": marks.append(struct.unpack("<II", pl))
        elif t == "D": break
        elif t == "E": print("ERROR:", pl.decode()); break
    send(s, "Q"); s.close()
    try: p.wait(timeout=5)
    except Exception: p.terminate()

    if pcm and fmt:
        with wave.open(OUT, "wb") as w:
            w.setnchannels(fmt["channels"]); w.setsampwidth(fmt["bits"]//8)
            w.setframerate(fmt["rate"]); w.writeframes(bytes(pcm))
        print("OK wrote %s (%d bytes, %.2fs, marks=%d)" % (
            OUT, len(pcm), len(pcm)/(fmt["rate"]*fmt["channels"]*fmt["bits"]//8), len(marks)))
        return 0
    print("NO AUDIO via serve protocol"); return 3

if __name__ == "__main__":
    sys.exit(main())
