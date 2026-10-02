<!--
Post de divulgação (português), para subs brasileiros ou como referência do post em inglês.
Antes de publicar: confira as regras do sub na barra lateral (autopromoção / conteúdo feito com IA) e escolha um flair, se for obrigatório.
Dica: anexe uma foto ou um vídeo curto dos LEDs funcionando no Game Mode.
-->

# Título

Fiz um plugin do Decky que faz o HyperHDR (luz ambiente) funcionar no Game Mode (gamescope) — procuro testadores, principalmente no SteamOS

# Texto

Uso o HyperHDR para controlar a fita de LED atrás da TV, e sempre me incomodou que ele só funcionava no **modo Desktop**. A captura de tela do HyperHDR no Linux passa pelo `xdg-desktop-portal`, que o gamescope não implementa. No Game Mode os LEDs simplesmente ficam sem imagem.

O gamescope, porém, publica a imagem composta da tela como um nó PipeWire chamado `gamescope`, o mesmo que o Steam usa para gravar e para o Remote Play. Então fiz um plugin do Decky que lê esse nó e entrega a imagem ao HyperHDR.

**O que ele faz**

- Botão no menu rápido (…) para ligar e desligar a captura e o HyperHDR sem sair do jogo
- Funciona com o HyperHDR em **distrobox** (meu caso no Bazzite), numa versão **portátil** que o plugin baixa das releases oficiais (sem root, sem layering), num **pacote do sistema** ou rodando em **outro computador** (Raspberry Pi, Home Assistant…)
- Envia os quadros pelo servidor Flatbuffers do HyperHDR. Não precisa de root, de módulo de kernel nem de mudar a configuração do HyperHDR. O v4l2loopback é opcional.
- Chaves para a saída de LEDs e o forwarder, início automático e perfis de qualidade

**Desempenho** (Crimson Desert em 4K, ~105 fps, MangoHud, Ryzen 7 9700X + RX 9070 XT)

| | FPS médio |
|---|---|
| Captura desligada | 105,8 |
| Captura ligada (com o "freio", padrão) | 104,2 (~−1,6%) |
| Captura ligada, sem freio | 100,2 (~−5,3%) |

O custo vem do próprio gamescope: ele renderiza uma cópia da tela em resolução cheia para qualquer programa que consome o nó PipeWire. O plugin segura os buffers para o gamescope pular a maior parte dessas cópias. O efeito colateral é que o gamescope grava muito `out of buffers` no log enquanto você joga. Não faz mal ao sistema, mas com o limite de 50 MB do journal no Bazzite ele empurra os logs antigos para fora rapidinho. Dá para desligar o freio no painel.

**Problemas conhecidos / cuidados**

- Uma vez o gamescope travou, e levou o jogo junto, quando a captura foi desligada **durante** um jogo pesado. Agora o plugin pausa o stream antes de desconectar, e depois disso foram 0 travamentos em 50 ciclos de teste. Mesmo assim, por enquanto recomendo ligar e desligar fora dos jogos.
- No Bazzite, as opções do v4l2loopback em `/etc/modprobe.d` não sobrevivem ao reboot, porque o módulo carrega pelo initramfs. Por isso o padrão é o Flatbuffers.

**Instalação**

Decky → Configurações → ligue o Modo desenvolvedor → Desenvolvedor → *Instalar plugin de uma URL*:

    https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest/download/hyperhdr-toggle.zip

Documentação completa, configuração para cada cenário e solução de problemas: https://github.com/DarkTiengo/decky-hyperhdr-toggle

**Procuro testadores 🙋**

Só testei no Bazzite (PC de mesa, AMD, HyperHDR em distrobox). Relatos ajudariam muito, principalmente de **SteamOS no Steam Deck**, Bazzite em portáteis (Ally, Legion Go), **NVIDIA**, ChimeraOS, etc. O roteiro de teste está na issue fixada: https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/1 (pode escrever em português). Até um "instalou, mas falta X" já ajuda.

**Transparência:** fiz isso com bastante ajuda de um assistente de IA (Claude). Por isso o plugin **não está na loja do Decky** (a política deles não aceita código escrito por LLM), e a instalação é manual pelo GitHub. Os testes e números acima são da minha própria máquina. Sugestões e PRs são bem-vindos.
