"""要員への案件提案メール本文（共通テンプレート経由）。"""

from __future__ import annotations

from typing import Any, Sequence

from app.outreach_templates import (
    DEFAULT_PROJECT_PROPOSE_TEMPLATE,
    ProjectProposeLine,
    render_project_propose_body,
)

# 後方互換エイリアス
TalentProposalProjectLine = ProjectProposeLine


def build_talent_proposal_body(
    *,
    talent_display_name: str | None,
    project_title: str | None,
    required_skills: list[Any] | None,
    rate_min: int | None,
    rate_max: int | None,
    work_style: str | None,
    start_date: str | None,
    score: int,
    template: str | None = None,
    foreign_nationality_ng: bool | None = None,
    commerce_flow_limit: str | None = None,
    interview_count: int | None = None,
    summary: str | None = None,
) -> str:
    return build_talent_proposal_body_multi(
        talent_display_name=talent_display_name,
        projects=[
            ProjectProposeLine(
                title=project_title,
                required_skills=required_skills,
                rate_min=rate_min,
                rate_max=rate_max,
                work_style=work_style,
                start_date=start_date,
                score=score,
                foreign_nationality_ng=foreign_nationality_ng,
                commerce_flow_limit=commerce_flow_limit,
                interview_count=interview_count,
                summary=summary,
            )
        ],
        template=template,
    )


def build_talent_proposal_body_multi(
    *,
    talent_display_name: str | None,
    projects: Sequence[ProjectProposeLine],
    template: str | None = None,
    company_name: str | None = None,
    contact_name: str | None = None,
    rate_markdown_man_yen: int = 0,
) -> str:
    return render_project_propose_body(
        template=template or DEFAULT_PROJECT_PROPOSE_TEMPLATE,
        company_name=company_name,
        contact_name=contact_name or talent_display_name,
        projects=projects,
        rate_markdown_man_yen=rate_markdown_man_yen,
    )
