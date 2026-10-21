"use client";

import { createClient, type Session } from "@supabase/supabase-js";
import { Fragment, type FormEvent, useCallback, useEffect, useState } from "react";
type ProposalRequest = {
  id: string;
  title: string;
  status: string;
  source: string;
  deadline?: string | null;
  created_at: string;
  extracted_fields?: Record<string, any>;
};
type Service = { service_id: string; category: string; name: string; unit: string; selling_price: number };
type Detail = {
  request: ProposalRequest;
  analysis: { categories?: string[]; missing_information?: string[]; analysis_mode?: string; extracted?: Record<string, any> } | null;
  proposal: { id: string; proposal_no: string; status: string; vat_rate: number; validity_days?: number; execution_period?: string | null } | null;
  items: Array<{ id: string; name: string; unit: string; quantity: number; unit_price: number; enabled: boolean; origin?: string; source_mqt_item_id?: string | null; activity_class?: "BASE" | "CONDITIONAL" | null; trigger_condition?: string | null }>;
  solution_hypotheses?: Array<{ id: string; pathology_code: string; solution_code: string; solution_name: string; evidence?: string | null; status: string }>;
  documents: Array<{ id: string; file_name: string; storage_path?: string | null }>;
  visits: Array<{ id: string; scheduled_at: string; note: string; status: string }>;
  mqt_items: Array<{ id: string; code?: string | null; description: string; unit: string; quantity: number }>;
};
type Knowledge = Record<string, Array<Record<string, any>>>;
type ItemDetail = {
  linked: boolean;
  note?: string | null;
  technical_basis?: string;
  duration?: { minutes: number; team_size: number | null; condition?: string | null; condition_to_confirm: boolean; source: string } | null;
  labor?: Array<{ name: string; role?: string; quantity?: number | null }>;
  resources?: Array<{ name: string; type: string; role?: string; quantity?: number | null; condition?: string | null; external?: boolean; rentable?: boolean; needs_calibration?: boolean }>;
  tests?: Array<{ code: string; name?: string }>;
  procedures?: Array<{ code: string; title: string }>;
  triggers?: Array<{ name?: string; service_id: string; relation?: string; note?: string; quantity: number }>;
  required_by?: Array<{ name?: string; service_id: string; relation?: string; note?: string }>;
};
type ProposalReference = {
  source: "uploaded" | "generated"; id: string; request_id?: string | null; proposal_no?: string | null;
  title: string; client_name?: string | null; location?: string | null; summary?: string | null;
  file_name?: string | null; created_at: string; match_score?: number;
  status?: string | null; project_name?: string | null; objective?: string | null; total?: number | null;
};
type SimilarProposalReference = ProposalReference & {
  match_percent: number;
  match_components?: { scope?: number; objective?: number; location?: number };
  duplicates_hidden?: number;
};

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
type SupabaseAppClient = ReturnType<typeof createClient<any, "public", "public">>;
type BrowserGlobal = typeof globalThis & { __ozSupabaseClient?: SupabaseAppClient };

function getSupabaseClient() {
  if (!SUPABASE_URL || !SUPABASE_KEY) return null;
  if (typeof window === "undefined") return createClient(SUPABASE_URL, SUPABASE_KEY);
  const browserGlobal = globalThis as BrowserGlobal;
  browserGlobal.__ozSupabaseClient ??= createClient(SUPABASE_URL, SUPABASE_KEY);
  return browserGlobal.__ozSupabaseClient;
}

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Rascunho", ANALYSING: "A analisar", NEEDS_INFORMATION: "Falta informação",
  TECHNICAL_SCOPE: "Âmbito técnico", PRICING: "Orçamentação", TECHNICAL_REVIEW: "Revisão técnica",
  READY_FOR_APPROVAL: "Pronta para aprovação", APPROVED: "Aprovada", GENERATED: "Gerada",
  SENT: "Enviada", CLIENT_REVIEW: "Em análise pelo cliente", ACCEPTED: "Aceite",
  REJECTED: "Recusada", EXPIRED: "Expirada", CANCELLED: "Cancelada",
};
const STATUSES = Object.keys(STATUS_LABEL);
const FIELDS: Array<[string, string, string, string]> = [
  ["client_name", "Empresa cliente", "text", "cliente"], ["client_tax_id", "NIF / NUIT", "text", "cliente"],
  ["client_email", "Email da empresa cliente", "email", "cliente"], ["client_phone", "Telefone da empresa cliente", "tel", "cliente"],
  ["client_address", "Endereço da empresa cliente", "textarea", "cliente"],
  ["client_contact_name", "Pessoa de contacto do cliente", "text", "cliente"],
  ["client_contact_role", "Função do contacto", "text", "cliente"],
  ["client_contact_email", "Email do contacto", "email", "cliente"],
  ["project_name", "Obra / projeto", "text", "obra"], ["location", "Localização da obra", "text", "obra"],
  ["building_area_m2", "Área aproximada (m²)", "number", "obra"], ["storey_count", "N.º de pisos", "number", "obra"],
  ["construction_year", "Ano de construção", "number", "obra"], ["basement_count", "N.º de caves", "number", "obra"],
  ["deadline", "Prazo pretendido", "date", "obra"], ["objective", "Objetivo do pedido", "textarea", "obra"],
  ["request_type", "Tipo de pedido", "text", "obra"], ["problem_type", "Problema identificado", "text", "obra"],
  ["problem_summary", "Resumo técnico preliminar", "textarea", "obra"],
  ["symptom_locations", "Localização das anomalias", "textarea", "obra"],
  ["requested_services", "Serviços pedidos", "textarea", "obra"],
  ["requested_conditions", "Condições comerciais pedidas", "textarea", "obra"],
  ["source_subject", "Assunto original", "text", "remetente"],
  ["sender_name", "Nome do remetente", "text", "remetente"],
  ["sender_role", "Função do remetente", "text", "remetente"],
  ["sender_organization", "Organização do remetente", "text", "remetente"],
  ["sender_email", "Email do remetente", "email", "remetente"],
  ["sender_phone", "Telefone do remetente", "tel", "remetente"],
];

