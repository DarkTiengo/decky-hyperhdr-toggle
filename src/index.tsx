import {
  ButtonItem,
  DropdownItem,
  Field,
  Navigation,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { FaLightbulb } from "react-icons/fa";
import { SETUP_ROUTE, SetupWizard } from "./Setup";

type Status = {
  kind: "native" | "distrobox" | "external" | "missing";
  detail: string;
  hyperhdr: string;
  bridge: string;
  openrgb: string;
  api: boolean;
  leds: boolean | null;
  forwarding: boolean | null;
  autostart: boolean;
  webui: string;
  v4l2_missing: boolean;
  portable: boolean;
};

type Settings = Record<string, string>;

const getStatus = callable<[], Status>("get_status");
const getSettings = callable<[], Settings>("get_settings");
const setSetting = callable<[key: string, value: string], boolean>("set_setting");
const setQuality = callable<[width: number, height: number, fps: number], boolean>("set_quality");
const setEnabled = callable<[enabled: boolean], boolean>("set_enabled");
const setComponent = callable<[component: string, enabled: boolean], boolean>("set_component");
const setAutostart = callable<[enabled: boolean], boolean>("set_autostart");
const installPortable = callable<[], { ok: boolean; version?: string; error?: string }>("install_portable");

const STATE_LABEL: Record<string, string> = {
  active: "Rodando",
  activating: "Iniciando…",
  deactivating: "Parando…",
  inactive: "Parado",
  failed: "Falhou",
  external: "Externo",
  disabled: "Desligado",
  waiting_main: "Aguardando a chave HyperHDR",
  no_server: "Sem servidor do OpenRGB",
  no_devices: "OpenRGB sem dispositivos",
  no_data: "Sem cores do HyperHDR (instância PC RGB?)",
  syncing: "Sincronizando",
};

const KIND_LABEL: Record<Status["kind"], string> = {
  native: "nativo",
  distrobox: "distrobox",
  external: "externo",
  missing: "não encontrado",
};

const MODE_OPTIONS = [
  { data: "auto", label: "Automático" },
  { data: "native", label: "Nativo / portátil" },
  { data: "distrobox", label: "Distrobox" },
  { data: "external", label: "Outro computador" },
];

const CAPTURE_OPTIONS = [
  { data: "flatbuffers", label: "Flatbuffers (padrão)" },
  { data: "v4l2", label: "v4l2loopback" },
];

const QUALITY_OPTIONS = [
  { data: "160x90@25", label: "Econômico — 160x90, 25 fps" },
  { data: "320x180@30", label: "Padrão — 320x180, 30 fps" },
  { data: "640x360@30", label: "Detalhado — 640x360, 30 fps" },
  { data: "320x180@60", label: "Fluido — 320x180, 60 fps" },
];

function openSetup() {
  Navigation.CloseSideMenus();
  Navigation.Navigate(SETUP_ROUTE);
}

function label(state: string) {
  return STATE_LABEL[state] ?? state;
}

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [busy, setBusy] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [target, setTarget] = useState("");
  // O toggle do forwarder só interessa a quem usa o forwarder
  const sawForwarder = useRef(false);

  const refresh = async () => {
    const s = await getStatus();
    if (s.forwarding) sawForwarder.current = true;
    setStatus(s);
  };

  const loadSettings = async () => {
    const s = await getSettings();
    setSettings(s);
    setTarget(s.FLATBUFFERS_TARGET);
  };

  useEffect(() => {
    refresh();
    loadSettings();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, []);

  const running = status?.bridge === "active" || status?.bridge === "activating";

  const withBusy = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      await refresh();
      setBusy(false);
    }
  };

  const onToggle = (value: boolean) =>
    withBusy(async () => {
      if (!(await setEnabled(value))) {
        toaster.toast({ title: "HyperHDR", body: "Falha ao alterar o serviço (veja o log do Decky)" });
      }
    });

  const onComponent = async (component: string, value: boolean) => {
    if (!(await setComponent(component, value))) {
      toaster.toast({ title: "HyperHDR", body: "API do HyperHDR não respondeu" });
    }
    await refresh();
  };

  const onSetting = (key: string, value: string) =>
    withBusy(async () => {
      await setSetting(key, value);
      await loadSettings();
    });

  const onQuality = (value: string) =>
    withBusy(async () => {
      const [size, fps] = value.split("@");
      const [w, h] = size.split("x").map(Number);
      await setQuality(w, h, Number(fps));
      await loadSettings();
    });

  const onInstall = async () => {
    setInstalling(true);
    const res = await installPortable();
    setInstalling(false);
    toaster.toast({
      title: "HyperHDR",
      body: res.ok ? `HyperHDR ${res.version} instalado` : `Falha: ${res.error}`,
    });
    await refresh();
  };

  const quality = settings ? `${settings.BRIDGE_WIDTH}x${settings.BRIDGE_HEIGHT}@${settings.BRIDGE_FPS}` : undefined;
  const external = settings?.HYPERHDR_MODE === "external";
  const flatbuffers = settings?.CAPTURE_MODE !== "v4l2";

  return (
    <>
      {settings && settings.SETUP_DONE !== "1" && (
        <PanelSection title="Primeiros passos">
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={openSetup}>
              Abrir a configuração inicial
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
      <PanelSection title="Controle">
        <PanelSectionRow>
          <ToggleField
            label="HyperHDR"
            description="Captura do gamescope para os LEDs"
            checked={running}
            disabled={busy || status === null || status.kind === "missing"}
            onChange={onToggle}
          />
        </PanelSectionRow>
        {status?.api && status.leds !== null && (
          <PanelSectionRow>
            <ToggleField
              label="Saída de LEDs"
              checked={status.leds}
              onChange={(v) => onComponent("LEDDEVICE", v)}
            />
          </PanelSectionRow>
        )}
        {status?.api && status.forwarding !== null && sawForwarder.current && (
          <PanelSectionRow>
            <ToggleField
              label="Encaminhar (forwarder)"
              description="Envio da imagem para outro HyperHDR"
              checked={status.forwarding}
              onChange={(v) => onComponent("FORWARDER", v)}
            />
          </PanelSectionRow>
        )}
        {settings && (
          <PanelSectionRow>
            <ToggleField
              label="LEDs do PC (OpenRGB)"
              description="RAM, placa e fans seguem a tela; funciona junto com a chave HyperHDR"
              checked={settings.OPENRGB_ENABLE === "1"}
              disabled={busy}
              onChange={(v) => onSetting("OPENRGB_ENABLE", v ? "1" : "0")}
            />
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ToggleField
            label="Iniciar com o sistema"
            checked={status?.autostart ?? false}
            disabled={busy || status === null}
            onChange={(v) => withBusy(async () => void (await setAutostart(v)))}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Status">
        <PanelSectionRow>
          <Field label="HyperHDR" focusable>
            {status ? `${label(status.hyperhdr)} (${KIND_LABEL[status.kind]})` : "…"}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Captura" focusable>
            {status ? label(status.bridge) : "…"}
          </Field>
        </PanelSectionRow>
        {status && status.openrgb !== "disabled" && (
          <PanelSectionRow>
            <Field label="LEDs do PC" focusable>
              {label(status.openrgb)}
            </Field>
          </PanelSectionRow>
        )}
        {status?.v4l2_missing && (
          <PanelSectionRow>
            <Field label="Aviso" focusable>
              {settings?.V4L2_DEVICE} não existe — rode scripts/setup-v4l2loopback.sh ou use Flatbuffers
            </Field>
          </PanelSectionRow>
        )}
        {status?.api && (
          <PanelSectionRow>
            <Field label="Web UI" focusable>
              {status.webui}
            </Field>
          </PanelSectionRow>
        )}
      </PanelSection>

      {settings && (
        <PanelSection title="Configuração">
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={openSetup}>
              Assistente de configuração
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label="Onde está o HyperHDR"
              rgOptions={MODE_OPTIONS}
              selectedOption={settings.HYPERHDR_MODE}
              disabled={busy}
              onChange={(o) => onSetting("HYPERHDR_MODE", o.data)}
            />
          </PanelSectionRow>
          {(status?.kind === "missing" || status?.portable || settings.HYPERHDR_MODE === "native") && !external && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={installing} onClick={onInstall}>
                {installing
                  ? "Baixando…"
                  : status?.portable
                    ? "Atualizar HyperHDR portátil"
                    : "Instalar HyperHDR portátil"}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {!external && (
            <PanelSectionRow>
              <DropdownItem
                label="Método de captura"
                rgOptions={CAPTURE_OPTIONS}
                selectedOption={settings.CAPTURE_MODE}
                disabled={busy}
                onChange={(o) => onSetting("CAPTURE_MODE", o.data)}
              />
            </PanelSectionRow>
          )}
          {(flatbuffers || external) && (
            <PanelSectionRow>
              <TextField
                label="Servidor Flatbuffers (host:porta)"
                value={target}
                disabled={busy}
                onChange={(e) => setTarget(e.target.value)}
                onBlur={() => target !== settings.FLATBUFFERS_TARGET && onSetting("FLATBUFFERS_TARGET", target)}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ToggleField
              label="Freio da captura"
              description="Menos FPS perdido no jogo; o gamescope grava muitos avisos no log"
              checked={settings.BRIDGE_THROTTLE !== "0"}
              disabled={busy}
              onChange={(v) => onSetting("BRIDGE_THROTTLE", v ? "1" : "0")}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label="Qualidade da captura"
              rgOptions={QUALITY_OPTIONS}
              selectedOption={quality}
              disabled={busy}
              onChange={(o) => onQuality(o.data)}
            />
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(SETUP_ROUTE, SetupWizard, { exact: true });
  return {
    name: "HyperHDR Toggle",
    titleView: <div className={staticClasses.Title}>HyperHDR</div>,
    content: <Content />,
    icon: <FaLightbulb />,
    onDismount() {
      routerHook.removeRoute(SETUP_ROUTE);
    },
  };
});
