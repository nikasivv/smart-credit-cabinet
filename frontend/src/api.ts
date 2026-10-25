// Клиент API: токен, единый разбор ошибок, типы ответов.

export interface Company { id: number; inn: string; name: string; legal_form: string; okved: string | null; okved_name: string | null; region: string | null; }
export interface User { id: number; email: string; full_name: string; position: string | null; role: "CLIENT" | "ANALYST" | "RISK_ADMIN"; company: Company | null; }
export interface Product { code: string; name: string; tagline: string; description: string; min_amount: number; max_amount: number; min_term: number; max_term: number; base_rate: number; requires_collateral: boolean; purposes: string[]; features: string[]; }
export interface Purpose { code: string; title: string; hint: string; }
export interface Catalog { version: string; products: Product[]; purposes: Purpose[]; documents: Record<string, string>; }
export interface Offer { amount: number; term_months: number; rate: number; monthly_payment: number; overpayment: number; }
export interface StatusView { code: string; title: string; now: string; next_step: string; waiting_for: "client" | "bank" | "none"; stage: number; stages: string[]; allowed_actions: string[]; }
export interface Doc { id: number; doc_type: string; filename: string; content_type: string; size: number; sha256: string; created_at: string; }
export interface InfoItem { field: string; code: string; message: string; }
export interface InfoRequest { id: number; message: string; items: InfoItem[] | null; status: string; requested_by_type: string; created_at: string; }
export interface Factor { title: string; impact: "positive" | "negative" | "neutral"; text: string; }
export interface ClientScore { grade: string; factors: Factor[]; stop_factors: { title: string; text: string }[]; }
export interface Application {
  id: string; number: string; product_code: string; product_name: string; purpose: string | null; purpose_comment: string | null;
  amount: number | null; term_months: number | null; revenue_last_year: number | null; revenue_prev_year: number | null;
  monthly_debt_payments: number | null; collateral_type: string | null; collateral_value: number | null;
  status: StatusView; version: number; offer: Offer | null; decision: Record<string, any> | null; score: Record<string, any> | null;
  contract_number: string | null; required_documents: { code: string; title: string; uploaded: boolean }[];
  documents: Doc[]; info_request: InfoRequest | null; created_at: string; updated_at: string;
  submitted_at: string | null; decided_at: string | null; issued_at: string | null;
}
export interface AppEvent { id: number; kind: string; from_status: string | null; to_status: string | null; actor_type: string; message: string; payload: Record<string, any> | null; created_at: string; }
export interface FeedItem { id: string; kind: "action" | "offer" | "event" | "tip"; title: string; body: string; reason: string; date: string; application_id?: string; product_code?: string; amount?: number; }
export interface Feed { items: FeedItem[]; }
export interface Suggestion { source: "llm" | "rules" | "form"; purpose: string | null; purpose_title?: string; amount: number | null; term_months: number | null; recommendations: { product_code: string; name: string; fit: "best" | "alternative"; reason: string }[]; message: string | null; }
export interface AuditEvent extends AppEvent { application_id: string; application_number: string; company_name: string; actor_name: string | null; visible_to_client: boolean; }
export interface Policy {
  policy_version: string; scorecard_version: string; base_score: number;
  grades: { min_score: number; grade: string; pd: number }[];
  auto_decision_limit: number; min_dscr: number; counter_min_share: number;
  grade_rate_premium: Record<string, number>; grade_limit_multiplier: Record<string, number>;
  products: Record<string, { name: string; base_rate: number; revenue_share: number; min_amount: number; max_amount: number; min_term: number; max_term: number }>;
  industry_risk: Record<string, { risk: "low" | "medium" | "high"; margin: number }>;
}
export interface QueueItem { id: string; number: string; company_name: string; company_inn: string; product_name: string; amount: number | null; term_months: number | null; status: string; status_title: string; grade: string | null; score: number | null; analyst_id: number | null; analyst_name: string | null; submitted_at: string | null; waiting_minutes: number | null; reasons: string[]; }
export interface AnalystCard { application: Application; company: Company; applicant: { full_name: string; position: string | null; email: string }; enrichment: Record<string, any> | null; scoring: Record<string, any> | null; decision: Record<string, any> | null; summary: string[]; events: AppEvent[]; analyst_id: number | null; }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: { field?: string; message: string }[] = []) {
    super(message);
  }
}

const TOKEN_KEY = "scc.token";
let token: string | null = null;
try { token = sessionStorage.getItem(TOKEN_KEY); } catch { token = null; }

export function setToken(t: string | null): void {
  token = t;
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* приватный режим */ }
}
export function hasToken(): boolean { return token !== null; }