async function api<T>(token: string, path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`Não foi possível contactar a API em ${API_URL}. Confirma se a API Python está a correr.`);
    }
    throw error;
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail ?? payload?.message ?? `Pedido falhou (${response.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

function priceIsPending(item: { unit_price: number }) {
  return !(Number(item.unit_price) > 0);
}
function money(value: number) {
  return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" }).format(value || 0);
}
function statusClass(status: string) {
  return `status status-${status.toLowerCase()}`;
}
function displayDate(value?: string | null) {
  if (!value) return "Sem prazo";
  return new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}

export default function Home() {
  const supabase = getSupabaseClient();
  const [session, setSession] = useState<Session | null>(null);
  const [page, setPage] = useState<"dashboard" | "new" | "detail" | "knowledge" | "library">("dashboard");
  const [requests, setRequests] = useState<ProposalRequest[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      if (!next) { setRequests([]); setDetail(null); setSelectedId(null); }
    });
    return () => subscription.unsubscribe();
  }, [supabase]);

  const loadRequests = useCallback(async (token: string) => {
    setLoading(true);
    try { setRequests(await api<ProposalRequest[]>(token, "/api/proposals")); setError(""); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, []);

  const loadDetail = useCallback(async (token: string, id: string) => {
    setLoading(true);
    try { setDetail(await api<Detail>(token, `/api/proposals/${id}`)); setError(""); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    if (session?.access_token) void loadRequests(session.access_token);
  }, [session?.access_token, loadRequests]);

  const openDetail = (id: string) => {
    if (!session?.access_token) return;
    setSelectedId(id);
    setDetail(null);
    setPage("detail");
    void loadDetail(session.access_token, id);
  };

  if (!supabase) return <SetupPage />;
  if (!session) return <AuthPage supabase={supabase} />;
  const authClient = supabase;
  const accessToken = session.access_token;

  const filtered = requests.filter((request) => {
    const fields = request.extracted_fields ?? {};
    const text = `${request.title} ${fields.client_name ?? ""} ${fields.project_name ?? ""}`.toLowerCase();
    return text.includes(query.toLowerCase());
  });
  const metrics = {
    total: requests.length,
    open: requests.filter((r) => !["SENT", "ACCEPTED", "REJECTED", "EXPIRED", "CANCELLED"].includes(r.status)).length,
    approved: requests.filter((r) => r.status === "APPROVED").length,
    sent: requests.filter((r) => r.status === "SENT").length,
  };

  async function logout() {
    await authClient.auth.signOut();
    setPage("dashboard");
  }

  async function afterSave(id?: string) {
    await loadRequests(accessToken);
    if (id) {
      setSelectedId(id);
      setDetail(null);
      setPage("detail");
      await loadDetail(accessToken, id);
    } else setPage("dashboard");
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">OZ</span><span><b>OZ Propostas</b><small>DIAGNÓSTICO & ENGENHARIA</small></span></div>
        <div className="workspace-label">ÁREA DE TRABALHO</div>
        <nav className="side-nav" aria-label="Navegação principal">
          <button className={page === "dashboard" || page === "detail" ? "nav-item active" : "nav-item"} onClick={() => setPage("dashboard")}><span>▦</span> Pedidos e propostas</button>
          <button className={page === "new" ? "nav-item active" : "nav-item"} onClick={() => { setError(""); setPage("new"); }}><span>＋</span> Novo pedido</button>
          <button className={page === "knowledge" ? "nav-item active" : "nav-item"} onClick={() => { setError(""); setPage("knowledge"); }}><span>⌕</span> Base técnica</button>
          <button className={page === "library" ? "nav-item active" : "nav-item"} onClick={() => { setError(""); setPage("library"); }}><span>▤</span> Propostas anteriores</button>
        </nav>
        <div className="sidebar-bottom">
          <div className="safety-note"><span className="safety-icon">✳</span><div><b>A IA sugere.</b><br />O engenheiro valida.</div></div>
          <button className="account" onClick={logout}><span className="avatar">{(session.user.email ?? "U").slice(0, 1).toUpperCase()}</span><span><b>{session.user.email}</b><small>Terminar sessão</small></span><span className="account-menu">⋯</span></button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar"><div className="crumb">OZ <span>/</span> {page === "dashboard" ? "Pedidos e propostas" : page === "new" ? "Novo pedido" : page === "knowledge" ? "Base técnica" : page === "library" ? "Propostas anteriores" : "Proposta"}</div><div className="topbar-right"><span className="secure-label"><i /> Espaço privado</span><button className="icon-button" title="Atualizar" onClick={() => void loadRequests(session.access_token)}>↻</button></div></header>
        <div className="content">
          {error && <div className="alert alert-error" role="alert"><span>!</span>{error}<button onClick={() => setError("")}>×</button></div>}
          {notice && <div className="alert alert-success" role="status"><span>✓</span>{notice}<button onClick={() => setNotice("")}>×</button></div>}
          {page === "dashboard" && <Dashboard metrics={metrics} requests={filtered} query={query} setQuery={setQuery} openDetail={openDetail} loading={loading} create={() => setPage("new")} />}
          {page === "new" && <NewRequest token={session.access_token} onCancel={() => setPage("dashboard")} onCreated={(id, warning) => { if (warning) setNotice(warning); void afterSave(id); }} />}
          {page === "detail" && <RequestDetail token={session.access_token} detail={detail} loading={loading} onRefresh={() => selectedId && void loadDetail(session.access_token, selectedId)} onBack={() => setPage("dashboard")} onOpenRequest={openDetail} setError={setError} setNotice={setNotice} />}
          {page === "detail" && detail?.proposal && <ProposalTermsPanel token={session.access_token} requestId={detail.request.id} proposal={detail.proposal} onRefresh={() => selectedId && void loadDetail(session.access_token, selectedId)} setError={setError} setNotice={setNotice} />}
          {page === "detail" && detail?.proposal && <ProposalPdfDownload token={session.access_token} requestId={detail.request.id} setError={setError} />}
          {page === "detail" && detail && detail.mqt_items.length > 0 && <MqtPanel token={session.access_token} detail={detail} refresh={() => selectedId && void loadDetail(session.access_token, selectedId)} setError={setError} setNotice={setNotice} />}
          {page === "knowledge" && <KnowledgePage token={session.access_token} />}
          {page === "library" && <ProposalLibraryPage token={session.access_token} onOpen={openDetail} onNew={() => setPage("new")} />}
        </div>
      </main>
    </div>
  );
}

function SetupPage() {
  return <main className="setup-wrap"><section className="setup-card"><span className="brand-mark large">OZ</span><p className="eyebrow">OZ INTELLIGENT PROPOSAL</p><h1>A tua área de propostas<br />está quase pronta.</h1><p className="setup-copy">Falta ligar o novo projeto Supabase. Cria o projeto na conta nova e depois preenche os valores do projeto no ficheiro de ambiente do frontend.</p><div className="setup-steps"><div><b>01</b><span>Criar um projeto Supabase novo</span></div><div><b>02</b><span>Copiar URL e chave publicável para <code>apps/web/.env.local</code></span></div><div><b>03</b><span>Configurar a mesma URL e chave em <code>apps/api/.env</code></span></div></div><div className="setup-callout"><b>Não uses a chave secreta no browser.</b><br />OpenAI e Resend ficam apenas no ambiente do servidor Python.</div></section></main>;
}

function AuthPage({ supabase }: { supabase: SupabaseAppClient }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault(); setWorking(true); setError(""); setNotice("");
    try {
      const result = mode === "login"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password, options: { data: { full_name: name } } });
      if (result.error) setError(result.error.message);
      else if (mode === "signup" && !result.data.session) setNotice("Confirma o teu endereço de email para concluir a criação da conta.");
    } catch (e) { setError((e as Error).message); }
    finally { setWorking(false); }
  }

  return <main className="auth-layout"><section className="auth-story"><div className="brand brand-light"><span className="brand-mark">OZ</span><span><b>OZ Propostas</b><small>DIAGNÓSTICO & ENGENHARIA</small></span></div><div className="story-copy"><p className="eyebrow">DO PEDIDO À PROPOSTA</p><h1>Propostas técnicas<br />com clareza e rigor.</h1><p>Centraliza pedidos, estrutura o diagnóstico e prepara propostas consistentes para validação da equipa.</p><div className="story-rule" /><small>IA de apoio. Decisão técnica humana.</small></div><div className="story-footer">OZ INTELLIGENT PROPOSAL <span>·</span> PORTUGAL</div></section><section className="auth-panel"><form className="auth-card" onSubmit={submit}><span className="auth-kicker">ÁREA RESERVADA</span><h2>{mode === "login" ? "Bem-vindo de volta" : "Criar acesso"}</h2><p>{mode === "login" ? "Entra para continuar a gerir os pedidos." : "O perfil é criado automaticamente com acesso de engenharia."}</p>{error && <div className="inline-error">{error}</div>}{notice && <div className="inline-success">{notice}</div>}{mode === "signup" && <label>Nome completo<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required /></label>}<label>Email profissional<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required /></label><label>Palavra-passe<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} required /></label><button className="primary full" disabled={working}>{working ? "A processar…" : mode === "login" ? "Iniciar sessão" : "Criar conta"}<span>→</span></button><div className="auth-switch">{mode === "login" ? "Ainda não tens acesso?" : "Já tens conta?"}<button type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); setNotice(""); }}>{mode === "login" ? "Criar conta" : "Iniciar sessão"}</button></div><small className="auth-footnote">A tua organização controla quem pode aceder aos dados.</small></form></section></main>;
}

function Dashboard({ metrics, requests, query, setQuery, openDetail, loading, create }: {
  metrics: { total: number; open: number; approved: number; sent: number };
  requests: ProposalRequest[]; query: string; setQuery: (v: string) => void; openDetail: (id: string) => void; loading: boolean; create: () => void;
}) {
  return <>
    <section className="welcome-row"><div><p className="eyebrow">VISÃO GERAL</p><h1>Pedidos e propostas</h1><p className="subhead">Acompanha cada pedido desde a primeira mensagem até ao envio.</p></div><button className="primary" onClick={create}><span>＋</span> Novo pedido</button></section>
    <section className="metric-grid"><Metric label="Pedidos registados" value={metrics.total} hint="No teu espaço" icon="▤" /><Metric label="Em preparação" value={metrics.open} hint="A aguardar ação" icon="◷" /><Metric label="Aprovadas" value={metrics.approved} hint="Prontas para envio" icon="✓" /><Metric label="Enviadas" value={metrics.sent} hint="Acompanhamento ativo" icon="↗" /></section>
    <section className="panel request-panel"><div className="panel-heading"><div><h2>Pedidos recentes</h2><p>Abre um pedido para rever a análise ou continuar a proposta.</p></div><span className="count-pill">{requests.length} registos</span></div><div className="toolbar"><label className="search-box"><span>⌕</span><input placeholder="Pesquisar cliente, obra ou número…" value={query} onChange={(e) => setQuery(e.target.value)} /></label><button className="subtle-button" onClick={() => window.print()}>⤓ <span>Exportar lista</span></button></div>{loading && !requests.length ? <div className="empty-state"><span className="loader" />A carregar pedidos…</div> : requests.length ? <div className="table-scroll"><table className="request-table"><thead><tr><th>CLIENTE / OBRA</th><th>ESTADO</th><th>RECEBIDO</th><th>PRAZO</th><th /></tr></thead><tbody>{requests.map((request) => { const fields = request.extracted_fields ?? {}; return <tr key={request.id} onClick={() => openDetail(request.id)}><td><div className="request-name">{fields.project_name || request.title}</div><div className="request-meta">{fields.client_name || "Cliente por identificar"}{fields.location ? ` · ${fields.location}` : ""}</div></td><td><span className={statusClass(request.status)}><i />{STATUS_LABEL[request.status] ?? request.status}</span></td><td>{displayDate(request.created_at)}</td><td>{displayDate(request.deadline)}</td><td className="row-arrow">↗</td></tr>; })}</tbody></table></div> : <div className="empty-state"><div className="empty-icon">▤</div><h3>{query ? "Sem resultados" : "Ainda não há pedidos"}</h3><p>{query ? "Tenta outro termo de pesquisa." : "Regista um email ou anexo para criar a primeira proposta."}</p>{!query && <button className="secondary" onClick={create}>Criar primeiro pedido <span>→</span></button>}</div>}</section>
    <div className="footer-note"><span>✳</span> Os campos extraídos por IA são sugestões e devem ser revistos por um engenheiro.</div>
  </>;
}

function Metric({ label, value, hint, icon }: { label: string; value: number; hint: string; icon: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div><strong>{value.toString().padStart(2, "0")}</strong><small>{hint}</small></article>;
}

function NewRequest({ token, onCancel, onCreated }: { token: string; onCancel: () => void; onCreated: (id: string, warning?: string) => void }) {
  const [values, setValues] = useState({ client_name: "", client_email: "", project_name: "", location: "", deadline: "", raw_text: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setWorking(true); setError("");
    try {
      const form = new FormData();
      Object.entries(values).forEach(([key, value]) => form.append(key, value));
      files.forEach((file) => form.append("files", file));
      const result = await api<{ request: ProposalRequest; analysis_error?: string; storage_error?: string }>(token, "/api/proposals/analyze", { method: "POST", body: form });
      const warning = [result.analysis_error, result.storage_error].filter(Boolean).join(" ");
      onCreated(result.request.id, warning || undefined);
    } catch (e) { setError((e as Error).message); }
    finally { setWorking(false); }
  }
  function cancelCreation() {
    const hasContent = Object.values(values).some((value) => value.trim()) || files.length > 0;
    if (hasContent && !window.confirm("Cancelar e descartar os dados deste novo pedido? Ainda não foram guardados.")) return;
    onCancel();
  }
  function selectFiles(selected: FileList | null) {
    const next = Array.from(selected ?? []);
    const totalBytes = next.reduce((sum, item) => sum + item.size, 0);
    if (next.length > 5) { setError("Podes anexar até 5 ficheiros por pedido."); return; }
    if (totalBytes > 15 * 1024 * 1024) { setError("O total dos anexos não pode exceder 15 MB."); return; }
    setFiles(next);
    setError("");
  }
  const set = (key: keyof typeof values, value: string) => setValues((old) => ({ ...old, [key]: value }));
  return <>
    <section className="welcome-row compact"><div><p className="eyebrow">NOVO REGISTO</p><h1>Começar uma proposta</h1><p className="subhead">Cola o pedido do cliente ou usa documentos e fotografias como base.</p></div><button className="text-button" onClick={cancelCreation} disabled={working}>← Cancelar pedido</button></section>
    <form className="panel form-panel" onSubmit={submit}><div className="form-section-title"><span className="step-number">01</span><div><h2>Pedido de origem</h2><p>A análise automática propõe campos para revisão. Não inventa informação ausente.</p></div></div><label className="textarea-label">Email ou descrição do pedido<textarea value={values.raw_text} onChange={(e) => set("raw_text", e.target.value)} placeholder="Ex.: Bom dia, pretendemos uma inspeção e diagnóstico às fissuras observadas no edifício localizado em…" rows={7} /></label><label className="upload-zone"><span className="upload-icon">↑</span><span><b>{files.length ? `${files.length} anexo(s) selecionado(s)` : "Anexar imagens e/ou documentos"}</b><small>{files.length ? files.map((item) => `${item.name} (${(item.size / 1024 / 1024).toFixed(1)} MB)`).join(" · ") : "Fotos JPG, PNG, WebP; PDF, Word, Excel, TXT ou email · até 5 ficheiros e 15 MB no total"}</small></span><input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf,.docx,.xlsx,.txt,.csv,.eml" onChange={(e) => { selectFiles(e.target.files); e.currentTarget.value = ""; }} /></label>{files.length > 0 && <button className="text-button" type="button" onClick={() => { setFiles([]); setError(""); }}>Remover anexos</button>}<div className="form-divider" /><div className="form-section-title"><span className="step-number">02</span><div><h2>Dados conhecidos</h2><p>Preenche o que já sabes. Podes confirmar ou alterar tudo após a análise.</p></div></div><div className="form-grid"><label>Nome do cliente<input value={values.client_name} onChange={(e) => set("client_name", e.target.value)} placeholder="Empresa ou contacto" /></label><label>Email do cliente<input type="email" value={values.client_email} onChange={(e) => set("client_email", e.target.value)} placeholder="nome@empresa.pt" /></label><label>Obra / projeto<input value={values.project_name} onChange={(e) => set("project_name", e.target.value)} placeholder="Nome da obra" /></label><label>Localização<input value={values.location} onChange={(e) => set("location", e.target.value)} placeholder="Cidade ou morada" /></label><label>Prazo pretendido<input type="date" value={values.deadline} onChange={(e) => set("deadline", e.target.value)} /></label></div>{error && <div className="inline-error">{error}</div>}<div className="form-actions"><button className="secondary" type="button" onClick={cancelCreation} disabled={working}>Cancelar pedido</button><button className="primary" disabled={working || Boolean(error) || (!values.raw_text.trim() && !files.length)}>{working ? <><span className="loader light" /> A analisar…</> : <>Analisar pedido <span>→</span></>}</button></div><p className="privacy-hint">As fotos são analisadas visualmente pela IA e guardadas no espaço privado. A avaliação é preliminar; o engenheiro confirma o diagnóstico. PDFs digitalizados continuam a precisar de OCR.</p></form>
  </>;
}

function RequestDetail({ token, detail, loading, onRefresh, onBack, onOpenRequest, setError, setNotice }: {
  token: string; detail: Detail | null; loading: boolean; onRefresh: () => void; onBack: () => void; onOpenRequest: (id: string) => void; setError: (s: string) => void; setNotice: (s: string) => void;
}) {
  const [fields, setFields] = useState<Record<string, any>>({});
  const [services, setServices] = useState<Service[]>([]);
  const [serviceId, setServiceId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [emailTo, setEmailTo] = useState("");
  const [emailMessage, setEmailMessage] = useState("");
  const [visitDate, setVisitDate] = useState("");
  const [visitNote, setVisitNote] = useState("");
  const [diagnosing, setDiagnosing] = useState(false);
  const [versions, setVersions] = useState<Array<{ id: string; version: number; created_at: string }>>([]);
  const [references, setReferences] = useState<SimilarProposalReference[]>([]);
  const [referencesLoading, setReferencesLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [savingFields, setSavingFields] = useState(false);
const [itemDetails, setItemDetails] = useState<Record<string, ItemDetail>>({});
const [openItems, setOpenItems] = useState<Record<string, boolean>>({});
const itemsKey = detail?.items.map((i) => `${i.id}:${i.quantity}`).join("|") ?? "";
useEffect(() => {
  if (!detail?.proposal) { setItemDetails({}); return; }
  let active = true;
  void api<Record<string, ItemDetail>>(token, `/api/proposals/${detail.request.id}/item-details`)
    .then((d) => { if (active) setItemDetails(d); })
    .catch((e) => { if (active) setError((e as Error).message); });
  return () => { active = false; };
}, [token, detail?.request.id, detail?.proposal?.id, itemsKey, setError]);
  useEffect(() => {
    if (!detail) return;
    const extracted = detail.request.extracted_fields ?? {};
    setFields({ ...extracted,
      requested_services: Array.isArray(extracted.requested_services) ? extracted.requested_services.join("\n") : extracted.requested_services ?? "",
      requested_conditions: Array.isArray(extracted.requested_conditions) ? extracted.requested_conditions.join("\n") : extracted.requested_conditions ?? "",
      symptom_locations: Array.isArray(extracted.symptom_locations) ? extracted.symptom_locations.join("\n") : extracted.symptom_locations ?? "",
    });
    setEmailTo(detail.request.extracted_fields?.client_email ?? "");
  }, [detail]);
  const similarityRequestId = detail?.request.id;
  const similarityFieldsKey = detail ? JSON.stringify(detail.request.extracted_fields ?? {}) : "";
  useEffect(() => {
    if (!similarityRequestId) { setReferences([]); setReferencesLoading(false); return; }
    let active = true;
    setReferences([]);
    setReferencesLoading(true);
    void api<SimilarProposalReference[]>(token, `/api/proposal-library/matches?request_id=${encodeURIComponent(similarityRequestId)}`)
      .then((matches) => { if (active) setReferences(matches); })
      .catch((e) => { if (active) { setReferences([]); setError((e as Error).message); } })
      .finally(() => { if (active) setReferencesLoading(false); });
    return () => { active = false; };
  }, [token, similarityRequestId, similarityFieldsKey, setError]);
  useEffect(() => { void api<Service[]>(token, "/api/services").then(setServices).catch((e) => setError((e as Error).message)); }, [token, setError]);
  useEffect(() => {
    if (!detail?.proposal) { setVersions([]); return; }
    void api<Array<{ id: string; version: number; created_at: string }>>(token, `/api/proposals/${detail.request.id}/versions`)
      .then(setVersions).catch((e) => setError((e as Error).message));
  }, [token, detail?.request.id, detail?.proposal?.id, setError]);
  if (loading && !detail) return <div className="loading-detail"><span className="loader" />A abrir pedido…</div>;
  if (!detail) return <section className="panel empty-state"><h3>Não foi possível abrir este pedido</h3><button className="secondary" onClick={onBack}>Voltar</button></section>;

  const total = detail.items.filter((item) => item.enabled).reduce((sum, item) => sum + Number(item.quantity) * Number(item.unit_price), 0);
  const vat = total * Number(detail.proposal?.vat_rate ?? 23) / 100;
  const pendingPriceCount = detail.items.filter((item) => item.enabled && priceIsPending(item)).length;
  const allMissing = detail.analysis?.missing_information ?? [];
  const persistFields = async () => {
    setSavingFields(true); setError("");
    const normalized = { ...fields };
    for (const key of ["building_area_m2", "storey_count", "construction_year", "basement_count"]) normalized[key] = normalized[key] === "" || normalized[key] == null ? null : Number(normalized[key]);
    for (const key of ["requested_services", "requested_conditions", "symptom_locations"]) {
      normalized[key] = typeof normalized[key] === "string"
        ? normalized[key].split(/\r?\n/).map((item: string) => item.trim()).filter(Boolean)
        : normalized[key] ?? [];
    }
    if (!normalized.deadline) normalized.deadline = null;
    try { await api(token, `/api/proposals/${detail.request.id}/fields`, { method: "PATCH", body: JSON.stringify({ fields: normalized }) }); setNotice("Dados do pedido guardados."); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setSavingFields(false); }
  };
  const changeStatus = async (status: string) => {
    setBusy(true); setError("");
    try { await api(token, `/api/proposals/${detail.request.id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }); setNotice(`Estado alterado para ${STATUS_LABEL[status]}.`); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const changeStatusWithConfirmation = (status: string) => {
    if (status === "CANCELLED" && !window.confirm("Cancelar este pedido? A proposta deixará de poder ser gerada ou alterada. O pedido e o histórico ficam guardados e podem ser reativados mudando o estado.")) return;
    void changeStatus(status);
  };
  const generate = async () => {
    setBusy(true); setError("");
    try { await api(token, `/api/proposals/${detail.request.id}/generate`, { method: "POST" }); setNotice("Proposta criada. Adiciona os serviços e revê os valores."); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const suggestScope = async () => {
    setBusy(true); setError("");
    try {
      const result = await api<{ added: string[]; message: string }>(token, `/api/proposals/${detail.request.id}/suggest-scope`, { method: "POST" });
      setNotice(result.message); onRefresh();
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const rebuildScope = async () => {
    if (!window.confirm("Refazer o âmbito? As linhas sugeridas automaticamente (incluindo quantidades e preços que tenhas editado nelas) serão apagadas e recriadas a partir do diagnóstico atual. Os serviços que adicionaste à mão ficam.")) return;
    setBusy(true); setError("");
    try {
      const result = await api<{ message: string }>(token, `/api/proposals/${detail.request.id}/rebuild-scope`, { method: "POST" });
      setNotice(result.message); onRefresh();
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const addService = async () => {
    if (!serviceId) return;
    setBusy(true); setError("");
    try { await api(token, `/api/proposals/${detail.request.id}/items`, { method: "POST", body: JSON.stringify({ service_id: serviceId, quantity: Number(quantity) }) }); setServiceId(""); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const updateItem = async (id: string, update: Record<string, unknown>) => {
    try { await api(token, `/api/proposal-items/${id}`, { method: "PATCH", body: JSON.stringify(update) }); onRefresh(); }
    catch (e) { setError((e as Error).message); }
  };
  const removeItem = async (id: string) => {
    if (!window.confirm("Remover este serviço da proposta?")) return;
    try { await api(token, `/api/proposal-items/${id}`, { method: "DELETE" }); onRefresh(); }
    catch (e) { setError((e as Error).message); }
  };
  const saveVersion = async () => {
    setBusy(true); setError("");
    try { const result = await api<{ version: number }>(token, `/api/proposals/${detail.request.id}/versions`, { method: "POST" }); setNotice(`Versão ${result.version} guardada.`); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const scheduleVisit = async () => {
    if (!visitDate) return;
    setBusy(true); setError("");
    try { await api(token, `/api/proposals/${detail.request.id}/visits`, { method: "POST", body: JSON.stringify({ scheduled_at: new Date(visitDate).toISOString(), note: visitNote }) }); setVisitDate(""); setVisitNote(""); setNotice("Visita agendada."); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const updateVisitStatus = async (id: string, status: string) => {
    try { await api(token, `/api/visits/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }); onRefresh(); }
    catch (e) { setError((e as Error).message); }
  };
  const sendEmail = async () => {
    if (!detail.proposal || detail.proposal.status !== "APPROVED") return;
    if (!window.confirm(`Enviar a proposta ${detail.proposal.proposal_no} para ${emailTo}?`)) return;
    setBusy(true); setError("");
    try { await api(token, `/api/proposals/${detail.request.id}/send-email`, { method: "POST", body: JSON.stringify({ to: emailTo, message: emailMessage }) }); setNotice("Email enviado pelo Resend com a proposta completa em PDF anexa."); onRefresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const refreshDiagnosis = async () => {
    setDiagnosing(true); setError("");
    try {
      const diagnosis = await api<{ status: string }>(token, `/api/proposals/${detail.request.id}/technical-diagnosis`, { method: "POST" });
      setNotice(diagnosis.status === "matched" ? "Mapeamento técnico atualizado com a base de conhecimento." : "Análise atualizada; revê a nota técnica para ver o resultado.");
      onRefresh();
    } catch (e) { setError((e as Error).message); }
    finally { setDiagnosing(false); }
  };
  const diagnosis = detail.analysis?.extracted?.technical_diagnosis;

  return <>
    <section className="detail-heading"><button className="back-button" onClick={onBack}>←</button><div className="detail-title"><p className="eyebrow">PEDIDO DE PROPOSTA</p><h1>{fields.project_name || detail.request.title}</h1><p>{fields.client_name || "Cliente por identificar"}{fields.location ? ` · ${fields.location}` : ""}</p></div><div className="detail-tools">{detail.request.status !== "CANCELLED" && <button className="cancel-request-button" onClick={() => changeStatusWithConfirmation("CANCELLED")} disabled={busy}>Cancelar pedido</button>}<span className={statusClass(detail.request.status)}><i />{STATUS_LABEL[detail.request.status] ?? detail.request.status}</span><button className="icon-button" onClick={onRefresh} title="Atualizar">↻</button></div></section>
    <div className="detail-grid"><div className="detail-main-column">
      <section className="panel detail-panel"><div className="panel-heading"><div><h2>Dados extraídos</h2><p>Confirma os campos sugeridos antes de gerar a proposta.</p></div><span className={`mode-tag mode-${detail.analysis?.analysis_mode?.toLowerCase() ?? "rules"}`}>{detail.analysis?.analysis_mode === "OPENAI" ? "✳ OpenAI" : "↗ Regras básicas"}</span></div>{allMissing.length > 0 && <div className="missing-banner"><span>!</span><div><b>Informação por confirmar</b><p>{allMissing.join(" · ")}</p></div></div>}{fields.site_visit_recommended != null && <div className="technical-note">Visita ao local: {fields.site_visit_recommended ? "recomendada" : "não indicada pela análise preliminar"}. Confirma esta sugestão antes de a incluir no âmbito.</div>}{[["cliente", "DADOS DA EMPRESA CLIENTE"], ["obra", "PEDIDO E ANÁLISE PRELIMINAR"], ["remetente", "ASSINATURA DO REMETENTE"]].map(([group, heading]) => <section className="field-group" key={group}><h3>{heading}</h3><div className="detail-fields">{FIELDS.filter(([, , , fieldGroup]) => fieldGroup === group).map(([key, label, type]) => <label key={key} className={type === "textarea" ? "wide-field" : ""}>{label}{type === "textarea" ? <textarea rows={3} value={fields[key] ?? ""} onChange={(e) => setFields({ ...fields, [key]: e.target.value })} /> : <input type={type} value={fields[key] ?? ""} onChange={(e) => setFields({ ...fields, [key]: e.target.value })} />}</label>)}</div></section>)}{(fields.categories ?? []).length > 0 && <div className="category-line"><span>Categorias sugeridas</span>{(fields.categories ?? []).map((category: string) => <span className="category-chip" key={category}>{category}</span>)}</div>}<div className="panel-bottom"><span className="helper-copy">A análise automática é uma sugestão.</span><button className="secondary" onClick={persistFields} disabled={savingFields}>{savingFields ? "A guardar…" : "Guardar dados"}</button></div></section>
      <section className="panel technical-panel"><div className="panel-heading"><div><h2>Mapeamento técnico de patologias</h2><p>Hipóteses, causas, ensaios e soluções ligadas aos códigos da base de conhecimento.</p></div><button className="secondary" onClick={refreshDiagnosis} disabled={diagnosing}>{diagnosing ? "A analisar…" : "Reanalisar pedido"}</button></div>{diagnosis?.message && <div className={diagnosis.status === "knowledge_base_unavailable" ? "technical-warning" : "technical-note"}>{diagnosis.message}</div>}{diagnosis?.candidates?.length ? <div className="pathology-grid">{diagnosis.candidates.map((candidate: any) => <article className="pathology-card" key={candidate.code}><div className="pathology-card-heading"><div><span className="pathology-code">{candidate.code}</span><h3>{candidate.name}</h3></div><strong>{candidate.match_percent}%<small>aderência ao texto</small></strong></div><p className="pathology-severity">{candidate.group || "Base técnica"} · Severidade {candidate.severity?.map((level: any) => level.name).join(" / ") || `indicativa ${candidate.severity_min}–${candidate.severity_max}`}</p>{candidate.severity?.length > 0 && candidate.severity[candidate.severity.length - 1].action && <p className="pathology-action">Ação indicativa: {candidate.severity[candidate.severity.length - 1].action}</p>}<PathologyWhy candidate={candidate} /><div className="pathology-mappings">{([["Causas a verificar", candidate.causes], ["Ensaios recomendados", candidate.tests], ["Soluções de referência", candidate.solutions]] as Array<[string, any[]]>).map(([title, rows]) => <div key={`${candidate.code}-${title}`}><b>{title}</b>{rows?.length ? <ul>{rows.map((row: any) => <li key={row.code}><code>{row.code}</code> {row.name}</li>)}</ul> : <small>Sem código associado na base.</small>}</div>)}</div></article>)}</div> : diagnosis && diagnosis.status !== "knowledge_base_unavailable" ? <div className="empty-state technical-empty"><h3>Sem correspondência codificada</h3><p>A descrição ainda não permite ligar uma patologia aos códigos da base técnica. O engenheiro pode completar a classificação após rever o pedido.</p></div> : !diagnosis ? <div className="empty-state technical-empty"><p>Ainda não existe análise técnica guardada para este pedido. Usa “Reanalisar pedido” para consultar o catálogo de patologias.</p></div> : null}{diagnosis?.weak_candidates?.length > 0 && <WeakMatches items={diagnosis.weak_candidates} />}<div className="similarity-note">A percentagem mede aderência textual ao catálogo e não a probabilidade de diagnóstico. Todas as causas e soluções exigem validação do engenheiro responsável.</div></section>
      <section className="panel prior-reference-panel"><div className="panel-heading"><div><h2>Propostas parecidas já realizadas</h2><p>Comparação por âmbito, objetivo e localização com propostas e ficheiros anteriores.</p></div><span className="count-pill">{referencesLoading ? "A comparar…" : `${references.length} correspondências`}</span></div>{referencesLoading ? <div className="empty-state"><span className="loader" />A comparar com o histórico de propostas…</div> : references.length ? <div className="prior-reference-list">{references.map((reference) => <article className="prior-reference-row" key={`${reference.source}-${reference.id}`}><div className="reference-copy"><span className="reference-source">{reference.source === "uploaded" ? "ARQUIVO CARREGADO" : "PROPOSTA GERADA"}{reference.proposal_no ? ` · ${reference.proposal_no}` : ""}</span><b>{reference.title}</b><small>{[reference.client_name, reference.location, displayDate(reference.created_at)].filter(Boolean).join(" · ") || "Sem cliente/localização identificados"}</small>{reference.summary && <p>{reference.summary}</p>}{(reference.duplicates_hidden ?? 0) > 0 && <small>+{reference.duplicates_hidden} proposta(s) praticamente idêntica(s) agrupada(s) nesta referência.</small>}<small className="match-breakdown">{typeof reference.match_components?.scope === "number" ? `Âmbito ${reference.match_components.scope}%` : ""}{typeof reference.match_components?.objective === "number" ? ` · Objetivo ${reference.match_components.objective}%` : ""}{typeof reference.match_components?.location === "number" ? ` · Localização ${reference.match_components.location}%` : ""}</small><div className="match-track" role="img" aria-label={`Correspondência fuzzy ${reference.match_percent}%`}><span style={{ width: `${reference.match_percent}%` }} /></div></div><div className="reference-score"><strong>{reference.match_percent}%</strong><span>semelhança</span></div>{reference.source === "uploaded" ? <button className="secondary" onClick={async () => { try { const result = await api<{ url: string }>(token, `/api/proposal-library/${reference.id}/download`); window.open(result.url, "_blank", "noopener,noreferrer"); } catch (e) { setError((e as Error).message); } }}>Consultar</button> : <button className="secondary" onClick={() => reference.request_id && onOpenRequest(reference.request_id)}>Abrir</button>}</article>)}</div> : <div className="empty-state"><div className="empty-icon">⌕</div><h3>Não há propostas suficientemente parecidas</h3><p>À medida que guardares propostas geradas ou carregares propostas anteriores, o sistema compara o âmbito, o objetivo e a localização deste pedido.</p></div>}<div className="similarity-note">A percentagem é uma comparação textual aproximada. Revê sempre o âmbito, os preços e a adequação técnica da referência.</div></section>
      {detail.solution_hypotheses && detail.solution_hypotheses.length > 0 && <section className="panel detail-panel"><div className="panel-heading"><div><h2>Hipóteses de solução (só para consulta interna)</h2><p>Não constam da proposta. Serão conferidas com o diagnóstico de campo, que determina a solução final.</p></div></div><ul>{Object.entries(detail.solution_hypotheses.reduce<Record<string, { name: string; pathologies: string[] }>>((acc, h) => { const entry = (acc[h.solution_code] ??= { name: h.solution_name, pathologies: [] }); if (!entry.pathologies.includes(h.pathology_code)) entry.pathologies.push(h.pathology_code); return acc; }, {})).map(([code, entry]) => <li key={code}><b>{code}</b> · {entry.name} <small>(para {entry.pathologies.join(", ")})</small></li>)}</ul></section>}
      <section className="panel detail-panel"><div className="panel-heading"><div><h2>Âmbito e preços</h2><p>Os preços de catálogo servem de ponto de partida; revê quantidades e valores.</p></div>{detail.proposal ? <span className="proposal-no">{detail.proposal.proposal_no}</span> : <button className="secondary" onClick={generate} disabled={busy || detail.request.status === "CANCELLED"}>Criar proposta <span>→</span></button>}</div>{detail.proposal ? <><div className="service-add"><select value={serviceId} onChange={(e) => setServiceId(e.target.value)} disabled={detail.request.status === "CANCELLED"}><option value="">Escolher um serviço…</option>{services.map((s) => <option key={s.service_id} value={s.service_id}>{s.category} · {s.name}</option>)}</select><input aria-label="Quantidade" type="number" min="0" step="0.1" value={quantity} onChange={(e) => setQuantity(e.target.value)} disabled={detail.request.status === "CANCELLED"} /><button className="secondary" onClick={addService} disabled={busy || !serviceId || detail.request.status === "CANCELLED"}>Adicionar</button></div><div className="service-add" style={{ gridTemplateColumns: "1fr 1fr" }}><button className="secondary" onClick={suggestScope} disabled={busy || detail.request.status === "CANCELLED"}>Sugerir atividades de campo ✳</button><button className="secondary" onClick={rebuildScope} disabled={busy || detail.request.status === "CANCELLED"}>Refazer âmbito a partir do diagnóstico atual ↻</button></div>{detail.items.length ? <div className="table-scroll"><table className="items-table"><thead><tr><th>SERVIÇO</th><th>QTD.</th><th>PREÇO / UN.</th><th>TOTAL</th><th /></tr></thead><tbody>{detail.items.map((item) => <Fragment key={item.id}><tr><td><label className="item-name"><input type="checkbox" checked={item.enabled} onChange={(e) => void updateItem(item.id, { enabled: e.target.checked })} disabled={detail.request.status === "CANCELLED"} /><span>{item.name}<small>{item.unit}{item.activity_class === "CONDITIONAL" ? " · condicional (incluída no total)" : item.activity_class === "BASE" ? " · base" : ""}</small>{item.activity_class === "CONDITIONAL" && item.trigger_condition && <small>Condição: {item.trigger_condition}</small>}<button type="button" className="text-button" onClick={(e) => { e.preventDefault(); setOpenItems((o) => ({ ...o, [item.id]: !o[item.id] })); }}>{openItems[item.id] ? "▾ Ocultar detalhe" : "▸ Ver o que inclui"}</button></span></label></td><td><input className="number-input" type="number" min="0" step="0.1" defaultValue={item.quantity} onBlur={(e) => Number(e.target.value) !== Number(item.quantity) && void updateItem(item.id, { quantity: Number(e.target.value) })} disabled={detail.request.status === "CANCELLED"} /></td><td><input className="number-input price-input" type="number" min="0" step="0.01" defaultValue={item.unit_price} onBlur={(e) => Number(e.target.value) !== Number(item.unit_price) && void updateItem(item.id, { unit_price: Number(e.target.value) })} disabled={detail.request.status === "CANCELLED"} /></td><td>{priceIsPending(item) ? <b title="Sem preço validado. O valor 0 não significa gratuito.">Preço por validar</b> : money(Number(item.quantity) * Number(item.unit_price))}</td><td><button className="remove-button" title="Remover" onClick={() => void removeItem(item.id)} disabled={detail.request.status === "CANCELLED"}>×</button></td></tr>{openItems[item.id] && <tr className="item-detail-row"><td colSpan={5}><ItemDetailPanel d={itemDetails[item.id]} /></td></tr>}</Fragment>)}</tbody></table></div> : <div className="small-empty">Ainda não foram adicionados serviços.</div>}<div className="technical-note">Aprovação única do diagnóstico: as atividades condicionais incluídas neste âmbito executam-se quando a condição técnica se verificar, sem nova aprovação do cliente. Trabalhos de reparação e custos fora deste âmbito não estão incluídos nem autorizados.</div>{pendingPriceCount > 0 && <div className="technical-warning">{pendingPriceCount} serviço(s) ativo(s) sem preço validado. Não são gratuitos: o total abaixo é provisório até confirmares estes preços.</div>}<div className="totals"><span>Subtotal{pendingPriceCount > 0 ? " (provisório)" : ""} <b>{money(total)}</b></span><span>IVA ({detail.proposal.vat_rate}%) <b>{money(vat)}</b></span><strong>Total <b>{money(total + vat)}</b></strong></div><div className="proposal-actions"><div className="proposal-button-group"><button className="secondary" onClick={saveVersion} disabled={busy || detail.request.status === "CANCELLED"}>Guardar versão v{(versions[0]?.version ?? 0) + 1}</button></div><label className="status-select">Estado<select value={detail.proposal.status} onChange={(e) => changeStatusWithConfirmation(e.target.value)} disabled={busy}>{STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></label></div>{versions.length > 0 && <div className="version-line">Última versão: <b>v{versions[0].version}</b> · {displayDate(versions[0].created_at)}</div>}{detail.proposal.status === "APPROVED" && detail.request.status !== "CANCELLED" && <div className="send-box"><div><b>Enviar por email</b><small>O PDF da proposta será anexado automaticamente ao email.</small></div><input type="email" value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="email@cliente.pt" /><textarea rows={2} value={emailMessage} onChange={(e) => setEmailMessage(e.target.value)} placeholder="Mensagem opcional" /><button className="primary" onClick={sendEmail} disabled={busy || !emailTo}>Enviar com Resend <span>→</span></button></div>}{detail.request.status === "CANCELLED" && <div className="cancelled-banner">Pedido cancelado. Reativa-o pelo seletor de estado para continuar a trabalhar.</div>}</> : detail.request.status === "CANCELLED" ? <div className="cancelled-banner">Pedido cancelado. Reativa-o pelo seletor de estado para criar uma proposta.</div> : <div className="generate-callout"><span>✳</span><p>Cria uma proposta para escolher serviços, confirmar os preços e preparar o documento final.</p></div>}</section>
    </div><aside className="detail-side-column"><section className="panel side-panel"><p className="eyebrow">RESUMO</p><div className="side-stat"><span>Recebido</span><b>{displayDate(detail.request.created_at)}</b></div><div className="side-stat"><span>Prazo do cliente</span><b>{displayDate(detail.request.deadline)}</b></div><div className="side-stat"><span>Origem</span><b>{detail.request.source === "upload" ? "Anexo" : detail.request.source === "email" ? "Email" : "Manual"}</b></div><div className="side-stat"><span>Proposta</span><b>{detail.proposal?.proposal_no ?? "Ainda não criada"}</b></div>{detail.documents.length > 0 && <div className="side-documents"><span>Anexos originais</span>{detail.documents.map((document) => <button key={document.id} onClick={async () => { try { const result = await api<{ url: string }>(token, `/api/documents/${document.id}/download`); window.open(result.url, "_blank", "noopener,noreferrer"); } catch (e) { setError((e as Error).message); } }}>↗ {document.file_name}</button>)}</div>}</section><section className="panel side-panel visits-panel"><p className="eyebrow">VISITAS AO LOCAL</p><label>Data e hora<input type="datetime-local" value={visitDate} onChange={(e) => setVisitDate(e.target.value)} disabled={detail.request.status === "CANCELLED"} /></label><label>Nota<input value={visitNote} onChange={(e) => setVisitNote(e.target.value)} placeholder="Contacto, acesso, observações" disabled={detail.request.status === "CANCELLED"} /></label><button className="secondary" onClick={scheduleVisit} disabled={busy || !visitDate || detail.request.status === "CANCELLED"}>Agendar visita</button>{detail.visits.length > 0 && <div className="visit-list">{detail.visits.map((visit) => <div className="visit-row" key={visit.id}><div><b>{new Date(visit.scheduled_at).toLocaleString("pt-PT", { dateStyle: "medium", timeStyle: "short" })}</b><small>{visit.note || "Sem observações"}</small></div><select aria-label="Estado da visita" value={visit.status} onChange={(e) => void updateVisitStatus(visit.id, e.target.value)}><option value="SCHEDULED">Agendada</option><option value="COMPLETED">Concluída</option><option value="CANCELLED">Cancelada</option></select></div>)}</div>}</section><section className="side-tip"><span>✳</span><div><b>Revisão técnica</b><p>Confirma âmbito, quantidades, preços, exclusões e prazo antes de aprovar.</p></div></section><section className="panel side-panel status-panel"><label className="eyebrow" htmlFor="request-status">ESTADO DO PEDIDO</label><select id="request-status" value={detail.request.status} onChange={(e) => changeStatusWithConfirmation(e.target.value)} disabled={busy}>{STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABEL[status]}</option>)}</select><small>As alterações são guardadas no sistema.</small></section></aside></div>
  </>;
}

function ProposalTermsPanel({ token, requestId, proposal, onRefresh, setError, setNotice }: {
  token: string; requestId: string; proposal: NonNullable<Detail["proposal"]>; onRefresh: () => void;
  setError: (s: string) => void; setNotice: (s: string) => void;
}) {
  const [validityDays, setValidityDays] = useState(String(proposal.validity_days ?? 60));
  const [executionPeriod, setExecutionPeriod] = useState(proposal.execution_period ?? "");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setValidityDays(String(proposal.validity_days ?? 60));
    setExecutionPeriod(proposal.execution_period ?? "");
  }, [proposal.id, proposal.validity_days, proposal.execution_period]);
  async function save() {
    if (Number(validityDays) < 1 || Number(validityDays) > 365) {
      setError("A validade tem de ser entre 1 e 365 dias.");
      return;
    }
    if (["APPROVED", "SENT", "ACCEPTED"].includes(proposal.status) &&
        !window.confirm("Alterar as condições comerciais vai devolver a proposta ao estado de orçamentação. Continuar?")) return;
    setSaving(true); setError("");
    try {
      await api(token, `/api/proposals/${requestId}/terms`, {
        method: "PATCH", body: JSON.stringify({ validity_days: Number(validityDays), execution_period: executionPeriod }),
      });
      setNotice("Validade e prazo de execução guardados na proposta.");
      onRefresh();
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }
  return <section className="panel proposal-terms-panel"><div className="panel-heading"><div><h2>Prazo e validade</h2><p>Estas condições entram no PDF e podem ser ajustadas por proposta.</p></div></div><div className="proposal-terms-form"><label>Validade (dias)<input type="number" min="1" max="365" value={validityDays} onChange={(e) => setValidityDays(e.target.value)} /></label><label>Prazo de execução<input value={executionPeriod} onChange={(e) => setExecutionPeriod(e.target.value)} placeholder="A definir após confirmar âmbito e acessos" /></label><button className="secondary" onClick={save} disabled={saving}>{saving ? "A guardar…" : "Guardar condições"}</button></div><small className="terms-footnote">As condições de pagamento e dados da empresa configuram-se em <code>apps/api/.env</code>.</small></section>;
}

function ProposalPdfDownload({ token, requestId, setError }: { token: string; requestId: string; setError: (s: string) => void }) {
  const [busy, setBusy] = useState("");
  async function download(kind: "pdf" | "docx") {
    setBusy(kind); setError("");
    try {
      const response = await fetch(`${API_URL}/api/proposals/${requestId}/${kind}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? `Documento indisponível (${response.status})`);
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = kind === "pdf" ? "proposta-OZ.pdf" : "proposta-OZ.docx"; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }
  return <div className="pdf-download-row"><div><b>Proposta completa</b><small>Word editável (formato das propostas OZ) ou PDF.</small></div><div style={{ display: "flex", gap: 8 }}><button className="secondary" onClick={() => void download("docx")} disabled={Boolean(busy)}>{busy === "docx" ? "A preparar…" : "Transferir Word ↓"}</button><button className="secondary" onClick={() => void download("pdf")} disabled={Boolean(busy)}>{busy === "pdf" ? "A preparar…" : "Transferir PDF ↓"}</button></div></div>;
}
function MqtPanel({ token, detail, refresh, setError, setNotice }: {
  token: string; detail: Detail; refresh: () => void; setError: (s: string) => void; setNotice: (s: string) => void;
}) {
  const [busyId, setBusyId] = useState("");
  async function add(id: string) {
    if (!detail.proposal) { setError("Gera a proposta antes de importar linhas da MQT."); return; }
    setBusyId(id); setError("");
    try {
      await api(token, `/api/proposals/${detail.request.id}/mqt-items/${id}/add`, { method: "POST" });
      setNotice("Linha MQT adicionada com preço zero para validação."); refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusyId(""); }
  }
  return <section className="panel mqt-panel"><div className="panel-heading"><div><h2>Itens importados da MQT</h2><p>Revê as linhas extraídas do Excel e adiciona as relevantes ao âmbito.</p></div><span className="count-pill">{detail.mqt_items.length} itens</span></div><div className="table-scroll"><table className="items-table"><thead><tr><th>REFERÊNCIA</th><th>DESCRIÇÃO</th><th>QTD.</th><th>UN.</th><th /></tr></thead><tbody>{detail.mqt_items.map((item) => {
    const added = detail.items.some((proposalItem) => proposalItem.source_mqt_item_id === item.id);
    return <tr key={item.id}><td>{item.code || "—"}</td><td>{item.description}</td><td>{item.quantity}</td><td>{item.unit}</td><td><button className="secondary" disabled={!detail.proposal || detail.request.status === "CANCELLED" || added || busyId === item.id} onClick={() => void add(item.id)}>{added ? "Adicionado" : busyId === item.id ? "A adicionar…" : detail.request.status === "CANCELLED" ? "Pedido cancelado" : detail.proposal ? "Adicionar" : "Gera proposta"}</button></td></tr>;
  })}</tbody></table></div><div className="version-line">Os itens importados começam com preço zero e exigem validação de preço e correspondência técnica.</div></section>;
}

type KbKind = "pathology" | "cause" | "test" | "solution";
type KbLinked = Exclude<KbKind, "pathology">;
const KB_KEY: Record<KbLinked, string> = { cause: "causes", test: "tests", solution: "solutions" };
const KB_PLURAL: Record<KbLinked, string> = { cause: "Causas", test: "Ensaios", solution: "Soluções" };
const KB_SINGULAR: Record<KbKind, string> = { pathology: "Patologia", cause: "Causa", test: "Ensaio", solution: "Solução" };

function KnowledgePage({ token }: { token: string }) {
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<{ kind: KbKind; code: string } | null>(null);
  useEffect(() => { void api<Knowledge>(token, "/api/knowledge").then(setKnowledge).catch((e) => setError((e as Error).message)); }, [token]);

  const toMap = (rows?: Array<Record<string, any>>) => new Map<string, Record<string, any>>((rows ?? []).map((row) => [String(row.code), row]));
  const maps: Record<KbKind, Map<string, Record<string, any>>> = {
    pathology: toMap(knowledge?.pathologies), cause: toMap(knowledge?.causes), test: toMap(knowledge?.tests), solution: toMap(knowledge?.solutions),
  };
  const codesOf = (row: Record<string, any>, kind: KbLinked): string[] => ((row[KB_KEY[kind]] ?? []) as unknown[]).map(String);
  const pathologyList = knowledge?.pathologies ?? [];
  const pathologies = pathologyList.filter((row) => {
    const text = `${row.code} ${row.group_name} ${row.name}`.toLowerCase();
    return text.includes(query.toLowerCase()) && (group === "all" || row.group_name === group);
  });
  const groups = Array.from(new Set(pathologyList.map((row) => row.group_name))).sort();
  const isSelected = (kind: KbKind, code: string) => selected?.kind === kind && selected.code === code;
  const pick = (kind: KbKind, code: string) => setSelected({ kind, code });

  const linkList = (kind: KbKind, codes: string[]) => codes.length
    ? <ul>{codes.map((code) => <li key={code}><button type="button" className="text-button" onClick={() => pick(kind, code)}><code>{code}</code> {maps[kind].get(code)?.name ?? "(sem nome na base)"}</button></li>)}</ul>
    : <small>Sem ligações na base.</small>;

  const renderDetail = () => {
    if (!selected) return null;
    const { kind, code } = selected;
    const item = maps[kind].get(code);
    if (!item) return null;
    if (kind === "pathology") {
      return <>
        <p>{item.group_name} · Severidade de referência {item.sev_min}–{item.sev_max}{item.not_in_manual ? " · complementar" : ""}</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 16 }}>
          {(["cause", "test", "solution"] as KbLinked[]).map((other) => <div key={other}><b>{KB_PLURAL[other]}</b>{linkList(other, codesOf(item, other))}</div>)}
        </div>
      </>;
    }
    const linked = pathologyList.filter((row) => codesOf(row, kind).includes(code));
    const others = (["cause", "test", "solution"] as KbLinked[]).filter((other) => other !== kind);
    return <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 16 }}>
      <div><b>Patologias ligadas ({linked.length})</b>{linkList("pathology", linked.map((row) => String(row.code)))}</div>
      {others.map((other) => {
        const codes = Array.from(new Set(linked.flatMap((row) => codesOf(row, other))));
        return <div key={other}><b>{KB_PLURAL[other]} nessas patologias ({codes.length})</b>{linkList(other, codes)}</div>;
      })}
    </div>;
  };
  const detail = renderDetail();
  const selectedItem = selected ? maps[selected.kind].get(selected.code) : undefined;

  return <>
    <section className="welcome-row"><div><p className="eyebrow">CONSULTA TÉCNICA</p><h1>Base de conhecimento</h1><p className="subhead">Clica numa patologia, causa, ensaio ou solução para ver as ligações entre elas.</p></div><span className="count-pill">{knowledge ? pathologies.length + " patologias" : "A carregar…"}</span></section>
    {error && <div className="inline-error">{error}</div>}
    {selected && selectedItem && detail && <section className="panel" style={{ position: "sticky", top: 0, zIndex: 5, maxHeight: "45vh", overflowY: "auto" }}>
      <div className="panel-heading"><div><p className="eyebrow">{KB_SINGULAR[selected.kind].toUpperCase()} · {selected.code}</p><h2>{selectedItem.name}</h2></div><button className="secondary" onClick={() => setSelected(null)}>Fechar</button></div>
      {detail}
    </section>}
    <section className="panel knowledge-panel"><div className="toolbar"><label className="search-box"><span>⌕</span><input placeholder="Pesquisar patologia, código ou grupo…" value={query} onChange={(e) => setQuery(e.target.value)} /></label><select value={group} onChange={(e) => setGroup(e.target.value)}><option value="all">Todos os grupos</option>{groups.map((name) => <option key={name}>{name}</option>)}</select></div>
      {!knowledge ? <div className="empty-state"><span className="loader" />A carregar a base técnica…</div> : <>
        <div className="knowledge-grid">{pathologies.map((row) => <article className="knowledge-card" key={row.code} role="button" tabIndex={0} onClick={() => pick("pathology", String(row.code))} onKeyDown={(e) => { if (e.key === "Enter") pick("pathology", String(row.code)); }} style={{ cursor: "pointer", outline: isSelected("pathology", String(row.code)) ? "2px solid #4a6b57" : undefined }}><div className="knowledge-card-top"><span>{row.code}</span>{row.not_in_manual && <span className="category-chip">Complementar</span>}</div><h3>{row.name}</h3><p>{row.group_name}</p><div className="severity-range">Severidade de referência <b>{row.sev_min}–{row.sev_max}</b></div></article>)}</div>
        {pathologies.length === 0 && <div className="empty-state">Não foram encontradas patologias.</div>}
      </>}
    </section>
    {knowledge && <div className="knowledge-reference-grid">{(["test", "cause", "solution"] as KbLinked[]).map((kind) => {
      const rows = knowledge[KB_KEY[kind]] ?? [];
      return <section className="panel ref-panel" key={kind}><p className="eyebrow">CLICA PARA VER AS PATOLOGIAS LIGADAS</p><h2>{KB_PLURAL[kind]}</h2>
        <div style={{ maxHeight: 360, overflowY: "auto" }}>{rows.map((row) => <button type="button" key={row.code} className="ref-row" onClick={() => pick(kind, String(row.code))} style={{ cursor: "pointer", width: "100%", textAlign: "left", border: "none", font: "inherit", background: isSelected(kind, String(row.code)) ? "#e8efe9" : undefined }}><b>{row.code}</b><span>{row.name}</span></button>)}</div>
        <small>{rows.length} referências</small></section>;
    })}</div>}
  </>;
}

type LibraryReadingData = {
  library: { title?: string; client_name?: string; location?: string; proposal_no?: string; material?: string; work_type?: string; scope_summary?: string; total_value?: number | null; proposal_date?: string | null; extraction_status?: string | null; extraction_note?: string | null };
  items: Array<{ id: string; section?: string | null; designation: string; unit?: string | null; quantity?: number | null; unit_price?: number | null; total_price?: number | null; service_id?: string | null; service_name?: string | null; mapping_confidence?: string | null; price_consistent?: boolean | null }>;
};

function LibraryReading({ token, id, setError }: { token: string; id: string; setError: (s: string) => void }) {
  const [data, setData] = useState<LibraryReadingData | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setData(await api<LibraryReadingData>(token, `/api/proposal-library/${id}/reading`)); }
    catch (e) { setError((e as Error).message); }
  }, [token, id, setError]);
  useEffect(() => { void load(); }, [load]);
  async function reread() {
    setBusy(true); setError("");
    try { await api(token, `/api/proposal-library/${id}/reprocess`, { method: "POST" }); await load(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (!data) return <div className="small-empty">A carregar leitura…</div>;
  const lib = data.library;
  const statusLabel = lib.extraction_status === "DONE" ? "Lida com IA" : lib.extraction_status === "FAILED" ? "Falhou" : "Pendente";
  return <div className="item-detail">
    <p><b>Estado da leitura.</b> {statusLabel}{lib.extraction_note ? ` · ${lib.extraction_note}` : ""} <button className="secondary" disabled={busy} onClick={() => void reread()}>{busy ? "A reler…" : "Reler com IA"}</button></p>
    <p><b>Proposta.</b> {lib.proposal_no || "sem número"} · {lib.client_name || "cliente por identificar"} · {lib.location || "sem localização"} · material: {lib.material || "—"} · tipo: {lib.work_type || "—"}{lib.total_value != null ? ` · total s/ IVA: ${money(Number(lib.total_value))}` : ""}</p>
    {lib.scope_summary && <p><b>Âmbito.</b> {lib.scope_summary}</p>}
    {data.items.length > 0
      ? <div className="table-scroll"><table className="items-table"><thead><tr><th>SECÇÃO</th><th>DESIGNAÇÃO LIDA</th><th>UN.</th><th>QT.</th><th>PREÇO UN.</th><th>TOTAL</th><th>SERVIÇO DO CATÁLOGO</th></tr></thead><tbody>
          {data.items.map((item) => <tr key={item.id}><td>{item.section || "—"}</td><td>{item.designation}</td><td>{item.unit || "—"}</td><td>{item.quantity ?? "—"}</td><td>{item.unit_price != null ? money(Number(item.unit_price)) : "—"}</td><td>{item.total_price != null ? money(Number(item.total_price)) : "—"}{item.price_consistent === false ? " ⚠" : ""}</td><td>{item.service_name ? `${item.service_name} (${item.mapping_confidence || "?"})` : "sem correspondência"}</td></tr>)}
        </tbody></table></div>
      : <p>Não foram encontradas linhas de preços neste documento (pode ter só uma verba global).</p>}
  </div>;
}

function ProposalLibraryPage({ token, onOpen, onNew }: { token: string; onOpen: (id: string) => void; onNew: () => void }) {
  const [query, setQuery] = useState("");
  const [references, setReferences] = useState<ProposalReference[]>([]);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState("newest");
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState("");
  const [title, setTitle] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [readingId, setReadingId] = useState<string | null>(null);

  const load = useCallback(async (search: string) => {
    setWorking(true); setError("");
    try {
      const result = await api<ProposalReference[]>(token, `/api/proposal-library?query=${encodeURIComponent(search)}&limit=500`);
      setReferences(result);
    } catch (e) { setError((e as Error).message); }
    finally { setWorking(false); }
  }, [token]);
  useEffect(() => { void load(""); }, [load]);

  async function submitSearch(event: FormEvent) {
    event.preventDefault(); await load(query.trim());
  }
  function selectLibraryFiles(selected: FileList | null) {
    const next = Array.from(selected ?? []);
    if (next.length > 30) { setError("Podes enviar até 30 ficheiros de cada vez."); return; }
    const tooBig = next.find((item) => item.size > 15 * 1024 * 1024);
    if (tooBig) { setError(`${tooBig.name} excede o limite de 15 MB.`); return; }
    setError(""); setFiles(next);
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!files.length) return;
    setWorking(true); setError(""); setNotice(""); setProgress("");
    const failed: Array<{ name: string; reason: string }> = [];
    let done = 0;
    let read = 0;
    for (const [index, current] of files.entries()) {
      setProgress(`A enviar e ler ${index + 1} de ${files.length}: ${current.name}`);
      try {
        const form = new FormData();
        form.append("file", current);
        form.append("title", files.length === 1 ? title : "");
        const saved = await api<{ extraction_status?: string }>(token, "/api/proposal-library", { method: "POST", body: form });
        done += 1;
        if (saved.extraction_status === "DONE") read += 1;
      } catch (e) {
        failed.push({ name: current.name, reason: (e as Error).message });
      }
    }
    setProgress("");
    const input = document.getElementById("proposal-library-file") as HTMLInputElement | null;
    if (input) input.value = "";
    setFiles(failed.length ? files.filter((item) => failed.some((f) => f.name === item.name)) : []);
    if (!failed.length) setTitle("");
    if (done) setNotice(`${done} ficheiro(s) guardado(s); ${read} lido(s) com IA` + (done - read ? `, ${done - read} por ler (usa «Reprocessar leituras pendentes»).` : "."));
    if (failed.length) setError(`${failed.length} ficheiro(s) falharam: ` + failed.map((f) => `${f.name} (${f.reason})`).join(" · "));
    await load(query.trim());
    setWorking(false);
  }
  async function reprocessReadings() {
    setWorking(true); setError(""); setNotice("");
    try {
      const result = await api<{ processed: number; done: number; failed: number; remaining: boolean }>(token, "/api/proposal-library/reprocess", { method: "POST" });
      setNotice(result.processed === 0 ? "Não há leituras pendentes." : `${result.done} de ${result.processed} leitura(s) concluída(s)` + (result.failed ? `, ${result.failed} falharam` : "") + (result.remaining ? ". Pode haver mais pendentes: clica outra vez." : "."));
    } catch (e) { setError((e as Error).message); }
    finally { setWorking(false); }
  }
  async function openReference(reference: ProposalReference) {
    if (reference.source === "generated" && reference.request_id) { onOpen(reference.request_id); return; }
    try {
      const result = await api<{ url: string }>(token, `/api/proposal-library/${reference.id}/download`);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (e) { setError((e as Error).message); }
  }
  async function removeReference(reference: ProposalReference) {
    const label = reference.proposal_no || reference.title;
    const message = reference.source === "generated"
      ? `Apagar permanentemente a proposta ${label} e as respetivas linhas e versões? O pedido original continuará guardado.`
      : `Apagar permanentemente o ficheiro ${reference.file_name || label} e o respetivo registo da biblioteca?`;
    if (!window.confirm(message)) return;
    setWorking(true); setError(""); setNotice("");
    try {
      await api(token, `/api/proposal-library/${reference.id}?source=${reference.source}`, { method: "DELETE" });
      setNotice(reference.source === "generated" ? "Proposta e versões apagadas. O pedido original foi mantido." : "Ficheiro e registo apagados da biblioteca.");
      await load(query.trim());
    } catch (e) { setError((e as Error).message); }
    finally { setWorking(false); }
  }

  const collator = new Intl.Collator("pt", { sensitivity: "base", numeric: true });
  const visibleReferences = references
    .filter((reference) => sourceFilter === "all" || reference.source === sourceFilter)
    .filter((reference) => statusFilter === "all" || reference.status === statusFilter)
    .sort((left, right) => {
      if (sortBy === "oldest") return left.created_at.localeCompare(right.created_at);
      if (sortBy === "number") {
        if (!left.proposal_no) return 1;
        if (!right.proposal_no) return -1;
        return collator.compare(left.proposal_no, right.proposal_no);
      }
      if (sortBy === "client") return collator.compare(left.client_name || "", right.client_name || "");
      if (sortBy === "value") return (right.total ?? -1) - (left.total ?? -1);
      return right.created_at.localeCompare(left.created_at);
    });

  return <>
    <section className="welcome-row"><div><p className="eyebrow">CONSULTA DE TRABALHOS ANTERIORES</p><h1>Base de propostas</h1><p className="subhead">Organiza propostas por número, cliente, obra, estado, valor e data.</p></div><button className="primary" onClick={onNew}>＋ Novo pedido</button></section>
    {error && <div className="inline-error">{error}</div>}{notice && <div className="inline-success">{notice}</div>}
    <section className="panel library-upload-panel"><div className="panel-heading"><div><h2>Adicionar propostas existentes</h2><p>PDF, Word, Excel, TXT, CSV ou email até 15 MB. A IA lê cada proposta ao carregar: número, cliente, material e mapa de preços.</p></div><span className="secure-label"><i /> Privado</span></div><form className="library-upload-form" onSubmit={upload}><label>Título de consulta (opcional, só com 1 ficheiro)<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ex.: Diagnóstico elétrico — edifício Matola" /></label><label className="upload-zone"><span className="upload-icon">↑</span><span><b>{progress || (files.length ? `${files.length} ficheiro(s) selecionado(s)` : "Selecionar propostas anteriores (vários ficheiros)")}</b><small>{files.length ? files.map((item) => `${item.name} (${(item.size / 1024 / 1024).toFixed(1)} MB)`).join(" · ") : "Até 30 ficheiros de cada vez, 15 MB cada. Ficam no teu espaço privado."}</small></span><input id="proposal-library-file" type="file" multiple accept=".pdf,.docx,.xlsx,.txt,.csv,.eml" onChange={(e) => { selectLibraryFiles(e.target.files); e.currentTarget.value = ""; }} disabled={working} /></label><button className="secondary" disabled={working || !files.length}>{working ? "A guardar…" : files.length > 1 ? `Adicionar ${files.length} à biblioteca` : "Adicionar à biblioteca"}</button></form></section>
    <section className="panel proposal-library-results"><div className="panel-heading"><div><h2>Registos da biblioteca</h2><p>Propostas geradas e documentos anteriores, com pesquisa e filtros.</p></div><div style={{ display: "flex", gap: 8, alignItems: "center" }}><button className="secondary" disabled={working} onClick={() => void reprocessReadings()}>Reprocessar leituras pendentes</button><span className="count-pill">{visibleReferences.length} de {references.length} registos</span></div></div><form className="toolbar catalog-toolbar" onSubmit={submitSearch}><label className="search-box"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="N.º da proposta, cliente, obra, serviço ou localização…" /></label><button className="secondary" disabled={working}>{working ? "A pesquisar…" : "Pesquisar"}</button><select aria-label="Tipo de registo" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}><option value="all">Todos os registos</option><option value="generated">Propostas geradas</option><option value="uploaded">Ficheiros carregados</option></select><select aria-label="Estado da proposta" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">Todos os estados</option>{STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABEL[status]}</option>)}</select><select aria-label="Ordenar propostas" value={sortBy} onChange={(e) => setSortBy(e.target.value)}><option value="newest">Mais recentes</option><option value="oldest">Mais antigas</option><option value="number">N.º da proposta</option><option value="client">Cliente A–Z</option><option value="value">Valor mais alto</option></select></form>{working && !references.length ? <div className="empty-state"><span className="loader" />A carregar a base de propostas…</div> : visibleReferences.length ? <div className="table-scroll proposal-catalog-scroll"><table className="proposal-catalog-table"><thead><tr><th>N.º / TIPO</th><th>CLIENTE</th><th>OBJETO / OBRA</th><th>LOCALIZAÇÃO</th><th>ESTADO</th><th>VALOR C/ IVA</th><th>DATA</th><th>AÇÕES</th></tr></thead><tbody>{visibleReferences.map((reference) => <Fragment key={`${reference.source}-${reference.id}`}><tr><td><b className="catalog-proposal-no">{reference.proposal_no || "Sem número"}</b><small>{reference.source === "generated" ? "Gerada" : reference.file_name || "Importada"}</small></td><td><b>{reference.client_name || "Cliente por identificar"}</b><small>{reference.source === "uploaded" ? "Documento carregado" : "Cliente"}</small></td><td><b>{reference.project_name || reference.title}</b><small>{reference.objective || reference.summary || "Sem descrição do objeto"}</small></td><td>{reference.location || "—"}</td><td><span className={reference.status ? statusClass(reference.status) : "catalog-imported-status"}><i />{reference.status ? STATUS_LABEL[reference.status] || reference.status : "Importada"}</span></td><td>{reference.total != null ? money(Number(reference.total)) : "—"}</td><td>{displayDate(reference.created_at)}</td><td><div className="catalog-actions"><button className="secondary" disabled={working} onClick={() => void openReference(reference)}>{reference.source === "uploaded" ? "Consultar" : "Abrir"}</button>{reference.source === "uploaded" && <button className="secondary" disabled={working} onClick={() => setReadingId(readingId === reference.id ? null : reference.id)}>{readingId === reference.id ? "Ocultar leitura" : "Ver leitura"}</button>}<button className="danger-button" disabled={working} onClick={() => void removeReference(reference)}>Apagar</button></div></td></tr>{reference.source === "uploaded" && readingId === reference.id && <tr><td colSpan={8}><LibraryReading token={token} id={reference.id} setError={setError} /></td></tr>}</Fragment>)}</tbody></table></div> : <div className="empty-state"><div className="empty-icon">▤</div><h3>{references.length || query || statusFilter !== "all" || sourceFilter !== "all" ? "Sem registos com estes filtros" : "A biblioteca está vazia"}</h3><p>{references.length || query || statusFilter !== "all" || sourceFilter !== "all" ? "Altera a pesquisa ou os filtros para veres outras propostas." : "As propostas geradas aparecem aqui automaticamente. Também podes carregar propostas anteriores."}</p></div>}</section>
  </>;
}
function ItemDetailPanel({ d }: { d?: ItemDetail }) {
  if (!d) return <div className="small-empty">A carregar detalhe…</div>;
  if (!d.linked) return <div className="technical-note">Esta linha não tem serviço do catálogo associado (por exemplo, veio da MQT). Não há detalhe para mostrar.</div>;
  const groups = (d.resources ?? []).reduce<Record<string, NonNullable<ItemDetail["resources"]>>>((acc, r) => { (acc[r.type] ??= []).push(r); return acc; }, {});
  const nothing = !d.note && !d.technical_basis && !d.duration && !d.labor?.length && !d.resources?.length && !d.tests?.length && !d.procedures?.length && !d.triggers?.length && !d.required_by?.length;
  return <div className="item-detail">
    {nothing && <p><b>Sem detalhe na base de dados.</b> Este serviço ainda não tem recursos, duração, ensaios ou procedimentos ligados.</p>}
    {d.note && <p><b>Motivo e fonte.</b> {d.note}</p>}
    {d.technical_basis && <p><b>Fundamento técnico.</b> {d.technical_basis}</p>}
    {d.duration && <p><b>Duração prevista.</b> {d.duration.minutes} min{d.duration.team_size ? ` · equipa de ${d.duration.team_size}` : ""}{d.duration.condition ? ` · ${d.duration.condition}` : ""}{d.duration.condition_to_confirm ? " (condição por confirmar)" : ""}</p>}
    {(d.labor?.length ?? 0) > 0 && <p><b>Mão-de-obra.</b> {d.labor!.map((l) => `${l.name}${l.quantity ? ` ×${l.quantity}` : ""}${l.role ? ` (${l.role})` : ""}`).join(" · ")}</p>}
    {Object.entries(groups).map(([type, rows]) => <div key={type}><b>{type}</b><ul>{rows.map((r, i) => <li key={i}>{r.name}{r.quantity ? ` ×${r.quantity}` : ""}{r.role ? ` — ${r.role}` : ""}{r.condition ? ` · se: ${r.condition}` : ""}{r.external ? " · externo" : ""}{r.rentable ? " · alugável" : ""}{r.needs_calibration ? " · requer calibração" : ""}</li>)}</ul></div>)}
    {(d.tests?.length ?? 0) > 0 && <p><b>Ensaios associados.</b> {d.tests!.map((t) => `${t.code}${t.name ? ` ${t.name}` : ""}`).join(" · ")}</p>}
    {(d.procedures?.length ?? 0) > 0 && <p><b>Procedimentos.</b> {d.procedures!.map((p) => `${p.code} ${p.title}`).join(" · ")}</p>}
    {(d.triggers?.length ?? 0) > 0 && <div><b>Pode desencadear</b><ul>{d.triggers!.map((t, i) => <li key={i}>{t.name || t.service_id} ×{t.quantity}{t.relation ? ` (${t.relation})` : ""}{t.note ? ` — ${t.note}` : ""}</li>)}</ul></div>}
    {(d.required_by?.length ?? 0) > 0 && <p><b>Incluído por causa de.</b> {d.required_by!.map((r) => `${r.name || r.service_id}${r.note ? ` — ${r.note}` : ""}`).join(" · ")}</p>}
  </div>;
}
function Highlight({ text, words }: { text: string; words: string[] }) {
  const set = new Set(words.map((w) => w.toLowerCase()));
  return <>{text.split(/([A-Za-zÀ-ÿ0-9]+)/).map((part, i) => set.has(part.toLowerCase()) ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>)}</>;
}

function PathologyWhy({ candidate }: { candidate: any }) {
  const why = candidate.reasons;
  const words: string[] = why?.matched_words ?? [];
  return <div className="pathology-evidence">
    <b>Porque foi selecionada</b>
    {why ? <>
      <p><strong>Fiabilidade {why.reliability}</strong> · {why.channel_label}{why.compared_with?.label ? ` · «${why.compared_with.label}»` : ""}</p>
      <p>{why.explanation}</p>
      {words.length > 0 && <p>Palavras do pedido que coincidem: {words.map((w) => <span className="category-chip" key={w}>{w}</span>)}</p>}
      {why.missing_words?.length > 0 && <p>Palavras da designação que <u>não</u> aparecem no pedido: {why.missing_words.join(", ")}.</p>}
    </> : <p>Análise antiga sem justificação. Usa «Reanalisar pedido» para a obter.</p>}
    {candidate.evidence?.length > 0
      ? <><b>Excertos do pedido</b>{candidate.evidence.map((item: string, index: number) => <p key={`${candidate.code}-ev-${index}`}>“<Highlight text={item} words={words} />”</p>)}</>
      : <p>Nenhum excerto do pedido sustenta esta correspondência.</p>}
  </div>;
}

function WeakMatches({ items }: { items: any[] }) {
  return <details className="technical-note"><summary>{items.length} correspondência(s) fraca(s) não usada(s) no orçamento — ver porquê</summary>
    {items.map((c) => <div key={c.code} className="pathology-evidence"><b>{c.code} {c.name}</b> · {c.match_percent}%<p>{c.reasons?.explanation}</p></div>)}
  </details>;
}