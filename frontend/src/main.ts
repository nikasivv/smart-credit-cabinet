import { analystDemo, clientDemo } from "./demo.js";
import { api, ApiError, hasToken, setToken, setUnauthorizedHandler, User } from "./api.js";
import { queuePage, reviewPage } from "./analyst.js";
import { applicationPage, Cleanup, dashboard, wizard } from "./client.js";
import { initTheme, themeButton } from "./theme.js";
import { actionButton, field, h, mount, showErrors } from "./ui.js";
initTheme();

const app = document.getElementById("app")!;
const header = document.getElementById("header")!;
let user: User | null = null;
let cleanup: Cleanup | null = null;

/** Переход по адресу: если адрес не меняется, hashchange не придёт — перерисовываем сами. */
function navigate(hash: string): void {
  if (location.hash === hash) route(); else location.hash = hash;
}

setUnauthorizedHandler(() => { user = null; navigate("#/login"); });

function renderHeader(): void {
  if (!user) {
    header.replaceChildren(h("a", { class: "brand", href: "#/" }, h("span", { class: "brand-mark" }, "А"), "Кредитный кабинет"),
      h("div", { class: "who" }, themeButton()));
    return;
  }
  const isClient = user.role === "CLIENT";
  header.replaceChildren(
    h("a", { class: "brand", href: "#/" }, h("span", { class: "brand-mark" }, "А"), isClient ? "Кредитный кабинет" : "Кредитный конвейер"),
    h("nav", { class: "top-nav", "aria-label": "Основное меню" },
      isClient ? [h("a", { href: "#/" }, "Главная"), h("a", { href: "#/new" }, "Новая заявка")]
        : [h("a", { href: "#/queue/manual" }, "Очередь")]),
    h("div", { class: "who" },
      themeButton(),
      h("span", {}, user.company?.name ?? user.full_name),
      h("button", { type: "button", class: "btn btn-link", onclick: () => { setToken(null); user = null; navigate("#/login"); } }, "Выйти")));
}

function loginPage(): void {
  const email = h("input", { class: "input", type: "email", autocomplete: "username", required: true });
  const password = h("input", { class: "input", type: "password", autocomplete: "current-password", required: true });
  const box = h("div", { class: "login" });
  const doLogin = async () => {
    try {
      const r = await api.login(email.value, password.value);
      setToken(r.access_token); user = r.user;
      navigate(user.role === "CLIENT" ? "#/" : "#/queue/manual");
    } catch (e) { showErrors(box, e); }
  };
  const quick = (who: { email: string; password: string; title: string; text: string }) =>
    h("button", { type: "button", class: "demo-acc", onclick: () => { email.value = who.email; password.value = who.password; doLogin(); } },
      h("strong", {}, who.title), h("span", {}, who.text));
  password.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
  box.append(
    h("div", { class: "login-form" },
      h("h1", {}, "Вход"),
      h("p", { class: "lead" }, "Кредиты для бизнеса: от потребности до денег на счёте — в одном кабинете."),
      h("div", { class: "form-error", role: "alert", hidden: true }),
      field("Email", email, undefined, "email"), field("Пароль", password, undefined, "password"),
      actionButton("Войти", doLogin)),
    h("div", { class: "login-demo" },
      h("h2", {}, "Демо-клиенты"),
      h("p", { class: "hint" }, "Каждая компания проходит конвейер по-своему — нажмите, чтобы войти."),
      h("div", { class: "demo-grid" }, clientDemo.map(quick)),
      h("h2", {}, "Сотрудники банка"),
      h("div", { class: "demo-grid" }, analystDemo.map(quick)),
      h("p", { class: "hint login-api" }, "Для проверяющих: ",
        h("a", { href: "/docs", target: "_blank", rel: "noopener" }, "описание API в Swagger UI"), ".")));
  mount(app, box);
}

// Номер текущего перехода. Переход, который закончился позже более нового, ничего не рисует:
// иначе медленный ответ сервера выводит старую страницу поверх открытой.
let routeGen = 0;
let lastPage = "";

async function route(): Promise<void> {
  const gen = ++routeGen;
  cleanup?.(); cleanup = null;
  const [path, qs] = (location.hash.replace(/^#/, "") || "/").split("?");
  const parts = path.split("/").filter(Boolean);
  if (!user && hasToken()) {
    try { user = await api.me(); } catch { setToken(null); }
    if (gen !== routeGen) return;
  }
  renderHeader();
  if (!user) { lastPage = ""; loginPage(); return; }

  // Новая страница строится в отдельном контейнере и заменяет старую, только когда готова.
  // Пока она грузится, старая остаётся на экране; «Загружаем…» — лишь если ждать дольше 400 мс.
  const view = h("div", { class: "view" });
  const page = parts[0] ?? "";
  // Внутри той же страницы (вкладки очереди) старое содержимое просто притушается, а не исчезает
  const samePage = page === lastPage && app.querySelector(".view") !== null;
  const slow = window.setTimeout(() => {
    if (gen !== routeGen) return;
    if (samePage) app.setAttribute("aria-busy", "true");
    else mount(app, h("p", { class: "loading", role: "status" }, "Загружаем…"));
  }, samePage ? 150 : 400);
  try {
    let c: Cleanup;
    if (user.role === "CLIENT") {
      if (parts[0] === "new") c = await wizard(view, user, new URLSearchParams(qs ?? ""));
      else if (parts[0] === "applications" && parts[1]) c = await applicationPage(view, user, parts[1]);
      else c = await dashboard(view, user);
    } else {
      if (parts[0] === "review" && parts[1]) c = await reviewPage(view, user, parts[1]);
      else c = await queuePage(view, user, ["manual", "active", "all"].includes(parts[1]) ? parts[1] : "manual");
    }
    clearTimeout(slow);
    if (gen !== routeGen) { c(); return; }
    cleanup = c;
    app.removeAttribute("aria-busy");
    app.replaceChildren(view);
    // Переключение вкладок очереди не сбрасывает прокрутку, переход на другую страницу — сбрасывает
    if (page !== lastPage || page !== "queue") window.scrollTo(0, 0);
    lastPage = page;
  } catch (e) {
    clearTimeout(slow);
    if (gen !== routeGen) return;
    app.removeAttribute("aria-busy");
    const msg = e instanceof ApiError ? e.message : "Не удалось загрузить страницу.";
    mount(app, h("div", { class: "empty" }, h("h3", {}, "Ошибка"), h("p", {}, msg),
      h("button", { type: "button", class: "btn btn-secondary", onclick: () => route() }, "Повторить")));
  }
}

window.addEventListener("hashchange", () => { route(); });
route();
