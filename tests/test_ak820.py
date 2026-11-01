#!/usr/bin/env python3
"""Teste do teclado AK820 Pro sem hardware: mapeamento da grade, pacotes e atualização da instância.

Uso: python3 tests/test_ak820.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "defaults", "scripts")
sys.path.insert(0, SCRIPTS)
import ak820  # noqa: E402

failed = 0

# IDs na ordem do layout, capturados do driver oficial (ajazz-ak820-config, src/lighting/custom.ts)
CAPTURED_IDS = [
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x77, 0x13, 0x14,
    0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x67, 0x75, 0x25, 0x26, 0x27,
    0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x43, 0x76, 0x37, 0x38, 0x39, 0x3A,
    0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x55, 0x79, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E,
    0x4F, 0x50, 0x51, 0x52, 0x53, 0x54, 0x65, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x62, 0x63, 0x64,
    0x66,
]


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed
    print(("  OK      " if cond else "  FALHOU  ") + name + (f" — {detail}" if detail else ""))
    failed += not cond


def key(kid: int) -> int:
    return [k[0] for k in ak820.KEYS].index(kid)


def test_layout() -> None:
    print("\n=== layout e grade")
    check("81 teclas na ordem da captura", [k[0] for k in ak820.KEYS] == CAPTURED_IDS)
    leds = ak820.grid_leds()
    check("LED 0 = tela inteira", leds[0] == {"group": 0, "hmin": 0, "hmax": 1, "vmin": 0, "vmax": 1})
    check("grade completa", len(leds) == ak820.GRID_LED_COUNT == 1 + ak820.GRID_COLS * ak820.GRID_ROWS)
    cells = ak820.key_cells()
    last_col = ak820.GRID_COLS - 1
    corners = {"Esc": (0x01, 1), "Del": (0x77, 1 + last_col),
               "Ctrl": (0x5B, 1 + (ak820.GRID_ROWS - 1) * ak820.GRID_COLS),
               "Seta dir.": (0x66, ak820.GRID_LED_COUNT - 1)}
    for name, (kid, cell) in corners.items():
        check(f"{name} pega o canto da tela", cell in cells[key(kid)], str(cells[key(kid)]))
    check("barra de espaço cobre várias células", len(cells[key(0x5E)]) >= 5, str(cells[key(0x5E)]))
    check("toda célula da tela tem tecla", set(range(1, ak820.GRID_LED_COUNT)) <= {c for cs in cells for c in cs})


def test_colors() -> None:
    print("\n=== cores")
    # Metade esquerda da tela vermelha, direita azul
    leds = [(128, 0, 128)] + [(255, 0, 0) if (i % ak820.GRID_COLS) < ak820.GRID_COLS // 2 else (0, 0, 255)
                              for i in range(ak820.GRID_COLS * ak820.GRID_ROWS)]
    colors = ak820.colors_from_leds(leds)
    check("Esc vermelho", colors[key(0x01)] == (255, 0, 0), str(colors[key(0x01)]))
    check("Del azul", colors[key(0x77)] == (0, 0, 255), str(colors[key(0x77)]))
    space = colors[key(0x5E)]
    check("espaço no meio mistura as duas", space[0] > 0 and space[2] > 0, str(space))
    check("sem a grade, tudo segue o LED 0", set(ak820.colors_from_leds([(1, 2, 3)])) == {(1, 2, 3)})


def test_reports() -> None:
    print("\n=== pacotes")
    colors = [(i, 255 - i, 7) for i in range(ak820.KEY_COUNT)]
    reps = ak820.frame_reports(colors)
    check("10 pacotes de 64 bytes", len(reps) == 10 and all(len(r) == 64 for r in reps))
    check("início 04 20 com 8 tabelas", reps[0][:2] == b"\x04\x20" and reps[0][8] == 8)
    check("commit 04 02, sem o 04 F0 da flash", reps[-1][:2] == b"\x04\x02" and
          not any(r[:2] == b"\x04\xf0" for r in reps))
    check("Esc no primeiro registro", reps[1][:4] == bytes((0x01, 0, 255, 7)))
    last = ak820.KEY_COUNT - 1
    off = (last % 16) * 4
    check("última tecla no lugar certo", reps[1 + last // 16][off:off + 4] == bytes((0x66, last, 255 - last, 7)))


def make_db(path: str, pc_leds: list | None) -> None:
    c = sqlite3.connect(path)
    c.execute("create table instances (instance integer, friendly_name text, enabled integer)")
    c.execute("create table settings (type text, config text, hyperhdr_instance integer)")
    c.execute("insert into instances values (0, 'First LED instance', 1)")
    c.execute("insert into settings values ('leds', '[]', 0)")
    c.execute("insert into settings values ('smoothing', '{\"enable\": true}', 0)")
    if pc_leds is not None:
        c.execute("insert into instances values (1, 'PC RGB', 1)")
        c.execute("insert into settings values ('leds', ?, 1)", (json.dumps(pc_leds),))
    c.commit()
    c.close()


def run_add(db: str) -> tuple[dict, list]:
    out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "hyperhdr-add-instance.py"), db],
                         capture_output=True, text=True).stdout
    c = sqlite3.connect(db)
    row = c.execute("select s.config from settings s join instances i on i.instance=s.hyperhdr_instance "
                    "where i.friendly_name='PC RGB' and s.type='leds'").fetchone()
    c.close()
    return json.loads(out.splitlines()[-1]), json.loads(row[0]) if row else []


def test_instance() -> None:
    print("\n=== instância PC RGB")
    tmp = tempfile.mkdtemp(prefix="ak820-test-")
    db = os.path.join(tmp, "new.db")
    make_db(db, None)
    res, leds = run_add(db)
    check("instância nova já vem com a grade", res.get("created") and len(leds) == ak820.GRID_LED_COUNT, str(res))

    db = os.path.join(tmp, "legacy.db")
    make_db(db, [{"group": 0, "hmin": 0, "hmax": 1, "vmin": 0, "vmax": 1}])
    res, leds = run_add(db)
    check("layout antigo (1 LED) ganha a grade", res.get("upgraded") and len(leds) == ak820.GRID_LED_COUNT,
          str(res))
    check("backup antes de mexer", bool(res.get("backup")) and os.path.exists(res["backup"]))
    res, _ = run_add(db)
    check("rodar de novo não mexe", res.get("upgraded") is False, str(res))

    db = os.path.join(tmp, "custom.db")
    custom = [{"group": 0, "hmin": 0, "hmax": .5, "vmin": 0, "vmax": 1}] * 3
    make_db(db, custom)
    res, leds = run_add(db)
    check("layout feito à mão fica como está", res.get("upgraded") is False and leds == custom, str(res))


def main() -> int:
    test_layout()
    test_colors()
    test_reports()
    test_instance()
    print("\nTUDO OK" if not failed else f"\n{failed} FALHA(S)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
