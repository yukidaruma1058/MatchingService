"""企業マスタ API。"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.entity_delete import delete_company_cascade
from app.models import Company, Contact

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field("both", pattern="^(introducer|distributor|both)$")
    domain: str | None = None
    default_email: str | None = None
    notes: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    kind: str | None = Field(None, pattern="^(introducer|distributor|both)$")
    domain: str | None = None
    default_email: str | None = None
    notes: str | None = None


class ContactBrief(BaseModel):
    id: str
    name: str
    email: str
    role: str
    phone: str | None = None
    is_active: bool = True


class CompanyListItem(BaseModel):
    id: str
    name: str
    kind: str
    domain: str | None = None
    default_email: str | None = None
    notes: str | None = None
    contact_count: int = 0
    created_at: str


class CompanyDetail(CompanyListItem):
    contacts: list[ContactBrief] = Field(default_factory=list)


@router.get("", response_model=list[CompanyListItem])
def list_companies(
    q: str | None = Query(None),
    session: Session = Depends(get_db),
) -> list[CompanyListItem]:
    stmt = select(Company).order_by(Company.name.asc()).limit(300)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = (
            select(Company)
            .where(or_(Company.name.ilike(like), Company.domain.ilike(like), Company.default_email.ilike(like)))
            .order_by(Company.name.asc())
            .limit(300)
        )
    rows = list(session.scalars(stmt).all())
    counts: dict = {}
    if rows:
        counts = dict(
            session.execute(
                select(Contact.company_id, func.count())
                .where(Contact.company_id.in_([r.id for r in rows]))
                .group_by(Contact.company_id)
            ).all()
        )
    return [
        CompanyListItem(
            id=str(row.id),
            name=row.name,
            kind=row.kind,
            domain=row.domain,
            default_email=row.default_email,
            notes=row.notes,
            contact_count=int(counts.get(row.id, 0)),
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]


@router.post("", response_model=CompanyDetail)
def create_company(body: CompanyCreate, session: Session = Depends(get_db)) -> CompanyDetail:
    from datetime import datetime

    now = datetime.now().astimezone()
    row = Company(
        id=uuid4(),
        name=body.name.strip(),
        kind=body.kind,
        domain=(body.domain or "").strip().lower()[:255] or None,
        default_email=(body.default_email or "").strip().lower()[:255] or None,
        notes=(body.notes or "").strip() or None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return get_company(row.id, session)


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: UUID, session: Session = Depends(get_db)) -> CompanyDetail:
    row = session.get(Company, company_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "企業が見つかりません。"},
        )
    contacts = session.scalars(
        select(Contact).where(Contact.company_id == company_id).order_by(Contact.name.asc())
    ).all()
    return CompanyDetail(
        id=str(row.id),
        name=row.name,
        kind=row.kind,
        domain=row.domain,
        default_email=row.default_email,
        notes=row.notes,
        contact_count=len(contacts),
        created_at=row.created_at.isoformat() if row.created_at else "",
        contacts=[
            ContactBrief(
                id=str(c.id),
                name=c.name,
                email=c.email,
                role=c.role,
                phone=c.phone,
                is_active=c.is_active,
            )
            for c in contacts
        ],
    )


@router.patch("/{company_id}", response_model=CompanyDetail)
def update_company(
    company_id: UUID,
    body: CompanyUpdate,
    session: Session = Depends(get_db),
) -> CompanyDetail:
    from datetime import datetime

    row = session.get(Company, company_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "企業が見つかりません。"},
        )
    if body.name is not None:
        row.name = body.name.strip()
    if body.kind is not None:
        row.kind = body.kind
    if body.domain is not None:
        row.domain = body.domain.strip().lower()[:255] or None
    if body.default_email is not None:
        row.default_email = body.default_email.strip().lower()[:255] or None
    if body.notes is not None:
        row.notes = body.notes.strip() or None
    row.updated_at = datetime.now().astimezone()
    session.commit()
    return get_company(company_id, session)


@router.delete("/{company_id}")
def delete_company(company_id: UUID, session: Session = Depends(get_db)) -> dict:
    """企業と担当者を削除する。人材・案件・メールからの参照は外す。"""
    try:
        deleted = delete_company_cascade(session, company_id)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "企業が見つかりません。"},
        ) from None
    return {"status": "ok", "message": "企業を削除しました", "deleted": deleted}
