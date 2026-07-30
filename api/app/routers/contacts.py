"""担当者マスタ API。"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Company, Contact

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class ContactCreate(BaseModel):
    company_id: str
    name: str = Field(..., min_length=1, max_length=128)
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field("primary", pattern="^(primary|secondary)$")
    phone: str | None = None
    is_active: bool = True


class ContactUpdate(BaseModel):
    company_id: str | None = None
    name: str | None = Field(None, min_length=1, max_length=128)
    email: str | None = Field(None, min_length=3, max_length=255)
    role: str | None = Field(None, pattern="^(primary|secondary)$")
    phone: str | None = None
    is_active: bool | None = None


class ContactListItem(BaseModel):
    id: str
    company_id: str
    company_name: str | None = None
    name: str
    email: str
    role: str
    phone: str | None = None
    is_active: bool = True
    created_at: str


def _to_item(row: Contact, company_name: str | None = None) -> ContactListItem:
    return ContactListItem(
        id=str(row.id),
        company_id=str(row.company_id),
        company_name=company_name,
        name=row.name,
        email=row.email,
        role=row.role,
        phone=row.phone,
        is_active=row.is_active,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


@router.get("", response_model=list[ContactListItem])
def list_contacts(
    company_id: str | None = Query(None),
    q: str | None = Query(None),
    session: Session = Depends(get_db),
) -> list[ContactListItem]:
    stmt = select(Contact, Company.name).join(Company, Company.id == Contact.company_id)
    if company_id:
        try:
            cid = UUID(company_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "company_id が不正です。"},
            ) from exc
        stmt = stmt.where(Contact.company_id == cid)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.name.ilike(like),
                Contact.email.ilike(like),
                Company.name.ilike(like),
            )
        )
    rows = session.execute(stmt.order_by(Contact.name.asc()).limit(500)).all()
    return [_to_item(contact, company_name) for contact, company_name in rows]


@router.post("", response_model=ContactListItem)
def create_contact(body: ContactCreate, session: Session = Depends(get_db)) -> ContactListItem:
    from datetime import datetime

    try:
        company_id = UUID(body.company_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "company_id が不正です。"},
        ) from exc
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "企業が見つかりません。"},
        )
    email = body.email.strip().lower()
    existing = session.scalar(select(Contact).where(Contact.email == email).limit(1))
    if existing is not None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "同じメールアドレスの担当者が既に存在します。"},
        )
    now = datetime.now().astimezone()
    row = Contact(
        id=uuid4(),
        company_id=company_id,
        name=body.name.strip(),
        email=email,
        role=body.role,
        phone=(body.phone or "").strip()[:32] or None,
        is_active=body.is_active,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_item(row, company.name)


@router.get("/{contact_id}", response_model=ContactListItem)
def get_contact(contact_id: UUID, session: Session = Depends(get_db)) -> ContactListItem:
    row = session.get(Contact, contact_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "担当者が見つかりません。"},
        )
    company = session.get(Company, row.company_id)
    return _to_item(row, company.name if company else None)


@router.patch("/{contact_id}", response_model=ContactListItem)
def update_contact(
    contact_id: UUID,
    body: ContactUpdate,
    session: Session = Depends(get_db),
) -> ContactListItem:
    from datetime import datetime

    row = session.get(Contact, contact_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "担当者が見つかりません。"},
        )
    if body.company_id is not None:
        try:
            company_id = UUID(body.company_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "company_id が不正です。"},
            ) from exc
        if session.get(Company, company_id) is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "ERR-0012", "error_message": "企業が見つかりません。"},
            )
        row.company_id = company_id
    if body.name is not None:
        row.name = body.name.strip()
    if body.email is not None:
        email = body.email.strip().lower()
        clash = session.scalar(
            select(Contact).where(Contact.email == email, Contact.id != contact_id).limit(1)
        )
        if clash is not None:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "同じメールアドレスの担当者が既に存在します。"},
            )
        row.email = email
    if body.role is not None:
        row.role = body.role
    if body.phone is not None:
        row.phone = body.phone.strip()[:32] or None
    if body.is_active is not None:
        row.is_active = body.is_active
    row.updated_at = datetime.now().astimezone()
    session.commit()
    session.refresh(row)
    company = session.get(Company, row.company_id)
    return _to_item(row, company.name if company else None)
