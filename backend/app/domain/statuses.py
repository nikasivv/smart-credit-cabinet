"""Статусы заявки, участники процесса и человекочитаемые описания.

Модуль не зависит от фреймворков: его используют API, воркер и тесты.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATION = "VALIDATION"
    NEEDS_INFO = "NEEDS_INFO"
    ENRICHMENT = "ENRICHMENT"
    SCORING = "SCORING"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    COUNTER_OFFER = "COUNTER_OFFER"
    REJECTED = "REJECTED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    SIGNED = "SIGNED"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class Actor(StrEnum):
    CLIENT = "CLIENT"
    SYSTEM = "SYSTEM"
    ANALYST = "ANALYST"


TERMINAL: frozenset[Status] = frozenset({Status.REJECTED, Status.ISSUED, Status.CANCELLED})

# Статусы, в которых заявка «в работе у банка» — клиент ждёт.
BANK_SIDE: frozenset[Status] = frozenset(
    {Status.SUBMITTED, Status.VALIDATION, Status.ENRICHMENT, Status.SCORING, Status.MANUAL_REVIEW, Status.SIGNED}
)

# Этапы, которые видит клиент в трекере (индексы 0..4).
STAGES: tuple[str, ...] = ("Заявка", "Проверка", "Решение", "Подписание", "Деньги")


@dataclass(frozen=True)
class StatusInfo:
    stage: int
    title: str
    now: str          # что происходит сейчас — простым языком
    next_step: str    # что будет дальше / что сделать клиенту
    waiting_for: str  # "client" | "bank" | "none"


STATUS_INFO: dict[Status, StatusInfo] = {
    Status.DRAFT: StatusInfo(0, "Черновик", "Заявка сохранена, но ещё не отправлена в банк.",
                             "Проверьте данные и отправьте заявку.", "client"),
    Status.SUBMITTED: StatusInfo(1, "Заявка отправлена", "Банк принял заявку и поставил её в очередь на проверку.",
                                 "Обычно проверка занимает несколько минут.", "bank"),
    Status.VALIDATION: StatusInfo(1, "Проверяем полноту данных", "Сверяем, что заполнены все поля и приложены нужные документы.",
                                  "Если чего-то не хватит, мы попросим это здесь, в кабинете.", "bank"),
    Status.NEEDS_INFO: StatusInfo(1, "Нужны уточнения", "Для решения банку не хватает информации.",
                                  "Посмотрите запрос ниже, дополните данные и отправьте ответ.", "client"),
    Status.ENRICHMENT: StatusInfo(1, "Проверяем компанию", "Запрашиваем сведения из ЕГРЮЛ/ЕГРИП, ФНС и бюро кредитных историй.",
                                  "После этого банк оценит заявку.", "bank"),
    Status.SCORING: StatusInfo(2, "Оцениваем заявку", "Считаем кредитный рейтинг и подбираем условия под вашу выручку и нагрузку.",
                               "Решение появится здесь автоматически.", "bank"),
    Status.MANUAL_REVIEW: StatusInfo(2, "Заявку смотрит специалист", "Кредитный аналитик проверяет детали, которые не оценить автоматически.",
                                     "Решение появится здесь, обычно в течение рабочего дня.", "bank"),
    Status.APPROVED: StatusInfo(2, "Одобрено", "Банк готов выдать финансирование на запрошенных условиях.",
                                "Ознакомьтесь с условиями и примите предложение.", "client"),
    Status.COUNTER_OFFER: StatusInfo(2, "Есть встречное предложение", "Банк готов выдать финансирование, но на других условиях.",
                                     "Сравните условия и решите, подходят ли они вам.", "client"),
    Status.REJECTED: StatusInfo(2, "Отказ", "Сейчас банк не может предоставить финансирование.",
                                "Ниже — причины и что можно сделать, чтобы подать заявку снова.", "none"),
    Status.OFFER_ACCEPTED: StatusInfo(3, "Документы готовы к подписанию", "Мы подготовили кредитный договор по принятым условиям.",
                                      "Проверьте договор и подпишите его в кабинете.", "client"),
    Status.SIGNED: StatusInfo(3, "Договор подписан", "Договор подписан, готовим зачисление средств.",
                              "Деньги поступят на расчётный счёт компании.", "bank"),
    Status.ISSUED: StatusInfo(4, "Деньги зачислены", "Средства зачислены на расчётный счёт компании.",
                              "График платежей доступен в карточке кредита.", "none"),
    Status.CANCELLED: StatusInfo(0, "Заявка отменена", "Заявка закрыта по вашему запросу.",
                                 "Вы можете создать новую заявку в любой момент.", "none"),
}
