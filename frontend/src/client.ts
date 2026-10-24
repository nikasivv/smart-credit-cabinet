// Кабинет клиента.

import { api, Application, ApiError, AppEvent, Catalog, Feed, Product, Suggestion, User } from "./api.js";
import {
  actionButton, clearErrors, dateOnly, dateTime, emptyState, field, h, money, moneyInput, moneyShort, months, mount,
  readMoney, schedule, showErrors, statusPill, toast, tracker, uuid,
} from "./ui.js";

export type Cleanup = () => void;
let catalogCache: Catalog | null = null;
export async function catalog(): Promise<Catalog> {
  return (catalogCache ??= await api.catalog());
}
const go = (hash: string) => { location.hash = hash; };

// ============ Главная ============

export async function dashboard(root: HTMLElement, user: User): Promise<Cleanup> {
  const [apps, feed] = await Promise.all([api.applications(), api.feed(), catalog()]);
  const active = apps.filter((a) => !["ISSUED", "REJECTED", "CANCELLED"].includes(a.status.code));
  const closed = apps.filter((a) => !active.includes(a));

  mount(root,
    h("section", { class: "hero" },
      h("div", {},
        h("h1", {}, `Здравствуйте, ${user.full_name.split(" ")[0]}`),
        h("p", { class: "lead" }, user.company?.name ?? "", user.company ? ` · ИНН ${user.company.inn}` : "")),
      h("a", { class: "btn btn-primary btn-lg", href: "#/new" }, "Получить финансирование")),
    h("div", { class: "grid-main" },
      h("section", { "aria-labelledby": "apps-h" },
        h("h2", { id: "apps-h" }, "Заявки"),
        active.length ? h("div", { class: "app-list" }, active.map(appRow))
          : emptyState("Активных заявок нет", "Расскажите, на что нужны деньги, — подберём продукт и рассчитаем платёж.",
            h("a", { class: "btn btn-secondary", href: "#/new" }, "Подобрать продукт")),
        closed.length ? h("details", { class: "closed-apps" },
          h("summary", {}, `Завершённые заявки (${closed.length})`), h("div", { class: "app-list" }, closed.map(appRow))) : null),
      feedView(feed)));
  return () => undefined;
}

function appRow(a: Application): HTMLElement {
  return h("a", { class: "app-row", href: `#/applications/${a.id}` },
    h("div", { class: "app-row-main" },
      h("span", { class: "app-row-title" }, a.product_name),
      h("span", { class: "app-row-meta" }, `${a.number} · ${dateOnly(a.created_at)}`)),
    h("span", { class: "app-row-amount" }, moneyShort(a.offer?.amount ?? a.amount)),
    statusPill(a.status.code, a.status.title));
}

function feedView(feed: Feed): HTMLElement {
  const label: Record<string, string> = { action: "Нужно действие", offer: "Предложение", event: "По заявке", tip: "Совет по заявке" };
  return h("aside", { class: "feed", "aria-labelledby": "feed-h" },
    h("h2", { id: "feed-h" }, "Ваши заявки и предложения"),
    h("p", { class: "feed-profile" }, "Что нужно сделать, что изменилось и что банк готов предложить."),
    feed.items.length ? h("ul", { class: "feed-list" }, feed.items.map((it) =>
      h("li", { class: `feed-item feed-${it.kind}` },
        h("div", { class: "feed-kind" }, label[it.kind] ?? it.kind),
        it.application_id ? h("a", { class: "feed-title", href: `#/applications/${it.application_id}` }, it.title)
          : it.kind === "offer" ? h("a", { class: "feed-title", href: `#/new?product=${it.product_code}&amount=${it.amount}` }, it.title)
          : h("div", { class: "feed-title" }, it.title),
        h("p", {}, it.body),
        h("div", { class: "feed-why", title: "Почему вы это видите" }, it.reason)))) : emptyState("Пока пусто", "Здесь появятся действия и события по вашим заявкам и персональные предложения банка."));
}

// ============ Мастер новой заявки ============

