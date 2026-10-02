<!--
Announcement post for r/Bazzite (English).
Before posting: check the subreddit rules in the sidebar (self-promotion / AI content) and pick a flair if required.
Tip: attach a photo or short video of the LEDs working in Game Mode.
-->

# Title

I made a Decky plugin that gets HyperHDR ambient lighting working in Game Mode (gamescope) — testers wanted, especially SteamOS

# Body

I use HyperHDR to drive the LED strip behind my TV, and it always bugged me that it only worked in **Desktop Mode**. HyperHDR's Linux screen grabber goes through `xdg-desktop-portal`, which gamescope doesn't implement, so in Game Mode the LEDs just get no picture.

gamescope does publish its composited output as a PipeWire node called `gamescope` (it's what Steam uses for recording and Remote Play). So I built a Decky plugin that reads that node and feeds it to HyperHDR.

**What it does**

- Quick-access toggle (…) to turn the capture and HyperHDR on/off without leaving the game
- Works with HyperHDR in **distrobox** (my setup on Bazzite), a **portable** build the plugin downloads from the official releases (no root, no layering), a **system package**, or HyperHDR running on **another machine** (Pi, Home Assistant…)
- Sends frames over HyperHDR's Flatbuffers server. No root, no kernel module, no HyperHDR config changes needed. v4l2loopback is optional.
- LED output / forwarder toggles, autostart, quality presets

**Performance** (Crimson Desert at 4K, ~105 fps, MangoHud, Ryzen 7 9700X + RX 9070 XT)

| | Avg FPS |
|---|---|
| Capture off | 105.8 |
| Capture on (default "throttle") | 104.2 (~−1.6%) |
| Capture on, throttle off | 100.2 (~−5.3%) |

The cost comes from gamescope itself: it renders a full-res copy for any PipeWire consumer. The plugin holds buffers so gamescope skips most of those copies. Side effect: gamescope logs `out of buffers` a lot while you play. That's harmless, but on Bazzite's 50 MB journal limit it pushes out older logs fast. You can turn the throttle off in the panel.

**Known issues / be careful**

- Once, gamescope crashed (and took the game with it) when the capture was turned off **during** a heavy game. The plugin now pauses the stream before disconnecting, and I got 0 crashes in 50 test cycles after that. Still, I'd recommend toggling outside games for now.
- On Bazzite, v4l2loopback options in `/etc/modprobe.d` don't survive a reboot (the module loads from the initramfs). That's why Flatbuffers is the default.

**Install**

Decky → Settings → enable Developer mode → Developer → *Install plugin from URL*:

    https://github.com/DarkTiengo/decky-hyperhdr-toggle/releases/latest/download/hyperhdr-toggle.zip

Full docs, setup per scenario and troubleshooting: https://github.com/DarkTiengo/decky-hyperhdr-toggle

**Testers wanted 🙋**

I've only tested it on Bazzite (desktop, AMD, HyperHDR in distrobox). I'd really appreciate reports from **SteamOS on a Steam Deck**, Bazzite handhelds (Ally, Legion Go), **NVIDIA**, ChimeraOS, etc. There's a test plan in the pinned issue: https://github.com/DarkTiengo/decky-hyperhdr-toggle/issues/1. Even "it installed but X is missing" helps.

**Transparency:** I built this with a lot of help from an AI assistant (Claude). Because of that it's **not on the Decky store** (their policy doesn't accept LLM-written code), so install is manual from GitHub. The tests and numbers above are from my own machine. Feedback and PRs welcome.
