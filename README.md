# HyperHDR Toggle

**Luz ambiente com [HyperHDR](https://github.com/awawa-dev/HyperHDR) no Game Mode do Steam.** Este é um plugin do [Decky Loader](https://decky.xyz) que captura a imagem do jogo direto do gamescope e manda para os seus LEDs. Ligar e desligar fica no menu rápido (…), sem sair do jogo e sem passar pelo modo Desktop.

[![Release](https://img.shields.io/github/v/release/DarkTiengo/decky-hyperhdr-toggle)](https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest)
[![License](https://img.shields.io/github/license/DarkTiengo/decky-hyperhdr-toggle)](LICENSE)

*English summary at the end.* · **🙋 Testadores procurados (SteamOS e outras distros):** [#1](https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/1)

---

## Sumário

- [O problema](#o-problema)
- [Como funciona](#como-funciona)
- [Recursos](#recursos)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração passo a passo](#configuração-passo-a-passo)
- [Painel do plugin](#painel-do-plugin)
- [Configuração avançada](#configuração-avançada)
- [Luzes do PC (OpenRGB)](#luzes-do-pc-openrgb)
- [Desempenho](#desempenho)
- [Problemas conhecidos](#problemas-conhecidos)
- [Solução de problemas](#solução-de-problemas)
- [Desinstalação](#desinstalação)
- [Desenvolvimento](#desenvolvimento)
- [Status e créditos](#status-e-créditos)
- [English](#english)

---

## O problema

No Linux, o HyperHDR captura a tela pelo `xdg-desktop-portal` (ScreenCast). O KDE e o GNOME têm esse portal, mas **o gamescope, compositor do Game Mode do Steam, não tem**. Por isso o HyperHDR funciona no modo Desktop e fica sem imagem no Game Mode, justamente onde se joga. Quem usa Bazzite, SteamOS, ChimeraOS e similares acabava tendo que jogar no Desktop para ter luz ambiente.

O gamescope, porém, publica a imagem já composta da tela como um **nó PipeWire chamado `gamescope`**. É o mesmo que o Steam usa para gravar e para o Remote Play. Este plugin lê esse nó e entrega os quadros ao HyperHDR.

## Como funciona

```
 ┌───────────┐  PipeWire   ┌──────────────────────────┐   Flatbuffers (TCP 19400)   ┌──────────┐     ┌──────┐
 │ gamescope │ ──────────▶ │ ponte (GStreamer+Python) │ ──────────────────────────▶ │ HyperHDR │ ──▶ │ LEDs │
 │ (Game     │  nó         │ reduz p/ 320x180 @30fps  │   ou v4l2loopback           │ (local ou│     └──────┘
 │  Mode)    │ "gamescope" │ freio + desligamento     │   (/dev/video50)            │  remoto) │
 └───────────┘             │ suave                    │                             └──────────┘
                           └──────────────────────────┘
```

- **Ponte de captura** (`decky-hyperhdr-bridge.service`): espera o nó `gamescope` aparecer, lê os quadros com o GStreamer, reduz a imagem e envia ao HyperHDR. Quando você troca para o Desktop, ela volta a esperar sozinha.
- **HyperHDR** (`decky-hyperhdr.service`): roda nativo, portátil ou dentro de um distrobox. Também pode estar em outro computador.
- **Plugin**: cria os dois serviços systemd do usuário, liga e desliga os dois e mostra o estado no menu rápido. Os serviços não dependem do Decky, então a captura continua mesmo se a interface do Steam reiniciar.

## Recursos

- Botão no menu rápido (…) para ligar e desligar a captura e o HyperHDR
- HyperHDR **nativo**, **portátil** (o plugin baixa a release oficial, sem root), em **distrobox** ou **em outro computador** (Raspberry Pi, Home Assistant, etc.)
- Dois métodos de captura:
  - **Flatbuffers** (padrão): sem root, sem módulo de kernel, sem mudar a configuração do HyperHDR
  - **v4l2loopback**: webcam virtual lida pelo grabber de vídeo do HyperHDR
- **Freio da captura** (ligado por padrão): reduz a perda de FPS no jogo de ~5,3% para ~1,6%
- **Desligamento suave**: pausa o stream antes de desconectar, para evitar um travamento do gamescope
- Liga e desliga a saída de LEDs e o forwarder do HyperHDR sem parar o serviço
- **Luzes do PC via OpenRGB:** RAM, placa-mãe e ventoinhas RGB seguem a mesma imagem, sincronizadas com a TV
- Opção "Iniciar com o sistema"
- Quatro perfis de qualidade, de 160x90 a 640x360 e de 25 a 60 fps

## Requisitos

### O que precisa estar instalado

| Componente | Para quê | Obrigatório? |
| --- | --- | --- |
| [Decky Loader](https://decky.xyz) v3+ | Roda o plugin no Game Mode | **Sim** |
| Sessão gamescope do Steam | É de onde vem a imagem (SteamOS, Bazzite, ChimeraOS…) | **Sim** |
| GStreamer + plugin PipeWire (`gst-launch-1.0`, `pipewiresrc`, `videoscale`, `videoconvert`, `videorate`) | Captura a tela do gamescope | **Sim** |
| `python3` | Ponte de captura e cliente Flatbuffers | **Sim** |
| `pw-cli` (utilitários do PipeWire) | Detecta quando o gamescope está ativo | **Sim** |
| Bindings do GStreamer para Python (`python3-gi` + typelib `Gst-1.0`) | Freio da captura e desligamento suave | Muito recomendado |
| [HyperHDR](https://github.com/awawa-dev/HyperHDR) | Processa a imagem e controla os LEDs | **Sim**, mas o plugin pode baixar a versão portátil sozinho, ou ele pode rodar em outro computador |
| `curl` | Baixar o HyperHDR portátil | Só se usar o portátil |
| [distrobox](https://distrobox.it) | Rodar o HyperHDR dentro de um container | Só no cenário distrobox |
| [OpenRGB](https://openrgb.org) 0.9+ e as [regras udev](https://openrgb.org/udev) | Luzes RGB do PC | Só para as [luzes do PC](#luzes-do-pc-openrgb) |
| `ss` (iproute2), `flatpak` | Servidor do OpenRGB | Só para as luzes do PC |
| Módulo `v4l2loopback` + `v4l2-ctl` (v4l-utils) | Método de captura v4l2loopback | Só se não usar o Flatbuffers (o padrão) |

### Pacotes por distribuição

| | Bazzite / Fedora | Arch / CachyOS | Debian / Ubuntu |
| --- | --- | --- | --- |
| GStreamer | `gstreamer1` | `gstreamer` | `gstreamer1.0-tools` |
| Elementos básicos | `gstreamer1-plugins-base` | `gst-plugins-base` | `gstreamer1.0-plugins-base` |
| Plugin PipeWire | `pipewire-gstreamer` | `gst-plugin-pipewire` | `gstreamer1.0-pipewire` |
| `pw-cli` | `pipewire-utils` | `pipewire` | `pipewire-bin` |
| Python + GStreamer | `python3-gobject-base` | `python-gobject` | `python3-gi` + `gir1.2-gstreamer-1.0` |
| `ss` | `iproute` | `iproute2` | `iproute2` |
| `curl` | `curl` | `curl` | `curl` |
| `v4l2-ctl` (opcional) | `v4l-utils` | `v4l-utils` | `v4l-utils` |
| distrobox (opcional) | `distrobox` | `distrobox` | `distrobox` |

**Bazzite:** tudo isso já vem na imagem (conferido no Bazzite 44), inclusive o distrobox e as regras udev do OpenRGB. Não precisa instalar nada além do Decky e, se quiser as luzes do PC, do OpenRGB.

**Fedora (não atômico):**
```bash
sudo dnf install gstreamer1 gstreamer1-plugins-base pipewire-gstreamer pipewire-utils python3-gobject-base iproute curl
```

**Arch / CachyOS:**
```bash
sudo pacman -S --needed gstreamer gst-plugins-base gst-plugin-pipewire pipewire python-gobject iproute2 curl
```

**Debian / Ubuntu:**
```bash
sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-pipewire pipewire-bin python3-gi gir1.2-gstreamer-1.0 iproute2 curl
```

**SteamOS (Steam Deck): não verificado.** O sistema é somente leitura e ainda não sabemos se ele traz o `pipewiresrc` e o `python3-gi`. Instalar pacotes com `steamos-readonly disable` + `pacman` funciona, mas é apagado a cada atualização do SteamOS. Se você tem um Steam Deck, rode a checagem abaixo e conte o resultado na [issue #1](https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/1).

**OpenRGB (opcional, para as luzes do PC):**
```bash
flatpak install flathub org.openrgb.OpenRGB
```
Também instale as [regras udev](https://openrgb.org/udev), que já vêm no Bazzite, e confira se os seus dispositivos aparecem:
```bash
flatpak run --command=openrgb org.openrgb.OpenRGB --list-devices
```

### Checagem rápida

Rode no terminal (Konsole no Desktop, ou SSH). Cada linha deve dizer `OK`:

```bash
for c in gst-launch-1.0 python3 pw-cli; do command -v $c >/dev/null && echo "$c OK" || echo "$c FALTANDO"; done
for e in pipewiresrc videoscale videoconvert videorate; do gst-inspect-1.0 $e >/dev/null 2>&1 && echo "$e OK" || echo "$e FALTANDO"; done
python3 -c 'import gi; gi.require_version("Gst","1.0"); from gi.repository import Gst' 2>/dev/null && echo "python3-gi OK" || echo "python3-gi FALTANDO (sem freio e sem desligamento suave)"
# opcionais
command -v curl >/dev/null && echo "curl OK (HyperHDR portátil)"
command -v distrobox >/dev/null && echo "distrobox OK"
flatpak info org.openrgb.OpenRGB >/dev/null 2>&1 && echo "OpenRGB OK (luzes do PC)"
```

## Instalação

### 1. Instale o Decky Loader

Siga as instruções em [decky.xyz](https://decky.xyz). No Bazzite ele também pode ser instalado com `ujust setup-decky`.

### 2. Ative o modo desenvolvedor do Decky

No Game Mode: menu rápido (…) → ícone da tomada (Decky) → engrenagem → **Geral** → ligue **Modo desenvolvedor**. Aparece a aba **Desenvolvedor**.

### 3. Instale o plugin

Na aba **Desenvolvedor** do Decky, escolha uma das opções:

- **Instalar plugin de uma URL** e cole:
  ```
  https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest/download/hyperhdr-toggle.zip
  ```
- **Instalar plugin de um arquivo ZIP**, depois de baixar o `hyperhdr-toggle.zip` da [última release](https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest).

O plugin aparece no menu rápido como **HyperHDR**. Ao carregar, ele cria os serviços em `~/.config/systemd/user/` e o arquivo de configuração `~/.config/hyperhdr-decky.env`.

### 4. Rode o assistente de configuração

Na primeira vez, o painel mostra **Abrir a configuração inicial**. Depois, o assistente continua disponível em **Configuração → Assistente de configuração**. Ele abre em tela cheia, navegável pelo controle, e passa por:

1. **Dependências:** confere tudo da tabela de [Requisitos](#requisitos) e, quando falta algo, mostra o nome do pacote para a sua distro.
2. **HyperHDR:** você escolhe onde ele está (ou instala o portátil) e testa a conexão. O assistente inicia o HyperHDR se estiver parado e confere a API (porta 8090, com a versão), o servidor Flatbuffers (porta 19400) e as instâncias.
3. **Teste dos LEDs:** acende vermelho, verde e azul pelo HyperHDR, sem precisar de jogo aberto, e pergunta se você viu. Se não, mostra o que conferir na Web UI.
4. **Luzes do PC (opcional):** procura o OpenRGB e os dispositivos e confere se existe a instância "PC RGB". Se não existir, oferece criá-la, como descrito em [Luzes do PC](#luzes-do-pc-openrgb). No fim testa o caminho inteiro (HyperHDR → instância → ponte → OpenRGB).
5. **Concluir:** escolhe se a captura inicia com o sistema e se liga agora.

> Os testes ligam o HyperHDR se ele estiver parado, mas não desligam nada. Mesmo assim, se um jogo estiver aberto, salve antes.

> O plugin ainda não está na loja oficial do Decky. Os detalhes estão em [Status e créditos](#status-e-créditos).

## Configuração passo a passo

Escolha o cenário que corresponde ao seu caso.

### Cenário A: HyperHDR num distrobox (comum no Bazzite)

Se você já usa o HyperHDR num container (por exemplo, um `hyperhdr-box` com Ubuntu):

1. No painel, deixe **Onde está o HyperHDR** em **Automático**. O plugin procura um container chamado `hyperhdr-box` ou qualquer um com "hyperhdr" no nome.
2. Em **Status**, a linha HyperHDR deve mostrar `(distrobox)`.
3. Ligue a chave **HyperHDR**.

A configuração do HyperHDR (`~/.hyperhdr`) é a mesma do Desktop, porque o distrobox compartilha a pasta pessoal. Se o container tiver outro nome, ajuste `HYPERHDR_BOX` em [Configuração avançada](#configuração-avançada).

### Cenário B: sem HyperHDR instalado (SteamOS, sistemas imutáveis)

1. Em **Onde está o HyperHDR**, escolha **Nativo / portátil**.
2. Toque em **Instalar HyperHDR portátil**. O plugin baixa o pacote oficial `HyperHDR-<versão>-Linux-x86_64.tar.gz` da [release mais recente](https://github.com/awawa-dev/HyperHDR/releases/latest) e instala em `~/.local/share/hyperhdr-portable`, sem root.
3. Ligue a chave **HyperHDR**.
4. Abra a **Web UI** mostrada no painel (`http://<ip>:8090`) em qualquer navegador da rede e configure os LEDs:
   - **LED Hardware**: tipo de controlador (WLED, Adalight/serial, etc.) e layout
   - **Capturing hardware**: nada a mudar no modo Flatbuffers
5. Se os LEDs forem por **USB/serial**, o seu usuário precisa de acesso à porta (grupo `uucp` ou `dialout`, conforme a distro).

O mesmo botão atualiza o HyperHDR portátil depois.

### Cenário C: HyperHDR instalado no sistema

Se o comando `hyperhdr` existe no PATH (pacote `.deb`, `.rpm` ou `.pkg.tar.zst`), o modo **Automático** usa esse binário. Para apontar outro caminho, defina `HYPERHDR_BIN`.

> Se a distro já rodar o HyperHDR como serviço do sistema (`hyperhdr@<usuário>.service`), desative esse serviço ou use o cenário D apontando para `127.0.0.1:19400`, para não rodar dois ao mesmo tempo.

### Cenário D: HyperHDR em outro computador

Para quem tem o HyperHDR num Raspberry Pi, no Home Assistant ou em outro PC ligado aos LEDs:

1. Em **Onde está o HyperHDR**, escolha **Outro computador**.
2. Em **Servidor Flatbuffers (host:porta)**, informe o endereço, por exemplo `192.168.0.127:19400`.
3. Ligue a chave **HyperHDR**. Só a captura roda nesta máquina; a Web UI e as chaves de LEDs passam a falar com o HyperHDR remoto.

No HyperHDR remoto, confira em **Network services** se o **Flatbuffers server** está ativo (porta 19400). Ele vem ativo por padrão.

### Escolha do método de captura

| | Flatbuffers (padrão) | v4l2loopback |
| --- | --- | --- |
| Root | Não | Sim, uma vez |
| Configuração no HyperHDR | Nenhuma | Ativar *Video capture* em `/dev/video50` |
| Funciona com HyperHDR remoto | Sim | Não |
| Prioridade no HyperHDR | 150 (acima dos grabbers) | a do grabber de vídeo (240) |

Use o **Flatbuffers**, a menos que você tenha um motivo específico. Para o v4l2loopback:

```bash
sudo bash ~/homebrew/plugins/hyperhdr-toggle/scripts/setup-v4l2loopback.sh
```

Depois, na Web UI do HyperHDR, ative **Video capture** em `GamescopeCapture (video50)`, 320x180, YUYV, e escolha **v4l2loopback** em **Método de captura** no painel. No Bazzite e no Fedora Atomic, leia [Problemas conhecidos](#problemas-conhecidos) antes, porque a configuração do módulo não sobrevive ao reboot sem um passo extra.

## Painel do plugin

| Seção | Item | O que faz |
| --- | --- | --- |
| Controle | **HyperHDR** | Liga e desliga a captura e o HyperHDR local |
| | **Saída de LEDs** | Liga e desliga o componente `LEDDEVICE` do HyperHDR sem parar o serviço |
| | **Encaminhar (forwarder)** | Só aparece se você usa o forwarder. Pausa o envio para outro HyperHDR. |
| | **LEDs do PC (OpenRGB)** | Faz as luzes RGB do PC seguirem a cor da tela (veja [Luzes do PC](#luzes-do-pc-openrgb)). **Só funciona com a chave HyperHDR ligada**, porque as cores vêm do HyperHDR. Liga e desliga sem mexer na captura. |
| Configuração | **Assistente de configuração** | Abre o assistente (dependências, teste do HyperHDR, teste dos LEDs, luzes do PC) |
| | **Iniciar com o sistema** | Habilita os serviços no login. A captura começa sozinha quando o Game Mode abre. |
| Status | **HyperHDR** | Estado do serviço e o modo detectado (nativo, distrobox, externo, não encontrado) |
| | **Captura** | Estado da ponte. "Rodando" no Desktop significa que ela está esperando o gamescope. |
| | **LEDs do PC** | *Aguardando a chave HyperHDR*, *Sem servidor do OpenRGB*, *OpenRGB sem dispositivos*, *Sem cores do HyperHDR* (instância "PC RGB" faltando ou mal configurada) ou *Sincronizando* |
| | **Web UI** | Endereço da interface web do HyperHDR |
| Configuração | **Onde está o HyperHDR** | Automático / Nativo ou portátil / Distrobox / Outro computador |
| | **Instalar/Atualizar HyperHDR portátil** | Baixa a última release oficial para `~/.local/share/hyperhdr-portable` |
| | **Método de captura** | Flatbuffers ou v4l2loopback |
| | **Servidor Flatbuffers** | `host:porta` para onde os quadros vão. Padrão `127.0.0.1:19400`. |
| | **Freio da captura** | Liga e desliga o freio (veja [Desempenho](#desempenho)) |
| | **Qualidade da captura** | Econômico 160x90@25, Padrão 320x180@30, Detalhado 640x360@30, Fluido 320x180@60 |

Mudanças de configuração com a captura ligada reiniciam a ponte. Faça isso com o jogo fechado; o motivo está em [Problemas conhecidos](#problemas-conhecidos).

## Configuração avançada

O plugin guarda tudo em `~/.config/hyperhdr-decky.env`. Você pode editar o arquivo à mão e depois reiniciar a captura. Chaves extras são preservadas.

| Chave | Padrão | Descrição |
| --- | --- | --- |
| `HYPERHDR_MODE` | `auto` | `auto`, `native`, `distrobox` ou `external` |
| `HYPERHDR_BOX` | `hyperhdr-box` | Nome do container do distrobox |
| `HYPERHDR_BIN` | — | Caminho de um binário `hyperhdr` específico (modo nativo) |
| `HYPERHDR_PORTABLE_DIR` | `~/.local/share/hyperhdr-portable` | Onde fica o HyperHDR portátil |
| `CAPTURE_MODE` | `flatbuffers` | `flatbuffers` ou `v4l2` |
| `FLATBUFFERS_TARGET` | `127.0.0.1:19400` | Servidor Flatbuffers de destino |
| `FLATBUFFERS_PRIORITY` | `150` | Prioridade da imagem no HyperHDR (menor = mais importante) |
| `V4L2_DEVICE` | `/dev/video50` | Dispositivo do modo v4l2 |
| `BRIDGE_WIDTH` / `BRIDGE_HEIGHT` / `BRIDGE_FPS` | `320` / `180` / `30` | Tamanho e taxa da captura |
| `BRIDGE_THROTTLE` | `1` | `0` desliga o freio |
| `BRIDGE_IMPL` | `auto` | `gst-launch` força a ponte antiga, sem freio e sem desligamento suave |
| `OPENRGB_ENABLE` | `0` | `1` liga as luzes do PC |
| `OPENRGB_HOST` / `OPENRGB_PORT` | `127.0.0.1` / `6742` | Servidor SDK do OpenRGB |
| `OPENRGB_UDP_PORT` | `19446` | Porta onde o HyperHDR (saída `udpraw`) entrega as cores |
| `OPENRGB_CMD` | — | Comando do OpenRGB, se não for o Flatpak nem o `openrgb` no PATH |

Ordem da detecção automática: `HYPERHDR_BIN` → HyperHDR portátil → `hyperhdr` no PATH → distrobox.

**Arquivos e comandos úteis:**

```bash
# serviços
systemctl --user status decky-hyperhdr decky-hyperhdr-bridge
# logs da ponte e do HyperHDR
journalctl --user -u decky-hyperhdr-bridge -u decky-hyperhdr -f
# logs do plugin (Decky)
ls ~/homebrew/logs/hyperhdr-toggle/
```

## Luzes do PC (OpenRGB)

Além da TV, as luzes RGB do próprio PC (memórias, placa-mãe, ventoinhas, fitas) podem seguir a imagem. Elas usam o mesmo HyperHDR e a mesma captura, então ficam sincronizadas com a TV, no Game Mode e no Desktop.

```
captura ─▶ HyperHDR ┬ instância 0 → TV (sem mudanças)
                    └ instância "PC RGB" (1 LED = tela inteira) ─udpraw─▶ ponte ─SDK─▶ OpenRGB ─▶ RAM, placa, fans
```

- A imagem do Flatbuffers chega a **todas** as instâncias do HyperHDR. Por isso a instância nova recebe a mesma captura sem nada extra.
- A ponte (`decky-hyperhdr-openrgb.service`) recebe a cor pela saída `udpraw` do HyperHDR e aplica nos dispositivos pelo protocolo SDK do OpenRGB. O cliente do SDK é implementação própria, sem dependências.
- O plugin sobe o servidor do OpenRGB sem janela (`decky-openrgb-server.service`). Se a interface do OpenRGB já estiver rodando como servidor na mesma porta, ele usa essa.
- **Depende da chave HyperHDR.** As cores são calculadas pelo HyperHDR, então as luzes do PC só funcionam com a captura e o HyperHDR ligados. Com a chave HyperHDR desligada, a chave das luzes do PC só guarda a escolha, e o painel mostra *Aguardando a chave HyperHDR*. É também isso que mantém o PC sincronizado com a TV.
- **Ao desligar**, cada dispositivo volta a um efeito de hardware. O padrão é o primeiro disponível entre `Rainbow Wave`, `Rainbow`, `Spectrum Cycle` e `Color Shift`. O OpenRGB não consegue ler o efeito que estava ativo antes, então a escolha é configurável.

### Requisitos

- [OpenRGB](https://openrgb.org) 0.9 ou mais novo. O Flatpak `org.openrgb.OpenRGB` funciona.
- As [regras udev do OpenRGB](https://openrgb.org/udev) instaladas. No Bazzite elas já vêm (`openrgb-udev-rules`).
- Seus dispositivos aparecendo em `flatpak run --command=openrgb org.openrgb.OpenRGB --list-devices`.

### Passo a passo

O jeito mais fácil é o [assistente de configuração](#4-rode-o-assistente-de-configuração). Com o HyperHDR nesta máquina, ele cria a instância "PC RGB" sozinho: para o HyperHDR por alguns segundos, faz backup do `~/.hyperhdr/db/hyperhdr.db`, copia a configuração da instância principal e define a saída `udpraw`. Para fazer à mão:

1. **Crie uma segunda instância no HyperHDR.** Na Web UI (`:8090`): *Instances* (ou *Instance management*) → criar → nome **PC RGB** → iniciar.
2. **Configure a saída da instância.** Selecione a instância **PC RGB** no topo da Web UI e vá em *LED Hardware*:
   - **Controller type:** `udpraw`, **Target IP:** `127.0.0.1`, **Port:** `19446`
   - **LED layout:** 1 LED cobrindo a tela inteira, ou seja, *Classic* com 1 LED, ou no modo avançado `hmin 0 / hmax 1 / vmin 0 / vmax 1`
   - Para ficar no mesmo ritmo da TV, copie a suavização (*Smoothing*) e a correção de cor da instância principal.
3. **No painel do plugin**, ligue **LEDs do PC (OpenRGB)** e a chave **HyperHDR**.

**HyperHDR em outro computador:** crie a instância "PC RGB" **no HyperHDR remoto**, com saída `udpraw` apontando para o **IP deste PC** (aparece no assistente) e porta `19446`. Nesse modo a ponte escuta na rede (`0.0.0.0:19446`), e não só em `127.0.0.1`. Se houver firewall, libere a porta UDP 19446.

Na primeira execução a ponte cria `~/.config/hyperhdr-decky-openrgb.json`, com uma entrada por dispositivo:

```json
{
  "Corsair Vengeance RGB DDR5": { "led": 0, "enabled": true, "max_hz": 10, "restore_mode": "Rainbow Wave" },
  "ASUS ROG STRIX B650E-I GAMING WIFI": { "led": 0, "enabled": true, "max_hz": 30, "restore_mode": "Rainbow" }
}
```

| Campo | Para que serve |
| --- | --- |
| `led` | Qual LED da instância "PC RGB" o dispositivo segue. Com mais LEDs no layout do HyperHDR (ex.: esquerda/direita), dá para separar dispositivos por região da tela. |
| `enabled` | `false` deixa o dispositivo de fora |
| `max_hz` | Atualizações por segundo. Memórias em SMBus são lentas (padrão 10), USB aguenta mais (30). |
| `restore_mode` | Efeito de hardware aplicado ao desligar. Use um nome da lista de modos do dispositivo, ou `""` para não mexer. |

Dispositivos com o mesmo nome, como dois pentes de memória iguais, compartilham a entrada.

### Desempenho e cuidados

- **Custo:** medido no Bazzite com vídeo tocando, em % de um núcleo: ponte do OpenRGB ~0,1%, servidor do OpenRGB ~0,3%. A ponte só envia quando a cor muda.
- **Plugin de efeitos do OpenRGB:** se ele estiver ativo ao mesmo tempo, os dois brigam pelos LEDs. Pause os efeitos enquanto sincroniza.
- **Programas que mexem no SMBus** (como os do fabricante da memória) podem conflitar com o OpenRGB.
- **Detecção do OpenRGB:** o servidor detecta um dispositivo por vez (ex.: memórias antes da placa-mãe). A ponte espera a lista ficar estável antes de começar e relê os dispositivos sempre que o OpenRGB avisa que a lista mudou. Até a v0.5.0, ao ligar tudo junto pela chave HyperHDR, só as memórias acendiam.
- **Ordem de parada:** o plugin para a ponte antes do servidor, para dar tempo de restaurar o efeito. A ponte também espera 2 s depois de restaurar, porque as memórias aplicam os comandos devagar.

## Desempenho

Medido no Bazzite (Ryzen 7 9700X, Radeon RX 9070 XT) com Crimson Desert em 4K a ~105 fps. Captura em 320x180 a 30 fps, rodadas de 30 s no MangoHud, em sequência A-B-A.

| Situação | FPS médio | Perda | CPU da ponte (1 núcleo) |
| --- | --- | --- | --- |
| Captura desligada | 105,8 | — | — |
| Captura ligada, **com freio** (padrão) | 104,2 | **~1,6%** | ~3,2% |
| Captura ligada, sem freio | 100,2 | ~5,3% | ~9,4% |

O HyperHDR em si usa ~1–2% de um núcleo e não teve custo mensurável no FPS. Com a captura desligada pelo botão, nada fica rodando.

**De onde vem a perda.** Enquanto alguém consome o nó PipeWire, o gamescope renderiza uma cópia da tela inteira a cada vblank e espera a GPU terminar (`paint_pipewire()` → `vulkan_screenshot` + `vulkan_wait`). A cópia é sempre em resolução cheia; o gamescope só oferece a resolução de saída. Por isso a qualidade escolhida no plugin não muda o custo no FPS, só o trabalho da ponte.

**O freio.** A ponte segura cada quadro até completar 1/FPS (33 ms a 30 fps) antes de devolvê-lo. Sem buffer livre, o gamescope pula a cópia: em vez de ~100 por segundo, ele faz ~30.

O efeito colateral é que o gamescope grava `pipewire: warning: out of buffers` no journal a cada vblank em que pulou a cópia. Medido:

| Situação | Linhas por segundo | Volume no disco |
| --- | --- | --- |
| Jogo rodando | ~90 | ~2,4 MB/min (~140 MB/h) |
| Só a tela do Steam | ~3 | desprezível |

- **Disco:** não enche. O journald apaga os registros mais antigos ao chegar no teto.
- **SSD e CPU:** desgaste e uso desprezíveis.
- **Histórico de logs:** este é o efeito real. O Bazzite limita o journal a 50 MB (`SystemMaxUse=50M`), então ~20 min de jogo substituem todo o histórico anterior.

Se você precisa de logs antigos, aumente o teto (exemplo: `SystemMaxUse=500M` em `/etc/systemd/journald.conf.d/`) ou desligue o **Freio da captura**. Não dá para filtrar a mensagem sem root, porque `LogFilterPatterns=` não vale para serviços de usuário.

## Problemas conhecidos

- **O gamescope pode travar ao desligar a captura com um jogo aberto.** No gamescope 3.16.x, desconectar um consumidor do nó PipeWire no meio da cópia de um quadro causou um SIGSEGV: uma vez em ~10 desligamentos, com um jogo pesado em 4K, e o jogo fechou junto.
  - Desde a v0.2.1 a ponte **pausa o stream e espera 300 ms antes de desconectar**. Depois disso foram 0 travamentos em 50 ciclos de teste, 20 deles com o jogo aberto. Isso não é prova.
  - **Prefira ligar e desligar fora dos jogos.** Mudar a qualidade, o método ou o freio também reinicia a ponte.
- **Nunca force um formato no nó `gamescope`.** Se um consumidor pede um formato que o gamescope recusa (exemplo: `pipewiresrc ! video/x-raw,format=NV12`), o PipeWire do gamescope encerra e o nó só volta quando a sessão reinicia. A ponte nunca restringe o formato. Reportado em [OpenGamingCollective/gamescope#27](https://github.com/OpenGamingCollective/gamescope/issues/27).
- **Logo depois de desconectar, o nó demora um pouco.** Por alguns segundos, uma nova conexão pode receber `target not found`. A ponte tenta de novo sozinha.
- **v4l2loopback no Bazzite e no Fedora Atomic.** O módulo é carregado pelo initramfs, que não lê `/etc/modprobe.d`, então o `setup-v4l2loopback.sh` vale só até o próximo boot. Para persistir, use argumentos de kernel:
  ```bash
  sudo rpm-ostree kargs --append-if-missing=v4l2loopback.devices=2 \
    --append-if-missing=v4l2loopback.video_nr=0,50 \
    --append-if-missing=v4l2loopback.exclusive_caps=1,1 \
    '--append-if-missing=v4l2loopback.card_label=OBS Virtual Camera,GamescopeCapture'
  ```
  A alternativa é usar o modo Flatbuffers, que não precisa do módulo.
- **HDR:** com jogos em HDR, ajuste o tone mapping no HyperHDR.

## Solução de problemas

| Sintoma | O que verificar |
| --- | --- |
| Captura "Rodando", mas os LEDs não reagem | Na Web UI do HyperHDR, a prioridade **150 "Decky gamescope"** deve aparecer. Ela só aparece no Game Mode, com o nó `gamescope` ativo. |
| "HyperHDR (não encontrado)" | Use **Instalar HyperHDR portátil**, escolha o modo certo ou defina `HYPERHDR_BIN` / `HYPERHDR_BOX`. |
| Captura reinicia sem parar | Veja `journalctl --user -u decky-hyperhdr-bridge`. No modo v4l2, o `/dev/video50` provavelmente sumiu depois do reboot (veja [Problemas conhecidos](#problemas-conhecidos)). |
| Captura parou de funcionar e não volta | Talvez algum programa tenha derrubado o PipeWire do gamescope (`pipewire: exiting` no journal). Troque para o Desktop e volte ao Game Mode. |
| "LEDs do PC: Aguardando a chave HyperHDR" | Ligue a chave **HyperHDR**: as cores das luzes do PC vêm dele. |
| "LEDs do PC: Sem cores do HyperHDR" | A instância "PC RGB" não existe ou a saída dela não aponta para `udpraw 127.0.0.1:19446`. Use o assistente ou confira na Web UI. |
| Toast "API do HyperHDR não respondeu" | Confirme se o HyperHDR está rodando e se a Web UI abre na porta 8090. |
| LEDs USB não acendem no modo nativo | Permissão da porta serial: adicione o usuário ao grupo `uucp` ou `dialout`. |

## Desinstalação

Remova o plugin pelo Decky (Configurações → Plugins → HyperHDR Toggle → Desinstalar). Ele para e desabilita os serviços e apaga as units.

Arquivos que ficam, para remover à mão se quiser:

```bash
rm -f ~/.config/hyperhdr-decky.env
rm -rf ~/.local/share/hyperhdr-portable          # se instalou o portátil
rm -f ~/.config/hyperhdr-decky-openrgb.json      # se usou as luzes do PC
sudo rm -f /etc/modprobe.d/99-hyperhdr-loopback.conf /etc/modules-load.d/99-hyperhdr-loopback.conf  # se usou o v4l2
```

A configuração do HyperHDR (`~/.hyperhdr`) não é tocada.

## Desenvolvimento

```
.
├── src/index.tsx                              # painel (React, @decky/ui)
├── src/Setup.tsx                              # assistente de configuração (página própria)
├── main.py                                    # backend do Decky: serviços, configuração, detecção, instalação do portátil
├── defaults/scripts/                          # vão para scripts/ no pacote
│   ├── hyperhdr-launch.sh                     # detecta e inicia/para o HyperHDR
│   ├── hyperhdr-gamescope-bridge.sh           # ponto de entrada da ponte (escolhe Python ou gst-launch)
│   ├── hyperhdr-gamescope-bridge.py           # ponte GStreamer com freio e desligamento suave
│   ├── hyperhdr-flatbuffers-sender.py         # cliente Flatbuffers do HyperHDR
│   ├── hyperhdr-openrgb-bridge.py             # luzes do PC: udpraw do HyperHDR → OpenRGB
│   ├── openrgb_sdk.py                         # cliente mínimo do OpenRGB SDK (protocolo 3)
│   ├── openrgb-server.sh                      # sobe o servidor do OpenRGB sem janela
│   ├── hyperhdr-add-instance.py               # cria a instância "PC RGB" no banco do HyperHDR (com backup)
│   ├── check-deps.sh                          # checagem de dependências usada pelo assistente
│   └── setup-v4l2loopback.sh                  # opcional, root
├── py_modules/flatbuffers/                    # biblioteca FlatBuffers (Apache-2.0), embutida
├── tests/                                     # OpenRGB simulado e teste da ponte (python3 tests/test_openrgb_bridge.py)
├── package.sh                                 # gera out/hyperhdr-toggle.zip
└── .github/workflows/release.yml              # tag v* → build e release com o zip
```

Build local (Node 20 e pnpm 9):

```bash
pnpm install
./package.sh            # gera out/hyperhdr-toggle.zip
```

Para publicar, crie uma tag `vX.Y.Z`. O GitHub Actions gera o zip e cria a release.

Para testar no aparelho sem reinstalar: copie os arquivos para `~/homebrew/plugins/hyperhdr-toggle/` e rode `sudo systemctl restart plugin_loader`. Isso é obrigatório para `main.py` e `dist/index.js`; os scripts valem no próximo início da captura.

**Protocolo usado com o HyperHDR:** cada mensagem tem 4 bytes de tamanho (big-endian) seguidos de um `hyperhdrnet.Request` ([`hyperhdr_request.fbs`](https://github.com/awawa-dev/HyperHDR/blob/master/include/flatbuffers/parser/hyperhdr_request.fbs)). A ponte envia um `Register` com origem "Decky gamescope" e depois um `Image` com `RawImage` RGB24 por quadro. Com a tela parada, ela reenvia o último quadro a cada 1 s.

## Status e créditos

- **Testado:** Bazzite 44 (KDE + Game Mode, gamescope 3.16.31-ogc1), HyperHDR 22 em distrobox, nos dois métodos de captura. Luzes do PC com OpenRGB 1.0 (Flatpak): Corsair Vengeance RGB DDR5 e ASUS Aura USB (placa + ventoinhas ARGB). O modo portátil foi testado fora do Decky (Arch e Bazzite).
- **Não testado:** SteamOS no Steam Deck, portáteis com Bazzite, GPUs NVIDIA, ChimeraOS e outras distros com gamescope.

> ### 🙋 Procuram-se testadores
> Se você usa **SteamOS (Steam Deck)** ou outra distro com o Game Mode do Steam, ajude a testar! O roteiro de teste está na issue fixada **[#1 Testers wanted](https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/1)**. Para relatar, abra uma issue com o modelo **[Relato de teste](https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/new?template=test-report.yml)**. Resultados parciais também ajudam, e pode escrever em português.
- **Loja do Decky:** ainda não enviado. O formulário da loja exige declarar que a maior parte do código não foi escrita por IA generativa e que o plugin foi testado no SteamOS Stable e Beta. Nenhuma das duas condições se aplica hoje, porque este projeto foi desenvolvido com a ajuda de um assistente de IA (Claude) e só foi testado no Bazzite. Enquanto isso, a instalação é pela release.

**Licenças:**

- Este plugin: [BSD-3-Clause](LICENSE), baseado no [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template)
- `py_modules/flatbuffers`: [FlatBuffers](https://github.com/google/flatbuffers), Apache-2.0 ([licença](py_modules/flatbuffers/LICENSE))
- Esquema `hyperhdr_request.fbs`: [HyperHDR](https://github.com/awawa-dev/HyperHDR), MIT

---

## English

**HyperHDR Toggle** is a Decky Loader plugin that brings [HyperHDR](https://github.com/awawa-dev/HyperHDR) ambient lighting to **Steam Game Mode**.

**Why:** HyperHDR's Linux screen grabber needs `xdg-desktop-portal`, which gamescope doesn't implement, so there is no picture in Game Mode. gamescope does publish its composited output as a PipeWire node named `gamescope`. This plugin reads that node with GStreamer, downscales it, and feeds HyperHDR.

**Features**

- Quick-access toggle for the capture and HyperHDR
- HyperHDR can run **native**, **portable** (downloaded by the plugin from the official releases, no root), in **distrobox**, or on **another machine**
- Capture via **Flatbuffers** (default: TCP 19400, priority 150, no root or kernel module) or **v4l2loopback** (`/dev/video50`)
- **Capture throttle** (default on): FPS loss ~1.6% instead of ~5.3%
- **Graceful shutdown**: pauses the stream before disconnecting
- **PC RGB lights via OpenRGB**: RAM, motherboard and fans follow the same picture, in sync with the TV. A second HyperHDR instance ("PC RGB", 1 LED = whole screen, `udpraw` output to `127.0.0.1:19446`) feeds a small bridge that drives OpenRGB over its SDK. When you turn it off, each device goes back to a hardware effect. PC lights only work while the main **HyperHDR** toggle is on, because HyperHDR computes the colors. With a remote HyperHDR, point the remote "PC RGB" instance's `udpraw` output at this PC's IP, port 19446.
- Toggles for the LED output and forwarder, autostart, and quality presets

**Install**

After installing, open the plugin and tap **Abrir a configuração inicial**, the first-run setup wizard. It checks dependencies, finds and tests HyperHDR (API, version, Flatbuffers), flashes your LEDs red/green/blue to confirm, and can set up the PC RGB lights, including creating the "PC RGB" HyperHDR instance.

1. Enable Decky's developer mode (Settings → General).
2. Go to Developer → *Install plugin from URL* and paste:
   ```
   https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest/download/hyperhdr-toggle.zip
   ```
3. Open the quick access menu (…) → **HyperHDR**.

**Setup**

- **HyperHDR in distrobox:** leave *Auto*. The plugin finds a container named `hyperhdr-box`, or any container with "hyperhdr" in its name.
- **No HyperHDR installed (e.g. SteamOS):** pick *Native / portable*, tap *Install portable HyperHDR*, start it, then configure your LEDs in the web UI on port 8090.
- **HyperHDR on another machine:** pick *Other computer* and enter `host:19400`.
- **Optional v4l2loopback:** run `sudo bash scripts/setup-v4l2loopback.sh`, then enable Video capture on `/dev/video50` in HyperHDR. On Fedora Atomic/Bazzite the options only persist through `rpm-ostree kargs`.

**Requirements:** Decky Loader, a gamescope session, GStreamer with the PipeWire plugin, `python3`, `pw-cli`, and (recommended) the GStreamer Python bindings. Packages:
- Bazzite: everything is preinstalled.
- Fedora: `gstreamer1 gstreamer1-plugins-base pipewire-gstreamer pipewire-utils python3-gobject-base`
- Arch: `gstreamer gst-plugins-base gst-plugin-pipewire pipewire python-gobject`
- Debian/Ubuntu: `gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-pipewire pipewire-bin python3-gi gir1.2-gstreamer-1.0`

Optional: `curl` (portable HyperHDR), `distrobox`, OpenRGB (`flatpak install flathub org.openrgb.OpenRGB`) for the PC lights, and `v4l-utils` + `v4l2loopback` for the v4l2 capture mode. SteamOS hasn't been checked yet. See the full table and a one-shot check script in [Requisitos](#requisitos).

**Performance** (Crimson Desert 4K, MangoHud):

| | FPS | CPU (bridge) |
| --- | --- | --- |
| Capture off | 105.8 | — |
| Throttle on | 104.2 (−1.6%) | ~3.2% of a core |
| Throttle off | 100.2 (−5.3%) | ~9.4% |

The FPS cost comes from gamescope rendering a full-resolution copy for every PipeWire consumer. The throttle holds buffers so gamescope skips most copies. The side effect is that gamescope logs `out of buffers` ~90×/s while you play (~140 MB/h of journal). That doesn't harm the system, but it shortens journal history on systems with a small `SystemMaxUse`.

**Known issues**

- gamescope 3.16.x once crashed (SIGSEGV) when the capture disconnected mid-copy during a heavy game. Since the graceful shutdown: 0 crashes in 50 test cycles. Still, prefer toggling outside games.
- Never force a pixel format on the `gamescope` node. A rejected negotiation kills gamescope's PipeWire until the session restarts ([OpenGamingCollective/gamescope#27](https://github.com/OpenGamingCollective/gamescope/issues/27)).

**Status:** tested on Bazzite only. **Testers wanted**, especially SteamOS on a Steam Deck: see the pinned issue [#1](https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/1) for the test plan, and report with the [test report template](https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/new?template=test-report.yml). Developed with the help of an AI assistant (Claude), so it is not submitted to the Decky store.

**Licenses:** BSD-3-Clause (plugin), Apache-2.0 (bundled FlatBuffers), MIT (HyperHDR schema).
