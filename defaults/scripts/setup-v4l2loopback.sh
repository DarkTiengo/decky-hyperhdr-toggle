#!/usr/bin/env bash
# Opcional: cria /dev/video50 para o modo de captura "v4l2" (grabber de vídeo do HyperHDR).
# O modo padrão (Flatbuffers) não precisa disto. Rode com: sudo bash setup-v4l2loopback.sh
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "rode como root: sudo bash $0" >&2; exit 1; }
modinfo v4l2loopback >/dev/null 2>&1 || { echo "este kernel não tem o módulo v4l2loopback; use o modo Flatbuffers" >&2; exit 1; }

CONF=/etc/modprobe.d/99-hyperhdr-loopback.conf
if grep -rqs "OBS Virtual Camera" /usr/lib/modprobe.d/ /etc/modprobe.d/*v4l2loopback*.conf 2>/dev/null; then
    # Distros como o Bazzite já usam o v4l2loopback para o OBS em /dev/video0: mantém esse device
    echo 'options v4l2loopback devices=2 video_nr=0,50 card_label="OBS Virtual Camera,GamescopeCapture" exclusive_caps=1,1' > "$CONF"
else
    echo 'options v4l2loopback video_nr=50 card_label=GamescopeCapture exclusive_caps=1' > "$CONF"
fi
echo v4l2loopback > /etc/modules-load.d/99-hyperhdr-loopback.conf
echo "config: $CONF"

if [[ ! -e /dev/video50 ]]; then
    if modprobe -r v4l2loopback 2>/dev/null; then
        modprobe v4l2loopback
    else
        echo "v4l2loopback em uso; /dev/video50 aparece depois de reiniciar" >&2
    fi
fi
ls -l /dev/video50 2>/dev/null || true
if command -v rpm-ostree >/dev/null 2>&1; then
    # Em sistemas atômicos o módulo carrega no initramfs, que não lê /etc/modprobe.d
    echo "AVISO: em sistemas rpm-ostree (Bazzite, Fedora Atomic) esta config não vale depois do reboot."
    echo "Para persistir, use argumentos do kernel:"
    echo "  sudo rpm-ostree kargs --append-if-missing=v4l2loopback.devices=2 --append-if-missing=v4l2loopback.video_nr=0,50 \\"
    echo "       --append-if-missing=v4l2loopback.exclusive_caps=1,1 '--append-if-missing=v4l2loopback.card_label=OBS Virtual Camera,GamescopeCapture'"
fi
echo "No HyperHDR ative Video capture em /dev/video50 e escolha 'v4l2loopback' no plugin."
