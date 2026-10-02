#!/usr/bin/env bash
# Verifica o que o plugin precisa no sistema e imprime uma linha JSON por item.
# Usado pelo assistente de configuração; as mesmas checagens estão no README.
set -uo pipefail

item() { # id ok obrigatório
    printf '{"id":"%s","ok":%s,"required":%s}\n' "$1" "$2" "$3"
}
has() { command -v "$1" >/dev/null 2>&1 && echo true || echo false; }
gst() { gst-inspect-1.0 "$1" >/dev/null 2>&1 && echo true || echo false; }

item gst-launch "$(has gst-launch-1.0)" true
item pipewiresrc "$(gst pipewiresrc)" true
item gst-base "$( [[ $(gst videoscale) == true && $(gst videoconvert) == true && $(gst videorate) == true ]] && echo true || echo false)" true
item python3 "$(has python3)" true
item pw-cli "$(has pw-cli)" true
item python3-gi "$(python3 -c 'import gi; gi.require_version("Gst","1.0"); from gi.repository import Gst' >/dev/null 2>&1 && echo true || echo false)" false
item curl "$(has curl)" false
item distrobox "$(has distrobox)" false
item openrgb "$( { command -v openrgb >/dev/null 2>&1 || flatpak info org.openrgb.OpenRGB >/dev/null 2>&1; } && echo true || echo false)" false
item ss "$(has ss)" false
