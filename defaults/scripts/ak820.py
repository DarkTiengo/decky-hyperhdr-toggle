#!/usr/bin/env python3
"""Teclado AJAZZ AK820 Pro: RGB por tecla ao vivo pelo hidraw (firmware original).

Protocolo (engenharia reversa da comunidade, ver github.com/nurlanjalil/ajazz-ak820-config):
  feature report na interface 3 (usage page 0xFF13), 64 bytes, report ID 0 no hidraw:
    04 20 .. byte8=8      início da tabela por tecla
    8 × [id, R, G, B]×16  cores (81 teclas)
    04 02                 commit — sem o 04 F0, que gravaria na flash
O efeito fica só na RAM: quando os quadros param de chegar, o firmware volta sozinho ao
efeito salvo. Só funciona no cabo USB; o dongle 2.4G e o Bluetooth não expõem esse canal.

Também é o lugar da grade da tela usada pela instância "PC RGB" do HyperHDR: LED 0 é a
média da tela inteira e os LEDs 1.. são uma grade GRID_COLS × GRID_ROWS, linha por linha.

Uso direto (teste): python3 ak820.py [segundos]
"""
import fcntl
import glob
import os

VENDOR_ID = 0x0C45
PRODUCT_IDS = (0x8009, 0x800A)
CONTROL_INTERFACE = 3

GRID_COLS = 16
GRID_ROWS = 6


def grid_leds() -> list[dict]:
    """Layout de LEDs da instância "PC RGB": média da tela + grade."""
    leds = [{"group": 0, "hmin": 0, "hmax": 1, "vmin": 0, "vmax": 1}]
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            leds.append({"group": 0,
                         "hmin": round(c / GRID_COLS, 4), "hmax": round((c + 1) / GRID_COLS, 4),
                         "vmin": round(r / GRID_ROWS, 4), "vmax": round((r + 1) / GRID_ROWS, 4)})
    return leds


GRID_LED_COUNT = 1 + GRID_COLS * GRID_ROWS

# Layout físico (ANSI 75%), linha a linha: (ID do LED no firmware, largura em teclas).
# ID None = espaço vazio entre blocos. A ordem dos IDs vem da captura do driver oficial.
_ROWS = [
    [(0x01, 1), (None, .35), (0x02, 1), (0x03, 1), (0x04, 1), (0x05, 1), (None, .25),
     (0x06, 1), (0x07, 1), (0x08, 1), (0x09, 1), (None, .25),
     (0x0A, 1), (0x0B, 1), (0x0C, 1), (0x0D, 1), (None, .15), (0x77, 1)],
    [*((i, 1) for i in range(0x13, 0x20)), (0x67, 2), (None, .75), (0x75, 1)],
    [(0x25, 1.5), *((i, 1) for i in range(0x26, 0x32)), (0x43, 1.5), (None, .75), (0x76, 1)],
    [(0x37, 1.75), *((i, 1) for i in range(0x38, 0x43)), (0x55, 2.25), (None, .75), (0x79, 1)],
    [(0x49, 2.25), *((i, 1) for i in range(0x4A, 0x54)), (0x54, 1.75), (None, .2), (0x65, 1)],
    [(0x5B, 1.25), (0x5C, 1.25), (0x5D, 1.25), (0x5E, 6.25), (0x5F, 1.25), (0x60, 1.25),
     (0x62, 1.25), (None, .2), (0x63, 1), (0x64, 1), (0x66, 1)],
]


def _key_spans() -> list[tuple[int, int, float, float]]:
    """(id, linha, x0, x1) de cada tecla, com x normalizado para 0..1.

    Cada fileira é normalizada pela própria largura: as fileiras do layout têm larguras um
    pouco diferentes, e assim as teclas das pontas (Esc, Del, setas) sempre pegam as bordas da tela.
    """
    keys = []
    for row, items in enumerate(_ROWS):
        width = sum(w for _, w in items)
        x = 0.0
        for kid, w in items:
            if kid is not None:
                keys.append((kid, row, x / width, (x + w) / width))
            x += w
    return keys


