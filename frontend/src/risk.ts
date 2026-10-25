// Рабочее место риск-менеджера: действующая кредитная политика, состояние конвейера и журнал аудита.
// Риск-менеджер ничего не решает по заявкам — он контролирует параметры и следы решений.

import { api, AuditEvent, Policy, User } from "./api.js";
import { Cleanup } from "./client.js";
import { dateTime, emptyState, h, mount, moneyShort } from "./ui.js";

const INDUSTRIES: Record<string, string> = {
  "01": "Сельское хозяйство", "10": "Пищевое производство", "41": "Строительство зданий", "43": "Строительные работы",
  "46": "Оптовая торговля", "47": "Розничная торговля", "49": "Грузоперевозки", "52": "Складская логистика",
  "56": "Общепит", "62": "Разработка ПО", "63": "IT-услуги", "68": "Операции с недвижимостью",
  "69": "Юридические и бухгалтерские услуги", "86": "Здравоохранение",
};
const RISK_TITLE = { low: "низкий", medium: "средний", high: "повышенный" } as const;
const ACTOR = { CLIENT: "Клиент", SYSTEM: "Система", ANALYST: "Аналитик" } as Record<string, string>;
const JOB_TITLE: Record<string, string> = { DONE: "выполнено", PENDING: "в очереди", RUNNING: "в работе", FAILED: "с ошибкой" };

const pct = (x: number, digits = 0) => `${(x * 100).toLocaleString("ru-RU", { maximumFractionDigits: digits })}%`;
const num = (x: number) => x.toLocaleString("ru-RU");

export async function riskPage(root: HTMLElement, user: User): Promise<Cleanup> {
  let stopped = false;
  let timer = 0;
  let hiddenOnly = false;
  let limit = 15;
  let lastKey = "";
  const [policy, jobs] = await Promise.all([api.policy(), api.jobs()]);

  const auditBox = h("section", { class: "panel" });
  const jobsBox = h("div", {});

  mount(root,
    h("section", { class: "hero" },
      h("div", {}, h("h1", {}, "Политика и аудит"),
        h("p", { class: "lead" }, `${user.full_name}, ${user.position?.toLowerCase() ?? ""} · контроль без права решения`)),
      h("div", { class: "kpis" },
        kpi(policy.policy_version, "кредитная политика"),
        kpi(policy.scorecard_version, "скоринговая карта"),
        kpi(`до ${moneyShort(policy.auto_decision_limit)}`, "решает автоматически"))),
    h("p", { class: "notice" }, "Решения по заявкам принимает кредитный аналитик. Здесь — параметры, по которым работает конвейер, ",
      "и неизменяемый журнал всех действий: по нему любое решение можно восстановить и проверить."),
    gradesBlock(policy),
    productsBlock(policy),
    industriesBlock(policy),
    jobsBox,
    auditBox);
  renderJobs(jobs);

  function renderJobs(j: Awaited<ReturnType<typeof api.jobs>>): void {
    const order = ["DONE", "PENDING", "RUNNING", "FAILED"];
    mount(jobsBox, h("section", { class: "panel" },
      h("h2", {}, "Очередь задач конвейера"),
      h("div", { class: "kpis" }, order.map((k) => kpi(num(j.counts[k] ?? 0), JOB_TITLE[k]))),
      j.failed.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Задача", "Заявка", "Попыток", "Ошибка"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, j.failed.map((f) => h("tr", {},
          h("td", {}, `${f.kind} #${f.id}`), h("td", {}, h("a", { href: `#/review/${f.application_id}` }, "открыть")),
          h("td", {}, String(f.attempts)), h("td", { class: "neg" }, f.error ?? "—"))))))
        : h("p", { class: "hint" }, "Задач с ошибкой нет: каждая заявка дошла до решения или ждёт своего шага.")));
  }

  function renderAudit(events: AuditEvent[]): void {
    const filter = h("div", { class: "seg", role: "group", "aria-label": "Фильтр журнала" },
      segButton("Все события", !hiddenOnly, () => { hiddenOnly = false; reload(); }),
      segButton("Внутренние", hiddenOnly, () => { hiddenOnly = true; reload(); }));
    mount(auditBox,
      h("div", { class: "audit-head" }, h("h2", {}, "Журнал аудита"), filter),
      h("p", { class: "hint" }, `Последние события по всем заявкам, новые сверху. Записи не редактируются и не удаляются.`),
      events.length ? h("div", { class: "table-wrap" }, h("table", { class: "audit" },
        h("thead", {}, h("tr", {}, ["Время", "Заявка", "Кто", "Событие", "Клиент видит"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, events.map((e) => h("tr", {},
          h("td", { class: "nowrap" }, dateTime(e.created_at)),
          h("td", {}, h("a", { href: `#/review/${e.application_id}` }, e.application_number), h("div", { class: "hint" }, e.company_name)),
          h("td", {}, e.actor_name ?? ACTOR[e.actor_type] ?? e.actor_type, e.actor_name ? h("div", { class: "hint" }, ACTOR[e.actor_type] ?? "") : null),
          h("td", {}, e.message),
          h("td", {}, e.visible_to_client ? "да" : h("span", { class: "pill pill-neutral" }, "нет")))))))
        : null,
      events.length >= limit && limit < 100 ? h("button", { type: "button", class: "btn btn-secondary audit-more",
        onclick: () => { limit = 100; reload(); } }, "Показать ещё") : null,
      events.length ? null : emptyState("Событий нет", hiddenOnly
          ? "Сюда попадают события, которые клиент не видит: кто из аналитиков взял заявку в работу и сбои внешних источников. Пока таких не было."
          : "Журнал пуст."));
  }

  // Журнал и очередь задач обновляются раз в 10 секунд; ответ после ухода со страницы отбрасывается
  async function load(): Promise<void> {
    const [events, j] = await Promise.all([api.audit(hiddenOnly, limit), api.jobs()]);
    if (stopped) return;
    const key = JSON.stringify([hiddenOnly, limit, events.map((e) => e.id), j]);
    if (key !== lastKey) { lastKey = key; renderAudit(events); renderJobs(j); }
  }
  function schedule(): void {
    timer = window.setTimeout(() => load().catch(() => undefined).finally(() => { if (!stopped) schedule(); }), 10000);
  }
  function reload(): void { clearTimeout(timer); load().catch(() => undefined).finally(() => { if (!stopped) schedule(); }); }

  await load();
  schedule();
  return () => { stopped = true; clearTimeout(timer); };
}

function kpi(value: string, label: string): HTMLElement {
  return h("div", { class: "kpi" }, h("strong", {}, value), h("span", {}, label));
}

function segButton(label: string, active: boolean, onclick: () => void): HTMLButtonElement {
  return h("button", { type: "button", class: `seg-btn ${active ? "active" : ""}`, "aria-pressed": String(active), onclick }, label);
}

function gradesBlock(p: Policy): HTMLElement {
  const rows = [...p.grades].sort((a, b) => b.min_score - a.min_score);
  return h("section", { class: "panel" },
    h("h2", {}, "Как рейтинг превращается в условия"),
    h("p", { class: "hint" }, `Баллы = ${p.base_score} + вклад факторов скоринга. Рейтинг E и стоп-факторы — отказ; `,
      `рейтинг D и суммы больше ${moneyShort(p.auto_decision_limit)} — ручное рассмотрение.`),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Рейтинг", "Баллов от", "Вероятность дефолта", "Надбавка к ставке", "Коэффициент лимита"].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", {}, rows.map((g, i) => h("tr", {},
        h("td", {}, h("span", { class: `grade grade-${g.grade}` }, g.grade)),
        h("td", {}, i === rows.length - 1 ? `ниже ${rows[i - 1]?.min_score ?? ""}` : num(g.min_score)),
        h("td", {}, pct(g.pd, 1)),
        h("td", {}, g.grade === "E" ? "—" : `+${num(p.grade_rate_premium[g.grade] ?? 0)} п.п.`),
        h("td", {}, g.grade === "E" ? "отказ" : `× ${num(p.grade_limit_multiplier[g.grade] ?? 0)}`)))))),
    h("dl", { class: "summary compact risk-params" },
      h("dt", {}, "Лимит"), h("dd", {}, "меньшее из: максимум продукта; доля выручки × коэффициент рейтинга; платёжеспособность"),
      h("dt", {}, "Платёжеспособность"), h("dd", {}, `денежный поток покрывает платежи по долгам с запасом: DSCR ≥ ${num(p.min_dscr)}`),
      h("dt", {}, "Встречное предложение"), h("dd", {}, `сначала больший срок, затем меньшая сумма — не меньше ${pct(p.counter_min_share)} запрошенного`)));
}

