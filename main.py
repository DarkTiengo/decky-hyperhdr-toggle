import asyncio
import json
import os
import platform
import re
import shutil
import socket
import tarfile
import tempfile
import time
import urllib.request

import decky

HYPERHDR_UNIT = "decky-hyperhdr.service"
BRIDGE_UNIT = "decky-hyperhdr-bridge.service"
# Units da primeira versão, instaladas à mão pelo install.sh
LEGACY_UNITS = ["hyperhdr.service", "hyperhdr-gamescope-bridge.service"]

HOME = decky.DECKY_USER_HOME
UNIT_DIR = os.path.join(HOME, ".config", "systemd", "user")
CONFIG_FILE = os.path.join(HOME, ".config", "hyperhdr-decky.env")
PORTABLE_DIR = os.path.join(HOME, ".local", "share", "hyperhdr-portable")
SCRIPTS = os.path.join(decky.DECKY_PLUGIN_DIR, "scripts")
RELEASES_API = "https://api.github.com/repos/awawa-dev/HyperHDR/releases/latest"

DEFAULTS = {
    "HYPERHDR_MODE": "auto",
    "HYPERHDR_BOX": "hyperhdr-box",
    "CAPTURE_MODE": "flatbuffers",
    "FLATBUFFERS_TARGET": "127.0.0.1:19400",
    "FLATBUFFERS_PRIORITY": "150",
    "V4L2_DEVICE": "/dev/video50",
    "BRIDGE_WIDTH": "320",
    "BRIDGE_HEIGHT": "180",
    "BRIDGE_FPS": "30",
    "BRIDGE_THROTTLE": "1",
}
CHOICES = {
    "HYPERHDR_MODE": {"auto", "native", "distrobox", "external"},
    "CAPTURE_MODE": {"flatbuffers", "v4l2"},
    "BRIDGE_THROTTLE": {"0", "1"},
}
DETECT_TTL = 30


def _user_env() -> dict:
    # O plugin roda como o usuário do Decky, mas sem o ambiente da sessão;
    # o systemctl --user precisa do runtime dir e do bus da sessão.
    uid = os.getuid()
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    env["HOME"] = HOME
    # O Decky é um binário PyInstaller e aponta LD_LIBRARY_PATH para as libs dele;
    # os programas do host quebram com o libcrypto empacotado.
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


