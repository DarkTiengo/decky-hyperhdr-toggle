# HyperHDR Toggle (Decky)

Plugin do [Decky Loader](https://decky.xyz) que liga e desliga o [HyperHDR](https://github.com/awawa-dev/HyperHDR) **direto pelo Game Mode** (sessão gamescope do Steam), capturando a tela do jogo para os seus LEDs.

*English version below.*

## Por que existe

O grabber de tela do HyperHDR no Linux usa o `xdg-desktop-portal`, que existe no KDE/GNOME mas **não no gamescope**. No Game Mode o HyperHDR fica sem imagem. O gamescope, porém, publica a saída composta como um nó PipeWire chamado `gamescope`. Este plugin lê esse nó com GStreamer e entrega os quadros ao HyperHDR.

```
gamescope ──PipeWire──▶ gst-launch (reduz p/ 320x180) ──▶ HyperHDR ──▶ LEDs
                                       │
                         Flatbuffers (TCP 19400, padrão)
                         ou v4l2loopback (/dev/video50, opcional)
```

## Recursos

- Botão no menu rápido (…) para ligar/desligar captura + HyperHDR
- Funciona com HyperHDR **nativo**, **portátil** (o plugin baixa a release oficial), **distrobox** ou **em outro computador** (só a captura roda aqui)
- Captura por **Flatbuffers** (sem root, sem módulo de kernel) ou **v4l2loopback**
- Liga/desliga a saída de LEDs e o forwarder sem parar o HyperHDR
- "Iniciar com o sistema" via serviços systemd do usuário
- Escolha de qualidade (160x90 até 640x360, 25–60 fps)
- **Freio da captura** (ligado por padrão): reduz a perda de FPS no jogo de ~5,3% para ~1,6%

## Requisitos

- Decky Loader
- Sessão gamescope do Steam (SteamOS, Bazzite, ChimeraOS, etc.)
- `gst-launch-1.0` com os plugins `pipewiresrc`, `videoscale`, `videoconvert`, `videorate`
- `python3` e `pw-cli` no sistema
- Para o modo v4l2loopback: o módulo `v4l2loopback` e `v4l2-ctl`

## Instalação

1. Baixe o `hyperhdr-toggle.zip` da [última release](https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest).
2. No Decky: **Configurações → Geral → Modo desenvolvedor** ligado, depois **Desenvolvedor → Instalar plugin de um ZIP** e escolha o arquivo.
   - Ou use **Instalar plugin de uma URL** com o link do zip da release.
3. Abra o menu (…) → **HyperHDR**.

### Escolhendo onde está o HyperHDR

| Opção | Quando usar |
| --- | --- |
| Automático | Detecta nesta ordem: `HYPERHDR_BIN`, portátil do plugin, `hyperhdr` no PATH, distrobox |
| Nativo / portátil | HyperHDR instalado no sistema, ou o portátil baixado pelo botão **Instalar HyperHDR portátil** (vai para `~/.local/share/hyperhdr-portable`, sem precisar de root; ideal em sistemas imutáveis como SteamOS) |
| Distrobox | HyperHDR dentro de um container (nome padrão `hyperhdr-box`, procura qualquer container com "hyperhdr" no nome) |
| Outro computador | O HyperHDR roda em outra máquina (ex.: Raspberry Pi, Home Assistant). Informe `host:19400` no campo **Servidor Flatbuffers** |

A configuração do HyperHDR (`~/.hyperhdr`) é a mesma nos modos nativo, portátil e distrobox.

### Métodos de captura

- **Flatbuffers (padrão):** envia os quadros para o servidor Flatbuffers do HyperHDR (habilitado por padrão, porta 19400) com prioridade 150. Não precisa de root nem de configuração no HyperHDR. Ao desligar, a prioridade some sozinha.
- **v4l2loopback:** escreve numa webcam virtual que o HyperHDR lê pelo grabber de vídeo. Rode uma vez `sudo bash ~/homebrew/plugins/<pasta do plugin>/scripts/setup-v4l2loopback.sh` e, na web UI do HyperHDR, ative **Video capture** em `/dev/video50`. O script preserva a câmera virtual do OBS no Bazzite.

## Desempenho

Medido no Bazzite com Crimson Desert em 4K (~105 fps), captura em 320x180 a 30 fps. Cada rodada foi registrada por 30 s no MangoHud.

| Situação | FPS médio | Perda | CPU da ponte (1 núcleo) |
| --- | --- | --- | --- |
| Captura desligada | 105,8 | — | — |
| Captura ligada, **com freio** (padrão) | 104,2 | ~1,6% | ~3,2% |
| Captura ligada, sem freio | 100,2 | ~5,3% | ~9,4% |

O HyperHDR em si usa ~1–2% de um núcleo e não teve custo mensurável no FPS.

**De onde vem a perda:** enquanto alguém consome o nó PipeWire, o gamescope renderiza uma cópia da tela inteira a cada vblank e espera a GPU terminar (`paint_pipewire()` → `vulkan_screenshot` + `vulkan_wait`). Em 4K isso pesa, e a qualidade escolhida no plugin não muda nada, porque a cópia acontece em resolução cheia antes da ponte reduzir a imagem.

**O freio:** a ponte segura cada quadro até completar 1/FPS (33 ms a 30 fps) antes de devolvê-lo. Sem buffer livre, o gamescope pula a cópia: em vez de ~100 cópias por segundo ele faz ~30. O efeito colateral é que o gamescope grava `pipewire: warning: out of buffers` no journal a cada vblank em que pulou a cópia, ~90 linhas por segundo enquanto a captura roda. Não há como filtrar isso sem root (`LogFilterPatterns=` não vale para serviços de usuário). Se o log incomodar, desligue o **Freio da captura** no painel. O freio precisa do `python3-gi`; sem ele, a ponte usa o `gst-launch` e roda sem freio.

Desligado pelo botão, nada fica rodando.

## Arquivos

- Configuração: `~/.config/hyperhdr-decky.env` (editada pelo plugin; dá para ajustar `HYPERHDR_BIN`, `HYPERHDR_BOX`, `FLATBUFFERS_PRIORITY`, `V4L2_DEVICE`)
- Serviços: `~/.config/systemd/user/decky-hyperhdr.service` e `decky-hyperhdr-bridge.service`
- Logs: `journalctl --user -u decky-hyperhdr -u decky-hyperhdr-bridge`

## Problemas conhecidos

- **O gamescope pode travar ao desligar a captura com um jogo aberto.** Se a captura desconecta no meio da cópia de um quadro, o gamescope 3.16.x pode fechar com SIGSEGV, levando o jogo junto. Foi visto 1 vez em ~10 desligamentos. Quando o `python3-gi` (bindings do GStreamer) está disponível, a ponte pausa o stream e espera antes de desconectar, para reduzir esse risco. Mesmo assim, **prefira ligar/desligar fora dos jogos**. Trocar a qualidade ou o método de captura também reinicia a ponte.
- **Nunca force formato no nó `gamescope`.** Se um consumidor pedir um formato que o gamescope recusa (ex.: `pipewiresrc ! video/x-raw,format=NV12`), o PipeWire do gamescope encerra e o nó só volta depois de reiniciar a sessão. A ponte não restringe o formato. Reportado em [OpenGamingCollective/gamescope#27](https://github.com/OpenGamingCollective/gamescope/issues/27).
- **v4l2loopback no Bazzite/Fedora Atomic:** o módulo é carregado no initramfs, que não lê `/etc/modprobe.d`. O `setup-v4l2loopback.sh` vale até o próximo boot. Para persistir, use argumentos do kernel: `rpm-ostree kargs --append-if-missing='v4l2loopback.devices=2' --append-if-missing='v4l2loopback.video_nr=0,50' --append-if-missing='v4l2loopback.exclusive_caps=1,1' --append-if-missing='v4l2loopback.card_label=OBS Virtual Camera,GamescopeCapture'`. Ou simplesmente use o modo Flatbuffers.
- **Log do gamescope com o freio ligado:** ~90 linhas/s de `out of buffers` no journal enquanto captura (veja *Desempenho*).

## Problemas comuns

- **Captura "Rodando" mas sem LEDs:** confira na web UI (porta 8090) se a prioridade 150 "Decky gamescope" aparece. Ela só aparece em Game Mode, porque fora dele não existe o nó `gamescope`.
- **"HyperHDR não encontrado":** use **Instalar HyperHDR portátil** ou defina `HYPERHDR_BIN` no arquivo de configuração.
- **LEDs via USB/serial no modo nativo:** o seu usuário precisa ter acesso à porta serial (grupo `uucp`/`dialout`, conforme a distro).
- **HDR:** com jogos em HDR, ajuste o tone mapping do HyperHDR.

## Status

Testado no Bazzite (Fedora 44, KDE + Game Mode, gamescope 3.16.31), com HyperHDR 22 em distrobox, nos dois métodos de captura. Ainda **não foi testado no SteamOS** do Steam Deck. Relatos são bem-vindos nas issues.

---

## English

Decky Loader plugin that toggles [HyperHDR](https://github.com/awawa-dev/HyperHDR) ambient lighting **from Steam Game Mode**. HyperHDR's Linux screen grabber needs `xdg-desktop-portal`, which gamescope doesn't provide. This plugin reads gamescope's own PipeWire node (`gamescope`) with GStreamer, downscales it, and feeds it to HyperHDR through:

- **Flatbuffers** (default): TCP 19400, priority 150. No root, no kernel module, no HyperHDR config changes.
- **v4l2loopback** (optional): `/dev/video50` used by HyperHDR's video grabber. Run `scripts/setup-v4l2loopback.sh` once as root.

HyperHDR can be **native**, a **portable** build the plugin downloads from the official releases (no root, good for SteamOS), inside **distrobox**, or on **another machine** (only the capture runs locally).

**Install:** download `hyperhdr-toggle.zip` from the [latest release](https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest), enable Decky developer mode, then use *Install plugin from ZIP*.

**Requirements:** gamescope session, `gst-launch-1.0` with `pipewiresrc`, `python3`, `pw-cli`.

**Cost:** gamescope renders a full-resolution copy every vblank for any PipeWire consumer. In Crimson Desert at 4K that cost ~5.3% FPS. The bridge's **capture throttle** (on by default) holds each buffer for 1/FPS, so gamescope skips most copies. With it the loss is ~1.6% and the bridge uses ~3% of one core. The side effect is that gamescope logs `out of buffers` ~90×/s while capturing, which you can turn off in the panel. Nothing runs while it is off.

**Known issues:** gamescope 3.16.x may SIGSEGV when the capture disconnects mid-copy (seen once in ~10 stops), so prefer toggling outside games. The bridge pauses the stream before disconnecting when `python3-gi` is available. Never force a format on the `gamescope` node: a rejected negotiation kills gamescope's PipeWire until the session restarts.

**Status:** tested on Bazzite only; SteamOS reports welcome.

## Licenças / Licenses

- Este plugin: BSD-3-Clause (baseado no [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template))
- `py_modules/flatbuffers`: [FlatBuffers](https://github.com/google/flatbuffers), Apache-2.0 (`py_modules/flatbuffers/LICENSE`)
- O esquema `hyperhdr_request.fbs` vem do [HyperHDR](https://github.com/awawa-dev/HyperHDR) (MIT)
