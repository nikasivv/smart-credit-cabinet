// Небольшой слой для построения DOM без фреймворка.
// Пользовательские данные всегда попадают в DOM через textContent — это исключает XSS.

import { ApiError, StatusView } from "./api.js";

export type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, string | number | boolean | EventListener | null | undefined>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v as EventListener);
    else if (k === "class") el.className = String(v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const c of (children as unknown[]).flat(Infinity) as (Node | string | number | null | undefined | false)[]) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function mount(root: HTMLElement, ...nodes: (Node | null | undefined | false)[]): void {
  root.replaceChildren(...nodes.filter((n): n is Node => !!n));
}

const nf = new Intl.NumberFormat("ru-RU");
export const money = (n: number | null | undefined): string => (n === null || n === undefined ? "—" : `${nf.format(n)} ₽`);
export const moneyShort = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн ₽`;
  if (n >= 1_000) return `${(n / 1_000).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} тыс. ₽`;
  return money(n);
};
export const months = (n: number | null | undefined): string => {
  if (!n) return "—";
  const m10 = n % 10, m100 = n % 100;
  const w = m10 === 1 && m100 !== 11 ? "месяц" : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? "месяца" : "месяцев";
  return `${n} ${w}`;
};
export const dateTime = (iso: string): string =>
  new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
export const dateOnly = (iso: string): string => new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });

/** Ввод сумм: цифры с пробелами-разделителями, значение — целое число. */
export function moneyInput(name: string, value: number | null, placeholder = ""): HTMLInputElement {
  const input = h("input", { name, inputmode: "numeric", autocomplete: "off", placeholder, class: "input money" });
  // Не больше 15 цифр (сотни миллиардов): дальше — заведомая опечатка, а JS теряет точность после 2^53
  const fmt = (raw: string) => { const d = raw.replace(/\D/g, "").slice(0, 15); return d ? nf.format(Number(d)) : ""; };
  input.value = value !== null && value !== undefined ? nf.format(value) : "";
  input.addEventListener("input", () => {
    const pos = input.value.length - (input.selectionStart ?? input.value.length);
    input.value = fmt(input.value);
    const p = Math.max(0, input.value.length - pos);
    input.setSelectionRange(p, p);
  });
  return input;
}
export function readMoney(input: HTMLInputElement): number | null {
  const d = input.value.replace(/\D/g, "");
  return d ? Number(d) : null;
}

export function field(label: string, control: HTMLElement, hint?: string, name?: string): HTMLElement {
  const id = `f-${name ?? Math.random().toString(36).slice(2)}`;
  control.id = id;
  return h("div", { class: "field", "data-field": name ?? "" },
    h("label", { for: id }, label), control, hint ? h("p", { class: "hint" }, hint) : null,
    h("p", { class: "field-error", role: "alert" }));
}

/** Показать ошибки API рядом с полями и общим сообщением. */
export function showErrors(scope: HTMLElement, err: unknown): void {
  scope.querySelectorAll(".field").forEach((f) => f.classList.remove("has-error"));
  scope.querySelectorAll(".field-error").forEach((e) => (e.textContent = ""));
  const box = scope.querySelector<HTMLElement>(".form-error");
  const e = err instanceof ApiError ? err : new ApiError(0, "error", "Что-то пошло не так. Повторите действие.");
  let unmatched: string[] = [];
  for (const d of e.details) {
    const f = d.field ? scope.querySelector<HTMLElement>(`.field[data-field="${CSS.escape(d.field)}"]`) : null;
    if (f) { f.classList.add("has-error"); f.querySelector(".field-error")!.textContent = d.message; }
    else unmatched.push(d.message);
  }
  if (box) {
    box.replaceChildren(h("strong", {}, e.message), ...unmatched.map((m) => h("div", {}, m)));
    box.hidden = false;
  } else toast(e.message, "error");
}
export function clearErrors(scope: HTMLElement): void {
  const box = scope.querySelector<HTMLElement>(".form-error");
  if (box) box.hidden = true;
  scope.querySelectorAll(".field").forEach((f) => f.classList.remove("has-error"));
  scope.querySelectorAll(".field-error").forEach((e) => (e.textContent = ""));
}

export function toast(message: string, kind: "ok" | "error" = "ok"): void {
  const host = document.getElementById("toasts")!;
  const t = h("div", { class: `toast toast-${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  host.append(t);
  setTimeout(() => t.remove(), 4500);
}

/** Кнопка, которая блокируется на время запроса. */
export function actionButton(label: string, run: () => Promise<void>, cls = "btn btn-primary"): HTMLButtonElement {
  const b = h("button", { type: "button", class: cls }, label);
  b.addEventListener("click", async () => {
    if (b.disabled) return;
    b.disabled = true; b.classList.add("is-busy");
    try { await run(); } finally { b.disabled = false; b.classList.remove("is-busy"); }
  });
  return b;
}

/** Маршрут заявки: пять этапов. Текущий этап выделен, если ход за банком — пульсирует. */
export function tracker(s: StatusView): HTMLElement {
  const final = ["REJECTED", "CANCELLED"].includes(s.code);
  const done = s.code === "ISSUED";
  return h("ol", { class: `route ${final ? "route-stopped" : ""}`, "aria-label": "Этапы заявки" },
    s.stages.map((name, i) => {
      const state = done || i < s.stage ? "passed" : i === s.stage ? (final ? "stopped" : `current wait-${s.waiting_for}`) : "ahead";
      return h("li", { class: `route-step ${state}`, "aria-current": i === s.stage ? "step" : null },
        h("span", { class: "route-dot" }), h("span", { class: "route-name" }, name));
    }));
}

export function statusPill(code: string, title: string): HTMLElement {
  const tone: Record<string, string> = {
    DRAFT: "neutral", CANCELLED: "neutral", NEEDS_INFO: "attention", APPROVED: "good", COUNTER_OFFER: "attention",
    OFFER_ACCEPTED: "attention", ISSUED: "good", SIGNED: "bank", REJECTED: "bad",
  };
  return h("span", { class: `pill pill-${tone[code] ?? "bank"}` }, title);
}

export function emptyState(title: string, text: string, action?: HTMLElement): HTMLElement {
  return h("div", { class: "empty" }, h("h3", {}, title), h("p", {}, text), action ?? null);
}

/** Аннуитетный график — для наглядности в карточке договора. */
export function schedule(amount: number, rate: number, term: number): { n: number; payment: number; principal: number; interest: number; rest: number }[] {
  const r = rate / 100 / 12;
  const p = r === 0 ? amount / term : (amount * r) / (1 - Math.pow(1 + r, -term));
  let rest = amount;
  const out = [];
  for (let n = 1; n <= term; n++) {
    const interest = rest * r;
    const principal = n === term ? rest : p - interest;
    rest = Math.max(0, rest - principal);
    out.push({ n, payment: Math.round(principal + interest), principal: Math.round(principal), interest: Math.round(interest), rest: Math.round(rest) });
  }
  return out;
}

export function uuid(): string {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}