let onUnauthorized: () => void = () => undefined;
export function setUnauthorizedHandler(fn: () => void): void { onUnauthorized = fn; }

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const h: Record<string, string> = { ...headers };
  if (token) h["Authorization"] = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { h["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res: Response;
  try {
    res = await fetch(path, { method, headers: h, body: payload });
  } catch {
    throw new ApiError(0, "network", "Нет связи с сервером. Проверьте подключение и повторите.");
  }
  if (res.status === 401 && token) { setToken(null); onUnauthorized(); }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data?.code ?? "error", data?.message ?? `Ошибка ${res.status}`, data?.details ?? []);
  return data as T;
}

export const api = {
  login: (email: string, password: string) => request<{ access_token: string; user: User }>("POST", "/api/auth/login", { email, password }),
  register: (body: { inn: string; full_name: string; position: string; email: string; password: string }) =>
    request<{ access_token: string; user: User }>("POST", "/api/auth/register", body),
  me: () => request<User>("GET", "/api/auth/me"),
  catalog: () => request<Catalog>("GET", "/api/catalog"),
  calc: (product_code: string, amount: number, term_months: number) =>
    request<{ rate_from: number; monthly_payment_from: number; overpayment_from: number; note: string }>("POST", "/api/calculator", { product_code, amount, term_months }),
  suggest: (body: { text?: string; purpose?: string; amount?: number | null }) => request<Suggestion>("POST", "/api/assistant/suggest", body),
  feed: () => request<Feed>("GET", "/api/feed"),
  applications: () => request<Application[]>("GET", "/api/applications"),
  application: (id: string) => request<Application>("GET", `/api/applications/${id}`),
  create: (body: Record<string, unknown>, key: string) => request<Application>("POST", "/api/applications", body, { "Idempotency-Key": key }),
  patch: (id: string, body: Record<string, unknown>) => request<Application>("PATCH", `/api/applications/${id}`, body),
  submit: (id: string) => request<Application>("POST", `/api/applications/${id}/submit`),
  upload: (id: string, docType: string, file: File) => {
    const fd = new FormData(); fd.append("doc_type", docType); fd.append("file", file);
    return request<Doc>("POST", `/api/applications/${id}/documents`, fd);
  },
  deleteDocument: (id: string, docId: number) => request<null>("DELETE", `/api/applications/${id}/documents/${docId}`),
  infoResponse: (id: string, body: Record<string, unknown>) => request<Application>("POST", `/api/applications/${id}/info-response`, body),
  accept: (id: string) => request<Application>("POST", `/api/applications/${id}/accept`),
  sign: (id: string, confirmation_inn: string) => request<Application>("POST", `/api/applications/${id}/sign`, { confirmation_inn, agree: true }),
  cancel: (id: string, reason?: string) => request<Application>("POST", `/api/applications/${id}/cancel`, { reason }),
  events: (id: string) => request<AppEvent[]>("GET", `/api/applications/${id}/events`),
  queue: (scope: string) => request<QueueItem[]>("GET", `/api/analyst/queue?scope=${scope}`),
  card: (id: string) => request<AnalystCard>("GET", `/api/analyst/applications/${id}`),
  assign: (id: string) => request<{ ok: boolean }>("POST", `/api/analyst/applications/${id}/assign`),
  decide: (id: string, body: Record<string, unknown>) => request<{ ok: boolean; status: string }>("POST", `/api/analyst/applications/${id}/decision`, body),
  requestInfo: (id: string, message: string, documents: string[]) => request<{ ok: boolean }>("POST", `/api/analyst/applications/${id}/request-info`, { message, documents }),
  stats: () => request<{ by_status: Record<string, { count: number; title: string }>; auto_share: number | null; auto_decisions: number; manual_reviews: number }>("GET", "/api/analyst/stats"),
  policy: () => request<Policy>("GET", "/api/admin/policy"),
  audit: (hiddenOnly: boolean, limit: number) => request<AuditEvent[]>("GET", `/api/admin/audit?limit=${limit}${hiddenOnly ? "&hidden_only=true" : ""}`),
  jobs: () => request<{ counts: Record<string, number>; failed: { id: number; kind: string; application_id: string; attempts: number; error: string | null }[] }>("GET", "/api/admin/jobs"),
  chaos: () => request<{ fail_rate: number; latency_ms: number; sources: string[] }>("GET", "/api/admin/integrations/chaos"),
  setChaos: (fail_rate: number) => request<{ fail_rate: number }>("POST", "/api/admin/integrations/chaos", { fail_rate }),
};