import asyncio
import importlib.util
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
OPENRGB_SERVER_UNIT = "decky-openrgb-server.service"
OPENRGB_UNIT = "decky-hyperhdr-openrgb.service"
OPENRGB_UNITS = [OPENRGB_SERVER_UNIT, OPENRGB_UNIT]
ALL_UNITS = [HYPERHDR_UNIT, BRIDGE_UNIT, *OPENRGB_UNITS]
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
    "OPENRGB_ENABLE": "0",
    "OPENRGB_HOST": "127.0.0.1",
    "OPENRGB_PORT": "6742",
    "OPENRGB_UDP_PORT": "19446",
    "SETUP_DONE": "0",
}
CHOICES = {
    "HYPERHDR_MODE": {"auto", "native", "distrobox", "external"},
    "CAPTURE_MODE": {"flatbuffers", "v4l2"},
    "BRIDGE_THROTTLE": {"0", "1"},
    "OPENRGB_ENABLE": {"0", "1"},
    "SETUP_DONE": {"0", "1"},
}
# Chaves que só afetam a parte do OpenRGB: mudam sem reiniciar a captura do gamescope
OPENRGB_KEYS = {"OPENRGB_ENABLE", "OPENRGB_HOST", "OPENRGB_PORT", "OPENRGB_UDP_PORT"}
DETECT_TTL = 30
PC_INSTANCE_NAME = "PC RGB"
HYPERHDR_DB = os.path.join(HOME, ".hyperhdr", "db", "hyperhdr.db")
OPENRGB_STATUS = f"/run/user/{os.getuid()}/decky-hyperhdr-openrgb.json"
# Sem cor nova por este tempo, o painel mostra "sem cores do HyperHDR"
OPENRGB_STALE_S = 10
# Cores do teste de LEDs: prioridade acima da captura (150) para aparecer mesmo com ela ligada
TEST_COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
TEST_PRIORITY = 100

# Pacote que fornece cada dependência, por família de distro (conferidos no Bazzite, Arch e Debian)
PACKAGES = {
    "gst-launch": {"fedora": "gstreamer1", "arch": "gstreamer", "debian": "gstreamer1.0-tools"},
    "pipewiresrc": {"fedora": "pipewire-gstreamer", "arch": "gst-plugin-pipewire", "debian": "gstreamer1.0-pipewire"},
    "gst-base": {"fedora": "gstreamer1-plugins-base", "arch": "gst-plugins-base", "debian": "gstreamer1.0-plugins-base"},
    "python3": {"fedora": "python3", "arch": "python", "debian": "python3"},
    "pw-cli": {"fedora": "pipewire-utils", "arch": "pipewire", "debian": "pipewire-bin"},
    "python3-gi": {"fedora": "python3-gobject-base", "arch": "python-gobject", "debian": "python3-gi gir1.2-gstreamer-1.0"},
    "curl": {"fedora": "curl", "arch": "curl", "debian": "curl"},
    "distrobox": {"fedora": "distrobox", "arch": "distrobox", "debian": "distrobox"},
    "openrgb": {"fedora": "flatpak: org.openrgb.OpenRGB", "arch": "flatpak: org.openrgb.OpenRGB",
                "debian": "flatpak: org.openrgb.OpenRGB"},
    "ss": {"fedora": "iproute", "arch": "iproute2", "debian": "iproute2"},
}


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


