"use client";

import { DownloadOutlined, LogoutOutlined, UploadOutlined } from "@ant-design/icons";
import { App, Badge, Button, Form, Input, Layout, Modal, Segmented, Slider, Space, Spin, Upload } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, setUnauthorizedHandler, streamImport } from "@/lib/api";
import { annotate, draftParts, newId, sensText, stripLine } from "@/lib/lines";
import type { AuthState, Line, Page, Session, TranscribeJob } from "@/lib/types";
import { Corrections } from "./Corrections";
import { Library } from "./Library";
import { ThemeToggle } from "./theme-mode";
import { LinePanel } from "./LinePanel";
import { Viewer, type ViewerHandle } from "./Viewer";

const { Header, Content } = Layout;

type DeskTab = "inicio" | "mesa" | "correcoes";

const MESA_PAGE_KEY = "paleonia.mesaPage";

export function DeskApp() {
  const { message, modal } = App.useApp();
  const [booting, setBooting] = useState(true);
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [pageId, setPageId] = useState<string | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);
  const [selectedPartId, setSelectedPartId] = useState<string | null>(null);
  const [tool, setTool] = useState<"select" | "draw">("select");
  const [showOriginal, setShowOriginal] = useState(false);
  const [saveState, setSaveState] = useState("");
  const [busy, setBusy] = useState<{ title: string; detail: string; error?: boolean } | null>(null);
  const [loginError, setLoginError] = useState("");
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [tab, setTab] = useState<DeskTab>("inicio");
  const [importing, setImporting] = useState(false);
  const importingRef = useRef(false);
  const previewRef = useRef<HTMLCanvasElement>(null);
  const previewScale = useRef(1);
  const viewerRef = useRef<ViewerHandle>(null);
  const saveTimer = useRef<number>(0);
  const pageRef = useRef<Page | null>(null);
  const transcribing = useRef(false);
  const importRef = useRef<(files: File[]) => Promise<void>>(async () => {});
  pageRef.current = page;

  const remember = useCallback((data: Session) => {
    setSession(data);
  }, []);

  const loadSession = useCallback(async () => {
    const data = await api<Session>("/api/session");
    remember(data);
    return data;
  }, [remember]);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth((current) => ({ ...(current || { username: "" }), required: true, authenticated: false })));
    api<AuthState>("/api/auth")
      .then(async (state) => {
        setAuth(state);
        if (!state.required || state.authenticated) {
          const data = await loadSession();
          if (window.location.hash === "#mesa") {
            const savedId = window.sessionStorage.getItem(MESA_PAGE_KEY);
            const found = savedId ? data.pages.find((item) => item.id === savedId) : undefined;
            if (found) {
              openStored(found);
              setTab("mesa");
            } else {
              window.sessionStorage.removeItem(MESA_PAGE_KEY);
              chooseTab("inicio");
            }
          }
        }
      })
      .catch((error: Error) => message.error(error.message))
      .finally(() => setBooting(false));
  }, [loadSession]);

  useEffect(() => {
    const over = (event: DragEvent) => {
      if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
      event.preventDefault();
    };
    const drop = (event: DragEvent) => {
      if (!event.dataTransfer?.files?.length) return;
      event.preventDefault();
      void importRef.current([...event.dataTransfer.files]);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, []);

  function openStored(next: Page, focus?: { lineId: string; partId: string | null }) {
    if (pageRef.current && pageRef.current.id !== next.id) void flushSave();
    pageRef.current = next;
    window.sessionStorage.setItem(MESA_PAGE_KEY, next.id);
    setPageId(next.id);
    setPage(next);
    setSelectedLineId(focus?.lineId ?? null);
    setSelectedPartId(focus?.partId ?? null);
    setTool("select");
    setShowOriginal(false);
  }

  function chooseTab(next: DeskTab) {
    setTab(next);
    const hash = next === "inicio" ? "" : `#${next}`;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hash}`);
  }

  useEffect(() => {
    if (window.location.hash === "#correcoes") setTab("correcoes");
  }, []);

  function scheduleSave(next: Page) {
    pageRef.current = next;
    setPage(next);
    setSaveState("Alterações não salvas");
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void flushSave();
    }, 400);
  }

  async function flushSave() {
    window.clearTimeout(saveTimer.current);
    const current = pageRef.current;
    if (!current || transcribing.current) return;
    setSaveState("Salvando…");
    try {
      await api(`/api/pages/${current.id}`, {
        method: "PUT",
        body: JSON.stringify({
          lines: current.lines.map(stripLine),
          sensitivity: Number(current.sensitivity),
        }),
      });
      if (pageRef.current?.id === current.id) setSaveState("Salvo");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Falha ao salvar");
    }
  }

  async function login(values: { username: string; password: string }) {
    setLoginError("");
    try {
      await api("/api/login", { method: "POST", body: JSON.stringify(values) });
      const state = await api<AuthState>("/api/auth");
      setAuth(state);
      await loadSession();
      chooseTab("inicio");
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Usuário ou senha incorretos.");
    }
  }

  async function logout() {
    await api("/api/logout", { method: "POST" });
    setAuth({ required: true, authenticated: false, username: "" });
    setPage(null);
    setPageId(null);
  }

  async function importFiles(fileList: File[]) {
    if (importingRef.current) return;
    const files = fileList.filter((file) => /\.(jpe?g|png|tif|tiff|webp)$/i.test(file.name) || file.type.startsWith("image/"));
    if (!files.length) {
      message.warning("Use imagens JPG, PNG, TIFF ou WEBP.");
      return;
    }
    importingRef.current = true;
    setImporting(true);
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    setBusy({
      title: files.length === 1 ? "Importando imagem" : `Importando ${files.length} imagens`,
      detail: "Enviando e preparando as páginas. A marcação das linhas pode demorar.",
    });
    try {
      await flushSave();
      const created = await streamImport(body, async (event) => {
        const detail = event.stage === "original" ? `${event.filename} · Preparando o documento…`
          : event.stage === "tile" ? `Zoom + Melhorias · bloco ${event.done} de ${event.total}`
          : event.stage === "crop" ? "Refilagem · ajustando as bordas…"
          : event.stage === "finished" ? "Melhorias concluídas · marcando as linhas…" : null;
        if (detail) setBusy({ title: "Preparando documento", detail });
        if (!event.image) return;
        const image = new Image();
        image.src = event.image;
        await image.decode();
        const canvas = previewRef.current;
        const ctx = canvas?.getContext("2d");
        if (!canvas || !ctx) return;
        if (event.stage === "original" || event.stage === "finished") {
          previewScale.current = Math.min(1, 1400 / Math.max(event.width, event.height));
          canvas.width = Math.round(event.width * previewScale.current);
          canvas.height = Math.round(event.height * previewScale.current);
          ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        } else {
          const unit = previewScale.current / event.scale;
          ctx.drawImage(image, event.x * unit, event.y * unit, event.width * unit, event.height * unit);
        }
      });
      setImporting(false);
      if (!created.pages.length) throw new Error(created.errors.join(" ") || "Nenhuma imagem recebida");
      if (created.errors.length) message.warning(created.errors.join(" "));
      if (created.errors?.length) setBusy((current) => current && { ...current, detail: created.errors.join(" ") });
      const data = await loadSession();
      const ids = (created.pages || []).map((item) => item.id);
      if (ids[0]) {
        const first = data.pages.find((item) => item.id === ids[0]);
        if (first) openStored(first);
        chooseTab("mesa");
      }
      if (ids.length) {
        setBusy({ title: "Lendo o texto", detail: "A transcrição das linhas vazias começou." });
        for (const id of ids) {
          const target = (await loadSession()).pages.find((item) => item.id === id);
          if (target) openStored(target);
          const status = await runTranscribe(id, true);
          if (status === "error") return;
        }
      }
      setBusy(null);
      message.success(ids.length === 1 ? "Imagem importada." : `${ids.length} imagens importadas.`);
    } catch (error) {
      setBusy({ title: "Não foi possível concluir", detail: error instanceof Error ? error.message : "Falha na importação", error: true });
    } finally {
      importingRef.current = false;
      setImporting(false);
    }
  }
  importRef.current = importFiles;

  async function runTranscribe(id: string, onlyEmpty: boolean) {
    if (transcribing.current) {
      message.warning("Já há uma transcrição em andamento.");
      return "error";
    }
    await flushSave();
    transcribing.current = true;
    setSaveState("Lendo o texto…");
    try {
      await api(`/api/pages/${id}/transcribe`, {
        method: "POST",
        body: JSON.stringify({ only_empty: onlyEmpty }),
      });
    } catch (error) {
      transcribing.current = false;
      throw error;
    }
    while (transcribing.current) {
      const job = await api<TranscribeJob>(`/api/pages/${id}/transcribe`);
      setSaveState(job.message || "Lendo o texto…");
      setBusy((current) => current && { ...current, detail: job.message || current.detail });
      if (job.page && pageRef.current?.id === job.page.id) {
        setPage(job.page);
        pageRef.current = job.page;
      }
      if (job.status !== "running") {
        transcribing.current = false;
        if (job.status === "error") {
          setBusy({ title: "Não foi possível concluir", detail: job.message || "A transcrição falhou.", error: true });
          return "error";
        }
        if (job.page) {
          setPage(job.page);
          setSession((current) =>
            current
              ? { ...current, pages: current.pages.map((item) => (item.id === job.page!.id ? job.page! : item)) }
              : current,
          );
        }
        return "done";
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    return "done";
  }

  async function transcribe() {
    if (!page) return;
    const hasText = page.lines.some((line) => line.parts.some((part) => (part.text || "").trim()));
    const start = async (onlyEmpty: boolean) => {
      setBusy({ title: "Lendo o texto", detail: "A transcrição está em andamento." });
      try {
        const status = await runTranscribe(page.id, onlyEmpty);
        if (status !== "error") {
          setBusy(null);
          message.success("Transcrição pronta. O texto fica como rascunho até você conferir.");
        }
      } catch (error) {
        setBusy({ title: "Não foi possível concluir", detail: error instanceof Error ? error.message : "Falha na transcrição", error: true });
      }
    };
    if (!hasText) {
      await start(true);
      return;
    }
    setRewriteOpen(true);
  }

  function downloadExport(path: string) {
    if (transcribing.current) {
      message.warning("A transcrição ainda está em andamento. Exporte quando ela terminar.");
      return;
    }
    void flushSave().then(() => {
      const link = document.createElement("a");
      link.href = path;
      link.download = "";
      document.body.appendChild(link);
      link.click();
      link.remove();
    });
  }

  async function detect() {
    if (!page) return;
    const hasText = page.lines.some((line) => line.parts.some((part) => (part.text || "").trim()));
    const run = async () => {
      setBusy({ title: "Detectando linhas", detail: "Localizando as faixas do manuscrito." });
      try {
        await flushSave();
        const saved = await api<Page>(`/api/pages/${page.id}/detect`, {
          method: "POST",
          body: JSON.stringify({ sensitivity: Number(pageRef.current?.sensitivity ?? page.sensitivity) }),
        });
        setPage(saved);
        pageRef.current = saved;
        setSession((current) =>
          current ? { ...current, pages: current.pages.map((item) => (item.id === saved.id ? saved : item)) } : current,
        );
        const first = annotate(saved.lines)[0];
        setSelectedLineId(first?.id || null);
        setSelectedPartId(first?.parts[0]?.id || null);
        setBusy(null);
        message.success(`${saved.lines.length} linhas no documento.`);
      } catch (error) {
        setBusy({ title: "Não foi possível concluir", detail: error instanceof Error ? error.message : "Falha na detecção", error: true });
      }
    };
    if (!hasText) {
      await run();
      return;
    }
    modal.confirm({
      title: "Detectar de novo substitui as faixas. O texto é mantido quando a faixa nova coincide com a antiga.",
      okText: "Detectar",
      cancelText: "Cancelar",
      onOk: run,
    });
  }

  function updateLines(lines: Line[]) {
    if (!pageRef.current) return;
    const added = lines.find((line) => !pageRef.current?.lines.some((item) => item.id === line.id));
    const next = { ...pageRef.current, lines };
    scheduleSave(next);
    setSession((current) =>
      current ? { ...current, pages: current.pages.map((item) => (item.id === next.id ? { ...item, lines } : item)) } : current,
    );
    if (added) setTool("select");
  }

  function commitReview(target: Page, lineId: string, partId: string, text: string, mark: "confirmed" | "skipped") {
    const source = pageRef.current?.id === target.id ? pageRef.current : target;
    const lines = source.lines.map((line) =>
      line.id === lineId
        ? {
            ...line,
            parts: line.parts.map((part) =>
              part.id === partId
                ? { ...part, text, confirmed: mark === "confirmed", skipped: mark === "skipped" }
                : part,
            ),
          }
        : line,
    );
    if (pageRef.current?.id === target.id) {
      updateLines(lines);
      return;
    }
    const next = { ...target, lines };
    setSession((current) =>
      current ? { ...current, pages: current.pages.map((item) => (item.id === next.id ? next : item)) } : current,
    );
    void api(`/api/pages/${next.id}`, {
      method: "PUT",
      body: JSON.stringify({ lines: lines.map(stripLine), sensitivity: Number(next.sensitivity) }),
    }).catch((error: Error) => message.error(error.message));
  }

  function select(lineId: string | null, partId: string | null) {
    setSelectedLineId(lineId);
    setSelectedPartId(partId);
  }

  function moveSelection(delta: number) {
    const lines = annotate(pageRef.current?.lines || []);
    const flat = lines.flatMap((line) => line.parts.map((part) => ({ lineId: line.id, partId: part.id })));
    let index = flat.findIndex((item) => item.partId === selectedPartId && item.lineId === selectedLineId);
    if (index < 0) index = flat.findIndex((item) => item.lineId === selectedLineId);
    const next = flat[index + delta];
    if (next) select(next.lineId, next.partId);
  }

  async function removePage(item: Page) {
    modal.confirm({
      title: `Remover ${item.filename}?`,
      okText: "Remover",
      okButtonProps: { danger: true },
      cancelText: "Cancelar",
      onOk: async () => {
        await flushSave();
        const data = await api<Session>(`/api/pages/${item.id}`, { method: "DELETE" });
        remember(data);
        if (pageId === item.id) {
          pageRef.current = null;
          window.sessionStorage.removeItem(MESA_PAGE_KEY);
          setPage(null);
          setPageId(null);
          chooseTab("inicio");
        }
      },
    });
  }

  if (booting) {
    return (
      <div className="boot">
        <Spin size="large" />
      </div>
    );
  }

  if (auth?.required && !auth.authenticated) {
    return (
      <div className="login-screen">
        <aside className="login-aside">
          <div>
            <img src="/brand/PaleonIA-logo-white.svg" alt="PaleonIA" />
            <h1>Mesa de transcrição</h1>
            <p>Importe o manuscrito, revise cada linha e exporte o texto.</p>
          </div>
          <small>Acesso restrito a esta instalação.</small>
        </aside>
        <main className="login-panel">
          <div className="login-card">
            <div className="login-card-head">
              <h2>Entrar</h2>
              <ThemeToggle />
            </div>
            <p className="lead">Use as credenciais definidas para esta instalação.</p>
            <Form layout="vertical" initialValues={{ username: auth.username || "paleonia" }} onFinish={login} requiredMark={false}>
              <Form.Item label="Usuário" name="username" rules={[{ required: true, message: "Informe o usuário" }]}>
                <Input size="large" autoComplete="username" />
              </Form.Item>
              <Form.Item label="Senha" name="password" rules={[{ required: true, message: "Informe a senha" }]}>
                <Input.Password size="large" autoComplete="current-password" />
              </Form.Item>
              {loginError ? <p style={{ color: "var(--danger)", marginTop: 0 }}>{loginError}</p> : null}
              <Button type="primary" htmlType="submit" size="large" block>
                Entrar
              </Button>
            </Form>
          </div>
        </main>
      </div>
    );
  }

  const pages = session?.pages || [];
  const livePages = pages.map((item) => (page && item.id === page.id ? page : item));
  const draftTotal = draftParts(livePages).length;
  const name = session?.app_name || "PaleonIA";
  const lineCount = page?.lines.length ?? 0;

  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <div className="app-brand">
          <img src="/brand/PaleonIA-logo-white.svg" alt={name} />
          <span className="app-brand-rule" />
          <span className="app-brand-caption">Mesa de transcrição</span>
        </div>
        <nav className="app-tabs" aria-label="Mesa de transcrição">
            <button type="button" aria-current={tab === "inicio" ? "page" : undefined} onClick={() => chooseTab("inicio")}>
              Início
            </button>
            <button
              type="button"
              aria-current={tab === "mesa" ? "page" : undefined}
              onClick={() => {
                if (!pageRef.current) {
                  message.info("Escolha uma página para abrir a mesa.");
                  chooseTab("inicio");
                  return;
                }
                chooseTab("mesa");
              }}
            >
              Mesa
            </button>
            <button type="button" aria-current={tab === "correcoes" ? "page" : undefined} onClick={() => chooseTab("correcoes")}>
              Correções
              {draftTotal > 0 ? <span className="app-tab-count">{draftTotal}</span> : null}
            </button>
          </nav>
        <div className="app-header-actions">
          {auth?.username ? <span className="app-user">{auth.username}</span> : null}
          <ThemeToggle />
          <ImageUpload onFiles={(files) => void importFiles(files)}>
            <Button className="header-primary" icon={<UploadOutlined />}>
              Importar
            </Button>
          </ImageUpload>
          {tab === "mesa" ? (
            <Button type="text" icon={<DownloadOutlined />} onClick={() => downloadExport("/api/export.txt")}>
              Baixar texto
            </Button>
          ) : null}
          {auth?.required ? (
            <Button type="text" icon={<LogoutOutlined />} onClick={() => void logout()}>
              Sair
            </Button>
          ) : null}
        </div>
      </Header>
      <Layout className="app-body">
        <Content style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {tab === "inicio" ? (
            <Library
              pages={livePages}
              vectorSearch={Boolean(session?.vector_search)}
              onOpen={(target, focus) => {
                openStored(target, focus);
                chooseTab("mesa");
              }}
              onRemove={(item) => void removePage(item)}
              importAction={
                <ImageUpload onFiles={(files) => void importFiles(files)}>
                  <Button type="primary" icon={<UploadOutlined />}>
                    Escolher imagens
                  </Button>
                </ImageUpload>
              }
            />
          ) : tab === "correcoes" ? (
            <Corrections
              pages={livePages}
              onCommit={commitReview}
              onOpen={(target, lineId, partId) => {
                openStored(target, { lineId, partId });
                chooseTab("mesa");
              }}
            />
          ) : page ? (
          <div className="workspace">
            <div className="workspace-head">
              <div className="workspace-title">
                <p className="eyebrow">Página</p>
                <h1>{page ? page.filename : "Nenhuma página aberta"}</h1>
              </div>
              <div className="workspace-status">
                <SaveMark state={saveState} />
                {page ? (
                  <span>
                    {lineCount} {lineCount === 1 ? "linha" : "linhas"}
                  </span>
                ) : null}
              </div>
              {page ? (
                <div className="workspace-actions">
                  <Button onClick={() => void detect()}>Detectar linhas</Button>
                  <Button type={tool === "draw" ? "primary" : "default"} onClick={() => setTool((value) => (value === "draw" ? "select" : "draw"))}>
                    {tool === "draw" ? "Desenho ativo" : "Nova linha"}
                  </Button>
                  <Button type="primary" onClick={() => void transcribe()}>
                    Transcrever
                  </Button>
                </div>
              ) : null}
            </div>
            <div className="work-grid">
                <section className="document-pane">
                  <div className="toolstrip">
                    <Space.Compact>
                      <Button onClick={() => viewerRef.current?.zoomBy(0.8)} aria-label="Reduzir">
                        −
                      </Button>
                      <Button onClick={() => viewerRef.current?.zoomBy(1.25)} aria-label="Ampliar">
                        +
                      </Button>
                      <Button onClick={() => viewerRef.current?.fit()}>Ajustar</Button>
                      <Button onClick={() => viewerRef.current?.actual()}>1:1</Button>
                    </Space.Compact>
                    <Segmented
                      value={showOriginal ? "original" : "tratada"}
                      onChange={(value) => setShowOriginal(value === "original")}
                      options={[
                        { label: "Tratada", value: "tratada" },
                        { label: "Original", value: "original" },
                      ]}
                    />
                    <div className="sens">
                      <span>Sensibilidade</span>
                      <Slider
                        min={0.15}
                        max={0.9}
                        step={0.05}
                        value={page.sensitivity}
                        tooltip={{ formatter: (value) => sensText(Number(value)) }}
                        onChange={(value) => scheduleSave({ ...page, sensitivity: value })}
                      />
                      <span>{sensText(page.sensitivity)}</span>
                    </div>
                  </div>
                  <Viewer
                    ref={viewerRef}
                    page={page}
                    showOriginal={showOriginal}
                    selectedLineId={selectedLineId}
                    tool={tool}
                    onSelect={select}
                    onLines={updateLines}
                  />
                  <p className="stage-hint">
                    A roda do mouse amplia. Arraste o fundo para mover. Arraste a faixa ou as bordas para ajustá-la. Enter avança a linha transcrita.
                  </p>
                </section>
                <LinePanel
                  page={page}
                  showOriginal={showOriginal}
                  selectedLineId={selectedLineId}
                  selectedPartId={selectedPartId}
                  onSelect={(lineId, partId) => select(lineId, partId)}
                  onText={(partId, text) => {
                    if (!pageRef.current) return;
                    updateLines(
                      pageRef.current.lines.map((line) => ({
                        ...line,
                        parts: line.parts.map((part) =>
                          part.id === partId
                            ? {
                                ...part,
                                text,
                                confirmed: Boolean(text.trim()) && Boolean(part.confirmed),
                                skipped: Boolean(text.trim()) && Boolean(part.skipped) && !part.confirmed,
                              }
                            : part,
                        ),
                      })),
                    );
                  }}
                  onSplit={(lineId) => {
                    if (!pageRef.current) return;
                    const part = { id: newId("pt"), text: "" };
                    updateLines(
                      pageRef.current.lines.map((line) => {
                        if (line.id !== lineId) return line;
                        const index = line.parts.findIndex((item) => item.id === selectedPartId);
                        const parts = [...line.parts];
                        parts.splice(index + 1, 0, part);
                        return { ...line, parts };
                      }),
                    );
                    setSelectedPartId(part.id);
                  }}
                  onInclude={(lineId, include) => {
                    if (!pageRef.current) return;
                    updateLines(pageRef.current.lines.map((line) => (line.id === lineId ? { ...line, include } : line)));
                  }}
                  onRemovePart={(lineId, partId) => {
                    if (!pageRef.current) return;
                    updateLines(
                      pageRef.current.lines.map((line) =>
                        line.id === lineId ? { ...line, parts: line.parts.filter((part) => part.id !== partId) } : line,
                      ),
                    );
                  }}
                  onDelete={(lineId) => {
                    if (!pageRef.current) return;
                    updateLines(pageRef.current.lines.filter((line) => line.id !== lineId));
                    if (selectedLineId === lineId) select(null, null);
                  }}
                  onNext={() => moveSelection(1)}
                />
            </div>
          </div>
          ) : null}
        </Content>
      </Layout>
      <Modal
        open={rewriteOpen}
        title="Esta página já tem texto"
        onCancel={() => setRewriteOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setRewriteOpen(false)}>
            Cancelar
          </Button>,
          <Button
            key="empty"
            onClick={() => {
              setRewriteOpen(false);
              if (!page) return;
              setBusy({ title: "Lendo o texto", detail: "A transcrição está em andamento." });
              void runTranscribe(page.id, true)
                .then((status) => {
                  if (status !== "error") {
                    setBusy(null);
                    message.success("Transcrição pronta. O texto fica como rascunho até você conferir.");
                  }
                })
                .catch((error: Error) => setBusy({ title: "Não foi possível concluir", detail: error.message, error: true }));
            }}
          >
            Só as vazias
          </Button>,
          <Button
            key="all"
            type="primary"
            onClick={() => {
              setRewriteOpen(false);
              if (!page) return;
              setBusy({ title: "Lendo o texto", detail: "A transcrição está em andamento." });
              void runTranscribe(page.id, false)
                .then((status) => {
                  if (status !== "error") {
                    setBusy(null);
                    message.success("Transcrição pronta. O texto fica como rascunho até você conferir.");
                  }
                })
                .catch((error: Error) => setBusy({ title: "Não foi possível concluir", detail: error.message, error: true }));
            }}
          >
            Ler todas de novo
          </Button>,
        ]}
      >
        <p style={{ margin: 0, color: "var(--muted-2)" }}>
          A leitura nova entra como rascunho. Pode preencher só as linhas vazias ou refazer o texto que já está na página.
          Refazer tira a marca de conferida.
        </p>
      </Modal>
      <Modal
        open={Boolean(busy)}
        title={busy?.title}
        width={importing ? 820 : 520}
        closable={Boolean(busy?.error)}
        maskClosable={false}
        footer={busy?.error ? <Button onClick={() => setBusy(null)}>Fechar</Button> : null}
        onCancel={() => busy?.error && setBusy(null)}
      >
        {importing && (
          <div className="import-preview" aria-label="Documento sendo melhorado em blocos" aria-busy="true">
            <canvas ref={previewRef} />
          </div>
        )}
        <Space align="start">
          {busy?.error ? null : <Spin />}
          <p style={{ margin: 0 }}>{busy?.detail}</p>
        </Space>
      </Modal>
    </Layout>
  );
}

function ImageUpload({ children, onFiles }: { children: React.ReactNode; onFiles: (files: File[]) => void }) {
  return (
    <Upload
      accept=".jpg,.jpeg,.png,.tif,.tiff,.webp,image/*"
      multiple
      showUploadList={false}
      beforeUpload={(_file, fileList) => {
        if (_file === fileList[fileList.length - 1]) onFiles(fileList);
        return false;
      }}
    >
      {children}
    </Upload>
  );
}

function SaveMark({ state }: { state: string }) {
  if (!state) return null;
  const status = state === "Salvo" ? "success" : state.includes("não") ? "warning" : "processing";
  return <Badge status={status} text={state} />;
}
