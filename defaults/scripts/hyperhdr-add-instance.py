#!/usr/bin/env python3
"""Cria no banco do HyperHDR a instância "PC RGB" usada pelas luzes do PC (OpenRGB).

Rode com o HyperHDR PARADO. Copia todas as configurações da instância 0 (cor, suavização…)
para a nova, para que ela reaja no mesmo ritmo da principal, e troca só:
  device -> udpraw 127.0.0.1:<porta>    leds -> 1 LED cobrindo a tela inteira
Faz backup do banco antes. Imprime uma linha JSON com o resultado.

Uso: hyperhdr-add-instance.py <caminho do hyperhdr.db> [porta] [nome]
"""
import json
import shutil
import sqlite3
import sys
import time


def fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        fail("uso: hyperhdr-add-instance.py <hyperhdr.db> [porta] [nome]")
    db = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 19446
    name = sys.argv[3] if len(sys.argv) > 3 else "PC RGB"

    try:
        c = sqlite3.connect(f"file:{db}?mode=rw", uri=True)
    except sqlite3.Error as e:
        fail(f"não abri o banco {db}: {e}")

    # Confere o formato esperado antes de mexer (HyperHDR 20+)
    cols = {t: {r[1] for r in c.execute(f"pragma table_info({t})")} for t in ("instances", "settings")}
    if not {"instance", "friendly_name", "enabled"} <= cols["instances"] or \
            not {"type", "config", "hyperhdr_instance"} <= cols["settings"]:
        fail("formato do banco do HyperHDR desconhecido; crie a instância pela Web UI")

    existing = {r[1]: r[0] for r in c.execute("select instance, friendly_name from instances")}
    if name in existing:
        print(json.dumps({"ok": True, "instance": existing[name], "created": False}))
        return
    if 0 not in existing.values():
        fail("instância 0 não encontrada")

    backup = f"{db}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(db, backup)

    index = max(existing.values()) + 1
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    has_last_use = "last_use" in cols["instances"]
    has_updated = "updated_at" in cols["settings"]
    with c:
        if has_last_use:
            c.execute("insert into instances (instance, friendly_name, enabled, last_use) values (?, ?, 1, ?)",
                      (index, name, now))
        else:
            c.execute("insert into instances (instance, friendly_name, enabled) values (?, ?, 1)", (index, name))
        for t, cfg in c.execute("select type, config from settings where hyperhdr_instance=0").fetchall():
            if has_updated:
                c.execute("insert into settings (type, config, hyperhdr_instance, updated_at) values (?, ?, ?, ?)",
                          (t, cfg, index, now))
            else:
                c.execute("insert into settings (type, config, hyperhdr_instance) values (?, ?, ?)", (t, cfg, index))
        overrides = {
            "device": {"type": "udpraw", "host": "127.0.0.1", "port": port, "colorOrder": "rgb", "refreshTime": 0},
            "leds": [{"group": 0, "hmin": 0, "hmax": 1, "vmin": 0, "vmax": 1}],
        }
        for t, cfg in overrides.items():
            value = json.dumps(cfg, separators=(",", ":"))
            if not c.execute("update settings set config=? where type=? and hyperhdr_instance=?",
                             (value, t, index)).rowcount:
                c.execute("insert into settings (type, config, hyperhdr_instance) values (?, ?, ?)", (t, value, index))
    print(json.dumps({"ok": True, "instance": index, "created": True, "backup": backup}))


if __name__ == "__main__":
    main()