async def _stop(*units: str) -> tuple[int, str]:
    # A ponte do OpenRGB precisa do servidor para devolver as luzes ao efeito de fábrica;
    # o systemd não garantiu essa ordem na parada, então para a ponte antes, em separado.
    if OPENRGB_UNIT in units:
        await _systemctl("stop", OPENRGB_UNIT)
        units = tuple(u for u in units if u != OPENRGB_UNIT)
    return await _systemctl("stop", *units) if units else (0, "")


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
    orgb_server = os.path.join(SCRIPTS, "openrgb-server.sh")
    orgb_bridge = os.path.join(SCRIPTS, "hyperhdr-openrgb-bridge.py")
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
        OPENRGB_SERVER_UNIT: f"""[Unit]
Description=Servidor OpenRGB sem interface (Decky HyperHDR Toggle)
After=graphical-session.target

[Service]
Type=simple
EnvironmentFile=-{CONFIG_FILE}
ExecStart=/bin/bash "{orgb_server}"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
""",
        OPENRGB_UNIT: f"""[Unit]
Description=Luzes do PC seguindo o HyperHDR via OpenRGB (Decky HyperHDR Toggle)
Wants={OPENRGB_SERVER_UNIT}
After={OPENRGB_SERVER_UNIT}

[Service]
Type=simple
EnvironmentFile=-{CONFIG_FILE}
ExecStart=/usr/bin/python3 "{orgb_bridge}"
# Ao parar, devolve as luzes ao efeito de fábrica antes de sair
TimeoutStopSec=10
Restart=on-failure
RestartSec=5

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


def _distro_family() -> str:
    try:
        info = {}
        with open("/etc/os-release") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                info[k] = v.strip('"').lower()
        ids = " ".join([info.get("ID", ""), info.get("ID_LIKE", "")])
    except OSError:
        return ""
    for family in ("fedora", "arch", "debian"):
        if family in ids or (family == "debian" and "ubuntu" in ids):
            return family
    return ""


def _load_script(name: str):
    """Importa um módulo de scripts/ (os nomes têm hífen, então não dá para usar import normal)."""
    path = os.path.join(SCRIPTS, name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_").removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _read_openrgb_status() -> dict | None:
    try:
        with open(OPENRGB_STATUS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _send_test_colors(target: str, colors: list[tuple[int, int, int]], seconds: float) -> None:
    """Mostra cada cor por alguns segundos pelo servidor Flatbuffers; ao fechar, a prioridade some."""
    sender = _load_script("hyperhdr-flatbuffers-sender.py")
    host, _, port = target.rpartition(":")
    w, h = 64, 36
    with socket.create_connection((host or "127.0.0.1", int(port)), timeout=3) as s:
        s.sendall(sender.frame(sender.register_message("Decky teste de LEDs", TEST_PRIORITY)))
        for r, g, b in colors:
            msg = sender.frame(sender.image_message(bytes((r, g, b)) * (w * h), w, h))
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                s.sendall(msg)
                time.sleep(0.2)


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
        units = [BRIDGE_UNIT] if cfg["HYPERHDR_MODE"] == "external" else [BRIDGE_UNIT, HYPERHDR_UNIT]
        if cfg.get("OPENRGB_ENABLE") == "1":
            units += OPENRGB_UNITS
        return units

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
        for unit in (HYPERHDR_UNIT, BRIDGE_UNIT, OPENRGB_UNIT):
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
            "openrgb": self._openrgb_state(cfg, states),
            "api": info is not None,
            "leds": components.get("LEDDEVICE"),
            "forwarding": components.get("FORWARDER"),
            "autostart": enabled == "enabled",
            "webui": f"http://{_local_ip() if host == '127.0.0.1' else host}:8090",
            "v4l2_missing": cfg["CAPTURE_MODE"] == "v4l2" and not os.path.exists(cfg["V4L2_DEVICE"]),
            "portable": os.path.exists(os.path.join(PORTABLE_DIR, "bin", "hyperhdr")),
        }

    def _openrgb_state(self, cfg: dict, states: dict) -> str:
        if cfg["OPENRGB_ENABLE"] != "1":
            return "disabled"
        if states[OPENRGB_UNIT] != "active":
            # As cores vêm do HyperHDR: sem a chave principal ligada não há o que sincronizar
            return "waiting_main" if states[BRIDGE_UNIT] != "active" else states[OPENRGB_UNIT]
        st = _read_openrgb_status() or {}
        if st.get("state") == "no_server":
            return "no_server"
        if not st.get("devices"):
            return "no_devices"
        if time.time() - (st.get("last_packet") or 0) > OPENRGB_STALE_S:
            return "no_data"
        return "syncing"

    async def get_settings(self) -> dict:
        return _read_config()

    async def set_setting(self, key: str, value: str) -> bool:
        value = str(value).strip()
        if key not in DEFAULTS or "\n" in value:
            return False
        if key in CHOICES and value not in CHOICES[key]:
            return False
        cfg = _read_config()
        if key in OPENRGB_KEYS:
            return await self._set_openrgb_setting(cfg, key, value)
        old_units = self._units(cfg)
        _, active = await _systemctl("is-active", BRIDGE_UNIT)
        _, enabled = await _systemctl("is-enabled", BRIDGE_UNIT)
        cfg[key] = value
        _write_config(cfg)
        await self._detect(force=True)
        if active == "active":
            # Aplica na hora: para o conjunto antigo e sobe o novo (pode mudar com HyperHDR externo)
            await _stop(*old_units)
            await _systemctl("start", *self._units(cfg))
        if enabled == "enabled":
            await _systemctl("disable", *old_units)
            await _systemctl("enable", *self._units(cfg))
        return True

    async def _set_openrgb_setting(self, cfg: dict, key: str, value: str) -> bool:
        # Liga/desliga só as luzes do PC, sem desconectar a captura do gamescope
        _, active = await _systemctl("is-active", BRIDGE_UNIT)
        _, enabled = await _systemctl("is-enabled", BRIDGE_UNIT)
        was_on = cfg["OPENRGB_ENABLE"] == "1"
        cfg[key] = value
        _write_config(cfg)
        now_on = cfg["OPENRGB_ENABLE"] == "1"
        if was_on and (not now_on or active == "active"):
            await _stop(*OPENRGB_UNITS)
        if now_on and active == "active":
            await _systemctl("start", *OPENRGB_UNITS)
        if enabled == "enabled":
            await _systemctl("enable" if now_on else "disable", *OPENRGB_UNITS)
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
        if enabled:
            code, out = await _systemctl("start", *self._units(_read_config()))
        else:
            code, out = await _stop(*ALL_UNITS)
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
        await _systemctl("disable", *ALL_UNITS)
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

    # ---------- Assistente de configuração ----------

    async def check_dependencies(self) -> list[dict]:
        _, out = await _run("/bin/bash", os.path.join(SCRIPTS, "check-deps.sh"))
        family = _distro_family()
        items = []
        for line in out.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            item["package"] = PACKAGES.get(item["id"], {}).get(family, "")
            items.append(item)
        return items

    async def _wait_api(self, host: str, seconds: float) -> dict | None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            info = await asyncio.to_thread(_rpc, host, {"command": "sysinfo"})
            if info and info.get("success"):
                return info
            await asyncio.sleep(1)
        return None

    async def test_hyperhdr(self) -> dict:
        """Garante que o HyperHDR está no ar e testa a API (8090) e o Flatbuffers (19400)."""
        cfg = _read_config()
        kind, detail = await self._detect(force=True)
        host = self._api_host(cfg)
        result = {"kind": kind, "detail": detail, "host": host, "started": False, "api": False,
                  "version": None, "flatbuffers": False, "instances": [], "error": None}
        if kind == "missing":
            result["error"] = "HyperHDR não encontrado. Instale o portátil ou escolha onde ele está."
            return result
        if kind != "external":
            _, active = await _systemctl("is-active", HYPERHDR_UNIT)
            if active != "active":
                code, out = await _systemctl("start", HYPERHDR_UNIT)
                if code != 0:
                    result["error"] = f"não consegui iniciar o HyperHDR: {out[-200:]}"
                    return result
                result["started"] = True
        info = await self._wait_api(host, 30 if result["started"] else 5)
        if not info:
            result["error"] = f"a API do HyperHDR não respondeu em http://{host}:8090"
            return result
        result["api"] = True
        result["version"] = (info.get("info", {}).get("hyperhdr") or {}).get("version")
        server = await asyncio.to_thread(_rpc, host, {"command": "serverinfo"})
        if server and server.get("success"):
            result["instances"] = [
                {"index": i.get("instance"), "name": i.get("friendly_name"), "running": bool(i.get("running"))}
                for i in server["info"].get("instance", [])
            ]
        fb_host, _, fb_port = cfg["FLATBUFFERS_TARGET"].rpartition(":")
        result["flatbuffers"] = await asyncio.to_thread(_tcp_open, fb_host or "127.0.0.1", int(fb_port))
        if not result["flatbuffers"]:
            result["error"] = (f"o servidor Flatbuffers não respondeu em {cfg['FLATBUFFERS_TARGET']}. "
                               "Ative-o na Web UI do HyperHDR (Network services).")
        return result

    async def test_leds(self) -> dict:
        """Acende vermelho, verde e azul nos LEDs pelo HyperHDR, sem precisar do gamescope."""
        target = _read_config()["FLATBUFFERS_TARGET"]
        try:
            await asyncio.to_thread(_send_test_colors, target, TEST_COLORS, 1.5)
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": f"não consegui enviar para {target}: {e}"}

    async def openrgb_check(self) -> dict:
        """Garante um servidor OpenRGB e lista os dispositivos."""
        cfg = _read_config()
        host, port = cfg["OPENRGB_HOST"], int(cfg["OPENRGB_PORT"])
        result = {"installed": False, "started": False, "devices": [], "error": None}
        deps = {d["id"]: d["ok"] for d in await self.check_dependencies()}
        result["installed"] = deps.get("openrgb", False)
        if not result["installed"] and host == "127.0.0.1":
            result["error"] = "OpenRGB não encontrado. Instale: flatpak install flathub org.openrgb.OpenRGB"
            return result
        if not await asyncio.to_thread(_tcp_open, host, port, 1.0):
            await _systemctl("start", OPENRGB_SERVER_UNIT)
            result["started"] = True
        sdk = _load_script("openrgb_sdk.py")
        end = time.monotonic() + 40
        last_error = "servidor não respondeu"
        while time.monotonic() < end:
            try:
                client = await asyncio.to_thread(sdk.OpenRGBClient, host, port, "Decky HyperHDR (assistente)")
                try:
                    devices = await asyncio.to_thread(client.controllers)
                finally:
                    client.close()
                if devices:
                    result["devices"] = [{"name": d.name, "leds": d.num_leds} for d in devices]
                    return result
                last_error = "o OpenRGB não encontrou dispositivos"
            except (OSError, ValueError) as e:
                last_error = str(e)
            await asyncio.sleep(2)
        result["error"] = f"OpenRGB: {last_error}"
        return result

    async def pc_instance_status(self) -> dict:
        cfg = _read_config()
        kind, _ = await self._detect()
        server = await asyncio.to_thread(_rpc, self._api_host(cfg), {"command": "serverinfo"})
        instances = server["info"].get("instance", []) if server and server.get("success") else []
        found = next((i for i in instances if i.get("friendly_name") == PC_INSTANCE_NAME), None)
        return {
            "exists": found is not None,
            "running": bool(found and found.get("running")),
            "can_create": kind in ("native", "distrobox") and os.path.exists(HYPERHDR_DB),
            "external": kind == "external",
            "ip": _local_ip(),
            "udp_port": cfg["OPENRGB_UDP_PORT"],
        }

    async def create_pc_instance(self) -> dict:
        """Cria a instância "PC RGB" no banco do HyperHDR local (com backup), com o HyperHDR parado."""
        cfg = _read_config()
        kind, _ = await self._detect()
        if kind not in ("native", "distrobox") or not os.path.exists(HYPERHDR_DB):
            return {"ok": False, "error": "só dá para criar automaticamente com o HyperHDR nesta máquina"}
        await _systemctl("stop", HYPERHDR_UNIT)
        # Editar com o HyperHDR rodando perde a mudança: espera o processo sumir de verdade
        end = time.monotonic() + 20
        while time.monotonic() < end:
            code, _ = await _run("pgrep", "-x", "hyperhdr")
            if code != 0 and not await asyncio.to_thread(_tcp_open, "127.0.0.1", 8090, 0.5):
                break
            await asyncio.sleep(1)
        else:
            await _systemctl("start", HYPERHDR_UNIT)
            return {"ok": False, "error": "o HyperHDR não parou; feche-o (inclusive no Desktop) e tente de novo"}
        code, out = await _run("python3", os.path.join(SCRIPTS, "hyperhdr-add-instance.py"),
                               HYPERHDR_DB, cfg["OPENRGB_UDP_PORT"], PC_INSTANCE_NAME)
        try:
            result = json.loads(out.splitlines()[-1])
        except (ValueError, IndexError):
            result = {"ok": False, "error": out[-300:] or "falha ao editar o banco"}
        # Sobe de novo mesmo se estava parado: confirma que a instância nova inicia
        await _systemctl("start", HYPERHDR_UNIT)
        if result.get("ok") and not await self._wait_api("127.0.0.1", 30):
            result["warning"] = "a instância foi criada, mas o HyperHDR demorou para voltar"
        return result

    async def test_pc_leds(self) -> dict:
        """Testa o caminho inteiro: HyperHDR → instância PC RGB → ponte → OpenRGB."""
        cfg = _read_config()
        if cfg["OPENRGB_ENABLE"] != "1":
            cfg["OPENRGB_ENABLE"] = "1"
            _write_config(cfg)
        await _systemctl("start", *OPENRGB_UNITS)
        end = time.monotonic() + 40
        st = None
        while time.monotonic() < end:
            st = _read_openrgb_status()
            if st and st.get("devices"):
                break
            await asyncio.sleep(1)
        else:
            state = (st or {}).get("state", "sem resposta da ponte")
            return {"ok": False, "error": f"a ponte do OpenRGB não ficou pronta ({state})"}
        before = st.get("last_packet") or 0
        leds = await self.test_leds()
        if not leds["ok"]:
            return leds
        await asyncio.sleep(2.5)  # o arquivo de status é atualizado a cada 2 s
        st = _read_openrgb_status() or {}
        if (st.get("last_packet") or 0) <= before:
            return {"ok": False, "error": "as cores não chegaram à ponte: confira a saída udpraw da instância "
                                          f"\"{PC_INSTANCE_NAME}\" (127.0.0.1:{cfg['OPENRGB_UDP_PORT']})"}
        return {"ok": True, "devices": st.get("devices")}

    async def finish_setup(self, autostart: bool, start_now: bool) -> bool:
        cfg = _read_config()
        cfg["SETUP_DONE"] = "1"
        _write_config(cfg)
        await self.set_autostart(autostart)
        if start_now:
            await self.set_enabled(True)
        return True

    async def _main(self):
        await self._install_units()
        await self._migrate_legacy()
        decky.logger.info("HyperHDR Toggle carregado")

    async def _unload(self):
        pass

    async def _uninstall(self):
        # Não deixa a captura rodando nem units apontando para um plugin removido
        await _stop(*ALL_UNITS)
        await _systemctl("disable", *ALL_UNITS)
        for name in _unit_files():
            try:
                os.remove(os.path.join(UNIT_DIR, name))
            except FileNotFoundError:
                pass
        await _systemctl("daemon-reload")
