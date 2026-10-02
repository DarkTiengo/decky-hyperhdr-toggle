import {
  DialogBody,
  DialogButton,
  DialogControlsSection,
  DialogControlsSectionHeader,
  DropdownItem,
  Field,
  Focusable,
  Navigation,
  ProgressBarWithInfo,
  Spinner,
  TextField,
  ToggleField,
} from "@decky/ui";
import { callable, toaster } from "@decky/api";
import { ReactNode, useEffect, useState } from "react";
import { FaCheckCircle, FaExclamationTriangle, FaTimesCircle } from "react-icons/fa";

export const SETUP_ROUTE = "/hyperhdr-toggle/setup";

type Dep = { id: string; ok: boolean; required: boolean; package: string };
type HyperTest = {
  kind: string;
  detail: string;
  host: string;
  started: boolean;
  api: boolean;
  version: string | null;
  flatbuffers: boolean;
  instances: { index: number; name: string; running: boolean }[];
  error: string | null;
};
type OrgbCheck = { installed: boolean; started: boolean; devices: { name: string; leds: number }[]; error: string | null };
type PcInstance = { exists: boolean; running: boolean; can_create: boolean; external: boolean; ip: string; udp_port: string };
type Result = { ok: boolean; error?: string; warning?: string; created?: boolean; backup?: string; version?: string };

const checkDependencies = callable<[], Dep[]>("check_dependencies");
const getSettings = callable<[], Record<string, string>>("get_settings");
const setSetting = callable<[key: string, value: string], boolean>("set_setting");
const installPortable = callable<[], Result>("install_portable");
const testHyperhdr = callable<[], HyperTest>("test_hyperhdr");
const testLeds = callable<[], Result>("test_leds");
const openrgbCheck = callable<[], OrgbCheck>("openrgb_check");
const pcInstanceStatus = callable<[], PcInstance>("pc_instance_status");
const createPcInstance = callable<[], Result>("create_pc_instance");
const testPcLeds = callable<[], Result>("test_pc_leds");
const finishSetup = callable<[autostart: boolean, startNow: boolean], boolean>("finish_setup");

const STEPS = ["Boas-vindas", "Dependências", "HyperHDR", "Teste dos LEDs", "Luzes do PC", "Concluir"];

const DEP_LABEL: Record<string, string> = {
  "gst-launch": "GStreamer (gst-launch-1.0)",
  pipewiresrc: "Plugin PipeWire do GStreamer",
  "gst-base": "Elementos básicos do GStreamer",
  python3: "Python 3",
  "pw-cli": "Utilitários do PipeWire (pw-cli)",
  "python3-gi": "GStreamer para Python (freio e desligamento suave)",
  curl: "curl (baixar o HyperHDR portátil)",
  distrobox: "distrobox (HyperHDR em container)",
  openrgb: "OpenRGB (luzes do PC)",
  ss: "ss / iproute (servidor do OpenRGB)",
};

const MODE_OPTIONS = [
  { data: "auto", label: "Automático" },
  { data: "native", label: "Nativo / portátil" },
  { data: "distrobox", label: "Distrobox" },
  { data: "external", label: "Outro computador" },
];

const KIND_LABEL: Record<string, string> = {
  native: "nativo",
  distrobox: "distrobox",
  external: "outro computador",
  missing: "não encontrado",
};

function Mark({ ok, warn }: { ok: boolean | null; warn?: boolean }) {
  if (ok === null) return <Spinner style={{ width: "1em", height: "1em" }} />;
  if (ok) return <FaCheckCircle color="#59bf40" />;
  return warn ? <FaExclamationTriangle color="#e4a84c" /> : <FaTimesCircle color="#d94126" />;
}

