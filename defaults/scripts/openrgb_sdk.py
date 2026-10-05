"""Cliente mínimo do OpenRGB SDK (protocolo de rede, porta 6742).

Implementação própria, sem dependências, seguindo a documentação oficial
(OpenRGB Documentation/OpenRGBSDK.md). Usa o protocolo 3: tem brilho nos modos
e ainda não tem segmentos/flags, então o parser fica pequeno.
"""
import select
import socket
import struct

PROTOCOL_VERSION = 3

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100  # enviado pelo servidor quando detecta/remove dispositivos
RGBCONTROLLER_UPDATELEDS = 1050
RGBCONTROLLER_SETCUSTOMMODE = 1100
RGBCONTROLLER_UPDATEMODE = 1101

HEADER = struct.Struct("<4sIII")


class Controller:
    def __init__(self, index: int, name: str, num_leds: int, active_mode: int, modes: list[tuple[str, bytes]]):
        self.index = index
        self.name = name
        self.num_leds = num_leds
        self.active_mode = active_mode
        # (nome, bloco cru do modo) para restaurar com UpdateMode
        self.modes = modes

    @property
    def active_mode_name(self) -> str:
        if 0 <= self.active_mode < len(self.modes):
            return self.modes[self.active_mode][0]
        return "?"


class _Reader:
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.pos = offset

    def take(self, n: int) -> bytes:
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u16(self) -> int:
        return struct.unpack_from("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack_from("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack_from("<i", self.take(4))[0]

    def string(self) -> str:
        n = self.u16()
        return self.take(n).rstrip(b"\0").decode(errors="replace")


def _parse_mode(r: _Reader, protocol: int) -> tuple[str, bytes]:
    start = r.pos
    name = r.string()
    r.take(4 * 4)  # value, flags, speed_min, speed_max
    if protocol >= 3:
        r.take(4 * 2)  # brightness_min, brightness_max
    r.take(4 * 3)  # colors_min, colors_max, speed
    if protocol >= 3:
        r.take(4)  # brightness
    r.take(4 * 2)  # direction, color_mode
    r.take(4 * r.u16())  # colors
    return name, r.data[start:r.pos]


def _parse_controller(index: int, data: bytes, protocol: int) -> Controller:
    r = _Reader(data)
    r.u32()  # data_size
    r.i32()  # type
    name = r.string()
    if protocol >= 1:
        r.string()  # vendor
    for _ in range(4):
        r.string()  # description, version, serial, location
    num_modes = r.u16()
    active_mode = r.i32()
    modes = [_parse_mode(r, protocol) for _ in range(num_modes)]
    for _ in range(r.u16()):  # zones
        r.string()
        r.take(4 * 4)  # type, leds_min, leds_max, leds_count
        r.take(r.u16())  # matrix map
        if protocol >= 4:
            raise ValueError("protocolo >= 4 não suportado por este parser")
    num_leds = r.u16()
    return Controller(index, name, num_leds, active_mode, modes)


class OpenRGBClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 6742, name: str = "Decky HyperHDR", timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.device_list_changed = False
        self._send(0, SET_CLIENT_NAME, name.encode() + b"\0")
        self._send(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", PROTOCOL_VERSION))
        try:
            server = struct.unpack("<I", self._recv(REQUEST_PROTOCOL_VERSION))[0]
        except socket.timeout:
            server = 0  # servidor protocolo 0 não responde
        self.protocol = min(server, PROTOCOL_VERSION)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, dev: int, pkt: int, payload: bytes = b"") -> None:
        self.sock.sendall(HEADER.pack(b"ORGB", dev, pkt, len(payload)) + payload)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("servidor OpenRGB fechou a conexão")
            buf += chunk
        return bytes(buf)

    def _read_packet(self) -> tuple[int, bytes]:
        magic, _dev, pkt, size = HEADER.unpack(self._recv_exact(HEADER.size))
        if magic != b"ORGB":
            raise ConnectionError("resposta inválida do servidor OpenRGB")
        payload = self._recv_exact(size)
        if pkt == DEVICE_LIST_UPDATED:
            self.device_list_changed = True
        return pkt, payload

    def _recv(self, expected: int) -> bytes:
        # O servidor pode mandar avisos no meio da resposta; guarda o de "lista mudou"
        while True:
            pkt, payload = self._read_packet()
            if pkt == expected:
                return payload

    def fileno(self) -> int:
        return self.sock.fileno()

    def poll_device_list_changed(self) -> bool:
        """Lê os avisos pendentes sem bloquear; True se a lista de dispositivos mudou desde a última vez."""
        while select.select([self.sock], [], [], 0)[0]:
            self._read_packet()
        changed, self.device_list_changed = self.device_list_changed, False
        return changed

    def controller_count(self) -> int:
        self._send(0, REQUEST_CONTROLLER_COUNT)
        return struct.unpack_from("<I", self._recv(REQUEST_CONTROLLER_COUNT))[0]

    def controllers(self) -> list[Controller]:
        count = self.controller_count()
        result = []
        for i in range(count):
            payload = struct.pack("<I", self.protocol) if self.protocol >= 1 else b""
            self._send(i, REQUEST_CONTROLLER_DATA, payload)
            result.append(_parse_controller(i, self._recv(REQUEST_CONTROLLER_DATA), self.protocol))
        return result

    def set_custom_mode(self, dev: int) -> None:
        self._send(dev, RGBCONTROLLER_SETCUSTOMMODE)

    def update_leds(self, dev: int, colors: list[tuple[int, int, int]]) -> None:
        body = struct.pack("<H", len(colors)) + b"".join(struct.pack("<BBBx", r, g, b) for r, g, b in colors)
        self._send(dev, RGBCONTROLLER_UPDATELEDS, struct.pack("<I", len(body) + 4) + body)

    def update_mode(self, dev: int, mode_idx: int, mode_block: bytes) -> None:
        body = struct.pack("<i", mode_idx) + mode_block
        self._send(dev, RGBCONTROLLER_UPDATEMODE, struct.pack("<I", len(body) + 4) + body)
