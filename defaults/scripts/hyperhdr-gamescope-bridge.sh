#!/usr/bin/env bash
# Lê a saída do gamescope (nó PipeWire "gamescope") e entrega ao HyperHDR.
#   CAPTURE_MODE=flatbuffers  -> envia quadros RGB ao servidor Flatbuffers (sem root, padrão)
#   CAPTURE_MODE=v4l2         -> escreve numa webcam virtual v4l2loopback (grabber de vídeo do HyperHDR)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODE="${CAPTURE_MODE:-flatbuffers}"
WIDTH="${BRIDGE_WIDTH:-320}"
HEIGHT="${BRIDGE_HEIGHT:-180}"
FPS="${BRIDGE_FPS:-30}"

until pw-cli ls Node 2>/dev/null | grep -q 'node.name = "gamescope"'; do
    sleep 3
done
echo "gamescope encontrado, modo $MODE ${WIDTH}x${HEIGHT}@${FPS}"

# Com as bindings do GStreamer para Python, usa a ponte com desligamento suave
# (pausa o stream antes de desconectar; evita um SIGSEGV do gamescope)
if [[ "${BRIDGE_IMPL:-auto}" != "gst-launch" ]] && python3 -c 'import gi; gi.require_version("Gst", "1.0")' 2>/dev/null; then
    [[ "$MODE" == "v4l2" && ! -e "${V4L2_DEVICE:-/dev/video50}" ]] && { echo "${V4L2_DEVICE:-/dev/video50} não existe (veja scripts/setup-v4l2loopback.sh)" >&2; exit 1; }
    exec python3 "$HERE/hyperhdr-gamescope-bridge.py"
fi
echo "python3-gi indisponível: usando gst-launch (sem desligamento suave)" >&2

# videorate antes de escalar/converter para descartar quadros o mais cedo possível
SRC=(pipewiresrc target-object=gamescope do-timestamp=true
     ! videorate drop-only=true max-rate="$FPS"
     ! videoscale method=nearest-neighbour
     ! "video/x-raw,width=$WIDTH,height=$HEIGHT"
     ! videoconvert)

case "$MODE" in
    v4l2)
        DEVICE="${V4L2_DEVICE:-/dev/video50}"
        [[ -e "$DEVICE" ]] || { echo "$DEVICE não existe (veja scripts/setup-v4l2loopback.sh)" >&2; exit 1; }
        exec gst-launch-1.0 -q "${SRC[@]}" \
            ! "video/x-raw,format=YUY2,framerate=$FPS/1" \
            ! v4l2sink device="$DEVICE" sync=false ;;
    flatbuffers)
        # -q é obrigatório: sem ele o gst-launch escreve mensagens no stdout, que é o canal dos quadros
        gst-launch-1.0 -q "${SRC[@]}" ! "video/x-raw,format=RGB" ! fdsink fd=1 \
            | exec python3 "$HERE/hyperhdr-flatbuffers-sender.py" \
                --target "${FLATBUFFERS_TARGET:-127.0.0.1:19400}" \
                --priority "${FLATBUFFERS_PRIORITY:-150}" \
                --width "$WIDTH" --height "$HEIGHT" ;;
    *)
        echo "CAPTURE_MODE inválido: $MODE" >&2; exit 1 ;;
esac