function Row({ label, ok, warn, children }: { label: string; ok: boolean | null; warn?: boolean; children?: ReactNode }) {
  return (
    <Field label={label} icon={<Mark ok={ok} warn={warn} />} focusable>
      {children}
    </Field>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <div style={{ padding: "0.5em 0", opacity: 0.8, lineHeight: 1.4 }}>{children}</div>;
}

function Ask({ question, onAnswer }: { question: string; onAnswer: (yes: boolean) => void }) {
  return (
    <>
      <Note>{question}</Note>
      <Focusable style={{ display: "flex", gap: "1em" }} flow-children="horizontal">
        <DialogButton style={{ flex: 1 }} onClick={() => onAnswer(true)}>
          Sim
        </DialogButton>
        <DialogButton style={{ flex: 1 }} onClick={() => onAnswer(false)}>
          Não
        </DialogButton>
      </Focusable>
    </>
  );
}

export function SetupWizard() {
  const [step, setStep] = useState(0);
  const [settings, setSettings] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [deps, setDeps] = useState<Dep[] | null>(null);
  const [hyper, setHyper] = useState<HyperTest | null>(null);
  const [target, setTarget] = useState("");
  const [ledsSent, setLedsSent] = useState<Result | null>(null);
  const [ledsSeen, setLedsSeen] = useState<boolean | null>(null);

  const [pcWanted, setPcWanted] = useState(false);
  const [orgb, setOrgb] = useState<OrgbCheck | null>(null);
  const [pcInst, setPcInst] = useState<PcInstance | null>(null);
  const [pcCreate, setPcCreate] = useState<Result | null>(null);
  const [pcTest, setPcTest] = useState<Result | null>(null);
  const [pcSeen, setPcSeen] = useState<boolean | null>(null);

  const [autostart, setAutostart] = useState(true);
  const [startNow, setStartNow] = useState(true);

  const reloadSettings = async () => {
    const s = await getSettings();
    setSettings(s);
    setTarget(s.FLATBUFFERS_TARGET);
    return s;
  };

  useEffect(() => {
    reloadSettings().then((s) => setPcWanted(s.OPENRGB_ENABLE === "1"));
  }, []);

  const run = async <T,>(name: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(name);
    try {
      return await fn();
    } catch (e) {
      toaster.toast({ title: "HyperHDR", body: `Erro: ${e}` });
      return undefined;
    } finally {
      setBusy(null);
    }
  };

  const loadDeps = () => run("deps", async () => setDeps(await checkDependencies()));

  useEffect(() => {
    if (step === 1 && deps === null) loadDeps();
  }, [step]);

  // ---------- passos ----------

  const welcome = (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Bem-vindo</DialogControlsSectionHeader>
      <Note>
        Este assistente confere o que o plugin precisa, encontra e testa o seu HyperHDR, acende os LEDs para você
        confirmar e, se quiser, configura as luzes RGB do PC pelo OpenRGB.
      </Note>
      <Note>
        Os testes ligam o HyperHDR se ele estiver parado. Se um jogo estiver aberto, salve antes: ao final você escolhe
        se a captura fica ligada.
      </Note>
    </DialogControlsSection>
  );

  const missingRequired = deps?.filter((d) => d.required && !d.ok) ?? [];
  const depsStep = (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Dependências do sistema</DialogControlsSectionHeader>
      {deps === null && <Row label="Verificando…" ok={null} />}
      {deps?.map((d) => (
        <Row key={d.id} label={DEP_LABEL[d.id] ?? d.id} ok={d.ok} warn={!d.required}>
          {d.ok ? "OK" : d.required ? "Obrigatório" : "Opcional"}
          {!d.ok && d.package ? ` — pacote: ${d.package}` : ""}
        </Row>
      ))}
      {deps && missingRequired.length > 0 && (
        <Note>
          Faltam itens obrigatórios. Instale os pacotes indicados (no Desktop, pelo terminal) e toque em "Verificar de
          novo". No Bazzite tudo já vem instalado.
        </Note>
      )}
      <DialogButton disabled={busy !== null} onClick={loadDeps}>
        Verificar de novo
      </DialogButton>
    </DialogControlsSection>
  );

  const hyperStep = settings && (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Onde está o HyperHDR</DialogControlsSectionHeader>
      <DropdownItem
        label="HyperHDR"
        rgOptions={MODE_OPTIONS}
        selectedOption={settings.HYPERHDR_MODE}
        disabled={busy !== null}
        onChange={async (o) => {
          await setSetting("HYPERHDR_MODE", o.data);
          await reloadSettings();
          setHyper(null);
        }}
      />
      {settings.HYPERHDR_MODE === "external" && (
        <TextField
          label="Servidor Flatbuffers do outro computador (host:19400)"
          value={target}
          disabled={busy !== null}
          onChange={(e) => setTarget(e.target.value)}
          onBlur={async () => {
            if (target !== settings.FLATBUFFERS_TARGET) {
              await setSetting("FLATBUFFERS_TARGET", target);
              await reloadSettings();
              setHyper(null);
            }
          }}
        />
      )}
      {settings.HYPERHDR_MODE !== "external" && (hyper?.kind === "missing" || settings.HYPERHDR_MODE === "native") && (
        <DialogButton
          disabled={busy !== null}
          onClick={() =>
            run("portable", async () => {
              const r = await installPortable();
              toaster.toast({ title: "HyperHDR", body: r.ok ? `HyperHDR ${r.version} instalado` : `Falha: ${r.error}` });
              setHyper(null);
            })
          }
        >
          {busy === "portable" ? "Baixando…" : "Instalar HyperHDR portátil"}
        </DialogButton>
      )}
      <DialogButton disabled={busy !== null} onClick={() => run("hyper", async () => setHyper(await testHyperhdr()))}>
        {busy === "hyper" ? "Testando… (pode levar até 30 s)" : "Testar conexão com o HyperHDR"}
      </DialogButton>
      {hyper && (
        <>
          <Row label="HyperHDR encontrado" ok={hyper.kind !== "missing"}>
            {KIND_LABEL[hyper.kind] ?? hyper.kind}
            {hyper.kind === "native" || hyper.kind === "distrobox" ? ` — ${hyper.detail}` : ""}
          </Row>
          <Row label={`API (http://${hyper.host}:8090)`} ok={hyper.api}>
            {hyper.api ? `HyperHDR ${hyper.version ?? "?"}` : "sem resposta"}
            {hyper.started ? " — iniciado pelo teste" : ""}
          </Row>
          <Row label="Servidor Flatbuffers" ok={hyper.flatbuffers}>
            {hyper.flatbuffers ? settings.FLATBUFFERS_TARGET : "sem resposta"}
          </Row>
          {hyper.instances.length > 0 && (
            <Row label="Instâncias" ok={true}>
              {hyper.instances.map((i) => `${i.name}${i.running ? "" : " (parada)"}`).join(", ")}
            </Row>
          )}
          {hyper.error && <Note>⚠ {hyper.error}</Note>}
        </>
      )}
    </DialogControlsSection>
  );

  const ledsStep = (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Teste dos LEDs</DialogControlsSectionHeader>
      <Note>
        Os LEDs da TV vão ficar vermelhos, verdes e azuis, 1,5 s cada. O teste usa o HyperHDR direto, sem precisar de
        um jogo aberto.
      </Note>
      <DialogButton
        disabled={busy !== null}
        onClick={() =>
          run("leds", async () => {
            setLedsSeen(null);
            setLedsSent(await testLeds());
          })
        }
      >
        {busy === "leds" ? "Acendendo…" : ledsSent ? "Repetir o teste" : "Acender os LEDs"}
      </DialogButton>
      {ledsSent && !ledsSent.ok && <Note>⚠ {ledsSent.error}</Note>}
      {ledsSent?.ok && ledsSeen === null && (
        <Ask question="Os LEDs acenderam vermelho, verde e azul?" onAnswer={setLedsSeen} />
      )}
      {ledsSeen === true && <Row label="LEDs confirmados" ok={true} />}
      {ledsSeen === false && (
        <Note>
          O HyperHDR recebeu as cores, mas elas não chegaram aos LEDs. Confira na Web UI do HyperHDR (porta 8090):
          <br />• <b>LED Hardware</b>: tipo do controlador, IP/porta serial e quantidade de LEDs
          <br />• a <b>saída de LEDs</b> (componente LED device) ligada
          <br />• se os LEDs ficam em outro HyperHDR, o <b>forwarder</b> configurado para ele
        </Note>
      )}
    </DialogControlsSection>
  );

  const togglePc = async (v: boolean) => {
    setPcWanted(v);
    await setSetting("OPENRGB_ENABLE", v ? "1" : "0");
    await reloadSettings();
    if (v && !orgb) {
      await run("orgb", async () => {
        setOrgb(await openrgbCheck());
        setPcInst(await pcInstanceStatus());
      });
    }
  };

  const pcStep = (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Luzes RGB do PC (opcional)</DialogControlsSectionHeader>
      <ToggleField
        label="Sincronizar as luzes do PC"
        description="RAM, placa-mãe e fans seguem a mesma imagem da TV, via OpenRGB"
        checked={pcWanted}
        disabled={busy !== null}
        onChange={togglePc}
      />
      {pcWanted && (
        <>
          {busy === "orgb" && <Row label="Procurando o OpenRGB e os dispositivos… (até 40 s)" ok={null} />}
          {orgb && (
            <Row label="OpenRGB" ok={orgb.devices.length > 0}>
              {orgb.devices.length > 0
                ? orgb.devices.map((d) => `${d.name} (${d.leds})`).join(", ")
                : orgb.error ?? "sem dispositivos"}
            </Row>
          )}
          {pcInst && (
            <Row label={`Instância "PC RGB" no HyperHDR`} ok={pcInst.exists} warn={!pcInst.exists}>
              {pcInst.exists ? (pcInst.running ? "rodando" : "existe, parada") : "não existe ainda"}
            </Row>
          )}
          {pcInst && !pcInst.exists && pcInst.can_create && (
            <>
              <Note>
                O plugin pode criar a instância sozinho: ele para o HyperHDR por alguns segundos, faz backup do banco,
                copia a configuração da instância principal (cor e suavização, para ficar no mesmo ritmo) e define a
                saída udpraw para as luzes do PC.
              </Note>
              <DialogButton
                disabled={busy !== null}
                onClick={() =>
                  run("create", async () => {
                    setPcCreate(await createPcInstance());
                    setPcInst(await pcInstanceStatus());
                  })
                }
              >
                {busy === "create" ? "Criando…" : `Criar a instância "PC RGB"`}
              </DialogButton>
            </>
          )}
          {pcInst && !pcInst.exists && !pcInst.can_create && (
            <Note>
              Crie a instância na Web UI do HyperHDR: <b>Instances</b> → nova instância <b>PC RGB</b> → em{" "}
              <b>LED Hardware</b> escolha <b>udpraw</b> com IP <b>{pcInst.external ? pcInst.ip : "127.0.0.1"}</b> e porta{" "}
              <b>{pcInst.udp_port}</b>, com 1 LED cobrindo a tela inteira. Depois toque em "Verificar de novo".
            </Note>
          )}
          {pcCreate && !pcCreate.ok && <Note>⚠ {pcCreate.error}</Note>}
          {pcCreate?.ok && pcCreate.created && <Note>Instância criada. Backup do banco: {pcCreate.backup}</Note>}
          <DialogButton
            disabled={busy !== null}
            onClick={() =>
              run("orgb", async () => {
                setOrgb(await openrgbCheck());
                setPcInst(await pcInstanceStatus());
              })
            }
          >
            Verificar de novo
          </DialogButton>
          {orgb && orgb.devices.length > 0 && pcInst?.exists && (
            <DialogButton
              disabled={busy !== null}
              onClick={() =>
                run("pctest", async () => {
                  setPcSeen(null);
                  setPcTest(await testPcLeds());
                })
              }
            >
              {busy === "pctest" ? "Testando… (até 40 s)" : "Testar as luzes do PC"}
            </DialogButton>
          )}
          {pcTest && !pcTest.ok && <Note>⚠ {pcTest.error}</Note>}
          {pcTest?.ok && pcSeen === null && (
            <Ask question="As luzes do PC acenderam vermelho, verde e azul junto com a TV?" onAnswer={setPcSeen} />
          )}
          {pcSeen === true && <Row label="Luzes do PC confirmadas" ok={true} />}
          {pcSeen === false && (
            <Note>
              As cores chegaram ao OpenRGB, mas não às luzes. Abra o OpenRGB no Desktop e veja se os dispositivos
              respondem a uma cor manual; pause o plugin de efeitos do OpenRGB, se estiver ativo.
            </Note>
          )}
        </>
      )}
    </DialogControlsSection>
  );

  const finishStep = (
    <DialogControlsSection>
      <DialogControlsSectionHeader>Pronto</DialogControlsSectionHeader>
      <Row label="Dependências obrigatórias" ok={deps !== null && missingRequired.length === 0} warn />
      <Row label="HyperHDR" ok={!!hyper?.api && !!hyper?.flatbuffers} warn />
      <Row label="LEDs" ok={ledsSeen === true} warn />
      {pcWanted && <Row label="Luzes do PC" ok={pcSeen === true} warn />}
      <ToggleField label="Iniciar com o sistema" checked={autostart} onChange={setAutostart} />
      <ToggleField
        label="Ligar a captura agora"
        description="Os LEDs passam a seguir o jogo no Game Mode"
        checked={startNow}
        onChange={setStartNow}
      />
      <Note>Dá para abrir este assistente de novo pelo painel do plugin, em Configuração.</Note>
    </DialogControlsSection>
  );

  const pages = [welcome, depsStep, hyperStep, ledsStep, pcStep, finishStep];
  const last = step === pages.length - 1;

  const next = async () => {
    if (!last) {
      setStep(step + 1);
      return;
    }
    await run("finish", () => finishSetup(autostart, startNow));
    toaster.toast({ title: "HyperHDR", body: "Configuração concluída" });
    Navigation.NavigateBack();
  };

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll" }}>
      <DialogBody>
        <ProgressBarWithInfo
          nProgress={(step / (pages.length - 1)) * 100}
          sOperationText={`Passo ${step + 1} de ${pages.length}: ${STEPS[step]}`}
        />
        {pages[step]}
        <Focusable style={{ display: "flex", gap: "1em", marginTop: "1.5em" }} flow-children="horizontal">
          <DialogButton style={{ flex: 1 }} disabled={step === 0 || busy !== null} onClick={() => setStep(step - 1)}>
            Voltar
          </DialogButton>
          <DialogButton style={{ flex: 1 }} disabled={busy !== null} onClick={next}>
            {last ? "Concluir" : "Avançar"}
          </DialogButton>
        </Focusable>
      </DialogBody>
    </div>
  );
}