async def _run(*args: str, env: dict | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        env=env or _user_env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


async def _systemctl(*args: str) -> tuple[int, str]:
    return await _run("systemctl", "--user", *args)


def _read_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep and not key.startswith("#"):
                    cfg[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return cfg


def _write_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write("# Gerado pelo plugin Decky HyperHDR Toggle\n")
        for key, value in cfg.items():
            f.write(f"{key}={value}\n")


def _unit_files() -> dict:
    launch = os.path.join(SCRIPTS, "hyperhdr-launch.sh")
    bridge = os.path.join(SCRIPTS, "hyperhdr-gamescope-bridge.sh")
    return {
        HYPERHDR_UNIT: f"""[Unit]
Description=HyperHDR (Decky HyperHDR Toggle)
Wants={BRIDGE_UNIT}
After=pipewire.service {BRIDGE_UNIT}

[Service]
Type=simple
EnvironmentFile=-{CONFIG_FILE}
ExecStart=/bin/bash "{launch}" start
ExecStop=/bin/bash "{launch}" stop
Restart=on-failure
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=default.target
""",
        BRIDGE_UNIT: f"""[Unit]
Description=Captura do gamescope para o HyperHDR (Decky HyperHDR Toggle)
After=pipewire.service

[Service]
Type=simple
EnvironmentFile=-{CONFIG_FILE}
ExecStart=/bin/bash "{bridge}"
# Sai quando o gamescope some (ex.: troca para o Desktop) e volta a esperar
Restart=always
RestartSec=5
Nice=10

[Install]
WantedBy=default.target
""",
    }


def _rpc(host: str, payload: dict, timeout: float = 1.5) -> dict | None:
    req = urllib.request.Request(
        f"http://{host}:8090/json-rpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class Plugin:
    _detected: tuple[str, str] = ("missing", "-")
    _detected_at = 0.0

    def _api_host(self, cfg: dict) -> str:
        if cfg["HYPERHDR_MODE"] == "external":
            return cfg["FLATBUFFERS_TARGET"].rpartition(":")[0] or "127.0.0.1"
        return "127.0.0.1"

    def _units(self, cfg: dict) -> list[str]:
        # Com HyperHDR externo só a captura roda nesta máquina
        if cfg["HYPERHDR_MODE"] == "external":
            return [BRIDGE_UNIT]
        return [BRIDGE_UNIT, HYPERHDR_UNIT]

    async def _detect(self, force: bool = False) -> tuple[str, str]:
        if force or time.monotonic() - self._detected_at > DETECT_TTL:
            env = _user_env()
            env.update(_read_config())
            _, out = await _run("/bin/bash", os.path.join(SCRIPTS, "hyperhdr-launch.sh"), "detect", env=env)
            kind, _, detail = out.splitlines()[-1].partition(" ") if out else ("missing", "", "-")
            self._detected = (kind, detail)
            self._detected_at = time.monotonic()
        return self._detected

    async def _install_units(self) -> None:
        os.makedirs(UNIT_DIR, exist_ok=True)
        for name, content in _unit_files().items():
            with open(os.path.join(UNIT_DIR, name), "w") as f:
                f.write(content)
        await _systemctl("daemon-reload")

    async def _migrate_legacy(self) -> None:
        # Só mexe nas units que a primeira versão deste plugin criou
        markers = {"hyperhdr.service": "HyperHDR (distrobox)", "hyperhdr-gamescope-bridge.service": "Ponte gamescope"}
        legacy = []
        for u in LEGACY_UNITS:
            path = os.path.join(UNIT_DIR, u)
            if os.path.exists(path) and markers[u] in open(path).read():
                legacy.append(u)
        if not legacy:
            return
        cfg = _read_config()
        if not os.path.exists(CONFIG_FILE) or "CAPTURE_MODE=" not in open(CONFIG_FILE).read():
            # A primeira versão só tinha o modo v4l2loopback
            cfg["CAPTURE_MODE"] = "v4l2"
        _write_config(cfg)
        _, active = await _systemctl("is-active", *legacy)
        _, enabled = await _systemctl("is-enabled", *legacy)
        await _systemctl("disable", "--now", *legacy)
        for u in legacy:
            os.remove(os.path.join(UNIT_DIR, u))
        old_script = os.path.join(HOME, ".local", "bin", "hyperhdr-gamescope-bridge.sh")
        if os.path.exists(old_script):
            os.remove(old_script)
        await self._install_units()
        if "enabled" in enabled.split():
            await _systemctl("enable", *self._units(cfg))
        if "active" in active.split():
            await _systemctl("start", *self._units(cfg))
        decky.logger.info(f"Units antigas migradas: {legacy}")

    async def get_status(self) -> dict:
        cfg = _read_config()
        kind, detail = await self._detect()
        states = {}
        for unit in (HYPERHDR_UNIT, BRIDGE_UNIT):
            _, out = await _systemctl("is-active", unit)
            states[unit] = out
        _, enabled = await _systemctl("is-enabled", BRIDGE_UNIT)

        components = {}
        info = await asyncio.to_thread(_rpc, self._api_host(cfg), {"command": "serverinfo"})
        if info and info.get("success"):
            for comp in info.get("info", {}).get("components", []):
                components[comp.get("name")] = bool(comp.get("enabled"))

        host = self._api_host(cfg)
        return {
            "kind": kind,
            "detail": detail,
            "hyperhdr": "external" if kind == "external" else states[HYPERHDR_UNIT],
            "bridge": states[BRIDGE_UNIT],
            "api": info is not None,
            "leds": components.get("LEDDEVICE"),
            "forwarding": components.get("FORWARDER"),
            "autostart": enabled == "enabled",
            "webui": f"http://{_local_ip() if host == '127.0.0.1' else host}:8090",
            "v4l2_missing": cfg["CAPTURE_MODE"] == "v4l2" and not os.path.exists(cfg["V4L2_DEVICE"]),
            "portable": os.path.exists(os.path.join(PORTABLE_DIR, "bin", "hyperhdr")),
        }

    async def get_settings(self) -> dict:
        return _read_config()

    async def set_setting(self, key: str, value: str) -> bool:
        value = str(value).strip()
        if key not in DEFAULTS or "\n" in value:
            return False
        if key in CHOICES and value not in CHOICES[key]:
            return False
        cfg = _read_config()
        old_units = self._units(cfg)
        _, active = await _systemctl("is-active", BRIDGE_UNIT)
        _, enabled = await _systemctl("is-enabled", BRIDGE_UNIT)
        cfg[key] = value
        _write_config(cfg)
        await self._detect(force=True)
        if active == "active":
            # Aplica na hora: para o conjunto antigo e sobe o novo (pode mudar com HyperHDR externo)
            await _systemctl("stop", *old_units)
            await _systemctl("start", *self._units(cfg))
        if enabled == "enabled":
            await _systemctl("disable", *old_units)
            await _systemctl("enable", *self._units(cfg))
        return True

    async def set_quality(self, width: int, height: int, fps: int) -> bool:
        cfg = _read_config()
        cfg.update(BRIDGE_WIDTH=str(int(width)), BRIDGE_HEIGHT=str(int(height)), BRIDGE_FPS=str(int(fps)))
        _write_config(cfg)
        _, active = await _systemctl("is-active", BRIDGE_UNIT)
        if active == "active":
            await _systemctl("restart", BRIDGE_UNIT)
        return True

    async def set_enabled(self, enabled: bool) -> bool:
        units = self._units(_read_config())
        code, out = await _systemctl("start" if enabled else "stop", *units)
        if code != 0:
            decky.logger.error(f"systemctl {'start' if enabled else 'stop'} falhou: {out}")
        return code == 0

    async def set_component(self, component: str, enabled: bool) -> bool:
        if component not in ("LEDDEVICE", "FORWARDER"):
            return False
        resp = await asyncio.to_thread(
            _rpc,
            self._api_host(_read_config()),
            {"command": "componentstate", "componentstate": {"component": component, "state": enabled}},
        )
        return bool(resp and resp.get("success"))

    async def set_autostart(self, enabled: bool) -> bool:
        cfg = _read_config()
        # Desativa os dois sempre, para não sobrar o HyperHDR habilitado ao mudar para externo
        await _systemctl("disable", HYPERHDR_UNIT, BRIDGE_UNIT)
        code, out = (0, "") if not enabled else await _systemctl("enable", *self._units(cfg))
        if code != 0:
            decky.logger.error(f"systemctl enable falhou: {out}")
        return code == 0

    async def install_portable(self) -> dict:
        """Baixa o pacote portátil oficial (tar.gz) da última release do HyperHDR."""
        arch = {"x86_64": "x86_64", "aarch64": "aarch64"}.get(platform.machine())
        if not arch:
            return {"ok": False, "error": f"arquitetura {platform.machine()} sem pacote portátil"}
        code, out = await _run("curl", "-fsSL", "-H", "Accept: application/vnd.github+json", RELEASES_API)
        if code != 0:
            return {"ok": False, "error": "não foi possível consultar o GitHub"}
        release = json.loads(out)
        pattern = re.compile(rf"^HyperHDR-[\d.]+-Linux-{arch}\.tar\.gz$")
        asset = next((a for a in release.get("assets", []) if pattern.match(a["name"])), None)
        if not asset:
            return {"ok": False, "error": f"release {release.get('tag_name')} sem pacote Linux {arch}"}

        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, asset["name"])
            code, out = await _run("curl", "-fsSL", "-o", archive, asset["browser_download_url"])
            if code != 0:
                return {"ok": False, "error": f"download falhou: {out[-200:]}"}
            staging = os.path.join(tmp, "hyperhdr")
            def extract():
                with tarfile.open(archive) as tar:
                    try:
                        tar.extractall(staging, filter="data")
                    except TypeError:  # Python sem extraction filters
                        tar.extractall(staging)

            await asyncio.to_thread(extract)
            if not os.path.exists(os.path.join(staging, "bin", "hyperhdr")):
                return {"ok": False, "error": "pacote sem bin/hyperhdr"}
            # Só troca a instalação se o HyperHDR estiver parado
            _, active = await _systemctl("is-active", HYPERHDR_UNIT)
            if active == "active":
                await _systemctl("stop", HYPERHDR_UNIT)
            shutil.rmtree(PORTABLE_DIR, ignore_errors=True)
            os.makedirs(os.path.dirname(PORTABLE_DIR), exist_ok=True)
            shutil.move(staging, PORTABLE_DIR)
            if active == "active":
                await _systemctl("start", HYPERHDR_UNIT)

        await self._detect(force=True)
        decky.logger.info(f"HyperHDR portátil {release.get('tag_name')} instalado em {PORTABLE_DIR}")
        return {"ok": True, "version": release.get("tag_name")}

    async def _main(self):
        await self._install_units()
        await self._migrate_legacy()
        decky.logger.info("HyperHDR Toggle carregado")

    async def _unload(self):
        pass

    async def _uninstall(self):
        # Não deixa a captura rodando nem units apontando para um plugin removido
        await _systemctl("disable", "--now", HYPERHDR_UNIT, BRIDGE_UNIT)
        for name in _unit_files():
            try:
                os.remove(os.path.join(UNIT_DIR, name))
            except FileNotFoundError:
                pass
        await _systemctl("daemon-reload")
