#!/usr/bin/env python3
"""Recebe as cores do HyperHDR (LED device "udpraw") e aplica nas luzes do PC via OpenRGB SDK.

O HyperHDR manda um datagrama UDP com N×3 bytes (RGB de cada LED da instância).
Cada dispositivo do OpenRGB segue um desses LEDs (padrão: LED 0 = cor média da tela).
Ao parar, cada dispositivo volta para um modo de hardware (efeito de fábrica).

Configuração por ambiente (ver ~/.config/hyperhdr-decky.env):
  OPENRGB_HOST / OPENRGB_PORT   servidor SDK do OpenRGB (127.0.0.1:6742)
  OPENRGB_UDP_PORT              porta UDP que o HyperHDR usa no udpraw (19446)
  OPENRGB_UDP_BIND              endereço onde escutar (padrão: 127.0.0.1; 0.0.0.0 com HyperHDR externo)
O estado (servidor encontrado, última cor recebida) fica em $XDG_RUNTIME_DIR/decky-hyperhdr-openrgb.json
para o painel do plugin.
Mapeamento por dispositivo: ~/.config/hyperhdr-decky-openrgb.json (gerado na primeira execução)
"""
import json
import os
import select
import signal
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openrgb_sdk  # noqa: E402

HOST = os.environ.get("OPENRGB_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPENRGB_PORT", "6742"))
UDP_PORT = int(os.environ.get("OPENRGB_UDP_PORT", "19446"))
# Com o HyperHDR em outro computador, as cores chegam pela rede
UDP_BIND = os.environ.get("OPENRGB_UDP_BIND") or (
    "0.0.0.0" if os.environ.get("HYPERHDR_MODE") == "external" else "127.0.0.1"
)
STATUS_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "decky-hyperhdr-openrgb.json")
STATUS_INTERVAL_S = 2.0
MAP_FILE = os.path.expanduser(os.environ.get("OPENRGB_MAP_FILE", "~/.config/hyperhdr-decky-openrgb.json"))

# Modos de hardware usados para "voltar ao normal", em ordem de preferência
RESTORE_PREFERENCE = ["Rainbow Wave", "Rainbow", "Spectrum Cycle", "Color Shift"]
# DRAM em SMBus é lenta; acima disso as atualizações enfileiram
DEFAULT_MAX_HZ = {"DRAM": 10}
DEFAULT_HZ = 30
# Diferença mínima (soma dos canais) para valer a pena reenviar
MIN_DELTA = 6
# Sem dados do HyperHDR por este tempo (captura parada), volta ao efeito de fábrica
IDLE_RESTORE_S = 10.0
# O servidor aplica os comandos numa fila; a DRAM em SMBus demora. Sem esperar, parar o
# servidor logo em seguida descartava a troca de modo das memórias.
RESTORE_SETTLE_S = 2.0


def log(msg: str) -> None:
    print(msg, flush=True)


def write_status(**fields) -> None:
    fields.update(pid=os.getpid(), updated=time.time())
    tmp = STATUS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(fields, f)
        os.replace(tmp, STATUS_FILE)
    except OSError:
        pass


def default_restore(dev: openrgb_sdk.Controller) -> str:
    names = [m[0] for m in dev.modes]
    return next((n for n in RESTORE_PREFERENCE if n in names), "")


def load_mapping(devices: list[openrgb_sdk.Controller]) -> dict:
    try:
        with open(MAP_FILE) as f:
            mapping = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        mapping = {}
    changed = False
    for d in devices:
        if d.name not in mapping:
            kind = "DRAM" if "DRAM" in d.name.upper() or "DDR" in d.name.upper() else ""
            mapping[d.name] = {
                "led": 0,
                "enabled": True,
                "max_hz": DEFAULT_MAX_HZ.get(kind, DEFAULT_HZ),
                "restore_mode": default_restore(d),
            }
            changed = True
    if changed:
        os.makedirs(os.path.dirname(MAP_FILE), exist_ok=True)
        with open(MAP_FILE, "w") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        log(f"mapeamento salvo em {MAP_FILE}")
    return mapping


