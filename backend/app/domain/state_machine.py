"""Машина состояний кредитной заявки.

Единственный источник правды о допустимых переходах. Каждый переход
разрешён только определённым участникам (клиент, система, аналитик).
Любое изменение статуса в приложении проходит через check_transition().
"""
from __future__ import annotations

from .statuses import TERMINAL, Actor, Status

C, S, A = Actor.CLIENT, Actor.SYSTEM, Actor.ANALYST

TRANSITIONS: dict[tuple[Status, Status], frozenset[Actor]] = {
    # Клиент формирует и отправляет заявку
    (Status.DRAFT, Status.SUBMITTED): frozenset({C}),
    (Status.DRAFT, Status.CANCELLED): frozenset({C}),
    # Автоматическая обработка
    (Status.SUBMITTED, Status.VALIDATION): frozenset({S}),
    (Status.VALIDATION, Status.NEEDS_INFO): frozenset({S}),
    (Status.VALIDATION, Status.ENRICHMENT): frozenset({S}),
    (Status.ENRICHMENT, Status.SCORING): frozenset({S}),
    (Status.ENRICHMENT, Status.NEEDS_INFO): frozenset({S}),       # расхождение данных клиента и ФНС
    (Status.ENRICHMENT, Status.MANUAL_REVIEW): frozenset({S}),    # внешний источник недоступен
    (Status.SCORING, Status.APPROVED): frozenset({S}),
    (Status.SCORING, Status.COUNTER_OFFER): frozenset({S}),
    (Status.SCORING, Status.REJECTED): frozenset({S}),
    (Status.SCORING, Status.MANUAL_REVIEW): frozenset({S}),
    # Дозапрос информации
    (Status.NEEDS_INFO, Status.SUBMITTED): frozenset({C}),
    (Status.NEEDS_INFO, Status.CANCELLED): frozenset({C}),
    # Ручное рассмотрение
    (Status.MANUAL_REVIEW, Status.APPROVED): frozenset({A}),
    (Status.MANUAL_REVIEW, Status.COUNTER_OFFER): frozenset({A}),
    (Status.MANUAL_REVIEW, Status.REJECTED): frozenset({A}),
    (Status.MANUAL_REVIEW, Status.NEEDS_INFO): frozenset({A}),
    (Status.MANUAL_REVIEW, Status.CANCELLED): frozenset({C}),
    # Решение клиента по предложению
    (Status.APPROVED, Status.OFFER_ACCEPTED): frozenset({C}),
    (Status.APPROVED, Status.CANCELLED): frozenset({C}),
    (Status.COUNTER_OFFER, Status.OFFER_ACCEPTED): frozenset({C}),
    (Status.COUNTER_OFFER, Status.CANCELLED): frozenset({C}),
    # Подписание и выдача (смоделированы)
    (Status.OFFER_ACCEPTED, Status.SIGNED): frozenset({C}),
    (Status.OFFER_ACCEPTED, Status.CANCELLED): frozenset({C}),
    (Status.SIGNED, Status.ISSUED): frozenset({S}),
}


class TransitionError(Exception):
    """Недопустимый переход статуса."""

    def __init__(self, current: Status, target: Status, actor: Actor, reason: str):
        self.current, self.target, self.actor = current, target, actor
        super().__init__(reason)


def check_transition(current: Status, target: Status, actor: Actor) -> None:
    if current in TERMINAL:
        raise TransitionError(current, target, actor, f"Заявка в финальном статусе {current}, изменить её нельзя")
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise TransitionError(current, target, actor, f"Переход {current} → {target} не предусмотрен процессом")
    if actor not in allowed:
        raise TransitionError(current, target, actor, f"Переход {current} → {target} недоступен для роли {actor}")


def allowed_targets(current: Status, actor: Actor) -> list[Status]:
    return [t for (f, t), actors in TRANSITIONS.items() if f == current and actor in actors]


def all_statuses_reachable() -> bool:
    """Самопроверка модели: каждый статус достижим из DRAFT."""
    seen, frontier = {Status.DRAFT}, [Status.DRAFT]
    while frontier:
        cur = frontier.pop()
        for (f, t) in TRANSITIONS:
            if f == cur and t not in seen:
                seen.add(t)
                frontier.append(t)
    return seen == set(Status)


def to_mermaid() -> str:
    """Диаграмма состояний генерируется из той же модели, что и код."""
    lines = ["stateDiagram-v2", "    [*] --> DRAFT"]
    for (f, t), actors in TRANSITIONS.items():
        who = "/".join(sorted(a.value.lower() for a in actors))
        lines.append(f"    {f.value} --> {t.value} : {who}")
    for t in sorted(TERMINAL):
        lines.append(f"    {t.value} --> [*]")
    return "\n".join(lines)
