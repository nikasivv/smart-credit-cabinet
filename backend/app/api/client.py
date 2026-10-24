from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from ..config import get_settings
from ..db import get_db
from ..errors import NotFound
from ..models import ApplicationEvent, Document, User
from ..schemas import (ApplicationIn, ApplicationOut, ApplicationPatch, CancelIn, DocumentOut, EventOut, InfoResponseIn,
                       SignIn)
from ..security import ROLE_CLIENT, require_roles
from ..services import applications as svc
from ..services.feed import build_feed
from .common import commit
from .serializers import application_out

router = APIRouter(prefix="/api", tags=["client"])
client_only = require_roles(ROLE_CLIENT)


def _out(db: Session, app) -> ApplicationOut:
    db.refresh(app)
    return application_out(db, app, "CLIENT")


@router.get("/applications", response_model=list[ApplicationOut], summary="Заявки моей компании")
def list_applications(db: Session = Depends(get_db), user: User = Depends(client_only)):
    return [application_out(db, a, "CLIENT") for a in svc.list_for_client(db, user)]


@router.post("/applications", response_model=ApplicationOut, status_code=201, summary="Создать черновик заявки")
def create_application(body: ApplicationIn, db: Session = Depends(get_db), user: User = Depends(client_only),
                       idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=64)):
    app = svc.create_draft(db, user, body.model_dump(exclude_unset=True), idempotency_key)
    commit(db)
    return _out(db, app)


@router.get("/applications/{app_id}", response_model=ApplicationOut, summary="Карточка заявки")
def get_application(app_id: str, db: Session = Depends(get_db), user: User = Depends(client_only)):
    return application_out(db, svc.get_for_client(db, user, app_id), "CLIENT")


@router.patch("/applications/{app_id}", response_model=ApplicationOut, summary="Изменить черновик")
def patch_application(app_id: str, body: ApplicationPatch, db: Session = Depends(get_db),
                      user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    fields = body.model_dump(exclude_unset=True)
    version = fields.pop("version", None)
    svc.update_draft(db, user, app, fields, version)
    commit(db)
    return _out(db, app)


@router.post("/applications/{app_id}/submit", response_model=ApplicationOut, summary="Отправить заявку в банк")
def submit_application(app_id: str, db: Session = Depends(get_db), user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    svc.submit(db, user, app)
    commit(db)
    return _out(db, app)


@router.post("/applications/{app_id}/documents", response_model=DocumentOut, status_code=201,
             summary="Загрузить документ")
async def upload_document(app_id: str, doc_type: str = Form(...), file: UploadFile = File(...),
                          db: Session = Depends(get_db), user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    max_bytes = get_settings().max_upload_bytes
    content = await file.read(max_bytes + 1)
    doc = svc.add_document(db, user, app, doc_type, file.filename or "document",
                           file.content_type or "application/octet-stream", content, max_bytes)
    commit(db)
    return doc


@router.get("/applications/{app_id}/documents/{doc_id}", summary="Скачать документ")
def download_document(app_id: str, doc_id: int, db: Session = Depends(get_db), user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    doc = db.scalar(select(Document).options(undefer(Document.content))
                    .where(Document.id == doc_id, Document.application_id == app.id))
    if doc is None:
        raise NotFound("Документ не найден")
    return Response(doc.content, media_type=doc.content_type,
                    headers={"Content-Disposition": f'attachment; filename="document-{doc.id}"'})


@router.post("/applications/{app_id}/info-response", response_model=ApplicationOut,
             summary="Ответить на запрос банка и вернуть заявку на рассмотрение")
def info_response(app_id: str, body: InfoResponseIn, db: Session = Depends(get_db),
                  user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    svc.answer_info_request(db, user, app, body.message, body.model_dump(exclude={"message"}))
    commit(db)
    return _out(db, app)


@router.post("/applications/{app_id}/accept", response_model=ApplicationOut, summary="Принять предложение банка")
def accept(app_id: str, db: Session = Depends(get_db), user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    svc.accept_offer(db, user, app)
    commit(db)
    return _out(db, app)


@router.post("/applications/{app_id}/sign", response_model=ApplicationOut, summary="Подписать договор (смоделировано)")
def sign(app_id: str, body: SignIn, db: Session = Depends(get_db), user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    svc.sign(db, user, app, body.confirmation_inn)
    commit(db)
    return _out(db, app)


@router.post("/applications/{app_id}/cancel", response_model=ApplicationOut, summary="Отменить заявку")
def cancel(app_id: str, body: CancelIn, db: Session = Depends(get_db), user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    svc.cancel(db, user, app, body.reason)
    commit(db)
    return _out(db, app)


@router.get("/applications/{app_id}/events", response_model=list[EventOut], summary="История заявки")
def events(app_id: str, after_id: int = Query(0, ge=0), db: Session = Depends(get_db),
           user: User = Depends(client_only)):
    app = svc.get_for_client(db, user, app_id)
    return list(db.scalars(select(ApplicationEvent)
                           .where(ApplicationEvent.application_id == app.id, ApplicationEvent.id > after_id,
                                  ApplicationEvent.visible_to_client.is_(True))
                           .order_by(ApplicationEvent.id)))


@router.get("/feed", summary="Ваши заявки и предложения: действия, события, предложения, советы")
def feed(db: Session = Depends(get_db), user: User = Depends(client_only)):
    return build_feed(db, user)
