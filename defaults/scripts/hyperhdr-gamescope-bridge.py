#!/usr/bin/env python3
"""Ponte gamescope -> HyperHDR com desligamento suave.

O gamescope pode travar (SIGSEGV) se o consumidor do nó PipeWire desconectar
enquanto ele copia um quadro. Ao receber SIGTERM/SIGINT, esta ponte primeiro
pausa o stream (pipewiresrc PLAYING->PAUSED => pw_stream_set_active(false)),
espera o gamescope parar de copiar e só então desconecta.

Lê a mesma configuração do script bash (variáveis de ambiente).
"""
import os
import signal
import sys
import threading

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))

# Tempo com o stream pausado antes de desconectar. Vários vblanks a 60 Hz+.
PAUSE_BEFORE_DISCONNECT_MS = 300

MODE = os.environ.get("CAPTURE_MODE", "flatbuffers")
WIDTH = int(os.environ.get("BRIDGE_WIDTH", "320"))
HEIGHT = int(os.environ.get("BRIDGE_HEIGHT", "180"))
FPS = int(os.environ.get("BRIDGE_FPS", "30"))


def build_pipeline() -> str:
    # Nunca restringir o formato direto no pipewiresrc: uma negociação recusada
    # derruba o PipeWire do gamescope até a sessão reiniciar.
    src = (
        "pipewiresrc target-object=gamescope do-timestamp=true"
        f" ! videorate drop-only=true max-rate={FPS}"
        " ! videoscale method=nearest-neighbour"
        f" ! video/x-raw,width={WIDTH},height={HEIGHT}"
        " ! videoconvert"
    )
    if MODE == "v4l2":
        device = os.environ.get("V4L2_DEVICE", "/dev/video50")
        return f"{src} ! video/x-raw,format=YUY2,framerate={FPS}/1 ! v4l2sink device={device} sync=false"
    return f"{src} ! video/x-raw,format=RGB ! appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false"


def main() -> int:
    Gst.init(None)
    pipeline = Gst.parse_launch(build_pipeline())
    loop = GLib.MainLoop()
    exit_code = 0

    if MODE != "v4l2":
        from importlib import import_module

        sender = import_module("hyperhdr-flatbuffers-sender")
        host, _, port = os.environ.get("FLATBUFFERS_TARGET", "127.0.0.1:19400").rpartition(":")
        conn = sender.Connection(
            host or "127.0.0.1", int(port), "Decky gamescope", int(os.environ.get("FLATBUFFERS_PRIORITY", "150"))
        )
        state = {"last": None}
        # on_sample roda no thread do GStreamer e resend no loop principal
        lock = threading.Lock()

        def send(payload):
            with lock:
                conn.send(payload)

        def on_sample(sink):
            sample = sink.emit("pull-sample")
            buf = sample.get_buffer()
            ok, info = buf.map(Gst.MapFlags.READ)
            if ok:
                try:
                    state["last"] = sender.image_message(bytes(info.data), WIDTH, HEIGHT)
                finally:
                    buf.unmap(info)
                send(state["last"])
            return Gst.FlowReturn.OK

        def resend():
            # Menu parado não gera quadros; reenvia para o servidor não fechar a conexão
            if state["last"] is not None:
                send(state["last"])
            return True

        pipeline.get_by_name("sink").connect("new-sample", on_sample)
        GLib.timeout_add(int(sender.RESEND_INTERVAL * 1000), resend)

    def on_message(_bus, msg):
        nonlocal exit_code
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"erro: {err.message} ({dbg})", file=sys.stderr, flush=True)
            exit_code = 1
            loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            loop.quit()

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)

    stopping = {"done": False}

    def disconnect():
        pipeline.set_state(Gst.State.NULL)
        loop.quit()
        return False

    def on_signal():
        if not stopping["done"]:
            stopping["done"] = True
            print("parando: pausando o stream antes de desconectar", flush=True)
            pipeline.set_state(Gst.State.PAUSED)
            GLib.timeout_add(PAUSE_BEFORE_DISCONNECT_MS, disconnect)
        return True

    try:  # GLib >= 2.80 move a API para GLibUnix
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix

        signal_add = GLibUnix.signal_add
    except (ImportError, ValueError):
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal_add(GLib.PRIORITY_HIGH, sig, on_signal)

    pipeline.set_state(Gst.State.PLAYING)
    print(f"gamescope conectado, modo {MODE} {WIDTH}x{HEIGHT}@{FPS} (desligamento suave)", flush=True)
    loop.run()
    pipeline.set_state(Gst.State.NULL)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
