"""BAT-004: OK/NG 反映後の AI 判定。

1. NG マッチのルールスコアを 0 にする
2. 外国籍のハード制約に抵触する場合は LLM を呼ばず 0 点にする
   （商流制限は足切りしない。自社名設定による商流調整はルール採点と同じ）
3. 返信 NG 以外をルールスコア降順にし、案件ごと上位 N 人に LLM 判定
   （パイプライン自動実行時は返信前のため未判定も含む）
4. match_ids 明示時は上記絞り込みをスキップして選択分を判定（ハード制約は適用）
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_concurrency import map_parallel, resolve_ai_concurrency
from app.batch_job_id import resolve_batch_job_id
from app.config import Settings, settings
from app.constraint_rules import (
    evaluate_match_hard_constraints,
    hard_reject_label,
    resolve_proposal_commerce_flow,
)
from app.db_bootstrap import create_session_factory, ensure_schema
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.models import (
    Company,
    Match,
    MatchRun,
    OutreachMessage,
    OutreachReply,
    Project,
    SystemSetting,
    Talent,
)
from app.skill_sheet_experience import load_skill_sheet_experience, prepare_skill_sheets_for_talent_ids

# score_band は BAT-003 と同じ定義をインライン（import 衝突回避）
def score_band_for(score: int) -> str:
    clamped = max(0, min(100, int(score)))
    if clamped >= 90:
        return "90-100"
    low = (clamped // 10) * 10
    if low == 0:
        return "0-9"
    return f"{low}-{low + 9}"


@dataclass
class AiJudgeStats:
    ng_zeroed: int = 0
    hard_rejected: int = 0
    ai_judged: int = 0
    skipped: int = 0
    failed: int = 0
    skill_sheets_prepared: int = 0
    skill_sheets_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class _LlmJudgeJob:
    match_id: UUID
    talent: Talent
    project: Project
    score: int
    commerce_flow_adjusted: str
    skill_sheet_experience: str | None = None


@dataclass
class _LlmJudgeResult:
    match_id: UUID
    ai_score: int = 0
    reason: str = ""
    recommendation_points: str = ""
    error: BaseException | None = None


class AiSettings(Protocol):
    cursor_api_key: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    gemini_api_key: str
    gemini_model: str


def _load_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SystemSetting, key)
    if row is None:
        return default
    return row.value if row.value is not None else default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _talent_company_name(session: Session, talent: Talent) -> str | None:
    if talent.introducer_company_id:
        company = session.get(Company, talent.introducer_company_id)
        if company and (company.name or "").strip():
            return company.name.strip()
    name = (talent.source_company_name or "").strip()
    return name or None


def _adjusted_commerce_flow(
    session: Session,
    talent: Talent,
    *,
    own_company_name: str | None,
) -> str:
    return resolve_proposal_commerce_flow(
        own_company_name=own_company_name,
        talent_company_name=_talent_company_name(session, talent),
        affiliation=talent.affiliation,
        commerce_flow=talent.commerce_flow,
    )


def _apply_hard_constraints(
    session: Session,
    match: Match,
    talent: Talent,
    project: Project,
    *,
    own_company_name: str | None,
) -> str | None:
    """外国籍に抵触すれば match を 0 点にして拒否コードを返す。OK なら None。"""
    code, adjusted = evaluate_match_hard_constraints(
        own_company_name=own_company_name,
        talent_company_name=_talent_company_name(session, talent),
        affiliation=talent.affiliation,
        commerce_flow=talent.commerce_flow,
        talent_is_foreign_national=getattr(talent, "is_foreign_national", None),
        project_foreign_nationality_ng=bool(getattr(project, "foreign_nationality_ng", False)),
        project_commerce_flow_limit=getattr(project, "commerce_flow_limit", None),
    )
    if not code:
        return None

    label = hard_reject_label(code) or code
    match.score = 0
    match.score_band = score_band_for(0)
    match.ai_score = 0
    match.reason = label
    match.recommendation_points = None
    match.ai_judged_at = datetime.now().astimezone()
    match.is_candidate = False
    breakdown = dict(match.score_breakdown or {}) if isinstance(match.score_breakdown, dict) else {}
    breakdown["hard_reject"] = code
    breakdown["hard_reject_label"] = label
    if adjusted:
        breakdown["commerce_flow_adjusted"] = adjusted
    match.score_breakdown = breakdown
    return code


def _nationality_label(is_foreign_national: bool | None) -> str:
    if is_foreign_national is True:
        return "外国籍"
    if is_foreign_national is False:
        return "日本国籍"
    return "不明"


def _latest_auto_judgment(session: Session, match: Match) -> str | None:
    """当該 match の talent_proposal に紐づく最新返信判定を返す。"""
    proposal = session.scalar(
        select(OutreachMessage)
        .where(
            OutreachMessage.kind == "talent_proposal",
            OutreachMessage.match_id == match.id,
            OutreachMessage.status == "sent",
        )
        .order_by(OutreachMessage.sent_at.desc())
        .limit(1)
    )
    if proposal is None:
        return None
    reply = session.scalar(
        select(OutreachReply)
        .where(OutreachReply.outreach_message_id == proposal.id)
        .order_by(OutreachReply.received_at.desc())
        .limit(1)
    )
    return reply.judgment if reply else None


def _build_llm_judge_prompt(
    talent: Talent,
    project: Project,
    score: int,
    *,
    commerce_flow_adjusted: str | None = None,
    skill_sheet_experience: str | None = None,
) -> str:
    nationality = _nationality_label(getattr(talent, "is_foreign_national", None))
    commerce = (commerce_flow_adjusted or talent.commerce_flow or "").strip() or "未記入"
    commerce_limit = (getattr(project, "commerce_flow_limit", None) or "").strip() or "制限なし/不明"
    experience_block = (
        skill_sheet_experience.strip()
        if skill_sheet_experience and skill_sheet_experience.strip()
        else "なし（メール情報のみ）"
    )
    return (
        "あなたは SES マッチングの評価者です。人材と案件の適合度を 0-100 で採点し、"
        "短い日本語の評価理由と、提案メール用のポジティブなおすすめポイントを付けて "
        "JSON のみ返してください。\n"
        "reason は評価理由（良い点・懸念の要約でよい）。\n"
        "recommendation_points の書き方:\n"
        "- 1〜2 文、前向き・具体的。誇張・虚偽・否定表現は禁止\n"
        "- 人材提案メール（案件側へ要員を紹介）と案件提案メール（紹介元へ案件を紹介）の"
        "両方でそのまま使える文言にする\n"
        "- 「この人材を推します」「この案件をおすすめします」など、一方の提案先だけに"
        "寄せた言い回しは避ける\n"
        "- スキル適合・稼働・単価・勤務形態など、両者のマッチ根拠を中立に述べる"
        "（例: 「Java/Spring の実務とリモート希望が本件要件と整合し、早期参画が期待できます。」）\n"
        "※ 外国籍不可のハード足切りは呼び出し側で実施済み。商流制限は足切りしない。"
        "残る懸念があれば reason に短く触れてよいが、recommendation_points は前向きに保つ。\n"
        "必須スキルとスキルシート経験の評価:\n"
        "- 必須スキル一覧について、スキルシート経験（抜粋）にそのスキルを使った具体的な案件・業務があるか確認する。\n"
        "- ある場合、各スキルの経験内容が案件の業務内容と整合するかを reason に簡潔に書く。\n"
        "- スキルシートに根拠が無い必須スキルは reason に懸念として明記し、"
        "メールの人材スキル一覧だけの一致は過度に加点しない（ai_score は控えめに）。\n"
        '形式: {"ai_score": 0-100, "reason": "...", "recommendation_points": "..."}\n\n'
        f"ルールスコア: {score}\n"
        f"人材名: {talent.display_name}\n"
        f"年齢: {talent.age}\n"
        f"性別: {getattr(talent, 'gender', None) or '未記入'}\n"
        f"人材スキル: {talent.skills}\n"
        f"希望単価: {talent.desired_rate}\n"
        f"稼働: {talent.available_from}\n"
        f"勤務形態: {talent.work_style}\n"
        f"最寄駅: {talent.nearest_station}\n"
        f"国籍: {nationality}\n"
        f"商流（自社視点）: {commerce}\n"
        f"所属: {talent.affiliation or '未記入'}\n"
        f"営業コメント/自己PR: {talent.summary}\n\n"
        f"スキルシート経験（抜粋）:\n{experience_block}\n\n"
        f"案件名: {project.title}\n"
        f"必須スキル: {project.required_skills}\n"
        f"単価: {project.rate_min}-{project.rate_max}\n"
        f"勤務形態: {project.work_style}\n"
        f"勤務時間: {getattr(project, 'working_hours', None)}\n"
        f"場所: {project.location}\n"
        f"精算幅: {getattr(project, 'settlement_range', None)}\n"
        f"外国籍: {('不可' if getattr(project, 'foreign_nationality_ng', None) is True else ('可/不問' if getattr(project, 'foreign_nationality_ng', None) is False else '未記入'))}\n"
        f"商流制限: {commerce_limit}\n"
        f"業務内容: {project.summary}\n"
    )


def _judge_with_llm(
    talent: Talent,
    project: Project,
    score: int,
    cfg: AiSettings,
    *,
    commerce_flow_adjusted: str | None = None,
    skill_sheet_experience: str | None = None,
) -> tuple[int, str, str]:
    prompt = _build_llm_judge_prompt(
        talent,
        project,
        score,
        commerce_flow_adjusted=commerce_flow_adjusted,
        skill_sheet_experience=skill_sheet_experience,
    )

    logger = get_batch_logger()
    raw_text = (
        _call_gemini(prompt, cfg, logger=logger)
        or _call_cursor(prompt, cfg, logger=logger)
        or _call_openai(prompt, cfg, logger=logger)
        or _call_claude(prompt, cfg, logger=logger)
    )
    if not raw_text:
        fallback_score = max(0, min(100, score))
        return (
            fallback_score,
            "AI 判定を実行できなかったためルールスコアを参考値として採用しました。",
            _fallback_recommendation_points(talent, project),
        )

    data = _parse_json(raw_text)
    if not data:
        fallback_score = max(0, min(100, score))
        return (
            fallback_score,
            "AI 応答を JSON として解釈できなかったためルールスコアを参考値として採用しました。",
            _fallback_recommendation_points(talent, project),
        )

    ai_score = data.get("ai_score", score)
    try:
        ai_score_int = max(0, min(100, int(ai_score)))
    except (TypeError, ValueError):
        ai_score_int = max(0, min(100, score))
    reason = str(data.get("reason") or "").strip() or "理由なし"
    points = str(data.get("recommendation_points") or "").strip()
    if not points:
        points = _fallback_recommendation_points(talent, project)
    return ai_score_int, reason[:2000], points[:500]


def _fallback_recommendation_points(talent: Talent, project: Project) -> str:
    talent_skills = [str(s).strip() for s in (talent.skills or []) if str(s).strip()][:5]
    project_skills = [str(s).strip() for s in (project.required_skills or []) if str(s).strip()][:5]
    overlap = [s for s in talent_skills if any(s.lower() == p.lower() for p in project_skills)]
    focus = overlap or talent_skills or project_skills
    if focus:
        return (
            f"{', '.join(focus)} の面で人材スキルと案件要件が整合し、"
            "早期の参画・戦力化が期待できます。"
        )
    return "スキル・稼働条件の面で適合が見込め、前向きにご検討いただける組み合わせです。"


_GEMINI_JUDGE_SYSTEM = (
    "You are an SES matching evaluator. "
    "recommendation_points must be reusable in both talent-proposal "
    "and project-proposal emails (neutral fit appeal). "
    "Reply with a single JSON object only: "
    '{"ai_score": 0-100, "reason": "...", "recommendation_points": "..."}'
)
_GEMINI_JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ai_score": {"type": "INTEGER"},
        "reason": {"type": "STRING"},
        "recommendation_points": {"type": "STRING"},
    },
    "required": ["ai_score", "reason", "recommendation_points"],
}


def _call_gemini(prompt: str, cfg: AiSettings, *, logger: logging.Logger | None = None) -> str | None:
    api_key = getattr(cfg, "gemini_api_key", "") or ""
    if not str(api_key).strip():
        return None
    try:
        from app.gemini_llm import call_gemini_json
    except ImportError as exc:
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.gemini_unavailable",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 Gemini",
                method_name="_call_gemini",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None

    try:
        return call_gemini_json(
            api_key=str(api_key),
            model=getattr(cfg, "gemini_model", None),
            system=_GEMINI_JUDGE_SYSTEM,
            user=prompt,
            response_schema=_GEMINI_JUDGE_SCHEMA,
            temperature=0.2,
            purpose="ai_judge",
        )
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.gemini_failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 Gemini",
                method_name="_call_gemini",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None


def _call_cursor(prompt: str, cfg: AiSettings, *, logger: logging.Logger | None = None) -> str | None:
    if not (cfg.cursor_api_key or "").strip():
        return None
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as exc:
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.cursor_unavailable",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 Cursor SDK",
                method_name="_call_cursor",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="bat004-cursor-") as cwd:
            result = Agent.prompt(
                prompt,
                AgentOptions(
                    api_key=cfg.cursor_api_key,
                    model="composer-2.5",
                    local=LocalAgentOptions(cwd=cwd),
                ),
            )
        text = getattr(result, "result", None) or str(result)
        return str(text) if text else None
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.cursor_failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 Cursor",
                method_name="_call_cursor",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None


def _call_openai(prompt: str, cfg: AiSettings, *, logger: logging.Logger | None = None) -> str | None:
    if not (cfg.openai_api_key or "").strip():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=cfg.openai_api_key)
        response = client.chat.completions.create(
            model=cfg.openai_model or "gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an SES matching evaluator. "
                        "recommendation_points must be reusable in both talent-proposal "
                        "and project-proposal emails (neutral fit appeal). "
                        "Reply with a single JSON object only: "
                        '{"ai_score": 0-100, "reason": "...", "recommendation_points": "..."}'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content
        return content if content else None
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.openai_failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 OpenAI",
                method_name="_call_openai",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None


def _call_claude(prompt: str, cfg: AiSettings, *, logger: logging.Logger | None = None) -> str | None:
    api_key = getattr(cfg, "anthropic_api_key", "") or ""
    if not str(api_key).strip():
        return None
    try:
        from app.claude_llm import call_claude_messages
    except ImportError as exc:
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.claude_unavailable",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 Claude",
                method_name="_call_claude",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None

    try:
        content = call_claude_messages(
            api_key=str(api_key),
            model=getattr(cfg, "anthropic_model", None),
            system=(
                "You are an SES matching evaluator. "
                "recommendation_points must be reusable in both talent-proposal "
                "and project-proposal emails (neutral fit appeal). "
                "Reply with a single JSON object only: "
                '{"ai_score": 0-100, "reason": "...", "recommendation_points": "..."}. '
                "Do not wrap the JSON in Markdown fences."
            ),
            user=prompt,
            max_tokens=2048,
            temperature=0.2,
        )
        return content
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            log_error_event(
                logger,
                event="matching.ai_judge.claude_failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定 Claude",
                method_name="_call_claude",
                job_id="ai_judge",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
        return None


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return {}
    return {}


def _run_llm_job(job: _LlmJudgeJob, cfg: AiSettings) -> _LlmJudgeResult:
    try:
        ai_score, reason, recommendation_points = _judge_with_llm(
            job.talent,
            job.project,
            job.score,
            cfg,
            commerce_flow_adjusted=job.commerce_flow_adjusted,
            skill_sheet_experience=job.skill_sheet_experience,
        )
        return _LlmJudgeResult(
            match_id=job.match_id,
            ai_score=ai_score,
            reason=reason,
            recommendation_points=recommendation_points,
        )
    except BaseException as exc:  # noqa: BLE001 — ワーカー内で捕捉
        return _LlmJudgeResult(match_id=job.match_id, error=exc)


def _apply_llm_results(
    *,
    session: Session,
    matches_by_id: dict[UUID, Match],
    results: list[_LlmJudgeResult],
    stats: AiJudgeStats,
    logger: logging.Logger,
    job_id: str,
) -> None:
    judged_at = datetime.now().astimezone()
    for result in results:
        match = matches_by_id.get(result.match_id)
        if match is None:
            stats.failed += 1
            continue
        if result.error is not None:
            stats.failed += 1
            stats.errors.append(str(result.error))
            log_error_event(
                logger,
                event="matching.ai_judge.failed",
                error_code="ERR-0030",
                detail=str(result.error),
                operation="AI判定",
                method_name="run_ai_judge_batch",
                job_id=job_id,
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
                extra={"match_id": str(result.match_id)},
            )
            continue
        match.ai_score = result.ai_score
        match.reason = result.reason
        match.recommendation_points = result.recommendation_points
        match.ai_judged_at = judged_at
        match.is_candidate = True
        stats.ai_judged += 1


def _enqueue_llm_job(
    *,
    session: Session,
    match: Match,
    own_company_name: str | None,
    stats: AiJudgeStats,
    jobs: list[_LlmJudgeJob],
    matches_by_id: dict[UUID, Match],
    cfg: Settings,
) -> None:
    talent = session.get(Talent, match.talent_id)
    project = session.get(Project, match.project_id)
    if talent is None or project is None:
        stats.failed += 1
        return
    if _apply_hard_constraints(
        session,
        match,
        talent,
        project,
        own_company_name=own_company_name,
    ):
        stats.hard_rejected += 1
        return
    adjusted = _adjusted_commerce_flow(session, talent, own_company_name=own_company_name)
    logger = get_batch_logger()
    skill_experience = load_skill_sheet_experience(
        session,
        talent.id,
        credentials_path=cfg.gmail_credentials_path,
        token_path=cfg.gmail_token_path,
        logger=logger,
    )
    # ワーカーは属性読み取りのみ。lazy load を避けるため必要列を先に触る
    _ = (
        talent.display_name,
        talent.skills,
        talent.desired_rate,
        talent.available_from,
        talent.work_style,
        talent.nearest_station,
        talent.is_foreign_national,
        talent.commerce_flow,
        talent.affiliation,
        talent.summary,
        project.title,
        project.required_skills,
        project.rate_min,
        project.rate_max,
        project.work_style,
        project.location,
        project.foreign_nationality_ng,
        project.commerce_flow_limit,
        project.summary,
    )
    session.expunge(talent)
    session.expunge(project)
    matches_by_id[match.id] = match
    jobs.append(
        _LlmJudgeJob(
            match_id=match.id,
            talent=talent,
            project=project,
            score=match.score,
            commerce_flow_adjusted=adjusted,
            skill_sheet_experience=skill_experience,
        )
    )


def run_ai_judge_batch(
    *,
    match_run_id: UUID | None = None,
    project_id: UUID | None = None,
    match_ids: list[UUID] | None = None,
    cfg: Settings | None = None,
) -> AiJudgeStats:
    cfg = cfg or settings
    logger = get_batch_logger()
    job_id = resolve_batch_job_id(default_prefix="job")
    stats = AiJudgeStats()
    concurrency = resolve_ai_concurrency(getattr(cfg, "ai_concurrency", 3))
    started = time.perf_counter()

    log_event(
        logger,
        logging.INFO,
        event="matching.ai_judge.started",
        message="AI judge batch started",
        operation="AI判定開始",
        method_name="run_ai_judge_batch",
        job_id=job_id,
        function_id="BAT-004",
        module_name="BAT-004.ai_judge",
        extra={"ai_concurrency": concurrency},
    )

    session_factory, engine = create_session_factory(cfg.database_url)
    ensure_schema(engine)

    results: list[_LlmJudgeResult] = []
    with session_factory() as session:
        top_n = max(1, min(20, _as_int(_load_setting(session, "ai_judgement_top_n", 5), 5)))
        own_company_name = str(_load_setting(session, "own_company_name", "") or "").strip() or None
        llm_jobs: list[_LlmJudgeJob] = []
        matches_by_id: dict[UUID, Match] = {}

        # 明示選択の match_ids がある場合は、返信 OK/NG 条件をスキップしてそのまま AI 判定する
        target_matches: list[Match] = []
        if match_ids:
            target_matches = list(session.scalars(select(Match).where(Match.id.in_(match_ids))).all())
        else:
            if match_run_id is None:
                run = session.scalar(select(MatchRun).order_by(MatchRun.started_at.desc()).limit(1))
                if run is None:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    log_event(
                        logger,
                        logging.INFO,
                        event="matching.ai_judge.finished",
                        message="AI judge batch finished",
                        operation="AI判定完了",
                        method_name="run_ai_judge_batch",
                        job_id=job_id,
                        function_id="BAT-004",
                        module_name="BAT-004.ai_judge",
                        duration_ms=duration_ms,
                        extra={
                            "ng_zeroed": stats.ng_zeroed,
                            "hard_rejected": stats.hard_rejected,
                            "ai_judged": stats.ai_judged,
                            "failed": stats.failed,
                            "ai_concurrency": concurrency,
                            "llm_jobs": 0,
                        },
                    )
                    return stats
                match_run_id = run.id

            query = select(Match).where(Match.match_run_id == match_run_id)
            if project_id is not None:
                query = query.where(Match.project_id == project_id)
            matches = list(session.scalars(query).all())

            by_project: dict[UUID, list[Match]] = {}
            for match in matches:
                by_project.setdefault(match.project_id, []).append(match)

            for _pid, project_matches in by_project.items():
                judgments: dict[UUID, str | None] = {
                    m.id: _latest_auto_judgment(session, m) for m in project_matches
                }

                for match in project_matches:
                    if judgments.get(match.id) == "ng":
                        match.score = 0
                        match.score_band = score_band_for(0)
                        stats.ng_zeroed += 1

                ok_matches = sorted(
                    [m for m in project_matches if judgments.get(m.id) != "ng"],
                    key=lambda m: m.score,
                    reverse=True,
                )
                selected = ok_matches[:top_n]
                stats.skipped += max(0, len(ok_matches) - len(selected))
                target_matches.extend(selected)

        # 採点対象人材のスキルシートを AI 判定直前に取込（メール取込時からは分離）
        talent_ids = [m.talent_id for m in target_matches]
        if talent_ids:
            sheet_stats = prepare_skill_sheets_for_talent_ids(
                session_factory=session_factory,
                talent_ids=talent_ids,
                cfg=cfg,
                logger=logger,
                job_id=job_id,
            )
            stats.skill_sheets_prepared = int(sheet_stats.get("ingested", 0))
            stats.skill_sheets_skipped = int(sheet_stats.get("skipped_existing", 0))
            log_event(
                logger,
                logging.INFO,
                event="matching.ai_judge.skill_sheets_prepared",
                message="Skill sheets prepared for AI judge targets",
                operation="スキルシート取込",
                method_name="run_ai_judge_batch",
                job_id=job_id,
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
                extra=sheet_stats,
            )

        for match in target_matches:
            _enqueue_llm_job(
                session=session,
                match=match,
                own_company_name=own_company_name,
                stats=stats,
                jobs=llm_jobs,
                matches_by_id=matches_by_id,
                cfg=cfg,
            )

        # LLM のみ軽度並列。DB 書き込みはメインスレッドで直列
        results = map_parallel(
            llm_jobs,
            lambda job: _run_llm_job(job, cfg),
            concurrency=concurrency,
        )
        _apply_llm_results(
            session=session,
            matches_by_id=matches_by_id,
            results=results,
            stats=stats,
            logger=logger,
            job_id=job_id,
        )
        session.commit()

    duration_ms = int((time.perf_counter() - started) * 1000)
    log_event(
        logger,
        logging.INFO,
        event="matching.ai_judge.finished",
        message="AI judge batch finished",
        operation="AI判定完了",
        method_name="run_ai_judge_batch",
        job_id=job_id,
        function_id="BAT-004",
        module_name="BAT-004.ai_judge",
        duration_ms=duration_ms,
        extra={
            "ng_zeroed": stats.ng_zeroed,
            "hard_rejected": stats.hard_rejected,
            "ai_judged": stats.ai_judged,
            "failed": stats.failed,
            "ai_concurrency": concurrency,
            "llm_jobs": len(results),
            "skill_sheets_prepared": stats.skill_sheets_prepared,
            "skill_sheets_skipped": stats.skill_sheets_skipped,
        },
    )
    return stats
