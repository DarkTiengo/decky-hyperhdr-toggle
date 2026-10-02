#!/usr/bin/env bash
# Descobre como o HyperHDR está instalado e o inicia/para.
#   hyperhdr-launch.sh detect  -> imprime "<modo> <detalhe>" (native <bin> | distrobox <box> | external - | missing -)
#   hyperhdr-launch.sh start   -> roda o HyperHDR em primeiro plano (usado pelo systemd)
#   hyperhdr-launch.sh stop    -> encerra o HyperHDR quando ele roda dentro do distrobox
set -uo pipefail

MODE="${HYPERHDR_MODE:-auto}"
BOX="${HYPERHDR_BOX:-hyperhdr-box}"
PORTABLE_BIN="${HYPERHDR_PORTABLE_DIR:-$HOME/.local/share/hyperhdr-portable}/bin/hyperhdr"

find_native() {
    if [[ -n "${HYPERHDR_BIN:-}" && -x "$HYPERHDR_BIN" ]]; then
        echo "$HYPERHDR_BIN"
    elif [[ -x "$PORTABLE_BIN" ]]; then
        echo "$PORTABLE_BIN"
    elif command -v hyperhdr >/dev/null 2>&1; then
        command -v hyperhdr
    else
        return 1
    fi
}

find_box() {
    command -v distrobox >/dev/null 2>&1 || return 1
    local names
    names="$(distrobox list --no-color 2>/dev/null | awk -F'|' 'NR>1 {gsub(/ /,"",$2); print $2}')"
    if grep -qx "$BOX" <<<"$names"; then
        echo "$BOX"
    else
        grep -m1 -i hyperhdr <<<"$names"
    fi
}

detect() {
    local found
    case "$MODE" in
        native)
            found="$(find_native)" && echo "native $found" || echo "missing -" ;;
        distrobox)
            found="$(find_box)" && echo "distrobox $found" || echo "missing -" ;;
        external)
            echo "external -" ;;
        *)
            if found="$(find_native)"; then echo "native $found"
            elif found="$(find_box)"; then echo "distrobox $found"
            else echo "missing -"
            fi ;;
    esac
}

wait_for_v4l2() {
    # O grabber V4L2 do HyperHDR só enxerga o loopback se a ponte já estiver escrevendo nele
    local dev="${V4L2_DEVICE:-/dev/video50}"
    for _ in $(seq 15); do
        v4l2-ctl -d "$dev" --info 2>/dev/null | grep -q "Video Capture" && return 0
        sleep 1
    done
}

read -r kind detail < <(detect)

case "${1:-start}" in
    detect)
        echo "$kind $detail" ;;
    start)
        [[ "${CAPTURE_MODE:-flatbuffers}" == "v4l2" ]] && wait_for_v4l2
        case "$kind" in
            native) exec "$detail" ;;
            distrobox) exec distrobox enter --no-tty --name "$detail" -- hyperhdr ;;
            external) echo "HyperHDR externo: nada para iniciar" >&2; exit 0 ;;
            *) echo "HyperHDR não encontrado (instale pelo plugin ou ajuste HYPERHDR_MODE)" >&2; exit 1 ;;
        esac ;;
    stop)
        # Processo dentro do container fica fora do cgroup deste serviço
        [[ "$kind" == "distrobox" ]] && distrobox enter --no-tty --name "$detail" -- pkill -x hyperhdr
        exit 0 ;;
esac