class Bridge:
    def __init__(self):
        self.client: openrgb_sdk.OpenRGBClient | None = None
        self.devices: list[openrgb_sdk.Controller] = []
        self.mapping: dict = {}
        self.direct = False
        self.last_sent: dict[int, tuple[tuple[int, int, int], float]] = {}

    def connect(self) -> None:
        while True:
            try:
                self.client = openrgb_sdk.OpenRGBClient(HOST, PORT)
                self.devices = self.client.controllers()
                if self.devices:
                    break
                # O servidor abre a porta antes de terminar a detecção
                log("OpenRGB ainda sem dispositivos, aguardando a detecção")
                write_status(state="no_devices", devices=0, last_packet=0)
                self.client.close()
            except OSError as e:
                log(f"sem conexão com o OpenRGB em {HOST}:{PORT}: {e}")
                write_status(state="no_server", devices=0, last_packet=0)
            time.sleep(3)
        self.mapping = load_mapping(self.devices)
        for d in self.devices:
            m = self.mapping[d.name]
            log(f"{d.index}: {d.name} ({d.num_leds} LEDs) → LED {m['led']} do HyperHDR, "
                f"{m['max_hz']} Hz, restaura '{m['restore_mode']}'{'' if m['enabled'] else ' [desativado]'}")

    def take_control(self) -> None:
        for d in self.devices:
            if self.mapping[d.name]["enabled"]:
                self.client.set_custom_mode(d.index)
        self.direct = True
        self.last_sent.clear()

    def apply(self, leds: list[tuple[int, int, int]]) -> None:
        if not self.direct:
            self.take_control()
        now = time.monotonic()
        for d in self.devices:
            m = self.mapping[d.name]
            if not m["enabled"] or not leds:
                continue
            color = leds[min(m["led"], len(leds) - 1)]
            prev = self.last_sent.get(d.index)
            if prev:
                last_color, last_time = prev
                if now - last_time < 1.0 / m["max_hz"]:
                    continue
                if sum(abs(a - b) for a, b in zip(color, last_color)) < MIN_DELTA:
                    continue
            self.client.update_leds(d.index, [color] * d.num_leds)
            self.last_sent[d.index] = (color, now)

    def restore(self) -> None:
        if not self.direct or self.client is None:
            return
        for d in self.devices:
            m = self.mapping[d.name]
            if not m["enabled"] or not m["restore_mode"]:
                continue
            for idx, (name, block) in enumerate(d.modes):
                if name == m["restore_mode"]:
                    self.client.update_mode(d.index, idx, block)
                    break
        self.direct = False
        time.sleep(RESTORE_SETTLE_S)
        log("luzes do PC de volta ao efeito de fábrica")


def main() -> int:
    bridge = Bridge()
    bridge.connect()

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind((UDP_BIND, UDP_PORT))
    log(f"aguardando cores do HyperHDR em udp://{UDP_BIND}:{UDP_PORT}")

    stop = {"now": False}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.update(now=True))

    last_packet = 0.0
    last_packet_wall = 0.0
    last_status = 0.0
    exit_code = 0
    try:
        while not stop["now"]:
            ready = select.select([udp], [], [], 1.0)[0]
            if time.monotonic() - last_status >= STATUS_INTERVAL_S:
                write_status(state="running", devices=len(bridge.devices), last_packet=last_packet_wall,
                             syncing=bridge.direct)
                last_status = time.monotonic()
            if not ready:
                if bridge.direct and time.monotonic() - last_packet > IDLE_RESTORE_S:
                    bridge.restore()
                continue
            data = udp.recv(65535)
            # Esvazia a fila: só a cor mais recente interessa
            while select.select([udp], [], [], 0)[0]:
                data = udp.recv(65535)
            last_packet = time.monotonic()
            last_packet_wall = time.time()
            n = len(data) // 3
            bridge.apply([tuple(data[i * 3:i * 3 + 3]) for i in range(n)])
    except (ConnectionError, OSError) as e:
        log(f"conexão com o OpenRGB perdida: {e}")
        exit_code = 1
    finally:
        try:
            bridge.restore()
        except OSError as e:
            log(f"não consegui devolver as luzes ao efeito de fábrica: {e}")
        if bridge.client:
            bridge.client.close()
        try:
            os.remove(STATUS_FILE)
        except OSError:
            pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