function productsBlock(p: Policy): HTMLElement {
  return h("section", { class: "panel" },
    h("h2", {}, "Продукты"),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Продукт", "Базовая ставка", "Доля выручки в лимите", "Сумма", "Срок, мес."].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", {}, Object.values(p.products).map((x) => h("tr", {},
        h("td", {}, x.name), h("td", {}, `${num(x.base_rate)}%`), h("td", {}, pct(x.revenue_share)),
        h("td", { class: "nowrap" }, `${moneyShort(x.min_amount)} – ${moneyShort(x.max_amount)}`),
        h("td", {}, `${x.min_term}–${x.max_term}`)))))));
}

function industriesBlock(p: Policy): HTMLElement {
  const order = { low: 0, medium: 1, high: 2 };
  const rows = Object.entries(p.industry_risk).sort(([, a], [, b]) => order[a.risk] - order[b.risk] || b.margin - a.margin);
  const half = Math.ceil(rows.length / 2);
  const table = (part: typeof rows) => h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["ОКВЭД", "Отрасль", "Риск", "Маржа"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, part.map(([code, r]) => h("tr", {},
      h("td", {}, code), h("td", {}, INDUSTRIES[code] ?? "—"),
      h("td", {}, h("span", { class: `risk risk-${r.risk}` }, RISK_TITLE[r.risk])), h("td", {}, pct(r.margin)))))));
  return h("section", { class: "panel" },
    h("h2", {}, "Отраслевой риск"),
    h("p", { class: "hint" }, "Влияет на баллы скоринга и на платёжеспособность: маржа — доля выручки, которая остаётся на обслуживание долга. Прочие отрасли: средний риск, 9%."),
    h("div", { class: "two-col risk-cols" }, table(rows.slice(0, half)), table(rows.slice(half))));
}