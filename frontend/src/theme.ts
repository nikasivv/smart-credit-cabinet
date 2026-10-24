// Светлая и тёмная тема. По умолчанию — как в системе; выбор пользователя запоминается в браузере.

import { h } from "./ui.js";

type Theme = "light" | "dark";
const KEY = "scc.theme";
const media = window.matchMedia("(prefers-color-scheme: dark)");

function saved(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch { return null; }   // приватный режим или запрет хранилища — просто следуем системе
}

function current(): Theme {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return media.matches ? "dark" : "light";
}

function label(btn: HTMLButtonElement): void {
  const dark = current() === "dark";
  btn.replaceChildren(h("span", { class: "tt-icon", "aria-hidden": "true" }, dark ? "☀" : "☾"),
    h("span", { class: "tt-text" }, dark ? "Светлая тема" : "Тёмная тема"));
  btn.setAttribute("aria-label", dark ? "Включить светлую тему" : "Включить тёмную тему");
}

/** Вызвать один раз при старте, до первой отрисовки. */
export function initTheme(): void {
  const t = saved();
  if (t) document.documentElement.dataset.theme = t;
  // Если пользователь ничего не выбирал, а система сменила тему — обновляем подписи кнопок
  media.addEventListener("change", () => document.querySelectorAll<HTMLButtonElement>(".theme-toggle").forEach(label));
}

export function themeButton(): HTMLButtonElement {
  const btn = h("button", { type: "button", class: "btn btn-link theme-toggle" });
  label(btn);
  btn.addEventListener("click", () => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(KEY, next); } catch { /* не запомнится — не страшно */ }
    label(btn);
  });
  return btn;
}