interface Draft {
  purpose: string | null; text: string; product: string | null; amount: number | null; term: number | null;
  revenue_last: number | null; revenue_prev: number | null; debt: number | null; collateral_type: string | null;
  collateral_value: number | null; comment: string; appId: string | null; key: string; suggestion: Suggestion | null;
}

const STEPS = ["Цель", "Продукт", "О бизнесе", "Документы", "Проверка"];

export async function wizard(root: HTMLElement, user: User, query: URLSearchParams): Promise<Cleanup> {
  const cat = await catalog();
  const d: Draft = {
    purpose: null, text: "", product: query.get("product"), amount: query.get("amount") ? Number(query.get("amount")) : null,
    term: null, revenue_last: null, revenue_prev: null, debt: null, collateral_type: null, collateral_value: null,
    comment: "", appId: null, key: uuid(), suggestion: null,
  };
  let step = d.product ? 1 : 0;
  if (d.product) d.purpose = cat.products.find((p) => p.code === d.product)?.purposes[0] ?? null;
  let calcTimer = 0;

  const render = () => {
    const body = [stepPurpose, stepProduct, stepBusiness, stepDocs, stepReview][step]();
    mount(root,
      h("a", { class: "back", href: "#/" }, "Вернуться на главную"),
      h("h1", {}, "Новая заявка на финансирование"),
      h("ol", { class: "steps", "aria-label": "Шаги заявки" }, STEPS.map((s, i) =>
        h("li", { class: i < step ? "done" : i === step ? "current" : "", "aria-current": i === step ? "step" : null }, s))),
      h("div", { class: "panel" }, h("div", { class: "form-error", role: "alert", hidden: true }), body));
    root.querySelector<HTMLElement>("h2, input, textarea")?.focus?.();
  };
  const product = (): Product => cat.products.find((p) => p.code === d.product)!;

  // --- Шаг 1: зачем деньги
  function stepPurpose(): HTMLElement {
    const text = h("textarea", { class: "input", rows: 3, maxlength: 1000, placeholder: "Например: нужно купить новую печь для пекарни, примерно 2,5 млн" });
    text.value = d.text;
    const result = h("div", { class: "suggestion" });
    if (d.suggestion) renderSuggestion(result, d.suggestion);
    return h("div", {},
      h("h2", {}, "На что нужны деньги?"),
      h("div", { class: "purpose-grid", role: "list" }, cat.purposes.map((p) =>
        h("button", { type: "button", role: "listitem", class: `purpose ${d.purpose === p.code ? "selected" : ""}`,
          onclick: async () => { d.purpose = p.code; d.text = ""; d.suggestion = await api.suggest({ purpose: p.code, amount: d.amount }); pickBest(); step = 1; render(); } },
          h("strong", {}, p.title), h("span", {}, p.hint)))),
      h("div", { class: "or" }, "или опишите своими словами"),
      field("Ваша задача", text, "Определим цель и сумму и подберём продукт", "text"),
      actionButton("Подобрать продукт", async () => {
        if (!text.value.trim()) { text.focus(); return; }
        d.text = text.value.trim();
        const s = await api.suggest({ text: d.text });
        d.suggestion = s;
        renderSuggestion(result, s);
      }, "btn btn-secondary"),
      result);
  }

  function renderSuggestion(host: HTMLElement, s: Suggestion): void {
    if (!s.purpose) { host.replaceChildren(h("p", { class: "notice" }, s.message ?? "")); return; }
    host.replaceChildren(
      h("p", { class: "suggest-head" }, `Понял задачу: ${s.purpose_title?.toLowerCase()}`, s.amount ? `, около ${moneyShort(s.amount)}` : "", "."),
      h("p", { class: "hint" }, s.source === "llm" ? "Разобрано языковой моделью (открытые веса, локально)." : "Разобрано по ключевым словам."),
      h("ul", { class: "rec-list" }, s.recommendations.map((r) => h("li", { class: r.fit },
        h("strong", {}, r.name), r.fit === "best" ? h("span", { class: "pill pill-good" }, "Подходит лучше всего") : null,
        h("p", {}, r.reason)))),
      h("button", { type: "button", class: "btn btn-primary", onclick: () => {
        d.purpose = s.purpose; if (s.amount) d.amount = s.amount; if (s.term_months) d.term = s.term_months; pickBest(); step = 1; render();
      } }, "Продолжить с этим продуктом"));
  }

  function pickBest(): void {
    const best = d.suggestion?.recommendations?.[0]?.product_code;
    if (best) d.product = best;
    else if (!d.product) d.product = cat.products.find((p) => d.purpose && p.purposes.includes(d.purpose))?.code ?? cat.products[0].code;
  }

  // --- Шаг 2: продукт и параметры
  function stepProduct(): HTMLElement {
    const recCodes = d.suggestion?.recommendations?.map((r) => r.product_code) ?? [];
    const options = [...cat.products].sort((a, b) => (recCodes.indexOf(a.code) + 1 || 99) - (recCodes.indexOf(b.code) + 1 || 99));
    if (!d.product) d.product = options[0].code;
    const p = product();
    d.amount = clamp(d.amount ?? Math.round((p.min_amount + Math.min(p.max_amount, p.min_amount * 20)) / 2 / 100_000) * 100_000, p.min_amount, p.max_amount);
    d.term = clamp(d.term ?? Math.min(p.max_term, 12), p.min_term, p.max_term);
    const amount = moneyInput("amount", d.amount);
    const term = h("input", { type: "range", min: p.min_term, max: p.max_term, value: d.term, class: "range" });
    const termLabel = h("output", {}, months(d.term));
    const calc = h("div", { class: "calc", "aria-live": "polite" });
    const recalc = () => {
      clearTimeout(calcTimer);
      calcTimer = window.setTimeout(async () => {
        const a = readMoney(amount);
        if (!a || a < p.min_amount || a > p.max_amount) {
          calc.replaceChildren(h("p", { class: "hint" }, `Сумма — от ${money(p.min_amount)} до ${money(p.max_amount)}`)); return;
        }
        const r = await api.calc(p.code, a, Number(term.value));
        calc.replaceChildren(
          h("div", { class: "calc-main" }, h("span", {}, "Платёж в месяц"), h("strong", {}, `от ${money(r.monthly_payment_from)}`)),
          h("div", { class: "calc-row" }, h("span", {}, "Ставка"), h("span", {}, `от ${r.rate_from.toLocaleString("ru-RU")}% годовых`)),
          h("div", { class: "calc-row" }, h("span", {}, "Переплата"), h("span", {}, `от ${money(r.overpayment_from)}`)),
          h("p", { class: "hint" }, r.note));
      }, 250);
    };
    amount.addEventListener("input", recalc);
    term.addEventListener("input", () => { termLabel.textContent = months(Number(term.value)); recalc(); });
    recalc();
    return h("div", {},
      h("h2", {}, "Продукт и сумма"),
      h("div", { class: "product-grid", role: "radiogroup", "aria-label": "Продукт" }, options.map((o) => {
        const rec = d.suggestion?.recommendations?.find((r) => r.product_code === o.code);
        return h("button", { type: "button", role: "radio", "aria-checked": String(o.code === d.product),
          class: `product ${o.code === d.product ? "selected" : ""}`,
          onclick: () => { d.product = o.code; d.amount = readMoney(amount); d.term = Number(term.value); render(); } },
          h("strong", {}, o.name), rec?.fit === "best" ? h("span", { class: "pill pill-good" }, "Рекомендуем") : null,
          h("span", {}, o.tagline),
          h("span", { class: "product-meta" }, `до ${moneyShort(o.max_amount)} · до ${months(o.max_term)} · от ${o.base_rate.toLocaleString("ru-RU")}%`));
      })),
      h("div", { class: "two-col" },
        h("div", {},
          field("Сумма", amount, `От ${money(p.min_amount)} до ${money(p.max_amount)}`, "amount"),
          h("div", { class: "field", "data-field": "term_months" }, h("label", {}, "Срок: ", termLabel), term,
            h("p", { class: "hint" }, `От ${months(p.min_term)} до ${months(p.max_term)}`), h("p", { class: "field-error" }))),
        calc),
      nav(() => { d.amount = readMoney(amount); d.term = Number(term.value); }));
  }

  // --- Шаг 3: данные о бизнесе
  function stepBusiness(): HTMLElement {
    const p = product();
    const rl = moneyInput("revenue_last_year", d.revenue_last, "Например, 48 000 000");
    const rp = moneyInput("revenue_prev_year", d.revenue_prev);
    const debt = moneyInput("monthly_debt_payments", d.debt ?? 0);
    const comment = h("textarea", { class: "input", rows: 2, maxlength: 2000, placeholder: "Например: закупка сырья к новогоднему сезону" });
    comment.value = d.comment;
    const cType = h("select", { class: "input" }, h("option", { value: "" }, "Выберите"),
      ...[["equipment", "Приобретаемое оборудование"], ["vehicle", "Транспорт"], ["real_estate", "Недвижимость"]].map(([v, t]) =>
        h("option", { value: v, selected: d.collateral_type === v }, t)));
    const cValue = moneyInput("collateral_value", d.collateral_value);
    const save = () => {
      d.revenue_last = readMoney(rl); d.revenue_prev = readMoney(rp); d.debt = readMoney(debt) ?? 0; d.comment = comment.value;
      d.collateral_type = cType.value || null; d.collateral_value = readMoney(cValue);
    };
    return h("div", {},
      h("h2", {}, "О бизнесе"),
      h("div", { class: "company-card" },
        h("strong", {}, user.company?.name ?? ""), h("span", {}, `ИНН ${user.company?.inn} · ${user.company?.okved_name ?? ""}`),
        h("span", { class: "hint" }, "Регистрационные данные банк проверит в ЕГРЮЛ/ЕГРИП сам — вводить их не нужно.")),
      h("div", { class: "two-col" },
        field("Выручка за 2025 год", rl, "Из декларации или отчётности", "revenue_last_year"),
        field("Выручка за 2024 год", rp, "Если бизнес моложе — оставьте пустым", "revenue_prev_year")),
      field("Платежи по текущим кредитам и лизингу в месяц", debt, "0, если кредитов нет", "monthly_debt_payments"),
      p.requires_collateral ? h("div", { class: "two-col" },
        field("Залог", cType, undefined, "collateral_type"),
        field("Оценочная стоимость залога", cValue, "Не менее 70% суммы кредита", "collateral_value")) : null,
      field("Подробнее о цели (необязательно)", comment, undefined, "purpose_comment"),
      nav(save, async () => {
        const body = {
          product_code: d.product, purpose: d.purpose, amount: d.amount, term_months: d.term, revenue_last_year: d.revenue_last,
          revenue_prev_year: d.revenue_prev, monthly_debt_payments: d.debt, purpose_comment: d.comment || null,
          collateral_type: d.collateral_type, collateral_value: d.collateral_value,
        };
        const app = d.appId ? await api.patch(d.appId, body) : await api.create(body, d.key);
        d.appId = app.id;
      }));
  }

  // --- Шаг 4: документы
  function stepDocs(): HTMLElement {
    const host = h("div", {}, h("p", { class: "hint" }, "Загружаем…"));
    api.application(d.appId!).then((app) => host.replaceChildren(docsBlock(app, () => render()))).catch((e) => showErrors(root, e));
    return h("div", {},
      h("h2", {}, "Документы"),
      h("p", {}, "Сведения из ЕГРЮЛ, ФНС и бюро кредитных историй банк получит сам. Загрузите только то, что есть у вас."),
      host, nav());
  }

  // --- Шаг 5: проверка и отправка
  function stepReview(): HTMLElement {
    const p = product();
    const purpose = cat.purposes.find((x) => x.code === d.purpose)?.title ?? "—";
    const rows: [string, string][] = [
      ["Продукт", p.name], ["Цель", purpose], ["Сумма", money(d.amount)], ["Срок", months(d.term)],
      ["Выручка за 2025 год", money(d.revenue_last)], ["Выручка за 2024 год", money(d.revenue_prev)],
      ["Платежи по текущим кредитам", money(d.debt)],
    ];
    if (p.requires_collateral) rows.push(["Залог", `${d.collateral_type ?? "—"}, ${money(d.collateral_value)}`]);
    return h("div", {},
      h("h2", {}, "Проверьте заявку"),
      h("dl", { class: "summary" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
      h("p", { class: "hint" }, "Отправляя заявку, вы соглашаетесь на запрос сведений в бюро кредитных историй и государственных реестрах."),
      h("div", { class: "wizard-nav" },
        h("button", { type: "button", class: "btn btn-ghost", onclick: () => { step--; render(); } }, "Назад"),
        actionButton("Отправить заявку", async () => {
          try {
            clearErrors(root);
            await api.submit(d.appId!);
            toast("Заявка отправлена");
            go(`#/applications/${d.appId}`);
          } catch (e) { showErrors(root, e); }
        })));
  }

  function nav(save?: () => void, persist?: () => Promise<void>): HTMLElement {
    return h("div", { class: "wizard-nav" },
      step > 0 ? h("button", { type: "button", class: "btn btn-ghost", onclick: () => { save?.(); step--; render(); } }, "Назад") : h("span"),
      actionButton("Далее", async () => {
        save?.();
        try {
          clearErrors(root);
          if (persist) await persist();
          step++; render();
        } catch (e) { showErrors(root, e); }
      }));
  }

  render();
  return () => clearTimeout(calcTimer);
}

function clamp(n: number, lo: number, hi: number): number { return Math.min(hi, Math.max(lo, n)); }

// ============ Документы ============

function docsBlock(app: Application, onChange: () => void): HTMLElement {
  const types = catalogCache?.documents ?? {};
  const required = app.required_documents;
  const select = h("select", { class: "input" }, Object.entries(types).map(([code, title]) =>
    h("option", { value: code, selected: required.find((r) => !r.uploaded)?.code === code }, title)));
  const file = h("input", { type: "file", class: "input", accept: ".pdf,.jpg,.jpeg,.png,.csv,.xlsx,.xls" });
  return h("div", { class: "docs" },
    required.length ? h("ul", { class: "checklist" }, required.map((r) =>
      h("li", { class: r.uploaded ? "ok" : "" }, r.uploaded ? "Загружено: " : "Нужно: ", r.title)))
      : app.status.code === "DRAFT" ? h("p", { class: "notice" }, "Для этой суммы обязательных документов нет — можно сразу отправить заявку.") : null,
    app.documents.length ? h("ul", { class: "doc-list" }, app.documents.map((doc) =>
      h("li", {}, h("strong", {}, types[doc.doc_type] ?? doc.doc_type), ` — ${doc.filename}, ${Math.ceil(doc.size / 1024)} КБ`))) : null,
    h("div", { class: "upload-row" },
      field("Тип документа", select, undefined, "doc_type"),
      field("Файл", file, "PDF, JPG, PNG, CSV или XLSX до 10 МБ", "file"),
      // Пустая подпись над кнопкой выравнивает её по полям ввода, а не по подсказке под ними
      h("div", { class: "field upload-action" }, h("span", { class: "label-spacer", "aria-hidden": "true" }, "\u00a0"),
        actionButton("Загрузить", async () => {
          const f = file.files?.[0];
          if (!f) { toast("Выберите файл", "error"); return; }
          try { await api.upload(app.id, select.value, f); toast("Документ загружен"); onChange(); }
          catch (e) { showErrors(file.closest(".docs") as HTMLElement, e); }
        }, "btn btn-secondary"))));
}

// ============ Карточка заявки ============

export async function applicationPage(root: HTMLElement, user: User, id: string): Promise<Cleanup> {
  await catalog();
  let timer = 0;
  let lastKey = "";
  let busy = false;
  let stopped = false;

  const load = async () => {
    if (busy || stopped) return;
    const [app, events] = await Promise.all([api.application(id), api.events(id)]);
    if (stopped) return;
    const key = `${app.version}:${events.length}`;
    // Не перерисовываем, пока пользователь вводит данные, и если ничего не изменилось
    const editing = root.contains(document.activeElement) && document.activeElement?.matches("input, textarea, select");
    if (key !== lastKey && !editing) { lastKey = key; render(app, events); }
    clearTimeout(timer);
    timer = window.setTimeout(() => load().catch(() => undefined), app.status.waiting_for === "bank" ? 1500 : 6000);
  };

  const act = async (fn: () => Promise<unknown>, done: string) => {
    busy = true;
    try { clearErrors(root); await fn(); toast(done); lastKey = ""; }
    catch (e) { showErrors(root, e); }
    finally { busy = false; await load(); }
  };

  function render(app: Application, events: AppEvent[]): void {
    const s = app.status;
    mount(root,
      h("a", { class: "back", href: "#/" }, "Все заявки"),
      h("header", { class: "app-head" },
        h("div", {}, h("h1", {}, `${app.product_name}, ${moneyShort(app.amount)}`),
          h("p", { class: "lead" }, `Заявка ${app.number} · ${months(app.term_months)}`)),
        statusPill(s.code, s.title)),
      tracker(s),
      h("section", { class: `now now-${s.waiting_for}`, "aria-live": "polite" },
        h("h2", {}, s.title), h("p", {}, s.now), h("p", { class: "now-next" }, s.next_step)),
      h("div", { class: "form-error", role: "alert", hidden: true }),
      actions(app),
      h("div", { class: "grid-main" },
        h("section", {}, h("h2", {}, "Что происходило"), timeline(events)),
        h("section", {}, h("h2", {}, "Параметры заявки"), params(app))));
  }

  function actions(app: Application): HTMLElement | null {
    const a = app.status.allowed_actions;
    const code = app.status.code;
    const blocks: HTMLElement[] = [];

    if (code === "DRAFT") {
      blocks.push(h("div", { class: "panel" }, h("h3", {}, "Документы"), docsBlock(app, () => { lastKey = ""; load(); }),
        h("div", { class: "row-actions" }, actionButton("Отправить заявку", () => act(() => api.submit(app.id), "Заявка отправлена")))));
    }
    if (code === "NEEDS_INFO" && app.info_request) blocks.push(infoRequestBlock(app));
    if ((code === "APPROVED" || code === "COUNTER_OFFER") && app.offer) blocks.push(offerBlock(app));
    if (code === "OFFER_ACCEPTED" && app.offer) blocks.push(signBlock(app));
    if (code === "ISSUED" && app.offer) blocks.push(issuedBlock(app));
    if (code === "REJECTED") blocks.push(rejectedBlock(app));
    if (app.score && ["APPROVED", "COUNTER_OFFER", "OFFER_ACCEPTED", "SIGNED", "ISSUED"].includes(code)) blocks.push(factorsBlock(app));
    if (code === "MANUAL_REVIEW") blocks.push(h("div", { class: "panel" }, h("h3", {}, "Можно ускорить"),
      h("p", {}, "Если у вас есть отчётность или выписки из других банков — загрузите их, специалист увидит сразу."),
      docsBlock(app, () => { lastKey = ""; load(); })));
    if (a.includes("cancel")) blocks.push(h("div", { class: "row-actions subtle" },
      actionButton("Отменить заявку", async () => {
        if (confirm("Отменить заявку? Это действие нельзя вернуть.")) await act(() => api.cancel(app.id, "Отменено клиентом"), "Заявка отменена");
      }, "btn btn-link")));
    return blocks.length ? h("div", { class: "actions" }, blocks) : null;
  }

  function infoRequestBlock(app: Application): HTMLElement {
    const req = app.info_request!;
    const msg = h("textarea", { class: "input", rows: 2, maxlength: 2000, placeholder: "Комментарий для банка (необязательно)" });
    const needsRevenue = (req.items ?? []).some((i) => i.field === "revenue_last_year");
    const rev = moneyInput("revenue_last_year", app.revenue_last_year);
    return h("div", { class: "panel panel-attention" },
      h("h3", {}, req.requested_by_type === "ANALYST" ? "Специалист банка просит уточнить" : "Банку не хватает сведений"),
      h("p", {}, req.message),
      h("ul", { class: "checklist" }, (req.items ?? []).map((i) => h("li", {}, i.message))),
      docsBlock(app, () => { lastKey = ""; load(); }),
      needsRevenue ? field("Выручка за 2025 год", rev, "Исправьте, если ошиблись, или оставьте и приложите отчётность", "revenue_last_year") : null,
      field("Ответ", msg, undefined, "message"),
      h("div", { class: "row-actions" }, actionButton("Отправить ответ", () => act(() =>
        api.infoResponse(app.id, { message: msg.value || null, revenue_last_year: needsRevenue ? readMoney(rev) : null }), "Ответ отправлен"))));
  }

  function offerBlock(app: Application): HTMLElement {
    const o = app.offer!;
    const counter = app.status.code === "COUNTER_OFFER";
    // Запрошенные условия считаем по той же ставке — так видно, как изменился платёж
    const askedPlan = app.amount && app.term_months ? schedule(app.amount, o.rate, app.term_months) : [];
    const askedPayment = askedPlan[0]?.payment ?? null;
    const askedOver = askedPlan.length ? askedPlan.reduce((s, r) => s + r.payment, 0) - (app.amount ?? 0) : null;
    const row = (label: string, asked: string, offered: string) => {
      const changed = counter && asked !== "—" && asked !== offered;
      return h("tr", { class: changed ? "changed" : "" }, h("th", { scope: "row" }, label),
        counter ? h("td", {}, asked) : null, h("td", {}, offered));
    };
    return h("div", { class: "panel panel-offer" },
      h("h3", {}, counter ? "Встречное предложение банка" : "Условия одобрены"),
      app.decision?.client_explanation ? h("p", {}, app.decision.client_explanation) : null,
      h("table", { class: "offer-table" },
        counter ? h("thead", {}, h("tr", {}, h("th"), h("th", { scope: "col" }, "Вы просили"), h("th", { scope: "col" }, "Банк предлагает"))) : null,
        h("tbody", {},
          row("Сумма", money(app.amount), money(o.amount)),
          row("Срок", months(app.term_months), months(o.term_months)),
          row("Ставка", `${o.rate.toLocaleString("ru-RU")}% годовых`, `${o.rate.toLocaleString("ru-RU")}% годовых`),
          row("Платёж в месяц", money(askedPayment), money(o.monthly_payment)),
          row("Переплата за весь срок", money(askedOver), money(o.overpayment)))),
      h("div", { class: "row-actions" }, actionButton(counter ? "Принять новые условия" : "Принять условия",
        () => act(() => api.accept(app.id), "Условия приняты — договор готов"))));
  }

  function signBlock(app: Application): HTMLElement {
    const o = app.offer!;
    const agree = h("input", { type: "checkbox", id: "agree" });
    const inn = h("input", { class: "input", inputmode: "numeric", maxlength: 12, autocomplete: "off" });
    return h("div", { class: "panel panel-attention" },
      h("h3", {}, `Кредитный договор ${app.contract_number}`),
      h("dl", { class: "summary" },
        h("dt", {}, "Заёмщик"), h("dd", {}, user.company?.name ?? ""),
        h("dt", {}, "Сумма"), h("dd", {}, money(o.amount)), h("dt", {}, "Срок"), h("dd", {}, months(o.term_months)),
        h("dt", {}, "Ставка"), h("dd", {}, `${o.rate}% годовых`), h("dt", {}, "Ежемесячный платёж"), h("dd", {}, money(o.monthly_payment))),
      scheduleTable(o.amount, o.rate, o.term_months, 3),
      h("label", { class: "check" }, agree, " Я ознакомился с условиями договора и графиком платежей"),
      field("Для подписи введите ИНН компании", inn, "Подписание смоделировано: в реальном продукте здесь — простая электронная подпись", "confirmation_inn"),
      h("div", { class: "row-actions" }, actionButton("Подписать договор", async () => {
        if (!agree.checked) { toast("Отметьте согласие с условиями", "error"); return; }
        await act(() => api.sign(app.id, inn.value), "Договор подписан");
      })));
  }

  function issuedBlock(app: Application): HTMLElement {
    const o = app.offer!;
    return h("div", { class: "panel panel-good" },
      h("h3", {}, `${money(o.amount)} на счёте компании`),
      h("p", {}, `Договор ${app.contract_number}. Первый платёж — ${money(o.monthly_payment)} через месяц.`),
      h("details", {}, h("summary", {}, "График платежей"), scheduleTable(o.amount, o.rate, o.term_months)));
  }

  function rejectedBlock(app: Application): HTMLElement {
    const sc = app.score as { stop_factors?: { title: string; text: string }[]; factors?: { title: string; impact: string; text: string }[] } | null;
    const negatives = sc?.factors?.filter((f) => f.impact === "negative") ?? [];
    return h("div", { class: "panel" },
      h("h3", {}, "Почему банк отказал"),
      app.decision?.client_explanation ? h("p", {}, app.decision.client_explanation) : null,
      (sc?.stop_factors?.length || negatives.length) ? h("ul", { class: "factors" },
        [...(sc?.stop_factors ?? []).map((f) => h("li", { class: "negative" }, h("strong", {}, f.title), h("span", {}, f.text))),
          ...negatives.map((f) => h("li", { class: "negative" }, h("strong", {}, f.title), h("span", {}, f.text)))]) : null,
      h("p", { class: "hint" }, "Повторную заявку стоит подавать, когда ситуация по этим пунктам изменится."));
  }

  function factorsBlock(app: Application): HTMLElement {
    const sc = app.score as { grade: string; factors: { title: string; impact: string; text: string }[] };
    return h("details", { class: "panel" },
      h("summary", {}, `Как банк оценил заявку — рейтинг ${sc.grade}`),
      h("ul", { class: "factors" }, sc.factors.map((f) =>
        h("li", { class: f.impact }, h("strong", {}, f.title), h("span", {}, f.text)))));
  }

  try { await load(); }
  catch (e) {
    if (e instanceof ApiError && e.status === 404) mount(root, emptyState("Заявка не найдена", "Возможно, ссылка устарела.", h("a", { class: "btn btn-secondary", href: "#/" }, "На главную")));
    else throw e;
  }
  return () => { stopped = true; clearTimeout(timer); };
}

function timeline(events: AppEvent[]): HTMLElement {
  return h("ol", { class: "timeline" }, [...events].reverse().map((e) =>
    h("li", { class: `tl-${e.kind.toLowerCase()} tl-${e.actor_type.toLowerCase()}` },
      h("time", { datetime: e.created_at }, dateTime(e.created_at)),
      h("span", {}, e.message))));
}

function params(app: Application): HTMLElement {
  const purpose = catalogCache?.purposes.find((p) => p.code === app.purpose)?.title ?? "—";
  return h("dl", { class: "summary" },
    h("dt", {}, "Цель"), h("dd", {}, purpose, app.purpose_comment ? ` — ${app.purpose_comment}` : ""),
    h("dt", {}, "Сумма"), h("dd", {}, money(app.amount)), h("dt", {}, "Срок"), h("dd", {}, months(app.term_months)),
    h("dt", {}, "Выручка за 2025 год"), h("dd", {}, money(app.revenue_last_year)),
    h("dt", {}, "Платежи по кредитам"), h("dd", {}, money(app.monthly_debt_payments)),
    h("dt", {}, "Документы"), h("dd", {}, app.documents.length ? app.documents.map((d) => d.filename).join(", ") : "нет"));
}

export function scheduleTable(amount: number, rate: number, term: number, limit?: number): HTMLElement {
  const rows = schedule(amount, rate, term);
  const shown = limit ? rows.slice(0, limit) : rows;
  return h("div", { class: "table-wrap" }, h("table", { class: "schedule" },
    h("thead", {}, h("tr", {}, ["№", "Платёж", "Основной долг", "Проценты", "Остаток"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, shown.map((r) => h("tr", {}, h("td", {}, r.n), h("td", {}, money(r.payment)), h("td", {}, money(r.principal)),
      h("td", {}, money(r.interest)), h("td", {}, money(r.rest))))),
    limit && rows.length > limit ? h("tfoot", {}, h("tr", {}, h("td", { colspan: 5 }, `…и ещё ${rows.length - limit} платежей`))) : null));
}
