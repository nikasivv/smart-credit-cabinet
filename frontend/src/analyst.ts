// Рабочее место кредитного аналитика.

import { AnalystCard, api, QueueItem, User } from "./api.js";
import { catalog, Cleanup, collateralText } from "./client.js";
import {
  actionButton, clearErrors, dateTime, emptyState, field, h, money, moneyInput, moneyShort, months, mount, readMoney,
  schedule, showErrors, statusPill, toast,
} from "./ui.js";

const SCOPES: [string, string, string][] = [
  ["manual", "Ждут решения специалиста", "Заявки, которые конвейер не смог решить автоматически: здесь решение за вами."],
  ["active", "Все незавершённые", "Все заявки в процессе: и у специалиста, и в автоматической проверке, и ждущие действий клиента (уточнения, подпись)."],
  ["all", "Все заявки", "Полная история, включая выданные, отклонённые и отменённые."],
];

type Chaos = Awaited<ReturnType<typeof api.chaos>>;

export async function queuePage(root: HTMLElement, user: User, scope: string): Promise<Cleanup> {
  let timer = 0;
  let stopped = false;
  let lastKey = "";
  let lastChaos = "";
  const chaosBox = h("div", { class: "chaos" });

  // Опрос раз в 5 секунд. Ответ, пришедший после ухода со страницы, отбрасывается;
  // страница перерисовывается, только если данные изменились — иначе экран не трогаем.
  const load = async () => {
    const [items, stats, chaos] = await Promise.all([api.queue(scope), api.stats(), api.chaos().catch(() => null)]);
    if (stopped) return;
    // Время ожидания меняется каждую минуту — его обновляем точечно, без перерисовки таблицы
    const key = JSON.stringify([items.map((i) => ({ ...i, waiting_minutes: null })), stats]);
    if (key !== lastKey) { lastKey = key; render(items, stats); }
    else items.forEach((i) => {
      const cell = root.querySelector<HTMLElement>(`[data-wait="${i.id}"]`);
      const text = i.waiting_minutes === null ? "—" : waitText(i.waiting_minutes);
      if (cell && cell.textContent !== text) cell.textContent = text;
    });
    const chaosKey = JSON.stringify(chaos);
    if (chaosKey !== lastChaos) { lastChaos = chaosKey; renderChaos(chaos); }
    timer = window.setTimeout(() => load().catch(() => {
      if (!stopped) timer = window.setTimeout(() => load().catch(() => undefined), 10000);
    }), 5000);
  };

  function render(items: QueueItem[], stats: Awaited<ReturnType<typeof api.stats>>): void {
    const manual = stats.by_status["MANUAL_REVIEW"]?.count ?? 0;
    const current = SCOPES.find(([code]) => code === scope)!;
    mount(root,
      h("section", { class: "hero" },
        h("div", {}, h("h1", {}, "Кредитный конвейер"),
          h("p", { class: "lead" }, `${user.full_name}, ${user.position?.toLowerCase() ?? ""}`)),
        h("div", { class: "kpis" },
          kpi(String(manual), "ждут решения"),
          kpi(stats.auto_share === null ? "—" : `${Math.round(stats.auto_share * 100)}%`, "решений принято автоматически"),
          kpi(String(stats.by_status["ISSUED"]?.count ?? 0), "кредитов выдано"))),
      h("nav", { class: "tabs", "aria-label": "Очередь" }, SCOPES.map(([code, title]) =>
        h("a", { href: `#/queue/${code}`, class: code === scope ? "active" : "", "aria-current": code === scope ? "page" : null }, title))),
      h("p", { class: "hint tabs-note" }, current[2]),
      items.length ? h("div", { class: "table-wrap" }, h("table", { class: "queue" },
        h("thead", {}, h("tr", {}, ["Заявка", "Компания", "Продукт и сумма", "Рейтинг", "Статус", "Ожидает", "Ответственный"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, items.map((i) => h("tr", { tabindex: 0, onclick: () => (location.hash = `#/review/${i.id}`),
          onkeydown: (e: Event) => { if ((e as KeyboardEvent).key === "Enter") location.hash = `#/review/${i.id}`; } },
          h("td", {}, h("a", { href: `#/review/${i.id}` }, i.number)),
          h("td", {}, h("div", {}, i.company_name), h("div", { class: "hint" }, `ИНН ${i.company_inn}`)),
          h("td", {}, h("div", {}, i.product_name), h("div", { class: "hint" }, `${moneyShort(i.amount)} · ${months(i.term_months)}`)),
          h("td", {}, i.grade ? h("span", { class: `grade grade-${i.grade}` }, i.grade) : "—", i.score ? h("span", { class: "hint" }, ` ${i.score}`) : null),
          h("td", {}, statusPill(i.status, i.status_title), i.reasons.length ? h("div", { class: "hint" }, i.reasons[0]) : null),
          h("td", { "data-wait": i.id }, i.waiting_minutes === null ? "—" : waitText(i.waiting_minutes)),
          h("td", {}, i.analyst_name ?? h("span", { class: "hint" }, "не назначен"))))))) :
        emptyState("Очередь пуста", scope === "manual" ? "Все заявки обработаны автоматически или уже решены." : "Заявок пока нет."),
      chaosBox);
  }

  function renderChaos(c: Chaos | null): void {
    if (!c) { chaosBox.replaceChildren(); chaosBox.hidden = true; return; }
    chaosBox.hidden = false;
    const on = c.fail_rate > 0;
    chaosBox.replaceChildren(
      h("h2", {}, "Проверка отказоустойчивости"),
      h("p", {}, on ? `Сейчас внешние источники отвечают ошибкой на ${Math.round(c.fail_rate * 100)}% запросов. ` +
        "Конвейер повторяет запрос, а если источник так и не ответил — передаёт заявку специалисту вместо зависания."
        : "Внешние источники работают штатно. Включите сбои, чтобы увидеть, как конвейер переживает недоступность ЕГРЮЛ, ФНС и БКИ."),
      actionButton(on ? "Вернуть штатный режим" : "Включить сбои источников", async () => {
        try {
          const next = await api.setChaos(on ? 0 : 1);
          toast(on ? "Источники работают штатно" : "Сбои включены");
          lastChaos = JSON.stringify({ ...c, fail_rate: next.fail_rate });
          renderChaos({ ...c, fail_rate: next.fail_rate });
        } catch (e) { showErrors(chaosBox, e); }
      }, "btn btn-secondary"));
  }

  await load();
  return () => { stopped = true; clearTimeout(timer); };
}

// Ширина задаётся через CSSOM, а не атрибутом style — это совместимо со строгой CSP
function bar(points: number, max: number): HTMLElement {
  const el = h("span", { class: `bar ${points >= 0 ? "bar-pos" : "bar-neg"}` });
  el.style.setProperty("--w", `${(Math.abs(points) / max) * 50}%`);
  return el;
}

function kpi(value: string, label: string): HTMLElement {
  return h("div", { class: "kpi" }, h("strong", {}, value), h("span", {}, label));
}

function waitText(min: number): string {
  if (min < 60) return `${min} мин`;
  if (min < 60 * 24) return `${Math.floor(min / 60)} ч ${min % 60} мин`;
  return `${Math.floor(min / 60 / 24)} дн`;
}

// ============ Карточка заявки для аналитика ============

export async function reviewPage(root: HTMLElement, user: User, id: string): Promise<Cleanup> {
  const cat = await catalog();
  let timer = 0;
  let stopped = false;
  let lastKey = "";

  const load = async () => {
    const c = await api.card(id);
    if (stopped) return;
    const key = `${c.application.version}:${c.events.length}`;
    const editing = root.contains(document.activeElement) && document.activeElement?.matches("input, textarea, select");
    if (key !== lastKey && !editing) { lastKey = key; render(c); }
    clearTimeout(timer);
    timer = window.setTimeout(() => load().catch(() => undefined), 4000);
  };

  function render(c: AnalystCard): void {
    const app = c.application;
    const canDecide = app.status.code === "MANUAL_REVIEW" && user.role === "ANALYST";
    mount(root,
      h("a", { class: "back", href: "#/queue/manual" }, "Очередь"),
      h("header", { class: "app-head" },
        h("div", {}, h("h1", {}, c.company.name),
          h("p", { class: "lead" }, `Заявка ${app.number} · ${app.product_name} · ${moneyShort(app.amount)} на ${months(app.term_months)}`)),
        statusPill(app.status.code, app.status.title)),
      h("div", { class: "form-error", role: "alert", hidden: true }),
      h("div", { class: "review-grid" },
        h("div", { class: "review-main" },
          summaryBlock(c),
          scoringBlock(c),
          sourcesBlock(c),
          h("section", { class: "panel" }, h("h2", {}, "Журнал"), h("ol", { class: "timeline" }, [...c.events].reverse().map((e) =>
            h("li", { class: `tl-${e.kind.toLowerCase()} tl-${e.actor_type.toLowerCase()}` },
              h("time", {}, dateTime(e.created_at)), h("span", {}, `${actorName(e.actor_type)}: ${e.message}`)))))),
        h("aside", { class: "review-side" },
          applicantBlock(c),
          canDecide ? decisionBlock(c) : app.status.code === "MANUAL_REVIEW"
            ? h("div", { class: "panel" }, h("p", {}, "Решение принимает кредитный аналитик.")) : outcomeBlock(c))));
  }

  function actorName(t: string): string { return { CLIENT: "Клиент", SYSTEM: "Система", ANALYST: "Аналитик" }[t] ?? t; }

  function summaryBlock(c: AnalystCard): HTMLElement {
    return h("section", { class: "panel panel-attention" }, h("h2", {}, "На что обратить внимание"),
      h("ul", { class: "checklist" }, c.summary.map((s) => h("li", {}, s))),
      (c.decision?.reasons as string[] | undefined)?.length ? h("p", { class: "hint" }, `Причина маршрутизации: ${(c.decision!.reasons as string[]).join("; ")}`) : null);
  }

  function scoringBlock(c: AnalystCard): HTMLElement {
    const s = c.scoring;
    if (!s) return h("section", { class: "panel" }, h("h2", {}, "Скоринг"), h("p", {}, "Скоринг не выполнялся: данные внешних источников не получены."));
    const lim = (c.decision?.limits ?? {}) as Record<string, number>;
    const max = Math.max(...(s.factors as { points: number }[]).map((f) => Math.abs(f.points)), 1);
    return h("section", { class: "panel" },
      h("div", { class: "score-head" },
        h("h2", {}, "Скоринг"), h("span", { class: `grade grade-${s.grade} grade-lg` }, s.grade),
        h("span", {}, `${s.score} баллов · вероятность дефолта ≈ ${(s.pd * 100).toFixed(1)}% · ${s.version}`)),
      (s.stop_factors as { title: string }[]).length ? h("p", { class: "notice notice-bad" }, "Стоп-факторы: ", (s.stop_factors as { title: string }[]).map((x) => x.title).join(", ")) : null,
      h("ul", { class: "bars" }, (s.factors as { title: string; value: string; points: number }[]).map((f) =>
        h("li", {},
          h("span", { class: "bar-label" }, f.title, h("span", { class: "hint" }, ` ${f.value}`)),
          h("span", { class: "bar-track" }, bar(f.points, max)),
          h("span", { class: "bar-points" }, f.points > 0 ? `+${f.points}` : String(f.points))))),
      lim.final !== undefined ? h("dl", { class: "summary compact" },
        h("dt", {}, "Лимит по выручке"), h("dd", {}, money(lim.by_revenue)),
        h("dt", {}, "Лимит по платёжеспособности (DSCR ≥ 1,25)"), h("dd", {}, money(lim.by_capacity)),
        h("dt", {}, "Максимум продукта"), h("dd", {}, money(lim.product_max)),
        h("dt", {}, "Ставка для рейтинга"), h("dd", {}, `${lim.rate}%`)) : null);
  }

  function sourcesBlock(c: AnalystCard): HTMLElement {
    const e = c.enrichment ?? {};
    const eg = e.egrul ?? {}, fns = e.fns ?? {}, bki = e.bki ?? {};
    const calls = (e.calls ?? []) as { source: string; ok: boolean; attempts?: number; latency_ms?: number; error?: string }[];
    return h("section", { class: "panel" }, h("h2", {}, "Данные внешних источников"),
      h("p", { class: "hint" }, calls.map((x) => `${x.source.toUpperCase()}: ${x.ok ? `ок, попыток ${x.attempts ?? 1}, ${x.latency_ms ?? 0} мс` : `ошибка — ${x.error}`}`).join(" · ") || "Не запрашивались"),
      h("div", { class: "sources" },
        h("div", {}, h("h3", {}, "ЕГРЮЛ/ЕГРИП"), h("dl", { class: "summary compact" },
          h("dt", {}, "Статус"), h("dd", {}, eg.status ?? "—"), h("dt", {}, "Регистрация"), h("dd", {}, eg.registration_date ?? "—"),
          h("dt", {}, "ОКВЭД"), h("dd", {}, `${eg.okved ?? "—"} ${eg.okved_name ?? ""}`),
          h("dt", {}, "Руководитель"), h("dd", {}, eg.director?.name ?? "—"), h("dt", {}, "Адрес"), h("dd", {}, eg.address ?? "—"))),
        h("div", {}, h("h3", {}, "ФНС"), h("dl", { class: "summary compact" },
          ...Object.entries((fns.revenue ?? {}) as Record<string, number>).flatMap(([y, v]) => [h("dt", {}, `Выручка ${y}`), h("dd", {}, money(v))]),
          h("dt", {}, "Заявлено клиентом"), h("dd", {}, money(c.application.revenue_last_year)),
          h("dt", {}, "Недоимка"), h("dd", {}, money(fns.tax_arrears ?? null)),
          h("dt", {}, "Сотрудников"), h("dd", {}, String(fns.employees ?? "—")), h("dt", {}, "Режим"), h("dd", {}, fns.tax_regime ?? "—")))),
      h("h3", {}, `Бюро кредитных историй — запросов за 30 дней: ${bki.inquiries_30d ?? "—"}`),
      (bki.obligations ?? []).length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Кредитор", "Вид", "Остаток", "Платёж/мес", "Макс. просрочка, дн"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, (bki.obligations as Record<string, any>[]).map((o) => h("tr", {},
          h("td", {}, o.creditor), h("td", {}, o.type), h("td", {}, money(o.balance)), h("td", {}, money(o.monthly_payment)),
          h("td", { class: o.max_overdue_days_12m > 0 ? "neg" : "" }, String(o.max_overdue_days_12m))))))) : h("p", {}, "Действующих обязательств нет."));
  }

  function applicantBlock(c: AnalystCard): HTMLElement {
    const app = c.application;
    const purpose = cat.purposes.find((p) => p.code === app.purpose)?.title ?? "—";
    return h("section", { class: "panel" }, h("h2", {}, "Заявка"),
      h("dl", { class: "summary compact" },
        h("dt", {}, "Заявитель"), h("dd", {}, `${c.applicant.full_name}, ${c.applicant.position ?? ""}`),
        h("dt", {}, "Цель"), h("dd", {}, purpose, app.purpose_comment ? ` — ${app.purpose_comment}` : ""),
        h("dt", {}, "Сумма и срок"), h("dd", {}, `${money(app.amount)}, ${months(app.term_months)}`),
        h("dt", {}, "Платежи по кредитам (со слов клиента)"), h("dd", {}, money(app.monthly_debt_payments)),
        app.collateral_type || app.collateral_value ? [h("dt", {}, "Залог"), h("dd", {}, collateralText(app.collateral_type, app.collateral_value))] : null,
        h("dt", {}, "Документы"), h("dd", {}, app.documents.length ? app.documents.map((d) => `${cat.documents[d.doc_type] ?? d.doc_type} (${d.filename})`).join("; ") : "нет")));
  }

  function decisionBlock(c: AnalystCard): HTMLElement {
    const app = c.application;
    const rec = c.decision?.offer as { amount: number; term_months: number; rate: number } | null | undefined;
    const product = cat.products.find((p) => p.code === app.product_code)!;
    const outcome = h("select", { class: "input" },
      h("option", { value: "APPROVED" }, "Одобрить"), h("option", { value: "COUNTER_OFFER" }, "Встречное предложение"),
      h("option", { value: "REJECTED" }, "Отказать"));
    if (c.decision?.recommended_outcome) outcome.value = c.decision.recommended_outcome;
    const amount = moneyInput("amount", rec?.amount ?? app.amount);
    const term = h("input", { class: "input", type: "number", min: product.min_term, max: product.max_term, value: rec?.term_months ?? app.term_months ?? 12 });
    const rate = h("input", { class: "input", type: "number", step: "0.1", min: 1, max: 60, value: rec?.rate ?? product.base_rate });
    const comment = h("textarea", { class: "input", rows: 3, maxlength: 2000, placeholder: "Обоснование увидит клиент" });
    const terms = h("div", { class: "terms" }, field("Сумма", amount, undefined, "amount"),
      h("div", { class: "two-col" }, field("Срок, мес.", term, undefined, "term_months"), field("Ставка, %", rate, undefined, "rate")));
    const preview = h("div", {});
    const sync = () => {
      terms.hidden = outcome.value === "REJECTED";
      const a = readMoney(amount), t = Number(term.value), r = Number(rate.value);
      if (terms.hidden || !a || !t || !r) { preview.replaceChildren(); return; }
      // В узкой колонке полный график не помещается — показываем то, что важно для решения
      const rows = schedule(a, r, t);
      const total = rows.reduce((sum, x) => sum + x.payment, 0);
      preview.replaceChildren(h("dl", { class: "summary compact terms-preview" },
        h("dt", {}, "Платёж в месяц"), h("dd", {}, money(rows[0]?.payment ?? 0)),
        h("dt", {}, "Переплата за срок"), h("dd", {}, money(Math.max(0, Math.round(total - a))))));
    };
    [outcome, term, rate].forEach((x) => x.addEventListener("change", sync));
    amount.addEventListener("change", sync);
    sync();
    const docs = h("div", { class: "doc-checks" }, Object.entries(cat.documents).map(([code, title]) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", value: code }), ` ${title}`)));
    const infoMsg = h("textarea", { class: "input", rows: 2, maxlength: 2000, placeholder: "Что нужно уточнить" });
    const scope = h("section", { class: "panel" });
    mount(scope,
      h("h2", {}, "Решение"),
      c.decision?.recommended_outcome ? h("p", { class: "hint" }, "Поля заполнены по рекомендации системы — проверьте и при необходимости измените.") : null,
      h("div", { class: "form-error", role: "alert", hidden: true }),
      c.analyst_id === null ? actionButton("Взять в работу", async () => {
        try { await api.assign(app.id); toast("Заявка закреплена за вами"); lastKey = ""; await load(); } catch (e) { showErrors(scope, e); }
      }, "btn btn-secondary take-btn") : null,
      field("Решение", outcome, undefined, "outcome"), terms, preview,
      field("Комментарий для клиента", comment, "Минимум 5 символов", "comment"),
      actionButton("Принять решение", async () => {
        clearErrors(scope);
        try {
          await api.decide(app.id, { outcome: outcome.value, comment: comment.value.trim(),
            ...(outcome.value === "REJECTED" ? {} : { amount: readMoney(amount), term_months: Number(term.value), rate: Number(rate.value) }) });
          toast("Решение сохранено"); lastKey = ""; clearTimeout(timer); await load();
        } catch (e) { showErrors(scope, e); }
      }),
      h("details", { class: "request-info" }, h("summary", {}, "Запросить у клиента документы"),
        docs, field("Сообщение клиенту", infoMsg, undefined, "message"),
        actionButton("Отправить запрос", async () => {
          const selected = [...docs.querySelectorAll<HTMLInputElement>("input:checked")].map((x) => x.value);
          try { await api.requestInfo(app.id, infoMsg.value.trim(), selected); toast("Запрос отправлен клиенту"); lastKey = ""; await load(); }
          catch (e) { showErrors(scope, e); }
        }, "btn btn-secondary")));
    return scope;
  }

  function outcomeBlock(c: AnalystCard): HTMLElement {
    const d = c.decision;
    if (!d) return h("section", { class: "panel" }, h("p", {}, "Решения пока нет."));
    const o = c.application.offer;
    return h("section", { class: "panel" }, h("h2", {}, "Решение"),
      h("p", {}, d.manual ? `Принято специалистом: ${d.manual.analyst}` : `Принято автоматически (${d.policy_version})`),
      d.client_explanation ? h("p", {}, d.client_explanation) : null,
      o ? h("p", {}, `${money(o.amount)} на ${months(o.term_months)} под ${o.rate}%`) : null);
  }

  await load();
  return () => { stopped = true; clearTimeout(timer); };
}