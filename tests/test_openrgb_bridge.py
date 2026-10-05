#!/usr/bin/env python3
"""Teste da ponte HyperHDR → OpenRGB contra o servidor simulado (sem HyperHDR, sem Decky).

Cenários (rodados com o servidor avisando "lista mudou" e com o servidor silencioso):
  1. detecção lenta: a ponte conecta quando só as memórias foram detectadas; a placa-mãe
     (ventoinhas) aparece depois e também precisa receber as cores
  2. parada: todos os dispositivos voltam ao efeito de fábrica

Uso: python3 tests/test_openrgb_bridge.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "defaults", "scripts", "hyperhdr-openrgb-bridge.py")
MOCK = os.path.join(ROOT, "tests", "mock_openrgb.py")
SDK_PORT, UDP_PORT = 16742, 19447
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed
    print(("  OK      " if cond else "  FALHOU  ") + name + (f" — {detail}" if detail else ""))
    failed += not cond


def events(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def scenario(title: str, mock_args: list[str]) -> None:
    print(f"\n=== {title}")
    tmp = tempfile.mkdtemp(prefix="orgb-test-")
    log = os.path.join(tmp, "mock.log")
    open(log, "w").close()
    mock = subprocess.Popen([sys.executable, MOCK, str(SDK_PORT), log, *mock_args])
    time.sleep(0.5)
    env = dict(os.environ, OPENRGB_PORT=str(SDK_PORT), OPENRGB_UDP_PORT=str(UDP_PORT),
               OPENRGB_MAP_FILE=os.path.join(tmp, "map.json"), XDG_RUNTIME_DIR=tmp, HYPERHDR_MODE="auto")
    out = open(os.path.join(tmp, "bridge.log"), "w")
    bridge = subprocess.Popen([sys.executable, BRIDGE], env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        print("1. detecção lenta (placa-mãe aparece depois)")
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        end = time.monotonic() + 12
        color = 0
        while time.monotonic() < end:
            color = (color + 40) % 256
            udp.sendto(bytes([color, 255 - color, 128]), ("127.0.0.1", UDP_PORT))
            time.sleep(0.1)
        ev = events(log)
        devs = {e["dev"] for e in ev if e["ev"] == "leds"}
        check("memórias receberam cores", {0, 1} <= devs, f"dispositivos com cor: {sorted(devs)}")
        check("placa-mãe/ventoinhas receberam cores depois da detecção", 2 in devs,
              f"dispositivos com cor: {sorted(devs)}")
        check("modo Direct na placa-mãe", any(e["ev"] == "custom_mode" and e["dev"] == 2 for e in ev))
        with open(os.path.join(tmp, "map.json")) as f:
            check("mapeamento inclui a placa-mãe", "Mock Mainboard" in json.load(f))

        print("2. parada devolve todos ao efeito de fábrica")
        open(log, "w").close()
        bridge.terminate()
        bridge.wait(timeout=15)
        modes = sorted((e["dev"], e["mode"]) for e in events(log) if e["ev"] == "mode")
        check("efeito de fábrica nos 3", modes == [(0, "Rainbow Wave"), (1, "Rainbow Wave"), (2, "Rainbow")],
              str(modes))
    finally:
        if bridge.poll() is None:
            bridge.kill()
        mock.kill()
        out.close()
        if failed:
            print("\n--- log da ponte:\n" + open(os.path.join(tmp, "bridge.log")).read())


def main() -> int:
    # Aviso chega depois que a ponte já terminou de esperar a detecção: testa a releitura
    scenario("servidor avisa que a lista mudou (placa-mãe em 4 s)", ["4"])
    # Sem aviso: quem segura é a espera pela contagem estável na inicialização
    scenario("servidor silencioso (placa-mãe em 2 s, sem aviso)", ["2", "silent"])
    print("\nTUDO OK" if not failed else f"\n{failed} FALHA(S)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