KEYS = _key_spans()
KEY_COUNT = len(KEYS)


def key_cells() -> list[list[int]]:
    """Para cada tecla, os índices (no pacote do HyperHDR) das células da grade que ela cobre."""
    cells = []
    for _, row, x0, x1 in KEYS:
        r = min(GRID_ROWS - 1, row * GRID_ROWS // len(_ROWS))
        c0 = min(GRID_COLS - 1, int(x0 * GRID_COLS))
        c1 = max(c0, min(GRID_COLS - 1, int(x1 * GRID_COLS - 1e-9)))
        cells.append([1 + r * GRID_COLS + c for c in range(c0, c1 + 1)])
    return cells


_KEY_CELLS = key_cells()


def colors_from_leds(leds: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Cor de cada tecla a partir dos LEDs da instância. Sem a grade, o teclado todo segue o LED 0."""
    if len(leds) < GRID_LED_COUNT:
        return [leds[0]] * KEY_COUNT if leds else [(0, 0, 0)] * KEY_COUNT
    out = []
    for cells in _KEY_CELLS:
        n = len(cells)
        out.append(tuple(sum(leds[i][ch] for i in cells) // n for ch in range(3)))
    return out


def frame_reports(colors: list[tuple[int, int, int]]) -> list[bytes]:
    """Os 10 feature reports (64 bytes, sem o report ID) de um quadro."""
    tables = [bytearray(64) for _ in range(8)]
    for i, (kid, *_) in enumerate(KEYS):
        r, g, b = colors[i]
        tables[i // 16][(i % 16) * 4:(i % 16) * 4 + 4] = bytes((kid, r, g, b))
    start = bytearray(64)
    start[0], start[1], start[8] = 0x04, 0x20, len(tables)
    commit = bytearray(64)
    commit[0], commit[1] = 0x04, 0x02
    return [bytes(start), *map(bytes, tables), bytes(commit)]


def _ioc(nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


_HIDIOCSFEATURE = _ioc(0x06, 65)
_HIDIOCGFEATURE = _ioc(0x07, 65)


def find_device() -> str | None:
    """Nó /dev/hidrawN da interface de controle do AK820 Pro no cabo, ou None."""
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(path, "device", "uevent")) as f:
                uevent = f.read()
        except OSError:
            continue
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        try:
            _, vid, pid = (int(x, 16) for x in fields.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if vid == VENDOR_ID and pid in PRODUCT_IDS and \
                fields.get("HID_PHYS", "").endswith(f"/input{CONTROL_INTERFACE}"):
            return "/dev/" + os.path.basename(path)
    return None


class Keyboard:
    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_RDWR)

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass

    def _send(self, report: bytes) -> None:
        fcntl.ioctl(self.fd, _HIDIOCSFEATURE, bytearray(b"\0" + report))

    def _ack(self) -> None:
        # O firmware espera a leitura da resposta; sem ela o canal de controle trava
        try:
            fcntl.ioctl(self.fd, _HIDIOCGFEATURE, bytearray(65))
        except OSError:
            pass

    def show(self, colors: list[tuple[int, int, int]]) -> None:
        """Envia um quadro (cores na ordem de KEYS). Levanta OSError se o teclado sumir."""
        reports = frame_reports(colors)
        self._send(reports[0])
        self._ack()
        for rep in reports[1:-1]:
            self._send(rep)
        self._send(reports[-1])
        self._ack()


if __name__ == "__main__":
    import colorsys
    import sys
    import time

    dev = find_device()
    if not dev:
        sys.exit("AK820 Pro não encontrado no cabo USB")
    kb = Keyboard(dev)
    print(f"{dev}: {KEY_COUNT} teclas, onda da esquerda para a direita")
    end = time.monotonic() + float(sys.argv[1] if len(sys.argv) > 1 else 5)
    while time.monotonic() < end:
        ph = time.monotonic() * 0.4
        kb.show([tuple(int(v * 255) for v in colorsys.hsv_to_rgb(((x0 + x1) / 2 + ph) % 1, 1, 1))
                 for _, _, x0, x1 in KEYS])
    kb.close()
