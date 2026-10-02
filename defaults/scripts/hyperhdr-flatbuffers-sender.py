#!/usr/bin/env python3
"""Lê quadros RGB24 crus do stdin e envia ao servidor Flatbuffers do HyperHDR.

Uso: gst-launch-1.0 ... ! video/x-raw,format=RGB,width=W,height=H ! fdsink fd=1 \
       | hyperhdr-flatbuffers-sender.py --target 127.0.0.1:19400 --width W --height H
"""
import argparse
import os
import select
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))
import flatbuffers  # noqa: E402

# Índices das uniões em hyperhdr_request.fbs
COMMAND_IMAGE = 2
COMMAND_REGISTER = 4
IMAGETYPE_RAW = 1

# Sem quadro novo (menu parado), reenvia o último para o servidor não fechar a conexão por timeout
RESEND_INTERVAL = 1.0


def _request(builder: flatbuffers.Builder, command_type: int, command: int) -> bytes:
    builder.StartObject(2)
    builder.PrependUint8Slot(0, command_type, 0)
    builder.PrependUOffsetTRelativeSlot(1, command, 0)
    builder.Finish(builder.EndObject())
    return bytes(builder.Output())


def register_message(origin: str, priority: int) -> bytes:
    b = flatbuffers.Builder(64)
    name = b.CreateString(origin)
    b.StartObject(2)
    b.PrependUOffsetTRelativeSlot(0, name, 0)
    # force_defaults para a prioridade sempre ir no buffer
    b.PrependInt32Slot(1, priority, -0x7FFFFFFF)
    return _request(b, COMMAND_REGISTER, b.EndObject())


def image_message(rgb: bytes, width: int, height: int) -> bytes:
    b = flatbuffers.Builder(len(rgb) + 128)
    data = b.CreateByteVector(rgb)
    b.StartObject(3)
    b.PrependUOffsetTRelativeSlot(0, data, 0)
    b.PrependInt32Slot(1, width, -1)
    b.PrependInt32Slot(2, height, -1)
    raw = b.EndObject()
    b.StartObject(3)
    b.PrependUint8Slot(0, IMAGETYPE_RAW, 0)
    b.PrependUOffsetTRelativeSlot(1, raw, 0)
    b.PrependInt32Slot(2, -1, 0)  # duração infinita: some quando a conexão fecha
    return _request(b, COMMAND_IMAGE, b.EndObject())


def frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


class Connection:
    def __init__(self, host: str, port: int, origin: str, priority: int):
        self.addr = (host, port)
        self.origin = origin
        self.priority = priority
        self.sock: socket.socket | None = None
        self.next_try = 0.0

    def _connect(self) -> bool:
        if time.monotonic() < self.next_try:
            return False
        try:
            s = socket.create_connection(self.addr, timeout=2)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.sendall(frame(register_message(self.origin, self.priority)))
            s.settimeout(2)
            self.sock = s
            print(f"conectado a {self.addr[0]}:{self.addr[1]} (prioridade {self.priority})", flush=True)
            return True
        except OSError as e:
            print(f"sem conexão com {self.addr[0]}:{self.addr[1]}: {e}", file=sys.stderr, flush=True)
            self.next_try = time.monotonic() + 3
            return False

    def send(self, payload: bytes) -> None:
        if self.sock is None and not self._connect():
            return
        try:
            self.sock.sendall(frame(payload))
            # Descarta as respostas do servidor para o buffer de recepção não encher
            while select.select([self.sock], [], [], 0)[0]:
                if not self.sock.recv(65536):
                    raise ConnectionError("servidor fechou a conexão")
        except OSError as e:
            print(f"conexão perdida: {e}", file=sys.stderr, flush=True)
            self.sock.close()
            self.sock = None


def read_exact(fd: int, buf: memoryview) -> bool:
    got = 0
    while got < len(buf):
        n = os.readv(fd, [buf[got:]])
        if n == 0:
            return False
        got += n
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="127.0.0.1:19400")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--priority", type=int, default=150)
    ap.add_argument("--origin", default="Decky gamescope")
    args = ap.parse_args()

    host, _, port = args.target.rpartition(":")
    conn = Connection(host or "127.0.0.1", int(port), args.origin, args.priority)

    fd = sys.stdin.fileno()
    buf = bytearray(args.width * args.height * 3)
    view = memoryview(buf)
    last: bytes | None = None
    last_sent = 0.0

    while True:
        ready = select.select([fd], [], [], RESEND_INTERVAL)[0]
        if ready:
            if not read_exact(fd, view):
                return 0  # pipeline do gstreamer terminou
            last = image_message(bytes(buf), args.width, args.height)
        elif last is None or time.monotonic() - last_sent < RESEND_INTERVAL:
            continue
        conn.send(last)
        last_sent = time.monotonic()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
