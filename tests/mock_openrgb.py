#!/usr/bin/env python3
"""Servidor OpenRGB SDK simulado (protocolo 3) para testes.

Uso: mock_openrgb.py <porta> <arquivo de log> [atraso_s] [silent]

Com atraso_s > 0, imita a detecção do OpenRGB real: as memórias aparecem na hora e a
placa-mãe (ventoinhas) só depois desse tempo, com o aviso DEVICE_LIST_UPDATED (100)
enviado a todos os clientes conectados, a menos que o 4º argumento seja "silent".
Cada comando recebido vira uma linha JSON no log.
"""
import json
import socket
import struct
import sys
import threading
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 6742
LOG = sys.argv[2] if len(sys.argv) > 2 else "/tmp/mock_openrgb.log"
DELAY = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
SILENT = len(sys.argv) > 4 and sys.argv[4] == "silent"

ALL_DEVICES = [
    ("Mock DRAM", 10, ["Direct", "Static", "Rainbow Wave"]),
    ("Mock DRAM", 10, ["Direct", "Static", "Rainbow Wave"]),
    ("Mock Mainboard", 73, ["Direct", "Off", "Rainbow"]),
]
HDR = struct.Struct("<4sIII")
DEVICE_LIST_UPDATED = 100
lock = threading.Lock()
clients: list[socket.socket] = []
detected = ALL_DEVICES[:2] if DELAY > 0 else list(ALL_DEVICES)


def log(**ev):
    with lock, open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")


def s(txt: str) -> bytes:
    b = txt.encode() + b"\0"
    return struct.pack("<H", len(b)) + b


def mode(name: str) -> bytes:
    return (s(name) + struct.pack("<iIII", 0, 0, 0, 0) + struct.pack("<II", 0, 100)
            + struct.pack("<III", 0, 0, 0) + struct.pack("<I", 100) + struct.pack("<II", 0, 0) + struct.pack("<H", 0))


def device(name: str, leds: int, modes: list[str]) -> bytes:
    body = struct.pack("<i", 0) + s(name) + s("Mock") + s("desc") + s("1.0") + s("serial") + s("loc")
    body += struct.pack("<H", len(modes)) + struct.pack("<i", 0) + b"".join(mode(m) for m in modes)
    body += struct.pack("<H", 1) + s("Zone") + struct.pack("<iIII", 0, leds, leds, leds) + struct.pack("<H", 0)
    body += struct.pack("<H", leds) + b"".join(s(f"LED {i}") + struct.pack("<I", i) for i in range(leds))
    body += struct.pack("<H", leds) + b"\0\0\0\0" * leds
    return struct.pack("<I", len(body) + 4) + body


def recv_exact(c, n):
    buf = b""
    while len(buf) < n:
        chunk = c.recv(n - len(buf))
        if not chunk:
            raise ConnectionError
        buf += chunk
    return buf


def send(c, dev, pkt, payload=b""):
    with lock:
        c.sendall(HDR.pack(b"ORGB", dev, pkt, len(payload)) + payload)


def finish_detection():
    time.sleep(DELAY)
    detected[:] = ALL_DEVICES
    log(ev="detection_complete", devices=len(detected))
    for c in [] if SILENT else list(clients):
        try:
            send(c, 0, DEVICE_LIST_UPDATED)
        except OSError:
            pass


def handle(c):
    clients.append(c)
    try:
        while True:
            _magic, dev, pkt, size = HDR.unpack(recv_exact(c, HDR.size))
            data = recv_exact(c, size) if size else b""
            if pkt == 40:
                send(c, dev, pkt, struct.pack("<I", 5))
            elif pkt == 0:
                send(c, dev, pkt, struct.pack("<I", len(detected)))
            elif pkt == 1:
                send(c, dev, pkt, device(*detected[dev]))
            elif pkt == 1100:
                log(ev="custom_mode", dev=dev)
            elif pkt == 1050:
                n = struct.unpack_from("<H", data, 4)[0]
                log(ev="leds", dev=dev, n=n, color=list(data[6:9]))
            elif pkt == 1101:
                idx = struct.unpack_from("<i", data, 4)[0]
                log(ev="mode", dev=dev, mode=detected[dev][2][idx])
    except (ConnectionError, OSError):
        pass
    finally:
        if c in clients:
            clients.remove(c)
        c.close()


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", PORT))
srv.listen()
if DELAY > 0:
    threading.Thread(target=finish_detection, daemon=True).start()
while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
