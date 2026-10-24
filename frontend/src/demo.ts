// Демо-учётные записи (синтетические данные). Описание сценариев — docs/test-scenarios.md.
export interface DemoAccount { email: string; password: string; title: string; text: string; }

export const clientDemo: DemoAccount[] = [
  { email: "bakery@demo.ru", password: "demo12345", title: "Северная пекарня", text: "Устойчивый бизнес — автоматическое одобрение" },
  { email: "logistic@demo.ru", password: "demo12345", title: "ТрансЛогистик", text: "Много платежей по кредитам — встречное предложение" },
  { email: "agro@demo.ru", password: "demo12345", title: "Агро Плюс", text: "Выручка расходится с ФНС — банк дозапросит документы" },
  { email: "coffee@demo.ru", password: "demo12345", title: "ИП Смирнова, кофейня", text: "Молодой бизнес — решение примет специалист" },
  { email: "build@demo.ru", password: "demo12345", title: "Вектор Строй", text: "Компания в ликвидации — отказ с объяснением" },
  { email: "it@demo.ru", password: "demo12345", title: "Код и Цифра", text: "Крупная заявка уже у специалиста" },
];

export const analystDemo: DemoAccount[] = [
  { email: "analyst@alfa.demo", password: "analyst12345", title: "Екатерина Волкова", text: "Кредитный аналитик" },
  { email: "analyst2@alfa.demo", password: "analyst12345", title: "Павел Громов", text: "Кредитный аналитик" },
  { email: "risk@alfa.demo", password: "risk12345", title: "Алексей Соколов", text: "Риск-менеджер, только просмотр" },
];
