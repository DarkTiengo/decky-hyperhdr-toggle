#!/usr/bin/env bash
# Sobe o servidor SDK do OpenRGB sem interface, para a ponte das luzes do PC.
# Se já houver um servidor na porta (ex.: a interface do OpenRGB aberta no Desktop
# com "Start server"), usa esse e só fica esperando, para não disputar o hardware.
set -uo pipefail

PORT="${OPENRGB_PORT:-6742}"

if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
    echo "já existe um servidor OpenRGB na porta $PORT; usando esse"
    exec sleep infinity
fi

if [[ -n "${OPENRGB_CMD:-}" ]]; then
    read -r -a CMD <<<"$OPENRGB_CMD"
elif command -v openrgb >/dev/null 2>&1; then
    CMD=(openrgb)
elif flatpak info org.openrgb.OpenRGB >/dev/null 2>&1; then
    # --die-with-parent: o Flatpak põe o app num scope próprio, fora deste serviço;
    # sem isso, parar o serviço deixaria o servidor rodando
    CMD=(flatpak run --die-with-parent org.openrgb.OpenRGB)
else
    echo "OpenRGB não encontrado (instale o Flatpak org.openrgb.OpenRGB ou defina OPENRGB_CMD)" >&2
    exit 1
fi

# --noautoconnect: não virar cliente de outro servidor; sem --gui não abre janela
exec "${CMD[@]}" --server --server-port "$PORT" --noautoconnect
