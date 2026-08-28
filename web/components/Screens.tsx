"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent, ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import {
  Badge,
  ButtonLink,
  CollapsiblePanel,
  CopyableReadonlyField,
  Field,
  HelpTooltip,
  Panel,
  StatCard,
  Topbar,
} from "@/components/ui";
import { settings } from "@/lib/mock-data";
import {
  BatchRunError,
  buildGmailOAuthRedirectUri,
  connectGmailFromWeb,
  createCompany,
  createContact,
  createProject,
  createSkillCategory,
  createTalent,
  deleteCompany,
  deleteProject,
  deleteSkillCategory,
  deleteTalent,
  fetchCompany,
  fetchCompanies,
  fetchContact,
  fetchContacts,
  fetchDashboard,
  fetchEmailDetail,
  fetchEmails,
  fetchGmailPipelineProgress,
  fetchRunningBatchJobs,
  fetchProject,
  fetchProjects,
  fetchSettings,
  fetchSkillCatalog,
  fetchSkillCategories,
  fetchSkillMaster,
  fetchTalent,
  fetchTalentMatches,
  fetchTalents,
  formatGmailCheckedAt,
  formatReceivedDate,
  formatEmailStatusLabel,
  formatOutreachStatusLabel,
  outreachStatusTone,
  formatMatchRunStatusLabel,
  formatContactRoleLabel,
  formatProjectStatusLabel,
  formatSkillSheetExperienceExtractLabel,
  formatTalentStatusLabel,
  formatRate,
  formatRateRange,
  formatScoreBreakdownLines,
  formatSkills,
  fetchProjectMatches,
  proposeTalents,
  previewTalentPropose,
  previewProjectPropose,
  proposeToProject,
  runAiJudge,
  runGmailPipelineBatch,
  runMatchScoreBatch,
  startGmailOAuth,
  stopRunningBatchJobs,
  syncOutreachReplies,
  updateCompany,
  updateContact,
  updateMatchOutreachStatus,
  updateSettings,
  updateSkillCategory,
  updateSkillCategoryId,
  updateTalent,
  updateProject,
  type PipelineProgressDto,
  type RunningBatchJobDto,
  type CompanyDto,
  type ContactDto,
  type DashboardCompanyIngestDto,
  type DashboardDailyPointDto,
  type DashboardDto,
  type DashboardFunnelDto,
  type DashboardPeriodRange,
  type DashboardScoreBandOkDto,
  type EmailDetailDto,
  type EmailDto,
  type ProjectDto,
  type ProjectMatchItemDto,
  type ProjectProposeDraftDto,
  type SettingsPayload,
  type SkillCategoryDto,
  type SkillMasterItemDto,
  type TalentDto,
  type TalentMatchItemDto,
  type TalentProposeDraftDto,
} from "@/lib/api";

/** カンマ/セミコロン/改行区切りの宛先文字列を配列にする。 */
function parseAddressList(raw: string): string[] {
  return raw
    .split(/[,;\n]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function formatByteSize(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes) || bytes < 0) {
    return "-";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function mergeTalentProposeBodies(drafts: TalentProposeDraftDto[]): string {
  if (drafts.length === 0) {
    return "";
  }
  if (drafts.length === 1) {
    return drafts[0].body_text;
  }
  const greetingMarker = "以下の案件をご提案いたします。";
  const closingMarker = "ご検討のほど";
  const first = drafts[0].body_text;
  const greetingEnd = first.indexOf(greetingMarker);
  const header =
    greetingEnd >= 0
      ? first.slice(0, greetingEnd + greetingMarker.length) + "\n\n"
      : "お世話になっております。マッチング結果に基づき、以下の案件をご提案いたします。\n\n";

  const blocks = drafts.map((draft, index) => {
    const body = draft.body_text || "";
    const end = body.indexOf(closingMarker);
    const sliced = end >= 0 ? body.slice(0, end) : body;

    // 新形式: 【n】案件名 + コア原文
    const newStart = sliced.search(/【\d+】/);
    if (newStart >= 0) {
      const block = sliced
        .slice(newStart)
        .trim()
        .replace(/^【\d+】/, `【${index + 1}】`);
      return `${block}\n`;
    }

    // 旧形式: ■ 案件名:
    const oldStart = sliced.indexOf("■ 案件名:");
    if (oldStart >= 0) {
      const block = sliced
        .slice(oldStart)
        .replace("■ 案件名:", `【${index + 1}】`)
        .replace(/■ /g, "  ")
        .trim();
      return `${block}\n`;
    }

    // フォールバック: 案件名 + 本文全体（挨拶・締めを除ける範囲）
    const afterGreeting = sliced.indexOf(greetingMarker);
    const core =
      afterGreeting >= 0
        ? sliced.slice(afterGreeting + greetingMarker.length).trim()
        : sliced.trim();
    const title = draft.project_title || draft.project_id || `案件${index + 1}`;
    return `【${index + 1}】${title}\n\n${core}\n`;
  });
  return `${header}${blocks.join("\n")}ご検討のほど、よろしくお願いいたします。\n`;
}

type ScreenProps = {
  path: string;
  searchParams?: SearchParams;
};

type SearchParams = Record<string, string | string[] | undefined>;

const fallbackSkillGroups = [
  {
    label: "開発言語",
    options: ["Java", "Kotlin", "TypeScript", "Python"],
  },
  {
    label: "環境",
    options: ["AWS", "Docker", "Linux"],
  },
  {
    label: "フレームワーク/パッケージ",
    options: ["Spring", "Vue.js", "React", "Next.js"],
  },
];

export function ScreenRouter({ path, searchParams = {} }: ScreenProps) {
  return <AppShell activePath={path}>{renderScreen(path, searchParams)}</AppShell>;
}

function renderScreen(path: string, searchParams: SearchParams) {
  if (path === "/") return <DashboardScreen />;
  if (path === "/talents") return <TalentsScreen searchParams={searchParams} />;
  if (path === "/talents/new") return <TalentFormScreen />;
  if (path.startsWith("/talents/"))
    return <TalentDetailScreen talentId={path.split("/")[2] ?? ""} searchParams={searchParams} />;
  if (path === "/projects") return <ProjectsScreen searchParams={searchParams} />;
  if (path === "/projects/new") return <ProjectFormScreen />;
  if (path.startsWith("/projects/"))
    return <ProjectDetailScreen projectId={path.split("/")[2] ?? ""} searchParams={searchParams} />;
  if (path === "/companies") return <CompaniesScreen />;
  if (path === "/companies/new") return <CompanyFormScreen mode="new" />;
  if (path.startsWith("/companies/") && path.endsWith("/edit")) {
    return <CompanyFormScreen mode="edit" companyId={path.split("/")[2] ?? ""} />;
  }
  if (path.startsWith("/companies/")) return <CompanyDetailScreen companyId={path.split("/")[2] ?? ""} />;
  if (path === "/contacts") return <ContactsScreen />;
  if (path === "/contacts/new") return <ContactFormScreen mode="new" searchParams={searchParams} />;
  if (path.startsWith("/contacts/") && path.endsWith("/edit")) {
    return <ContactFormScreen mode="edit" contactId={path.split("/")[2] ?? ""} />;
  }
  if (path === "/emails") return <EmailsScreen />;
  if (path === "/settings") return <SettingsScreen searchParams={searchParams} />;
  return <NotFoundScreen />;
}

function formatPipelineElapsed(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}秒`;
  }
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return rem > 0 ? `${minutes}分${rem}秒` : `${minutes}分`;
}

function formatGmailQueueCount(count: number | null | undefined, capped?: boolean): string {
  if (count == null) {
    return "—";
  }
  return capped ? `${count}+` : String(count);
}

/** 人材+案件の合計。2000超（打ち切りで実数がそれ以上の場合含む）は 2000+ */
function formatGmailQueueTotal(
  talentCount: number,
  projectCount: number,
  talentCapped?: boolean,
  projectCapped?: boolean,
): string {
  const total = talentCount + projectCount;
  const capped = Boolean(talentCapped || projectCapped);
  if (total > 2000 || (total >= 2000 && capped)) {
    return "2000+";
  }
  if (capped) {
    return `${total}+`;
  }
  return String(total);
}

function formatPipelineDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) {
    return "—";
  }
  return formatPipelineElapsed(seconds);
}

function MailIngestProgressPanel({ progress }: { progress: PipelineProgressDto }) {
  if (progress.status === "not_found") {
    return null;
  }

  const tone =
    progress.status === "failed"
      ? progress.error_message === "処理が停止されました" || progress.error_message === "処理が中断されました"
        ? "cancelled"
        : "failed"
      : progress.status === "completed"
        ? "completed"
        : "running";

  const totalEstimate = progress.total_estimated_seconds ?? null;

  return (
    <section className={`pipeline-progress pipeline-progress--${tone}`} aria-live="polite">
      <div className="pipeline-progress-head">
        <strong>
          {progress.status === "completed"
            ? "メール取込が完了しました"
            : progress.error_message === "処理が停止されました"
              ? "メール取込を停止しました"
              : progress.error_message === "処理が中断されました"
                ? "メール取込が中断されています"
                : progress.status === "failed"
                  ? "メール取込に失敗しました"
                  : "メール取込を実行中"}
        </strong>
        {progress.status === "running" && progress.eta_label ? (
          <span className="pipeline-progress-eta">全体の残り: {progress.eta_label}</span>
        ) : null}
      </div>
      <div
        className="pipeline-progress-bar pipeline-progress-bar--overall"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.progress_percent}
        aria-label="全体の進捗"
      >
        <span className="pipeline-progress-bar-fill" style={{ width: `${progress.progress_percent}%` }} />
      </div>
      <div className="pipeline-progress-meta">
        <span>全体 {progress.progress_percent}%</span>
        <span>
          工程 {progress.current_step}/{progress.total_steps}: {progress.phase_label}
        </span>
        <span>経過 {formatPipelineElapsed(progress.elapsed_seconds)}</span>
        {totalEstimate != null && progress.status === "running" ? (
          <span>想定 {formatPipelineDuration(totalEstimate)}</span>
        ) : null}
      </div>
      {progress.detail ? <p className="pipeline-progress-detail muted">{progress.detail}</p> : null}
      {progress.steps.length > 0 ? (
        <ol className="pipeline-step-list">
          {progress.steps.map((step) => (
            <li
              key={step.id}
              className={`pipeline-step pipeline-step--${step.status}`}
              aria-current={step.status === "running" ? "step" : undefined}
            >
              <div className="pipeline-step-head">
                <span className="pipeline-step-label">{step.label}</span>
                <span className="pipeline-step-percent">{step.progress_percent}%</span>
              </div>
              <div
                className="pipeline-progress-bar pipeline-progress-bar--step"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={step.progress_percent}
                aria-label={`${step.label}の進捗`}
              >
                <span className="pipeline-progress-bar-fill" style={{ width: `${step.progress_percent}%` }} />
              </div>
              <div className="pipeline-step-meta muted">
                <span>経過 {formatPipelineElapsed(step.elapsed_seconds)}</span>
                {step.status === "running" && step.eta_label ? <span>残り {step.eta_label}</span> : null}
                {step.status === "completed" ? <span>完了</span> : null}
                {step.status === "pending" ? <span>待機中</span> : null}
                {step.detail ? <span>{step.detail}</span> : null}
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      {progress.status === "failed" && progress.error_message ? (
        <p className="pipeline-progress-error">
          {progress.error_code ?? "ERR-0030"}: {progress.error_message}
        </p>
      ) : null}
    </section>
  );
}

type MailIngestProgressCallbacks = {
  onCompleted?: () => void | Promise<void>;
  onFailed?: (progress: PipelineProgressDto) => void;
};

function useMailIngestProgress(callbacks?: MailIngestProgressCallbacks) {
  const [progress, setProgress] = useState<PipelineProgressDto | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const jobIdRef = useRef<string | null>(null);
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;

  useEffect(() => {
    let cancelled = false;
    fetchGmailPipelineProgress()
      .then((initial) => {
        if (cancelled || initial.status !== "running") {
          return;
        }
        jobIdRef.current = initial.job_id;
        setProgress(initial);
        setIsRunning(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isRunning) {
      return;
    }
    const poll = async () => {
      const jobId = jobIdRef.current;
      if (!jobId) {
        return;
      }
      try {
        const next = await fetchGmailPipelineProgress(jobId);
        setProgress(next);
        if (next.status === "completed") {
          setIsRunning(false);
          await callbacksRef.current?.onCompleted?.();
        } else if (next.status === "failed") {
          setIsRunning(false);
          callbacksRef.current?.onFailed?.(next);
        }
      } catch {
        // 次回ポーリングで再試行
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => window.clearInterval(timer);
  }, [isRunning]);

  async function startMailIngest() {
    setIsRunning(true);
    setProgress(null);
    const result = await runGmailPipelineBatch();
    jobIdRef.current = result.job_id ?? null;
    if (jobIdRef.current) {
      const initial = await fetchGmailPipelineProgress(jobIdRef.current);
      setProgress(initial);
    }
  }

  async function syncProgress() {
    const jobId = jobIdRef.current;
    try {
      const next = jobId ? await fetchGmailPipelineProgress(jobId) : await fetchGmailPipelineProgress();
      if (next.status === "not_found") {
        setProgress(null);
        setIsRunning(false);
        return;
      }
      if (!jobId && next.job_id) {
        jobIdRef.current = next.job_id;
      }
      setProgress(next);
      setIsRunning(next.status === "running");
      if (next.status === "completed") {
        await callbacksRef.current?.onCompleted?.();
      } else if (next.status === "failed" && next.error_message !== "処理が停止されました" && next.error_message !== "処理が中断されました") {
        callbacksRef.current?.onFailed?.(next);
      }
    } catch {
      setIsRunning(false);
    }
  }

  return { progress, isRunning, startMailIngest, syncProgress };
}

function useRunningBatchJobs() {
  const [jobs, setJobs] = useState<RunningBatchJobDto[]>([]);

  const refresh = async () => {
    try {
      const result = await fetchRunningBatchJobs();
      setJobs(result.jobs);
    } catch {
      setJobs([]);
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, []);

  return { jobs, refresh };
}

function DashboardScreen() {
  const [isRunningMatchScore, setIsRunningMatchScore] = useState(false);
  const [mailIngestError, setMailIngestError] = useState<{ code: string; message: string } | null>(null);
  const [matchScoreError, setMatchScoreError] = useState<{ code: string; message: string } | null>(null);
  const [matchScoreNotice, setMatchScoreNotice] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<DashboardDto | null>(null);
  const [emails, setEmails] = useState<EmailDto[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [chartBusy, setChartBusy] = useState(false);
  const [chartRange, setChartRange] = useState<DashboardPeriodRange>("month");
  const [chartEnd, setChartEnd] = useState<string | undefined>(undefined);
  const [isStoppingBatch, setIsStoppingBatch] = useState(false);
  const [batchStopNotice, setBatchStopNotice] = useState<string | null>(null);

  const { jobs: runningBatchJobs, refresh: refreshRunningBatchJobs } = useRunningBatchJobs();

  const {
    progress: mailIngestProgress,
    isRunning: isRunningMailIngest,
    startMailIngest,
    syncProgress: syncMailIngestProgress,
  } = useMailIngestProgress({
    onCompleted: async () => {
      const [dash, mailList] = await Promise.all([
        fetchDashboard({ range: chartRange, end: chartEnd }),
        fetchEmails(),
      ]);
      setDashboard(dash);
      setEmails(mailList.slice(0, 8));
    },
    onFailed: (failedProgress) => {
      if (failedProgress.error_message === "処理が停止されました" || failedProgress.error_message === "処理が中断されました") {
        return;
      }
      setMailIngestError({
        code: failedProgress.error_code ?? "ERR-0030",
        message: failedProgress.error_message ?? "メール取込・ルール採点・返信同期の実行に失敗しました",
      });
    },
  });

  useEffect(() => {
    fetchEmails()
      .then((mailList) => setEmails(mailList.slice(0, 8)))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setChartBusy(true);
    setLoadError(null);
    fetchDashboard({ range: chartRange, end: chartEnd })
      .then((dash) => {
        if (!cancelled) {
          setDashboard(dash);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError("ダッシュボードの取得に失敗しました");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setChartBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [chartRange, chartEnd]);

  async function handleStopBatch() {
    const labels =
      runningBatchJobs.length > 0
        ? runningBatchJobs.map((job) => job.job_label).join("、")
        : isRunningMailIngest
          ? "メール取込"
          : isRunningMatchScore
            ? "ルール採点"
            : "実行中の処理";
    const confirmed = window.confirm(`${labels} を停止します。よろしいですか？`);
    if (!confirmed) {
      return;
    }
    setIsStoppingBatch(true);
    setBatchStopNotice(null);
    setMailIngestError(null);
    try {
      const result = await stopRunningBatchJobs();
      setBatchStopNotice(result.message);
      setIsRunningMatchScore(false);
      await syncMailIngestProgress();
      await refreshRunningBatchJobs();
    } catch {
      setMailIngestError({ code: "ERR-0030", message: "処理の停止に失敗しました" });
    } finally {
      setIsStoppingBatch(false);
    }
  }

  async function handleMailIngest() {
    setMailIngestError(null);
    try {
      await startMailIngest();
    } catch (error) {
      if (error instanceof BatchRunError) {
        setMailIngestError({ code: error.errorCode, message: error.errorMessage });
      } else {
        setMailIngestError({ code: "ERR-0030", message: "メール取込・ルール採点・返信同期の開始に失敗しました" });
      }
    }
  }

  async function handleUnscoredMatchScore() {
    const unscoredTalents = dashboard?.unscored_talent_count ?? 0;
    const unscoredProjects = dashboard?.unscored_project_count ?? 0;
    if (unscoredTalents <= 0 && unscoredProjects <= 0) {
      setMatchScoreError(null);
      setMatchScoreNotice("未採点の人材・案件はありません。");
      return;
    }
    const confirmed = window.confirm(
      `未採点の人材 ${unscoredTalents} 件・案件 ${unscoredProjects} 件向けに増分ルール採点を実行します。\n` +
        `既に採点済みの人材×案件は再計算しません。よろしいですか？`,
    );
    if (!confirmed) {
      return;
    }
    setIsRunningMatchScore(true);
    setMatchScoreError(null);
    setMatchScoreNotice(null);
    try {
      const result = await runMatchScoreBatch({ force: false });
      setMatchScoreNotice(
        `未採点ルール採点が完了しました（${formatMatchRunStatusLabel(result.status)}）: 組合せ ${String(result.stats?.match_count ?? "-")} 件` +
          (result.stats?.scored_count != null ? ` / 新規採点 ${String(result.stats.scored_count)} 件` : ""),
      );
      const dash = await fetchDashboard({ range: chartRange, end: chartEnd });
      setDashboard(dash);
    } catch (error) {
      if (error instanceof BatchRunError) {
        setMatchScoreError({ code: error.errorCode, message: error.errorMessage });
      } else {
        setMatchScoreError({ code: "ERR-0030", message: "ルール採点の実行に失敗しました" });
      }
    } finally {
      setIsRunningMatchScore(false);
    }
  }

  async function handleForceMatchScore() {
    const talentCount = dashboard?.talent_count ?? 0;
    const projectCount = dashboard?.project_count ?? 0;
    if (talentCount <= 0 || projectCount <= 0) {
      setMatchScoreError(null);
      setMatchScoreNotice("採点対象の人材または案件がありません。");
      return;
    }
    const pairEstimate = talentCount * projectCount;
    const confirmed = window.confirm(
      `【注意】全件強制再採点を実行します。\n\n` +
        `対象の目安: 人材 ${talentCount} × 案件 ${projectCount} ≒ ${pairEstimate} 組合せ\n` +
        `既に採点済みのスコアもルール再計算で差し替えます（時間がかかることがあります）。\n\n` +
        `本当に実行しますか？`,
    );
    if (!confirmed) {
      return;
    }
    setIsRunningMatchScore(true);
    setMatchScoreError(null);
    setMatchScoreNotice(null);
    try {
      const result = await runMatchScoreBatch({ force: true });
      setMatchScoreNotice(
        `全件強制再採点が完了しました（${formatMatchRunStatusLabel(result.status)}）: 組合せ ${String(result.stats?.match_count ?? "-")} 件`,
      );
      const dash = await fetchDashboard({ range: chartRange, end: chartEnd });
      setDashboard(dash);
    } catch (error) {
      if (error instanceof BatchRunError) {
        setMatchScoreError({ code: error.errorCode, message: error.errorMessage });
      } else {
        setMatchScoreError({ code: "ERR-0030", message: "全件強制再採点に失敗しました" });
      }
    } finally {
      setIsRunningMatchScore(false);
    }
  }

  const daily = dashboard?.daily ?? [];
  const periodLabel =
    dashboard?.period_start && dashboard?.period_end
      ? `${dashboard.period_start} 〜 ${dashboard.period_end}`
      : "期間を読み込み中";
  const canGoForward = Boolean(dashboard?.can_go_forward);
  const busy = isRunningMailIngest || isRunningMatchScore || isStoppingBatch;
  const canStopBatch =
    runningBatchJobs.length > 0 || isRunningMailIngest || isRunningMatchScore;
  const runningBatchLabel =
    runningBatchJobs.length > 0
      ? runningBatchJobs.map((job) => job.job_label).join(" / ")
      : null;
  const unscoredTalentCount = dashboard?.unscored_talent_count ?? 0;
  const unscoredProjectCount = dashboard?.unscored_project_count ?? 0;
  const hasUnscored = unscoredTalentCount > 0 || unscoredProjectCount > 0;
  const matchScoreLabel = hasUnscored
    ? `未採点ルール採点（人材${unscoredTalentCount}/案件${unscoredProjectCount}）`
    : "未採点ルール採点";
  const gmailTalentCount = dashboard?.gmail_ingest_talent_count;
  const gmailProjectCount = dashboard?.gmail_ingest_project_count;
  const hasGmailQueueCounts = gmailTalentCount != null && gmailProjectCount != null;
  const gmailQueueTotal = hasGmailQueueCounts
    ? formatGmailQueueTotal(
        gmailTalentCount,
        gmailProjectCount,
        dashboard?.gmail_ingest_talent_count_capped,
        dashboard?.gmail_ingest_project_count_capped,
      )
    : null;
  const gmailTalentLabel = dashboard?.gmail_ingest_talent_label || "人材ラベル";
  const gmailProjectLabel = dashboard?.gmail_ingest_project_label || "案件ラベル";

  const onSelectRange = (next: DashboardPeriodRange) => {
    setChartRange(next);
    setChartEnd(undefined);
  };

  const onShiftPeriod = (direction: -1 | 1) => {
    if (!dashboard?.period_start || !dashboard.period_end) {
      return;
    }
    if (direction === 1 && !canGoForward) {
      return;
    }
    const days = dashboard.period_days || DASHBOARD_PERIOD_DAYS[chartRange];
    if (direction === -1) {
      const prevEnd = shiftIsoDate(dashboard.period_start, -1);
      setChartEnd(prevEnd);
      return;
    }
    const nextEnd = shiftIsoDate(dashboard.period_end, days);
    setChartEnd(nextEnd);
  };

  return (
    <>
      <Topbar
        title="ダッシュボード"
        description="人材・案件・応募・取込の概況"
        actions={
          <>
            {canStopBatch ? (
              <button
                className="btn btn-danger"
                type="button"
                disabled={isStoppingBatch}
                onClick={() => void handleStopBatch()}
                title={runningBatchLabel ?? "実行中のバッチ処理を停止します"}
              >
                {isStoppingBatch ? "停止中..." : "処理停止"}
              </button>
            ) : null}
            <button
              className="btn btn-secondary"
              type="button"
              disabled={busy || !hasUnscored}
              onClick={() => void handleUnscoredMatchScore()}
              title={
                hasUnscored
                  ? "一度もルール採点されていない人材・案件だけを増分採点します"
                  : "未採点の人材・案件はありません"
              }
            >
              {isRunningMatchScore ? "採点中..." : matchScoreLabel}
            </button>
            <button
              className="btn btn-danger"
              type="button"
              disabled={busy || (dashboard?.talent_count ?? 0) <= 0 || (dashboard?.project_count ?? 0) <= 0}
              onClick={() => void handleForceMatchScore()}
              title="active 人材 × open 案件をすべてルール再計算します（重い処理）"
            >
              {isRunningMatchScore ? "採点中..." : "全件強制再採点"}
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={busy}
              onClick={() => void handleMailIngest()}
            >
              {isRunningMailIngest ? "取込中..." : "メール取り込み"}
            </button>
          </>
        }
      />
      {mailIngestError ? (
        <p className="notice">
          {mailIngestError.code}: {mailIngestError.message}
        </p>
      ) : null}
      {batchStopNotice ? <p className="notice">{batchStopNotice}</p> : null}
      {runningBatchLabel ? <p className="muted batch-running-label">実行中: {runningBatchLabel}</p> : null}
      {mailIngestProgress && mailIngestProgress.status !== "not_found" ? (
        <MailIngestProgressPanel progress={mailIngestProgress} />
      ) : null}
      {matchScoreError ? (
        <p className="notice">
          {matchScoreError.code}: {matchScoreError.message}
        </p>
      ) : null}
      {matchScoreNotice ? <p className="notice">{matchScoreNotice}</p> : null}
      {loadError ? <p className="notice">{loadError}</p> : null}
      <section className="stats">
        <StatCard label="登録人材" value={dashboard?.talent_count ?? 0} meta={<Link href="/talents">一覧へ</Link>} />
        <StatCard label="登録案件" value={dashboard?.project_count ?? 0} meta={<Link href="/projects">一覧へ</Link>} />
        <StatCard
          label="未処理メール"
          value={gmailQueueTotal ?? "—"}
          meta={
            <>
              {hasGmailQueueCounts ? (
                <span className="muted">
                  {gmailTalentLabel}{" "}
                  {formatGmailQueueCount(gmailTalentCount, dashboard?.gmail_ingest_talent_count_capped)} ·{" "}
                  {gmailProjectLabel}{" "}
                  {formatGmailQueueCount(gmailProjectCount, dashboard?.gmail_ingest_project_count_capped)}
                </span>
              ) : (
                <span className="muted">Gmail ラベル件数を取得できません</span>
              )}{" "}
              <Link href="/emails">取込へ</Link>
            </>
          }
        />
        <StatCard
          label="提案中"
          value={
            (dashboard?.talent_proposal_sent_count ?? 0) + (dashboard?.project_proposal_sent_count ?? 0)
          }
          meta={
            <span className="muted">
              案件提案 {dashboard?.talent_proposal_sent_count ?? 0} · 要員提案{" "}
              {dashboard?.project_proposal_sent_count ?? 0}
            </span>
          }
        />
      </section>
      <div className="chart-period-controls chart-period-controls--page">
        <div className="chart-range-tabs" role="group" aria-label="表示期間">
          {(
            [
              ["week", "1週間"],
              ["month", "1か月"],
              ["half_year", "半年"],
              ["year", "1年"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`btn btn-compact ${chartRange === value ? "btn-primary" : "btn-secondary"}`}
              disabled={chartBusy}
              onClick={() => onSelectRange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="chart-period-nav">
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            disabled={chartBusy || !dashboard}
            onClick={() => onShiftPeriod(-1)}
            aria-label="前の期間"
          >
            ←
          </button>
          <span className="muted chart-period-label">{chartBusy ? "読み込み中…" : periodLabel}</span>
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            disabled={chartBusy || !canGoForward}
            onClick={() => onShiftPeriod(1)}
            aria-label="次の期間"
          >
            →
          </button>
        </div>
      </div>
      <Panel
        title={
          <span className="th-with-help">
            供給バランス
            <HelpTooltip label="供給バランスの説明">
              <p>
                <strong>説明</strong>
                … 期間内に取り込んだメールの内訳です。案件/人材の偏りと、提案済みかどうかが分かります。
              </p>
              <p>
                <strong>棒の高さ</strong>
                … その日（週/月）の取込総数
              </p>
              <p>
                <strong>内訳（葉）</strong>
              </p>
              <p>案件・人材未提案 … email_type=project かつ 紐づく案件に人材提案（project_proposal）の sent が無い</p>
              <p>案件・人材提案済 … email_type=project かつ 人材提案 sent あり（現在時点）</p>
              <p>人材・案件未提案 … email_type=talent かつ 紐づく人材に案件提案（talent_proposal）の sent が無い</p>
              <p>人材・案件提案済 … email_type=talent かつ 案件提案 sent あり（現在時点）</p>
              <p>その他 … email_type が上記以外（unknown 等）</p>
              <p>
                <strong>提案済率</strong>
                … 案件側 = 案件・人材提案済 ÷ 案件メール、人材側 = 人材・案件提案済 ÷ 人材メール
              </p>
            </HelpTooltip>
          </span>
        }
      >
        <p className="chart-period-summary muted">
          期間合計: 総数 {dashboard?.emails_total ?? 0}
          {" · "}
          案件 {dashboard?.emails_project ?? 0}
          （提案済 {dashboard?.project_proposed_rate ?? 0}%）
          {" · "}
          人材 {dashboard?.emails_talent ?? 0}
          （提案済 {dashboard?.talent_proposed_rate ?? 0}%）
          {chartBucketHint(chartRange) ? ` · ${chartBucketHint(chartRange)}` : ""}
        </p>
        <DailyStackedBarChart
          points={daily}
          periodRange={chartRange}
          emptyLabel="この期間の取込データはありません"
        />
        <CompanyIngestBars rows={dashboard?.by_company ?? []} />
      </Panel>
      <Panel
        title={
          <span className="th-with-help">
            ファネル（取込 → OK）
            <HelpTooltip label="ファネルの説明">
              <p>
                <strong>説明</strong>
                … 期間内に取り込んだ人材・案件が、提案可能→提案→返信→OK まで進んだ件数です。
              </p>
              <p>
                <strong>各段</strong>
              </p>
              <p>取込 … 期間内取込メールに紐づく人材数 + 案件数</p>
              <p>提案可能 … 取込 entity のうち、最新 match_run で score &gt; 0 の相手が1件以上ある件数</p>
              <p>提案済 … 提案可能のうち、対応する提案メール（sent）がある件数</p>
              <p>返信あり … 提案済のうち、最新返信が存在する件数</p>
              <p>OK … 返信ありのうち、judgment = ok の件数</p>
              <p>
                <strong>前段比</strong>
                … 当該段 ÷ 直前段 × 100
              </p>
              <p>
                <strong>制約ロス</strong>
                … 取込 − 提案可能。内訳は最新マッチの score_breakdown.hard_reject（外国籍NG / 商流 / その他スコア0）
              </p>
            </HelpTooltip>
          </span>
        }
      >
        <FunnelPanel funnel={dashboard?.funnel} />
      </Panel>
      <Panel
        title={
          <span className="th-with-help">
            スコア帯別 OK率
            <HelpTooltip label="スコア帯別OK率の説明">
              <p>
                <strong>説明</strong>
                … 期間内に送信した提案を、紐づくマッチの score_band ごとに集計した OK 率です。
              </p>
              <p>
                <strong>対象</strong>
                … sent_at が期間内の talent_proposal / project_proposal
              </p>
              <p>
                <strong>OK率</strong>
                … OK件数 ÷ 提案件数 × 100（帯未設定は「不明」）
              </p>
              <p>
                <strong>OK件数</strong>
                … 当該提案の最新返信 judgment = ok
              </p>
              <p>棒の長さは OK率（最大 100%）です。</p>
            </HelpTooltip>
          </span>
        }
      >
        <ScoreBandOkBars rows={dashboard?.ok_by_score_band ?? []} />
      </Panel>
      <Panel title="最近の処理状況">
        <table className="table">
          <tbody>
            {emails.map((mail) => (
              <tr key={mail.id}>
                <td>{mail.id.slice(0, 8)}</td>
                <td>{mail.subject}</td>
                <td><Badge tone={mail.status === "pending" || mail.status === "failed" || mail.status === "needs_review" ? "warn" : "ok"}>{formatEmailStatusLabel(mail.status)}</Badge></td>
                <td>{mail.talent_id ? `人材 ${mail.talent_id.slice(0, 8)}` : mail.project_id ? `案件 ${mail.project_id.slice(0, 8)}` : "-"}</td>
              </tr>
            ))}
            {emails.length === 0 ? (
              <tr><td colSpan={4}><span className="muted">取込メールはまだありません。</span></td></tr>
            ) : null}
          </tbody>
        </table>
      </Panel>
    </>
  );
}

const DASHBOARD_PERIOD_DAYS: Record<DashboardPeriodRange, number> = {
  week: 7,
  month: 30,
  half_year: 182,
  year: 365,
};

function shiftIsoDate(iso: string, deltaDays: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + deltaDays);
  const yy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

type ChartBucketPoint = {
  date: string;
  emails_total: number;
  emails_project: number;
  emails_talent: number;
  project_unproposed: number;
  project_proposed: number;
  talent_unproposed: number;
  talent_proposed: number;
  emails_other: number;
  proposals_project_offer: number;
  proposals_talent_offer: number;
};

type StackedSeriesKey =
  | "project_unproposed"
  | "project_proposed"
  | "talent_unproposed"
  | "talent_proposed"
  | "emails_other";

function emptyBucket(date: string): ChartBucketPoint {
  return {
    date,
    emails_total: 0,
    emails_project: 0,
    emails_talent: 0,
    project_unproposed: 0,
    project_proposed: 0,
    talent_unproposed: 0,
    talent_proposed: 0,
    emails_other: 0,
    proposals_project_offer: 0,
    proposals_talent_offer: 0,
  };
}

function chartBucketHint(periodRange: DashboardPeriodRange): string {
  if (periodRange === "half_year") {
    return "週合計";
  }
  if (periodRange === "year") {
    return "月合計";
  }
  return "";
}

function sumChartChunk(chunk: DashboardDailyPointDto[]): ChartBucketPoint {
  const summed = chunk.reduce((acc, point) => {
    acc.emails_total += point.emails_total;
    acc.emails_project += point.emails_project;
    acc.emails_talent += point.emails_talent;
    acc.project_unproposed += point.project_unproposed ?? 0;
    acc.project_proposed += point.project_proposed ?? 0;
    acc.talent_unproposed += point.talent_unproposed ?? 0;
    acc.talent_proposed += point.talent_proposed ?? 0;
    acc.emails_other += point.emails_other ?? 0;
    acc.proposals_project_offer += point.proposals_project_offer;
    acc.proposals_talent_offer += point.proposals_talent_offer;
    return acc;
  }, emptyBucket(chunk[0]?.date ?? ""));
  return summed;
}

/** 表示期間に応じて日次を週/月バケットへ集約する。 */
function aggregateChartPoints(
  points: DashboardDailyPointDto[],
  periodRange: DashboardPeriodRange,
): ChartBucketPoint[] {
  if (points.length === 0) {
    return [];
  }
  if (periodRange === "week" || periodRange === "month") {
    return points.map((point) => ({
      date: point.date,
      emails_total: point.emails_total,
      emails_project: point.emails_project,
      emails_talent: point.emails_talent,
      project_unproposed: point.project_unproposed ?? 0,
      project_proposed: point.project_proposed ?? 0,
      talent_unproposed: point.talent_unproposed ?? 0,
      talent_proposed: point.talent_proposed ?? 0,
      emails_other: point.emails_other ?? 0,
      proposals_project_offer: point.proposals_project_offer,
      proposals_talent_offer: point.proposals_talent_offer,
    }));
  }
  if (periodRange === "half_year") {
    const buckets: ChartBucketPoint[] = [];
    for (let i = 0; i < points.length; i += 7) {
      buckets.push(sumChartChunk(points.slice(i, i + 7)));
    }
    return buckets;
  }
  const byMonth = new Map<string, DashboardDailyPointDto[]>();
  for (const point of points) {
    const key = point.date.slice(0, 7);
    const list = byMonth.get(key);
    if (list) {
      list.push(point);
    } else {
      byMonth.set(key, [point]);
    }
  }
  return [...byMonth.values()].map((chunk) => sumChartChunk(chunk));
}

/** 期間の長さに合わせた横軸ラベル位置。 */
function xLabelIndexesForPeriod(
  pointCount: number,
  periodRange: DashboardPeriodRange,
  points: { date: string }[],
): number[] {
  if (pointCount <= 1) {
    return pointCount === 1 ? [0] : [];
  }

  const pushUnique = (indexes: number[], value: number) => {
    if (!indexes.includes(value)) {
      indexes.push(value);
    }
  };

  const pushEndIfSpaced = (indexes: number[], minGap: number) => {
    const end = pointCount - 1;
    const last = indexes[indexes.length - 1];
    if (last == null) {
      indexes.push(end);
      return;
    }
    if (last === end) {
      return;
    }
    if (end - last >= minGap) {
      pushUnique(indexes, end);
      return;
    }
    if (last !== 0) {
      indexes[indexes.length - 1] = end;
    }
  };

  if (periodRange === "week") {
    return Array.from({ length: pointCount }, (_, i) => i);
  }

  if (periodRange === "month") {
    const indexes: number[] = [];
    for (let i = 0; i < pointCount; i += 7) {
      pushUnique(indexes, i);
    }
    pushEndIfSpaced(indexes, 4);
    return indexes;
  }

  if (periodRange === "half_year") {
    const indexes: number[] = [];
    for (let i = 0; i < pointCount; i += 2) {
      pushUnique(indexes, i);
    }
    pushEndIfSpaced(indexes, 1);
    return indexes;
  }

  // year（月バケット）→ すべて、または多い場合は間引き
  if (pointCount <= 12) {
    return Array.from({ length: pointCount }, (_, i) => i);
  }
  const indexes: number[] = [0];
  for (let i = 1; i < pointCount; i += 1) {
    const prevMonth = points[i - 1]?.date.slice(5, 7);
    const month = points[i]?.date.slice(5, 7);
    if (prevMonth && month && prevMonth !== month) {
      pushUnique(indexes, i);
    }
  }
  pushEndIfSpaced(indexes, 1);
  return indexes;
}

function formatChartAxisDay(
  iso: string,
  labelIndex: number,
  labelIndexes: number[],
  points: { date: string }[],
  periodRange: DashboardPeriodRange,
): string {
  const parts = iso.split("-");
  if (parts.length !== 3) {
    return iso;
  }
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  const prevIso = labelIndex > 0 ? points[labelIndexes[labelIndex - 1]]?.date : null;
  const prevYear = prevIso?.slice(0, 4);
  const showYear = !prevYear || prevYear !== String(year);
  if (periodRange === "year") {
    return showYear ? `${String(year).slice(2)}/${month}` : `${month}月`;
  }
  if (periodRange === "half_year") {
    return showYear ? `${String(year).slice(2)}/${month}/${day}` : `${month}/${day}`;
  }
  return showYear ? `${String(year).slice(2)}/${month}/${day}` : `${month}/${day}`;
}

function DailyStackedBarChart({
  points,
  emptyLabel,
  periodRange = "month",
}: {
  points: DashboardDailyPointDto[];
  emptyLabel: string;
  periodRange?: DashboardPeriodRange;
}) {
  const seriesDef: { key: StackedSeriesKey; label: string; color: string }[] = [
    { key: "project_unproposed", label: "案件・人材未提案", color: "#93c5fd" },
    { key: "project_proposed", label: "案件・人材提案済", color: "#1d4ed8" },
    { key: "talent_unproposed", label: "人材・案件未提案", color: "#fcd34d" },
    { key: "talent_proposed", label: "人材・案件提案済", color: "#b45309" },
    { key: "emails_other", label: "その他", color: "#64748b" },
  ];
  const [visible, setVisible] = useState<Record<StackedSeriesKey, boolean>>({
    project_unproposed: true,
    project_proposed: true,
    talent_unproposed: true,
    talent_proposed: true,
    emails_other: true,
  });

  const buckets = aggregateChartPoints(points, periodRange);
  const activeSeries = seriesDef.filter((s) => visible[s.key]);

  const width = 960;
  const height = 340;
  const padding = { top: 18, right: 28, bottom: 52, left: 40 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const stackTotals = buckets.map((bucket) =>
    activeSeries.reduce((sum, s) => sum + Number(bucket[s.key] ?? 0), 0),
  );
  const maxValue = Math.max(0, ...stackTotals);
  const yMax = Math.max(1, Math.ceil(maxValue * 1.1) || 1);
  const hasData = maxValue > 0;

  const slotW = buckets.length > 0 ? innerW / buckets.length : innerW;
  const barW = Math.max(4, Math.min(36, slotW * 0.62));

  const xCenter = (index: number) => padding.left + slotW * index + slotW / 2;
  const yFor = (value: number) => padding.top + innerH - (value / yMax) * innerH;

  const yTicks = [...new Set([0, Math.round(yMax / 2), yMax])];
  const xLabelIndexes = xLabelIndexesForPeriod(buckets.length, periodRange, buckets);
  const staggerLabels = periodRange === "week";

  const toggleSeries = (key: StackedSeriesKey) => {
    setVisible((current) => {
      const next = { ...current, [key]: !current[key] };
      if (!Object.values(next).some(Boolean)) {
        return current;
      }
      return next;
    });
  };

  return (
    <div className="line-chart">
      <div className="line-chart-legend">
        {seriesDef.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`line-chart-legend-item line-chart-legend-toggle${visible[s.key] ? "" : " is-off"}`}
            onClick={() => toggleSeries(s.key)}
            aria-pressed={visible[s.key]}
          >
            <span className="line-chart-swatch" style={{ background: s.color }} />
            {s.label}
          </button>
        ))}
      </div>
      {!hasData ? <p className="muted line-chart-empty">{emptyLabel}</p> : null}
      <svg className="line-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="供給バランス">
        {yTicks.map((tick) => {
          const y = yFor(tick);
          return (
            <g key={`y-${tick}`}>
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
                className="line-chart-grid"
              />
              <text x={padding.left - 8} y={y + 4} textAnchor="end" className="line-chart-axis">
                {tick}
              </text>
            </g>
          );
        })}
        {xLabelIndexes.map((pointIndex, labelIndex) => {
          const point = buckets[pointIndex];
          if (!point) {
            return null;
          }
          const x = xCenter(pointIndex);
          const staggered = staggerLabels && labelIndex % 2 === 1;
          return (
            <text
              key={`x-${point.date}-${pointIndex}`}
              x={x}
              y={height - (staggered ? 8 : 26)}
              textAnchor={pointIndex === 0 ? "start" : pointIndex === buckets.length - 1 ? "end" : "middle"}
              className="line-chart-axis"
            >
              {formatChartAxisDay(point.date, labelIndex, xLabelIndexes, buckets, periodRange)}
            </text>
          );
        })}
        {buckets.map((bucket, index) => {
          let stacked = 0;
          const cx = xCenter(index);
          const x = cx - barW / 2;
          return (
            <g key={`bar-${bucket.date}-${index}`}>
              {activeSeries.map((s) => {
                const value = Number(bucket[s.key] ?? 0);
                if (value <= 0) {
                  return null;
                }
                const yBottom = yFor(stacked);
                stacked += value;
                const yTop = yFor(stacked);
                const h = Math.max(0, yBottom - yTop);
                return (
                  <rect
                    key={s.key}
                    x={x}
                    y={yTop}
                    width={barW}
                    height={h}
                    fill={s.color}
                  >
                    <title>
                      {bucket.date} {s.label}: {value}（積上 {stacked}）
                    </title>
                  </rect>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function CompanyIngestBars({
  rows,
}: {
  rows: DashboardCompanyIngestDto[];
}) {
  if (rows.length === 0) {
    return <p className="muted chart-subpanel-empty">企業別の取込はまだありません。</p>;
  }
  const maxTotal = Math.max(1, ...rows.map((row) => row.emails_total));
  return (
    <div className="chart-subpanel">
      <h3 className="chart-subpanel-title th-with-help">
        企業別取込（Top）
        <HelpTooltip label="企業別取込の説明">
          <p>
            <strong>説明</strong>
            … 期間内取込を企業別に集計し、供給元の偏りを見ます。
          </p>
          <p>
            <strong>集計</strong>
          </p>
          <p>人材メール … Talent.introducer_company_id</p>
          <p>案件メール … Project.distributor_company_id</p>
          <p>未紐づけ … 「不明」。件数上位 8 社＋「その他」</p>
          <p>
            <strong>棒</strong>
            … 案件件数（青）+ 人材件数（橙）。長さは期間内最大企業の総数を 100% とした比率
          </p>
        </HelpTooltip>
      </h3>
      <div className="h-bar-list">
        {rows.map((row) => {
          const projectPct = (row.emails_project / maxTotal) * 100;
          const talentPct = (row.emails_talent / maxTotal) * 100;
          const label = (
            <span className="h-bar-label">
              {row.company_id ? (
                <Link href={`/companies/${row.company_id}`}>{row.company_name}</Link>
              ) : (
                row.company_name
              )}
            </span>
          );
          return (
            <div className="h-bar-row" key={`${row.company_id ?? "none"}-${row.company_name}`}>
              {label}
              <div className="h-bar-track" title={`案件 ${row.emails_project} / 人材 ${row.emails_talent}`}>
                <span className="h-bar-seg h-bar-seg-project" style={{ width: `${projectPct}%` }} />
                <span className="h-bar-seg h-bar-seg-talent" style={{ width: `${talentPct}%` }} />
              </div>
              <span className="h-bar-value muted">{row.emails_total}</span>
            </div>
          );
        })}
      </div>
      <p className="muted chart-subpanel-legend">
        <span className="line-chart-swatch" style={{ background: "#1d4ed8" }} /> 案件
        {" · "}
        <span className="line-chart-swatch" style={{ background: "#b45309" }} /> 人材
      </p>
    </div>
  );
}

function FunnelPanel({ funnel }: { funnel: DashboardFunnelDto | undefined }) {
  const data = funnel ?? {
    ingested: 0,
    proposable: 0,
    proposed: 0,
    replied: 0,
    ok: 0,
    constraint_loss: { foreign_nationality: 0, commerce_flow: 0, other_zero: 0, total: 0 },
  };
  const stages: { key: string; label: string; value: number; prev: number }[] = [
    { key: "ingested", label: "取込", value: data.ingested, prev: data.ingested },
    { key: "proposable", label: "提案可能", value: data.proposable, prev: data.ingested },
    { key: "proposed", label: "提案済", value: data.proposed, prev: data.proposable },
    { key: "replied", label: "返信あり", value: data.replied, prev: data.proposed },
    { key: "ok", label: "OK", value: data.ok, prev: data.replied },
  ];
  const max = Math.max(1, data.ingested);

  return (
    <div className="funnel-panel">
      <div className="funnel-stages">
        {stages.map((stage, index) => {
          const rate = index === 0 ? 100 : stage.prev > 0 ? Math.round((1000 * stage.value) / stage.prev) / 10 : 0;
          const widthPct = Math.max(8, (stage.value / max) * 100);
          return (
            <div className="funnel-stage" key={stage.key}>
              <div className="funnel-stage-meta">
                <strong>{stage.label}</strong>
                <span>
                  {stage.value}
                  {index > 0 ? <span className="muted">（前段比 {rate}%）</span> : null}
                </span>
              </div>
              <div className="funnel-stage-bar" style={{ width: `${widthPct}%` }} />
            </div>
          );
        })}
      </div>
      <div className="funnel-constraint">
        <h3 className="chart-subpanel-title th-with-help">
          制約ロス（取込 → 提案可能）
          <HelpTooltip label="制約ロスの説明">
            <p>
              <strong>説明</strong>
              … 取り込んだが提案可能にならなかった人材・案件の件数です。
            </p>
            <p>
              <strong>計算</strong>
              … 取込 − 提案可能
            </p>
            <p>
              <strong>内訳</strong>
              … 最新 match_run の score=0 マッチから score_breakdown.hard_reject を優先度付きで集計（外国籍NG → 商流 → その他スコア0）
            </p>
          </HelpTooltip>
        </h3>
        <p className="chart-period-summary muted">
          合計 {data.constraint_loss.total}
          {" · "}
          外国籍NG {data.constraint_loss.foreign_nationality}
          {" · "}
          商流 {data.constraint_loss.commerce_flow}
          {" · "}
          その他スコア0 {data.constraint_loss.other_zero}
        </p>
      </div>
    </div>
  );
}

function ScoreBandOkBars({
  rows,
}: {
  rows: DashboardScoreBandOkDto[];
}) {
  if (rows.length === 0) {
    return <p className="muted">この期間の提案実績はありません。</p>;
  }
  return (
    <div className="h-bar-list">
      {rows.map((row) => (
        <div className="h-bar-row" key={row.score_band}>
          <span className="h-bar-label">帯 {row.score_band}</span>
          <div className="h-bar-track" title={`OK ${row.ok_count} / 提案 ${row.proposed_count}`}>
            <span className="h-bar-seg h-bar-seg-ok" style={{ width: `${Math.min(100, row.ok_rate)}%` }} />
          </div>
          <span className="h-bar-value muted">
            {row.ok_rate}%（{row.ok_count}/{row.proposed_count}）
          </span>
        </div>
      ))}
    </div>
  );
}

const LIST_PAGE_SIZE_OPTIONS = [10, 50, 100] as const;
type ListPageSize = (typeof LIST_PAGE_SIZE_OPTIONS)[number];

function parseListPage(value: string | string[] | undefined): number {
  const parsed = Number.parseInt(asString(value), 10);
  return Number.isFinite(parsed) && parsed >= 1 ? parsed : 1;
}

function parseListPageSize(value: string | string[] | undefined): ListPageSize {
  const parsed = Number.parseInt(asString(value), 10);
  if (parsed === 50 || parsed === 100) {
    return parsed;
  }
  return 10;
}

function paginateListItems<T>(items: T[], page: number, pageSize: number): T[] {
  const start = (page - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

function listPageHref(
  basePath: string,
  searchParams: SearchParams,
  overrides: { page?: number; page_size?: ListPageSize },
): string {
  const params = new URLSearchParams();
  for (const [key, raw] of Object.entries(searchParams)) {
    if (key === "page" || key === "page_size") {
      continue;
    }
    if (Array.isArray(raw)) {
      raw.forEach((item) => {
        if (item) {
          params.append(key, item);
        }
      });
    } else if (raw) {
      params.set(key, raw);
    }
  }
  const page = overrides.page ?? parseListPage(searchParams.page);
  const pageSize = overrides.page_size ?? parseListPageSize(searchParams.page_size);
  if (page > 1) {
    params.set("page", String(page));
  }
  if (pageSize !== 10) {
    params.set("page_size", String(pageSize));
  }
  const qs = params.toString();
  return qs ? `${basePath}?${qs}` : basePath;
}

function listPageNumbers(current: number, total: number): number[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  const pages = new Set<number>([1, total, current, current - 1, current + 1]);
  return [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
}

function ListPagination({
  basePath,
  searchParams,
  page,
  pageSize,
  totalItems,
}: {
  basePath: string;
  searchParams: SearchParams;
  page: number;
  pageSize: ListPageSize;
  totalItems: number;
}) {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = totalItems === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, totalItems);
  const pageNumbers = listPageNumbers(safePage, totalPages);

  return (
    <div className="list-pagination">
      <div className="list-pagination-meta">
        {totalItems === 0 ? "0件" : `${start}–${end}件 / ${totalItems}件`}
      </div>
      <div className="list-pagination-nav">
        {safePage > 1 ? (
          <Link className="list-pagination-link" href={listPageHref(basePath, searchParams, { page: safePage - 1, page_size: pageSize })}>
            前へ
          </Link>
        ) : (
          <span className="list-pagination-link is-disabled">前へ</span>
        )}
        <div className="list-pagination-pages">
          {pageNumbers.map((pageNumber, index) => {
            const prev = pageNumbers[index - 1];
            const showEllipsis = index > 0 && prev != null && pageNumber - prev > 1;
            return (
              <Fragment key={pageNumber}>
                {showEllipsis ? <span className="list-pagination-ellipsis">…</span> : null}
                {pageNumber === safePage ? (
                  <span className="list-pagination-page is-active">{pageNumber}</span>
                ) : (
                  <Link
                    className="list-pagination-page"
                    href={listPageHref(basePath, searchParams, { page: pageNumber, page_size: pageSize })}
                  >
                    {pageNumber}
                  </Link>
                )}
              </Fragment>
            );
          })}
        </div>
        {safePage < totalPages ? (
          <Link className="list-pagination-link" href={listPageHref(basePath, searchParams, { page: safePage + 1, page_size: pageSize })}>
            次へ
          </Link>
        ) : (
          <span className="list-pagination-link is-disabled">次へ</span>
        )}
      </div>
      <div className="list-pagination-size">
        <span className="list-pagination-size-label">表示件数</span>
        {LIST_PAGE_SIZE_OPTIONS.map((size) =>
          size === pageSize ? (
            <span key={size} className="list-pagination-size-btn is-active">
              {size}件
            </span>
          ) : (
            <Link
              key={size}
              className="list-pagination-size-btn"
              href={listPageHref(basePath, searchParams, { page: 1, page_size: size })}
            >
              {size}件
            </Link>
          ),
        )}
      </div>
    </div>
  );
}

function TalentsScreen({ searchParams }: { searchParams: SearchParams }) {
  const [talents, setTalents] = useState<TalentDto[]>([]);
  const [skillGroups, setSkillGroups] = useState(fallbackSkillGroups);
  const [loadError, setLoadError] = useState<string | null>(null);
  const keyword = asString(searchParams.q) || asString(searchParams.name);
  const rateMin = asString(searchParams.rate_min);
  const rateMax = asString(searchParams.rate_max) || asString(searchParams.rate);
  const selectedSkills = asArray(searchParams.skills);
  const proposedFilter = asString(searchParams.proposed);
  const okFilter = asString(searchParams.ok);
  const skillSheetHas = isQueryFlag(searchParams.skill_sheet_has);
  const skillSheetNone = isQueryFlag(searchParams.skill_sheet_none);
  const page = parseListPage(searchParams.page);
  const pageSize = parseListPageSize(searchParams.page_size);

  useEffect(() => {
    fetchTalents()
      .then(setTalents)
      .catch(() => setLoadError("人材一覧の取得に失敗しました"));
    fetchSkillCatalog()
      .then((groups) => {
        const mapped = groups
          .filter((group) => group.options.length > 0)
          .map((group) => ({ label: group.label, options: group.options }));
        if (mapped.length > 0) {
          setSkillGroups(mapped);
        }
      })
      .catch(() => undefined);
  }, []);

  const filteredTalents = filterTalents(talents, {
    keyword,
    rateMin,
    rateMax,
    skills: selectedSkills,
    proposed: proposedFilter,
    ok: okFilter,
    skillSheetHas,
    skillSheetNone,
  });
  const totalPages = Math.max(1, Math.ceil(filteredTalents.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pagedTalents = paginateListItems(filteredTalents, safePage, pageSize);

  const onDeleteTalent = async (talent: TalentDto) => {
    const ok = window.confirm(
      `人材「${talent.display_name}」を削除しますか？\n採点結果・提案メール・返信・取込元メールも削除されます。`,
    );
    if (!ok) {
      return;
    }
    try {
      await deleteTalent(talent.id);
      setTalents((current) => current.filter((row) => row.id !== talent.id));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "人材の削除に失敗しました");
    }
  };

  return (
    <>
      <Topbar
        title="人材一覧"
        description="SES人材紹介メールから要約・登録された人材。画面からも登録できます。"
        actions={
          <ButtonLink href="/talents/new" variant="primary">
            人材を登録
          </ButtonLink>
        }
      />
      {loadError ? <p className="notice">{loadError}</p> : null}
      <KeywordChipFilter
        action="/talents"
        keyword={keyword}
        keywordPlaceholder="氏名 / 所属 / 配信元 / スキル"
        rateMin={rateMin}
        rateMax={rateMax}
        selectedSkills={selectedSkills}
        skillGroups={skillGroups}
        skillsInitiallyClosed
        proposedFilter={proposedFilter}
        okFilter={okFilter}
        showOutreachFilters
        showSkillSheetFilter
        skillSheetHas={skillSheetHas}
        skillSheetNone={skillSheetNone}
      />
      <Panel meta={<span className="muted">検索結果 {filteredTalents.length}件 / 全 {talents.length}件</span>}>
        <ListPagination
          basePath="/talents"
          searchParams={searchParams}
          page={safePage}
          pageSize={pageSize}
          totalItems={filteredTalents.length}
        />
        <SimpleTalentTable
          rows={pagedTalents}
          skillGroups={skillGroups}
          onDelete={(talent) => void onDeleteTalent(talent)}
        />
        <ListPagination
          basePath="/talents"
          searchParams={searchParams}
          page={safePage}
          pageSize={pageSize}
          totalItems={filteredTalents.length}
        />
      </Panel>
    </>
  );
}

function TalentDetailScreen({
  talentId,
  searchParams,
}: {
  talentId: string;
  searchParams: SearchParams;
}) {
  const router = useRouter();
  const [talent, setTalent] = useState<TalentDto | null>(null);
  const [matches, setMatches] = useState<TalentMatchItemDto[]>([]);
  const [skillGroups, setSkillGroups] = useState(fallbackSkillGroups);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<TalentProposeDraftDto[] | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const [draftTo, setDraftTo] = useState("");
  const [draftCc, setDraftCc] = useState("");
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editSourceCompany, setEditSourceCompany] = useState("");
  const [editAffiliation, setEditAffiliation] = useState("");
  const [editAge, setEditAge] = useState("");
  const [editGender, setEditGender] = useState<"unknown" | "male" | "female">("unknown");
  const [editExperienceYears, setEditExperienceYears] = useState("");
  const [editNationality, setEditNationality] = useState<"unknown" | "jp" | "foreign">("unknown");
  const [editCommerceFlow, setEditCommerceFlow] = useState("");
  const [editSkills, setEditSkills] = useState("");
  const [editDesiredRate, setEditDesiredRate] = useState("");
  const [editAvailableFrom, setEditAvailableFrom] = useState("");
  const [editWorkStyle, setEditWorkStyle] = useState("");
  const [editNearestStation, setEditNearestStation] = useState("");
  const [editStatus, setEditStatus] = useState<"active" | "inactive">("active");
  const [editSummary, setEditSummary] = useState("");
  const [editProposalCc, setEditProposalCc] = useState("");
  const proposePanelRef = useRef<HTMLDivElement | null>(null);
  const keyword = asString(searchParams.q) || asString(searchParams.name);
  const rateMin = asString(searchParams.rate_min);
  const rateMax = asString(searchParams.rate_max) || asString(searchParams.rate);
  const selectedSkills = asArray(searchParams.skills);
  const proposedFilter = asString(searchParams.proposed);
  const okFilter = asString(searchParams.ok);

  const filteredMatches = useMemo(
    () =>
      filterTalentMatches(matches, {
        keyword,
        rateMin,
        rateMax,
        skills: selectedSkills,
        proposed: proposedFilter,
        ok: okFilter,
      }),
    [matches, keyword, rateMin, rateMax, selectedSkills, proposedFilter, okFilter],
  );

  const reloadMatches = async () => {
    const list = await fetchTalentMatches(talentId);
    setMatches(list);
  };

  const fillEditForm = (row: TalentDto) => {
    setEditName(row.display_name || "");
    setEditSourceCompany(row.source_company_name || "");
    setEditAffiliation(row.affiliation || "");
    setEditAge(row.age != null ? String(row.age) : "");
    setEditGender(row.gender === "男性" ? "male" : row.gender === "女性" ? "female" : "unknown");
    setEditExperienceYears(row.experience_years != null ? String(row.experience_years) : "");
    setEditNationality(
      row.is_foreign_national === true ? "foreign" : row.is_foreign_national === false ? "jp" : "unknown",
    );
    setEditCommerceFlow(row.commerce_flow || "");
    setEditSkills((row.skills ?? []).join("\n"));
    setEditDesiredRate(
      row.desired_rate == null
        ? ""
        : String(row.desired_rate >= 10000 ? Math.round(row.desired_rate / 10000) : row.desired_rate),
    );
    setEditAvailableFrom(row.available_from || "");
    setEditWorkStyle(row.work_style || "");
    setEditNearestStation(row.nearest_station || "");
    setEditStatus(row.status === "inactive" ? "inactive" : "active");
    setEditSummary(row.summary || "");
    setEditProposalCc((row.proposal_cc_emails ?? []).join(", "));
  };

  const onStartEdit = () => {
    if (!talent) {
      return;
    }
    fillEditForm(talent);
    setEditing(true);
    setActionError(null);
    setMessage(null);
  };

  const onCancelEdit = () => {
    setEditing(false);
    setActionError(null);
  };

  const onSaveTalent = async () => {
    if (!talent) {
      return;
    }
    const name = editName.trim();
    if (!name) {
      setActionError("名前を入力してください");
      return;
    }
    const parseOptionalInt = (raw: string, label: string): number | null | undefined => {
      const text = raw.trim();
      if (!text) {
        return null;
      }
      const n = Number(text);
      if (!Number.isFinite(n) || !Number.isInteger(n) || n < 0) {
        throw new Error(`${label}は0以上の整数で入力してください`);
      }
      return n;
    };
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const age = parseOptionalInt(editAge, "年齢");
      const experienceYears = parseOptionalInt(editExperienceYears, "経験年数");
      const desiredRate = parseOptionalInt(editDesiredRate, "希望単価");
      const saved = await updateTalent(talent.id, {
        display_name: name,
        source_company_name: editSourceCompany.trim() || null,
        affiliation: editAffiliation.trim() || null,
        age: age ?? null,
        gender: editGender === "male" ? "男性" : editGender === "female" ? "女性" : null,
        experience_years: experienceYears ?? null,
        is_foreign_national:
          editNationality === "foreign" ? true : editNationality === "jp" ? false : null,
        commerce_flow: editCommerceFlow.trim() || null,
        skills: editSkills
          .split(/[\n,、]+/)
          .map((part) => part.trim())
          .filter(Boolean),
        desired_rate: desiredRate ?? null,
        available_from: editAvailableFrom.trim() || null,
        work_style: editWorkStyle.trim() || null,
        nearest_station: editNearestStation.trim() || null,
        status: editStatus,
        summary: editSummary.trim() || null,
        proposal_cc_emails: parseAddressList(editProposalCc),
      });
      setTalent(saved);
      setEditing(false);
      setMessage("人材情報を保存しました");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "人材情報の保存に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!drafts || drafts.length === 0) {
      return;
    }
    proposePanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [drafts]);

  useEffect(() => {
    if (!talentId) {
      setLoadError("人材 ID が不正です");
      return;
    }
    setLoadError(null);
    setMatchesError(null);
    fetchTalent(talentId)
      .then(setTalent)
      .catch(() => setLoadError("人材詳細の取得に失敗しました"));
    fetchTalentMatches(talentId)
      .then(setMatches)
      .catch(() => {
        setMatches([]);
        setMatchesError("採点結果の取得に失敗しました。先にルール採点を実行してください。");
      });
    fetchSkillCatalog()
      .then((groups) => {
        const mapped = groups
          .filter((group) => group.options.length > 0)
          .map((group) => ({ label: group.label, options: group.options }));
        if (mapped.length > 0) {
          setSkillGroups(mapped);
        }
      })
      .catch(() => undefined);
  }, [talentId]);

  const selectedIds = Object.entries(selected)
    .filter(([, on]) => on)
    .map(([id]) => id);

  const onSelectAllVisibleMatches = () => {
    setSelected((current) => {
      const next = { ...current };
      for (const row of filteredMatches) {
        next[row.match_id] = true;
      }
      return next;
    });
  };

  const onClearMatchSelection = () => {
    setSelected({});
  };

  const onAiJudgeSelected = async () => {
    if (selectedIds.length === 0) {
      setActionError("AI採点する案件を選択してください");
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const selectedRows = matches.filter((row) => selectedIds.includes(row.match_id));
      const runIds = [...new Set(selectedRows.map((row) => row.match_run_id).filter(Boolean))];
      if (runIds.length === 0) {
        throw new Error("match_run が見つかりません");
      }
      for (const runId of runIds) {
        const idsForRun = selectedRows
          .filter((row) => row.match_run_id === runId)
          .map((row) => row.match_id);
        await runAiJudge(runId, { matchIds: idsForRun });
      }
      setMessage(`選択した ${selectedIds.length} 件をAI採点しました`);
      await reloadMatches();
    } catch (err) {
      if (err instanceof BatchRunError) {
        setActionError(`${err.errorCode}: ${err.errorMessage}`);
      } else {
        setActionError(err instanceof Error ? err.message : "AI採点に失敗しました");
      }
    } finally {
      setBusy(false);
    }
  };

  const onOpenProposePreview = async () => {
    if (selectedIds.length === 0) {
      setActionError("提案する案件を選択してください");
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const list = await previewTalentPropose(selectedIds);
      const editable = list.filter((row) => !row.already_sent);
      if (editable.length === 0) {
        setDrafts(null);
        setDraftBody("");
        setDraftTo("");
        setDraftCc("");
        setActionError("選択した案件はすべて提案済みです");
        return;
      }
      // API は人材ごとに1下書き（複数案件は本文にコア原文を連結済み）。
      // 旧API互換で複数件返ってきた場合のみクライアントで結合する。
      const draft =
        editable.length === 1
          ? {
              ...editable[0],
              match_ids: editable[0].match_ids?.length ? editable[0].match_ids : [editable[0].match_id],
              project_titles: editable[0].project_titles?.length
                ? editable[0].project_titles
                : editable[0].project_title
                  ? [editable[0].project_title]
                  : [],
            }
          : {
              ...editable[0],
              match_ids: editable.flatMap((row) =>
                row.match_ids?.length ? row.match_ids : [row.match_id],
              ),
              project_ids: editable.flatMap((row) =>
                row.project_ids?.length ? row.project_ids : [row.project_id],
              ),
              project_titles: editable.flatMap((row) =>
                row.project_titles?.length
                  ? row.project_titles
                  : row.project_title
                    ? [row.project_title]
                    : [row.project_id],
              ),
              project_title: editable
                .flatMap((row) =>
                  row.project_titles?.length
                    ? row.project_titles
                    : [row.project_title || row.project_id],
                )
                .filter(Boolean)
                .join(" / "),
              body_text: mergeTalentProposeBodies(editable),
              already_sent: false,
            };
      setDrafts([draft]);
      setDraftBody(draft.body_text);
      setDraftTo(draft.to_address || "");
      setDraftCc((draft.cc_addresses && draft.cc_addresses.length > 0) ? draft.cc_addresses.join(", ") : "");
      const skipped = selectedIds.length - draft.match_ids.length;
      if (skipped > 0) {
        setMessage(`${skipped} 件は提案済みのため確認対象から除外しました`);
      }
    } catch (err) {
      setDrafts(null);
      setDraftBody("");
      setDraftTo("");
      setDraftCc("");
      setActionError(err instanceof Error ? err.message : "提案下書きの取得に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onCancelProposePreview = () => {
    setDrafts(null);
    setDraftBody("");
    setDraftTo("");
    setDraftCc("");
  };

  const onSendProposeDrafts = async () => {
    if (!drafts || drafts.length === 0) {
      setActionError("送信する下書きがありません");
      return;
    }
    const draft = drafts[0];
    const bodyText = draftBody.trim();
    if (!bodyText) {
      setActionError("本文が空です");
      return;
    }
    const toAddress = draftTo.trim();
    if (!toAddress) {
      setActionError("宛先を入力してください");
      return;
    }
    const matchIds = draft.match_ids?.length ? draft.match_ids : [draft.match_id];
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await proposeTalents(matchIds, [
        {
          match_id: draft.match_id,
          match_ids: matchIds,
          body_text: bodyText,
          to_address: toAddress,
          cc_addresses: parseAddressList(draftCc),
        },
      ]);
      setMessage(result.message || "案件提案を送信しました");
      setDrafts(null);
      setDraftBody("");
      setDraftTo("");
      setDraftCc("");
      setSelected({});
      await reloadMatches();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "案件提案の送信に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onSyncReplies = async () => {
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await syncOutreachReplies("all");
      setMessage(result.message || "案件提案メールの返信同期が完了しました");
      await reloadMatches();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "返信同期に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onRunMatchScoreForTalent = async () => {
    if (!talent) {
      return;
    }
    const ok = window.confirm(
      `人材「${talent.display_name}」と、公開中の全案件の組み合わせでルール採点します。\n既存のこの人材の採点は上書きされます。よろしいですか？`,
    );
    if (!ok) {
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await runMatchScoreBatch({ force: true, talentId: talent.id });
      setMessage(
        `全案件とのルール採点が完了しました（${formatMatchRunStatusLabel(result.status)}）: 採点 ${String(result.stats?.scored_count ?? "-")} 件`,
      );
      await reloadMatches();
    } catch (err) {
      if (err instanceof BatchRunError) {
        setActionError(`${err.errorCode}: ${err.errorMessage}`);
      } else {
        setActionError(err instanceof Error ? err.message : "ルール採点に失敗しました");
      }
    } finally {
      setBusy(false);
    }
  };

  const onDeleteTalent = async () => {
    if (!talent) {
      return;
    }
    const ok = window.confirm(
      `人材「${talent.display_name}」を削除しますか？\n採点結果・提案メール・返信・取込元メールも削除されます。`,
    );
    if (!ok) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteTalent(talent.id);
      router.push("/talents");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "人材の削除に失敗しました");
      setBusy(false);
    }
  };

  if (loadError) {
    return <Panel title="人材詳細"><p className="muted">{loadError}</p></Panel>;
  }
  if (!talent) {
    return <Panel title="人材詳細"><p className="muted">読み込み中...</p></Panel>;
  }

  return (
    <>
      <Topbar
        title={`${talent.display_name}（${talent.id.slice(0, 8)}）`}
        description="人材プロフィール・採点案件・取込元"
        actions={
          <>
            <ButtonLink href="/talents">人材一覧</ButtonLink>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void onRunMatchScoreForTalent()}>
              {busy ? "処理中…" : "全案件とルール採点"}
            </button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void onSyncReplies()}>
              {busy ? "処理中…" : "返信同期"}
            </button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void onAiJudgeSelected()}>
              {busy ? "処理中…" : "選択をAI採点"}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void onOpenProposePreview()}>
              {busy ? "処理中…" : "案件を提案"}
            </button>
            <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void onDeleteTalent()}>
              {busy ? "処理中…" : "削除"}
            </button>
          </>
        }
      />
      {message ? <p className="notice">{message}</p> : null}
      {actionError ? <p className="notice">{actionError}</p> : null}
      {drafts && drafts.length > 0 ? (
        <div ref={proposePanelRef}>
          <Panel title="案件提案の確認・編集">
            <p className="muted">
              選択した案件は1通のメールにまとめます。本文の案件部分は取込メールのコア原文です。宛先・CC・本文を確認・編集してから送信してください。件名は変更できません。
            </p>
            {drafts.map((draft) => (
              <article key={draft.match_id} className="propose-draft-card">
                <h3>
                  {(draft.project_titles?.length ? draft.project_titles : [draft.project_title || draft.project_id])
                    .filter(Boolean)
                    .join(" / ")}
                </h3>
                <p className="muted">{draft.match_ids?.length ?? 1} 件の案件を1通で送信</p>
                <div className="field">
                  <label htmlFor="propose-to-talent">宛先</label>
                  <input
                    id="propose-to-talent"
                    type="email"
                    value={draftTo}
                    onChange={(event) => setDraftTo(event.target.value)}
                    placeholder="to@example.com"
                  />
                </div>
                <div className="field">
                  <label htmlFor="propose-cc-talent">CC（カンマ区切り）</label>
                  <input
                    id="propose-cc-talent"
                    type="text"
                    value={draftCc}
                    onChange={(event) => setDraftCc(event.target.value)}
                    placeholder="cc1@example.com, cc2@example.com"
                  />
                </div>
                <dl className="kv-list">
                  <Kv label="件名" value={draft.subject} />
                </dl>
                <div className="field">
                  <label htmlFor="propose-body-combined">本文</label>
                  <textarea
                    id="propose-body-combined"
                    rows={16}
                    value={draftBody}
                    onChange={(event) => setDraftBody(event.target.value)}
                  />
                </div>
              </article>
            ))}
            <div className="topbar-actions" style={{ marginTop: 16 }}>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void onSendProposeDrafts()}>
                {busy ? "送信中…" : "送信"}
              </button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={onCancelProposePreview}>
                キャンセル
              </button>
            </div>
          </Panel>
        </div>
      ) : null}
      <CollapsiblePanel title="人材情報" className="detail-info-collapse">
        <section className="detail-layout">
          <article className="detail-card detail-card--nested">
            <div className="detail-card-header">
              <h3>プロフィール</h3>
              {!editing ? (
                <button type="button" className="btn btn-secondary btn-compact" disabled={busy} onClick={onStartEdit}>
                  編集
                </button>
              ) : (
                <div className="topbar-actions">
                  <button type="button" className="btn btn-primary btn-compact" disabled={busy} onClick={() => void onSaveTalent()}>
                    {busy ? "保存中…" : "保存"}
                  </button>
                  <button type="button" className="btn btn-ghost btn-compact" disabled={busy} onClick={onCancelEdit}>
                    キャンセル
                  </button>
                </div>
              )}
            </div>
            {editing ? (
              <form
                className="form-grid"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onSaveTalent();
                }}
              >
                <Field label="名前">
                  <input value={editName} onChange={(event) => setEditName(event.target.value)} required />
                </Field>
                <Field label="配信元">
                  <input
                    value={editSourceCompany}
                    onChange={(event) => setEditSourceCompany(event.target.value)}
                    placeholder="株式会社サンプル"
                  />
                </Field>
                <Field label="所属">
                  <input value={editAffiliation} onChange={(event) => setEditAffiliation(event.target.value)} />
                </Field>
                <Field label="年齢">
                  <input
                    type="number"
                    min={0}
                    max={120}
                    value={editAge}
                    onChange={(event) => setEditAge(event.target.value)}
                  />
                </Field>
                <Field label="性別">
                  <select
                    value={editGender}
                    onChange={(event) => setEditGender(event.target.value as "unknown" | "male" | "female")}
                  >
                    <option value="unknown">未記入</option>
                    <option value="male">男性</option>
                    <option value="female">女性</option>
                  </select>
                </Field>
                <Field label="経験年数">
                  <input
                    type="number"
                    min={0}
                    max={80}
                    value={editExperienceYears}
                    onChange={(event) => setEditExperienceYears(event.target.value)}
                  />
                </Field>
                <Field label="国籍">
                  <select
                    value={editNationality}
                    onChange={(event) => setEditNationality(event.target.value as "unknown" | "jp" | "foreign")}
                  >
                    <option value="unknown">未記入</option>
                    <option value="jp">日本国籍</option>
                    <option value="foreign">外国籍</option>
                  </select>
                </Field>
                <Field label="商流">
                  <input
                    value={editCommerceFlow}
                    onChange={(event) => setEditCommerceFlow(event.target.value)}
                    placeholder="一社先 / プロパー など"
                  />
                </Field>
                <Field label="スキル（改行またはカンマ区切り）">
                  <textarea rows={4} value={editSkills} onChange={(event) => setEditSkills(event.target.value)} />
                </Field>
                <Field label="希望単価（万円）">
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    value={editDesiredRate}
                    onChange={(event) => setEditDesiredRate(event.target.value)}
                  />
                </Field>
                <Field label="稼働開始">
                  <input value={editAvailableFrom} onChange={(event) => setEditAvailableFrom(event.target.value)} />
                </Field>
                <Field label="勤務形態">
                  <input value={editWorkStyle} onChange={(event) => setEditWorkStyle(event.target.value)} />
                </Field>
                <Field label="最寄駅">
                  <input value={editNearestStation} onChange={(event) => setEditNearestStation(event.target.value)} />
                </Field>
                <Field label="状態">
                  <select
                    value={editStatus}
                    onChange={(event) => setEditStatus(event.target.value as "active" | "inactive")}
                  >
                    <option value="active">有効</option>
                    <option value="inactive">無効</option>
                  </select>
                </Field>
                <Field label="営業コメント／自己PR">
                  <textarea rows={4} value={editSummary} onChange={(event) => setEditSummary(event.target.value)} />
                </Field>
                <Field label="提案CC（カンマ区切り）">
                  <input
                    value={editProposalCc}
                    onChange={(event) => setEditProposalCc(event.target.value)}
                    placeholder="cc1@example.com, cc2@example.com"
                  />
                </Field>
              </form>
            ) : (
              <>
                <dl className="kv-list">
                  <Kv label="名前" value={talent.display_name || "-"} />
                  <Kv
                    label="配信元"
                    value={
                      talent.introducer_company_id ? (
                        <Link href={`/companies/${talent.introducer_company_id}`}>
                          {talent.source_company_name || talent.introducer_company_id.slice(0, 8)}
                        </Link>
                      ) : (
                        talent.source_company_name || "-"
                      )
                    }
                  />
                  <Kv label="所属" value={talent.affiliation || "-"} />
                  <Kv label="年齢" value={talent.age != null ? `${talent.age}歳` : "-"} />
                  <Kv label="性別" value={talent.gender || "-"} />
                  <Kv
                    label="経験年数"
                    value={talent.experience_years != null ? `${talent.experience_years}年` : "-"}
                  />
                  <Kv
                    label="国籍"
                    value={
                      talent.is_foreign_national === true
                        ? "外国籍"
                        : talent.is_foreign_national === false
                          ? "日本国籍"
                          : "-"
                    }
                  />
                  <Kv label="商流" value={talent.commerce_flow || "-"} />
                  <Kv label="スキル" value={<SkillTags skills={talent.skills ?? []} />} />
                  <Kv label="希望単価" value={formatRate(talent.desired_rate)} />
                  <Kv
                    label="稼働"
                    value={[talent.available_from, talent.work_style].filter(Boolean).join(" / ") || "-"}
                  />
                  <Kv label="最寄駅" value={talent.nearest_station || "-"} />
                  <Kv label="状態" value={formatTalentStatusLabel(talent.status)} />
                  <Kv label="営業コメント／自己PR" value={talent.summary || "-"} />
                  <Kv
                    label="提案CC"
                    value={
                      talent.proposal_cc_emails && talent.proposal_cc_emails.length > 0
                        ? talent.proposal_cc_emails.join(", ")
                        : "-"
                    }
                  />
                </dl>
              </>
            )}
            <h3 style={{ marginTop: 16 }}>スキルシート</h3>
            {talent.skill_sheets && talent.skill_sheets.length > 0 ? (
              <ul className="plain-list">
                {talent.skill_sheets.map((sheet) => (
                  <li key={sheet.id}>
                    {sheet.web_view_link ? (
                      <a href={sheet.web_view_link} target="_blank" rel="noreferrer">
                        {sheet.filename || "(無題)"}
                      </a>
                    ) : (
                      <span>{sheet.filename || "(無題)"}</span>
                    )}
                    <span className="muted">
                      {" "}
                      · {sheet.access_status}
                      {sheet.source_type ? ` · ${sheet.source_type}` : ""}
                      {sheet.access_status === "ok"
                        ? ` · ${formatSkillSheetExperienceExtractLabel(sheet.experience_extract_status)}`
                        : ""}
                      {sheet.error_message ? ` · ${sheet.error_message}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">スキルシートはまだ取り込まれていません</p>
            )}
          </article>
          <SourceEmailCard
            emailId={talent.email_id}
            subject={talent.email_subject}
            fromAddress={talent.email_from}
            label={talent.email_label}
            receivedAt={talent.email_received_at}
          />
        </section>
      </CollapsiblePanel>
      <KeywordChipFilter
        action={`/talents/${talentId}`}
        keyword={keyword}
        keywordPlaceholder="案件名 / 勤務地 / 配信元 / スキル / 理由"
        rateMin={rateMin}
        rateMax={rateMax}
        selectedSkills={selectedSkills}
        skillGroups={skillGroups}
        skillsInitiallyClosed
        proposedFilter={proposedFilter}
        okFilter={okFilter}
        showOutreachFilters
      />
      <Panel
        title="採点されている案件（ルールスコア降順）"
        meta={
          <span className="muted">
            {filteredMatches.length}件 / {matches.length}件
            {selectedIds.length > 0 ? ` · ${selectedIds.length}件選択中` : ""}
          </span>
        }
      >
        <p className="muted">
          案件を選択して AI採点、または人材紹介メールへの案件提案送信ができます（複数選択時は1通にまとめます）。
          提案結果は「紹介元へ」（案件提案）と「配信元へ」（人材提案）を分けて表示します。送信後は編集でき、同期した返信は「本文」から確認できます。
        </p>
        {matchesError ? <p className="muted">{matchesError}</p> : null}
        {!matchesError && matches.length === 0 ? (
          <p className="muted">まだ採点結果がありません。案件一覧からルール採点を実行してください。</p>
        ) : null}
        {!matchesError && matches.length > 0 && filteredMatches.length === 0 ? (
          <p className="muted">条件に一致する案件がありません。検索条件を変えるかクリアしてください。</p>
        ) : null}
        {filteredMatches.length > 0 ? (
          <div className="list-filter-actions" style={{ marginBottom: 10 }}>
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              disabled={busy || filteredMatches.length === 0}
              onClick={onSelectAllVisibleMatches}
            >
              全選択
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              disabled={busy || selectedIds.length === 0}
              onClick={onClearMatchSelection}
            >
              全解除
            </button>
          </div>
        ) : null}
        {filteredMatches.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th></th>
                  <th>順位</th>
                  <th>ルールスコア</th>
                  <th>AI</th>
                  <th>案件</th>
                  <th>配信元</th>
                  <th className="col-proposal-result">
                    <span className="th-with-help">
                      提案結果
                      <HelpTooltip label="提案結果の見方">
                        <p>
                          <strong>紹介元へ</strong> … 人材紹介メールへ案件を提案した結果
                        </p>
                        <p>
                          <strong>配信元へ</strong> … 案件配信元へ人材を提案した結果
                        </p>
                        <p>未送信 / 返信待ち / 承諾 / 見送り / 不明</p>
                      </HelpTooltip>
                    </span>
                  </th>
                  <th className="col-reason">理由</th>
                </tr>
              </thead>
              <tbody>
                {filteredMatches.map((row, index) => (
                  <tr key={row.match_id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(selected[row.match_id])}
                        onChange={(event) =>
                          setSelected((current) => ({ ...current, [row.match_id]: event.target.checked }))
                        }
                      />
                    </td>
                    <td>{index + 1}</td>
                    <td>
                      <ScoreHover score={row.score} breakdown={row.score_breakdown} />
                    </td>
                    <td>{row.ai_score ?? "-"}</td>
                    <td>
                      <Link href={`/projects/${row.project_id}`}>
                        {row.project_title || row.project_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td>
                      {row.distributor_company_id ? (
                        <Link href={`/companies/${row.distributor_company_id}`}>
                          {row.distributor_company_name || row.distributor_company_id.slice(0, 8)}
                        </Link>
                      ) : (
                        row.distributor_company_name || "-"
                      )}
                    </td>
                    <td className="col-proposal-result">
                      <MatchProposalResults
                        matchId={row.match_id}
                        disabled={busy}
                        talentProposal={{
                          status: row.talent_proposal_status ?? "none",
                          replyJudgment: row.talent_proposal_reply_judgment,
                          replyBody: row.talent_proposal_reply_body,
                          replyReceivedAt: row.talent_proposal_reply_received_at,
                        }}
                        projectProposal={{
                          status: row.project_proposal_status ?? "none",
                          replyJudgment: row.project_proposal_reply_judgment,
                          replyBody: row.project_proposal_reply_body,
                          replyReceivedAt: row.project_proposal_reply_received_at,
                        }}
                        onUpdated={(next) => {
                          setMatches((current) =>
                            current.map((item) =>
                              item.match_id === row.match_id
                                ? {
                                    ...item,
                                    talent_proposal_status: next.talent_proposal_status,
                                    project_proposal_status: next.project_proposal_status,
                                    outreach_status: next.outreach_status,
                                    ...(next.kind === "talent_proposal"
                                      ? {
                                          talent_proposal_reply_judgment: next.judgment,
                                          talent_proposal_reply_id: next.reply_id,
                                          talent_proposal_reply_body: next.reply_body,
                                          talent_proposal_reply_received_at: next.reply_received_at,
                                        }
                                      : {
                                          project_proposal_reply_judgment: next.judgment,
                                          project_proposal_reply_id: next.reply_id,
                                          project_proposal_reply_body: next.reply_body,
                                          project_proposal_reply_received_at: next.reply_received_at,
                                        }),
                                  }
                                : item,
                            ),
                          );
                        }}
                        onError={(msg) => setActionError(msg)}
                      />
                    </td>
                    <td className="col-reason">{row.reason || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>
    </>
  );
}

function ProjectsScreen({ searchParams }: { searchParams: SearchParams }) {
  const [projects, setProjects] = useState<ProjectDto[]>([]);
  const [skillGroups, setSkillGroups] = useState(fallbackSkillGroups);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const keyword = asString(searchParams.q);
  const rateMin = asString(searchParams.rate_min);
  const rateMax = asString(searchParams.rate_max) || asString(searchParams.rate);
  const selectedSkills = asArray(searchParams.skills);
  const proposedFilter = asString(searchParams.proposed);
  const okFilter = asString(searchParams.ok);
  const foreignNationalityFilter = asString(searchParams.foreign_nationality_ng);
  const page = parseListPage(searchParams.page);
  const pageSize = parseListPageSize(searchParams.page_size);

  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch(() => setLoadError("案件一覧の取得に失敗しました"));
    fetchSkillCatalog()
      .then((groups) => {
        const mapped = groups
          .filter((group) => group.options.length > 0)
          .map((group) => ({ label: group.label, options: group.options }));
        if (mapped.length > 0) {
          setSkillGroups(mapped);
        }
      })
      .catch(() => undefined);
  }, []);

  const onRunMatchScore = async () => {
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await runMatchScoreBatch({ force: false });
      setMessage(
        `採点完了（${formatMatchRunStatusLabel(result.status)}）: 組合せ ${String(result.stats?.match_count ?? "-")} 件`,
      );
      const list = await fetchProjects();
      setProjects(list);
    } catch (err) {
      if (err instanceof BatchRunError) {
        setActionError(`${err.errorCode}: ${err.errorMessage}`);
      } else {
        setActionError(err instanceof Error ? err.message : "ルール採点に失敗しました");
      }
    } finally {
      setBusy(false);
    }
  };

  const onSyncReplies = async () => {
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await syncOutreachReplies();
      setMessage(result.message || "返信同期が完了しました");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "返信同期に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const filteredProjects = filterProjects(projects, {
    keyword,
    rateMin,
    rateMax,
    skills: selectedSkills,
    proposed: proposedFilter,
    ok: okFilter,
    foreignNationalityNg: foreignNationalityFilter,
  });
  const totalPages = Math.max(1, Math.ceil(filteredProjects.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pagedProjects = paginateListItems(filteredProjects, safePage, pageSize);

  const onDeleteProject = async (project: ProjectDto) => {
    const ok = window.confirm(
      `案件「${project.title}」を削除しますか？\n採点結果・提案メール・返信・取込元メールも削除されます。`,
    );
    if (!ok) {
      return;
    }
    try {
      await deleteProject(project.id);
      setProjects((current) => current.filter((row) => row.id !== project.id));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "案件の削除に失敗しました");
    }
  };

  return (
    <>
      <Topbar
        title="案件一覧"
        description="案件の検索・応募状況・マッチング結果を1画面で確認。画面からも登録できます。"
        actions={
          <>
            <ButtonLink href="/projects/new" variant="secondary">
              案件を登録
            </ButtonLink>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={() => void onSyncReplies()}
            >
              {busy ? "処理中…" : "返信同期"}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void onRunMatchScore()}>
              {busy ? "処理中…" : "ルール採点を実行"}
            </button>
          </>
        }
      />
      {loadError ? <p className="notice">{loadError}</p> : null}
      {message ? <p className="notice">{message}</p> : null}
      {actionError ? <p className="notice">{actionError}</p> : null}
      <KeywordChipFilter
        action="/projects"
        keyword={keyword}
        keywordPlaceholder="案件名 / 勤務地 / 配信元 / スキル"
        rateMin={rateMin}
        rateMax={rateMax}
        selectedSkills={selectedSkills}
        skillGroups={skillGroups}
        skillsInitiallyClosed
        proposedFilter={proposedFilter}
        okFilter={okFilter}
        showOutreachFilters
        showForeignNationalityFilter
        foreignNationalityFilter={foreignNationalityFilter}
      />
      <Panel title="案件" meta={<span className="muted">検索結果 {filteredProjects.length}件 / 全 {projects.length}件</span>}>
        <ListPagination
          basePath="/projects"
          searchParams={searchParams}
          page={safePage}
          pageSize={pageSize}
          totalItems={filteredProjects.length}
        />
        <SimpleProjectTable rows={pagedProjects} onDelete={(project) => void onDeleteProject(project)} />
        <ListPagination
          basePath="/projects"
          searchParams={searchParams}
          page={safePage}
          pageSize={pageSize}
          totalItems={filteredProjects.length}
        />
      </Panel>
    </>
  );
}

function ProjectDetailScreen({
  projectId,
  searchParams,
}: {
  projectId: string;
  searchParams: SearchParams;
}) {
  const router = useRouter();
  const [project, setProject] = useState<ProjectDto | null>(null);
  const [matches, setMatches] = useState<ProjectMatchItemDto[]>([]);
  const [skillGroups, setSkillGroups] = useState(fallbackSkillGroups);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ProjectProposeDraftDto | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const [draftTo, setDraftTo] = useState("");
  const [draftCc, setDraftCc] = useState("");
  /** 人材へ案件紹介（BAT-007）の下書き。配信元向け「人材を提案」とは別。 */
  const [talentDrafts, setTalentDrafts] = useState<TalentProposeDraftDto[] | null>(null);
  const [talentDraftCcTexts, setTalentDraftCcTexts] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editProjectCode, setEditProjectCode] = useState("");
  const [editSkills, setEditSkills] = useState("");
  const [editRateMin, setEditRateMin] = useState("");
  const [editRateMax, setEditRateMax] = useState("");
  const [editLocation, setEditLocation] = useState("");
  const [editWorkStyle, setEditWorkStyle] = useState("");
  const [editWorkingHours, setEditWorkingHours] = useState("");
  const [editStartDate, setEditStartDate] = useState("");
  const [editForeignNg, setEditForeignNg] = useState<"unknown" | "ok" | "ng">("unknown");
  const [editCommerceFlowLimit, setEditCommerceFlowLimit] = useState("");
  const [editSettlementRange, setEditSettlementRange] = useState("");
  const [editInterviewCount, setEditInterviewCount] = useState("");
  const [editHeadcount, setEditHeadcount] = useState("");
  const [editStatus, setEditStatus] = useState<"open" | "closed">("open");
  const [editSummary, setEditSummary] = useState("");
  const [editProposalCc, setEditProposalCc] = useState("");
  const [matchSortKey, setMatchSortKey] = useState<ProjectMatchSortKey>("score");
  const [matchSortDir, setMatchSortDir] = useState<SortDir>("desc");
  const proposePanelRef = useRef<HTMLDivElement | null>(null);
  const keyword = asString(searchParams.q) || asString(searchParams.name);
  const rateMin = asString(searchParams.rate_min);
  const rateMax = asString(searchParams.rate_max) || asString(searchParams.rate);
  const selectedSkills = asArray(searchParams.skills);
  const proposedFilter = asString(searchParams.proposed);
  const okFilter = asString(searchParams.ok);
  const skillSheetHas = isQueryFlag(searchParams.skill_sheet_has);
  const skillSheetNone = isQueryFlag(searchParams.skill_sheet_none);

  const onMatchSort = (key: ProjectMatchSortKey) => {
    if (matchSortKey === key) {
      setMatchSortDir((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setMatchSortKey(key);
    setMatchSortDir(key === "score" || key === "ai_score" || key === "desired_rate" ? "desc" : "asc");
  };

  const filteredMatches = useMemo(
    () =>
      filterProjectMatches(matches, {
        keyword,
        rateMin,
        rateMax,
        skills: selectedSkills,
        proposed: proposedFilter,
        ok: okFilter,
        skillSheetHas,
        skillSheetNone,
      }),
    [
      matches,
      keyword,
      rateMin,
      rateMax,
      selectedSkills,
      proposedFilter,
      okFilter,
      skillSheetHas,
      skillSheetNone,
    ],
  );

  const sortedMatches = useMemo(() => {
    const factor = matchSortDir === "asc" ? 1 : -1;
    // AI採点は `ai_score` が未採点なら null のため、
    // 降順ソート時に null が先頭へ来て「ルールスコア優先」に見える問題を防ぐ。
    if (matchSortKey === "ai_score") {
      const scored = filteredMatches.filter((m) => m.ai_score != null);
      const unscored = filteredMatches.filter((m) => m.ai_score == null);
      return [...scored].sort((a, b) => factor * compareProjectMatches(a, b, matchSortKey)).concat(unscored);
    }
    return [...filteredMatches].sort((a, b) => factor * compareProjectMatches(a, b, matchSortKey));
  }, [filteredMatches, matchSortKey, matchSortDir]);

  const rateToEditValue = (value: number | null | undefined): string => {
    if (value == null) {
      return "";
    }
    return String(value >= 10000 ? Math.round(value / 10000) : value);
  };

  const fillEditForm = (row: ProjectDto) => {
    setEditTitle(row.title || "");
    setEditProjectCode(row.project_code || "");
    setEditSkills((row.required_skills || []).join("\n"));
    setEditRateMin(rateToEditValue(row.rate_min));
    setEditRateMax(rateToEditValue(row.rate_max));
    setEditLocation(row.location || "");
    setEditWorkStyle(row.work_style || "");
    setEditWorkingHours(row.working_hours || "");
    setEditStartDate(row.start_date || "");
    setEditForeignNg(
      row.foreign_nationality_ng === true ? "ng" : row.foreign_nationality_ng === false ? "ok" : "unknown",
    );
    setEditCommerceFlowLimit(row.commerce_flow_limit || "");
    setEditSettlementRange(row.settlement_range || "");
    setEditInterviewCount(row.interview_count != null ? String(row.interview_count) : "");
    setEditHeadcount(row.headcount != null ? String(row.headcount) : "");
    setEditStatus(row.status === "closed" ? "closed" : "open");
    setEditSummary(row.summary || "");
    setEditProposalCc((row.proposal_cc_emails ?? []).join(", "));
  };

  const onStartEdit = () => {
    if (!project) {
      return;
    }
    fillEditForm(project);
    setEditing(true);
    setActionError(null);
  };

  const onCancelEdit = () => {
    setEditing(false);
    setActionError(null);
  };

  const onSaveProject = async () => {
    if (!project) {
      return;
    }
    const title = editTitle.trim();
    if (!title) {
      setActionError("案件名を入力してください");
      return;
    }
    const parseOptionalInt = (raw: string, label: string): number | null => {
      const text = raw.trim();
      if (!text) {
        return null;
      }
      const n = Number(text);
      if (!Number.isFinite(n) || !Number.isInteger(n) || n < 0) {
        throw new Error(`${label}は0以上の整数で入力してください`);
      }
      return n;
    };
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const rateMin = parseOptionalInt(editRateMin, "単価下限");
      const rateMax = parseOptionalInt(editRateMax, "単価上限");
      if (rateMin != null && rateMax != null && rateMin > rateMax) {
        throw new Error("単価下限は上限以下にしてください");
      }
      const interviewCount = parseOptionalInt(editInterviewCount, "面談回数");
      const headcount = parseOptionalInt(editHeadcount, "人数");
      const saved = await updateProject(project.id, {
        title,
        project_code: editProjectCode.trim() || null,
        required_skills: editSkills
          .split(/[\n,、]+/)
          .map((part) => part.trim())
          .filter(Boolean),
        rate_min: rateMin,
        rate_max: rateMax,
        location: editLocation.trim() || null,
        work_style: editWorkStyle.trim() || null,
        working_hours: editWorkingHours.trim() || null,
        start_date: editStartDate.trim() || null,
        foreign_nationality_ng:
          editForeignNg === "ng" ? true : editForeignNg === "ok" ? false : null,
        commerce_flow_limit: editCommerceFlowLimit.trim() || null,
        settlement_range: editSettlementRange.trim() || null,
        interview_count: interviewCount,
        headcount,
        status: editStatus,
        summary: editSummary.trim() || null,
        proposal_cc_emails: parseAddressList(editProposalCc),
      });
      setProject(saved);
      setEditing(false);
      setMessage("案件情報を保存しました");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "案件情報の保存に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const reloadMatches = async () => {
    const list = await fetchProjectMatches(projectId);
    setMatches(list);
  };

  useEffect(() => {
    if (!draft && !(talentDrafts && talentDrafts.length > 0)) {
      return;
    }
    proposePanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [draft, talentDrafts]);

  useEffect(() => {
    if (!projectId) {
      setLoadError("案件 ID が不正です");
      return;
    }
    setLoadError(null);
    setMatchesError(null);
    fetchProject(projectId)
      .then(setProject)
      .catch(() => setLoadError("案件詳細の取得に失敗しました"));
    fetchProjectMatches(projectId)
      .then(setMatches)
      .catch(() => {
        setMatches([]);
        setMatchesError("採点結果の取得に失敗しました。API を再起動するか、先にルール採点を実行してください。");
      });
    fetchSkillCatalog()
      .then((groups) => {
        const mapped = groups
          .filter((group) => group.options.length > 0)
          .map((group) => ({ label: group.label, options: group.options }));
        if (mapped.length > 0) {
          setSkillGroups(mapped);
        }
      })
      .catch(() => undefined);
  }, [projectId]);

  const selectedIds = Object.entries(selected)
    .filter(([, on]) => on)
    .map(([id]) => id);

  const onSelectAllVisibleMatches = () => {
    setSelected((current) => {
      const next = { ...current };
      for (const row of sortedMatches) {
        next[row.match_id] = true;
      }
      return next;
    });
  };

  const onClearMatchSelection = () => {
    setSelected({});
  };

  const onAiJudgeSelected = async () => {
    if (selectedIds.length === 0) {
      setActionError("AI採点する人材を選択してください");
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const selectedRows = matches.filter((row) => selectedIds.includes(row.match_id));
      const runIds = [...new Set(selectedRows.map((row) => row.match_run_id).filter(Boolean))];
      if (runIds.length === 0) {
        throw new Error("match_run が見つかりません");
      }
      for (const runId of runIds) {
        const idsForRun = selectedRows
          .filter((row) => row.match_run_id === runId)
          .map((row) => row.match_id);
        await runAiJudge(runId, { matchIds: idsForRun, projectId });
      }
      setMessage(`選択した ${selectedIds.length} 件をAI採点しました`);
      await reloadMatches();
    } catch (err) {
      if (err instanceof BatchRunError) {
        setActionError(`${err.errorCode}: ${err.errorMessage}`);
      } else {
        setActionError(err instanceof Error ? err.message : "AI採点に失敗しました");
      }
    } finally {
      setBusy(false);
    }
  };

  const onOpenProposePreview = async () => {
    if (selectedIds.length === 0) {
      setActionError("提案する人材を選択してください");
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    setTalentDrafts(null);
    setTalentDraftCcTexts([]);
    try {
      const next = await previewProjectPropose(projectId, selectedIds);
      if (next.already_sent) {
        setDraft(null);
        setDraftBody("");
        setDraftTo("");
        setDraftCc("");
        setActionError("選択した人材はすべて提案済みです");
        return;
      }
      setDraft(next);
      setDraftBody(next.body_text);
      setDraftTo(next.to_address || "");
      setDraftCc((next.cc_addresses && next.cc_addresses.length > 0) ? next.cc_addresses.join(", ") : "");
      const skipped = selectedIds.length - next.match_ids.length;
      if (skipped > 0) {
        setMessage(`${skipped} 名は提案済みのため確認対象から除外しました`);
      }
    } catch (err) {
      setDraft(null);
      setDraftBody("");
      setDraftTo("");
      setDraftCc("");
      setActionError(err instanceof Error ? err.message : "提案下書きの取得に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onCancelProposePreview = () => {
    setDraft(null);
    setDraftBody("");
    setDraftTo("");
    setDraftCc("");
  };

  const onOpenTalentIntroducePreview = async () => {
    if (selectedIds.length === 0) {
      setActionError("案件紹介する人材を選択してください");
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    setDraft(null);
    setDraftBody("");
    setDraftTo("");
    setDraftCc("");
    try {
      const rows = await previewTalentPropose(selectedIds);
      const editable = rows.filter((row) => !row.already_sent);
      if (editable.length === 0) {
        setTalentDrafts(null);
        setTalentDraftCcTexts([]);
        setActionError("選択した人材はすべて案件紹介済みです");
        return;
      }
      setTalentDrafts(
        editable.map((row) => ({
          ...row,
          to_address: row.to_address || "",
          body_text: row.body_text || "",
          cc_addresses: row.cc_addresses ?? [],
        })),
      );
      setTalentDraftCcTexts(
        editable.map((row) =>
          row.cc_addresses && row.cc_addresses.length > 0 ? row.cc_addresses.join(", ") : "",
        ),
      );
      const skipped = selectedIds.length - editable.reduce((sum, row) => sum + (row.match_ids?.length || 1), 0);
      const warnings = editable.filter((row) => row.warning).length;
      const parts: string[] = [];
      if (skipped > 0) {
        parts.push(`${skipped} 件は紹介済みのため確認対象から除外しました`);
      }
      if (warnings > 0) {
        parts.push(`${warnings} 名は送信不可の警告があります（手動登録など）`);
      }
      if (parts.length > 0) {
        setMessage(parts.join(" / "));
      }
    } catch (err) {
      setTalentDrafts(null);
      setTalentDraftCcTexts([]);
      setActionError(err instanceof Error ? err.message : "案件紹介下書きの取得に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onCancelTalentIntroducePreview = () => {
    setTalentDrafts(null);
    setTalentDraftCcTexts([]);
  };

  const updateTalentDraft = (
    index: number,
    patch: Partial<Pick<TalentProposeDraftDto, "body_text" | "to_address" | "cc_addresses">>,
  ) => {
    setTalentDrafts((current) => {
      if (!current) {
        return current;
      }
      return current.map((row, i) => (i === index ? { ...row, ...patch } : row));
    });
  };

  const onSendTalentIntroduceDrafts = async () => {
    if (!talentDrafts || talentDrafts.length === 0) {
      setActionError("送信する下書きがありません");
      return;
    }
    for (const row of talentDrafts) {
      if (row.warning) {
        setActionError(
          `${row.talent_name || row.talent_id || "人材"}: ${row.warning}`,
        );
        return;
      }
      if (!(row.body_text || "").trim()) {
        setActionError(`${row.talent_name || row.talent_id || "人材"}: 本文が空です`);
        return;
      }
      if (!(row.to_address || "").trim()) {
        setActionError(`${row.talent_name || row.talent_id || "人材"}: 宛先が空です`);
        return;
      }
    }
    const allMatchIds = talentDrafts.flatMap((row) =>
      row.match_ids?.length ? row.match_ids : [row.match_id],
    );
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await proposeTalents(
        allMatchIds,
        talentDrafts.map((row, index) => ({
          match_id: row.match_id,
          match_ids: row.match_ids?.length ? row.match_ids : [row.match_id],
          body_text: (row.body_text || "").trim(),
          to_address: (row.to_address || "").trim(),
          cc_addresses: parseAddressList(talentDraftCcTexts[index] ?? ""),
        })),
      );
      setMessage(result.message || "案件紹介メールを送信しました");
      setTalentDrafts(null);
      setTalentDraftCcTexts([]);
      setSelected({});
      await reloadMatches();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "案件紹介メールの送信に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onSendProposeDraft = async () => {
    if (!draft) {
      setActionError("送信する下書きがありません");
      return;
    }
    const bodyText = draftBody.trim();
    if (!bodyText) {
      setActionError("本文が空です");
      return;
    }
    const toAddress = draftTo.trim();
    if (!toAddress) {
      setActionError("宛先を入力してください");
      return;
    }
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await proposeToProject(projectId, draft.match_ids, draftBody, {
        to_address: toAddress,
        cc_addresses: parseAddressList(draftCc),
      });
      setMessage(result.message || `選択した ${draft.match_ids.length} 名を案件配信元へ提案しました`);
      setDraft(null);
      setDraftBody("");
      setDraftTo("");
      setDraftCc("");
      setSelected({});
      await reloadMatches();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "案件配信元への提案送信に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onSyncReplies = async () => {
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const result = await syncOutreachReplies("all");
      setMessage(result.message || "人材提案メールの返信同期が完了しました");
      await reloadMatches();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "返信同期に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onDeleteProject = async () => {
    if (!project) {
      return;
    }
    const ok = window.confirm(
      `案件「${project.title}」を削除しますか？\n採点結果・提案メール・返信・取込元メールも削除されます。`,
    );
    if (!ok) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteProject(project.id);
      router.push("/projects");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "案件の削除に失敗しました");
      setBusy(false);
    }
  };

  if (loadError) {
    return <Panel title="案件詳細"><p className="muted">{loadError}</p></Panel>;
  }
  if (!project) {
    return <Panel title="案件詳細"><p className="muted">読み込み中...</p></Panel>;
  }

  const rateLabel = formatRateRange(project.rate_min, project.rate_max);

  return (
    <>
      <Topbar
        title={`${project.title}（${project.project_code || project.id.slice(0, 8)}）`}
        description="案件情報・要員採点結果・取込元"
        actions={
          <>
            <ButtonLink href="/projects">案件一覧</ButtonLink>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void onSyncReplies()}>
              {busy ? "処理中…" : "返信同期"}
            </button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void onAiJudgeSelected()}>
              {busy ? "処理中…" : "選択をAI採点"}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void onOpenProposePreview()}>
              {busy ? "処理中…" : "人材を提案"}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={() => void onOpenTalentIntroducePreview()}
            >
              {busy ? "処理中…" : "人材へ案件紹介"}
            </button>
            <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void onDeleteProject()}>
              {busy ? "処理中…" : "削除"}
            </button>
          </>
        }
      />
      {message ? <p className="notice">{message}</p> : null}
      {actionError ? <p className="notice">{actionError}</p> : null}
      {draft ? (
        <div ref={proposePanelRef}>
          <Panel title="人材提案の確認・編集">
            <p className="muted">
              選択した人材は1通のメールにまとめて送信します。宛先・CC・本文を確認・編集してから送信してください。件名は変更できません。
            </p>
            <article className="propose-draft-card">
              <h3>
                {(draft.talent_names?.length ? draft.talent_names : draft.talent_ids)
                  .filter(Boolean)
                  .join(" / ") || "要員提案"}
              </h3>
              <p className="muted">{draft.match_ids.length} 名の人材を1通で送信</p>
              <div className="field">
                <label htmlFor="propose-to-project">宛先</label>
                <input
                  id="propose-to-project"
                  type="email"
                  value={draftTo}
                  onChange={(event) => setDraftTo(event.target.value)}
                  placeholder="to@example.com"
                />
              </div>
              <div className="field">
                <label htmlFor="propose-cc-project">CC（カンマ区切り）</label>
                <input
                  id="propose-cc-project"
                  type="text"
                  value={draftCc}
                  onChange={(event) => setDraftCc(event.target.value)}
                  placeholder="cc1@example.com, cc2@example.com"
                />
              </div>
              <dl className="kv-list">
                <Kv label="件名" value={draft.subject} />
              </dl>
              <div className="propose-attachments">
                <h4>添付ファイル</h4>
                {(draft.attachments && draft.attachments.length > 0) ? (
                  <>
                    <ul className="plain-list propose-attachment-list">
                      {draft.attachments.map((file) => (
                        <li key={`${file.talent_id}-${file.filename}`}>
                          <strong>{file.filename}</strong>
                          <span className="muted">
                            {" "}
                            · {file.talent_name || file.talent_id.slice(0, 8)}
                            {" · "}
                            {formatByteSize(file.size_bytes)}
                            {file.original_filename ? ` · 元: ${file.original_filename}` : ""}
                          </span>
                          {file.web_view_link ? (
                            <>
                              {" "}
                              <a href={file.web_view_link} target="_blank" rel="noreferrer">
                                開く
                              </a>
                            </>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                    <p className="muted">
                      合計 {formatByteSize(draft.attachments_total_bytes ?? 0)}
                      {draft.attachments_over_size_limit ? " · 上限超過の可能性あり" : ""}
                    </p>
                  </>
                ) : (
                  <p className="muted">添付ファイルはありません。</p>
                )}
                {draft.attachments_note ? <p className="muted">{draft.attachments_note}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="project-propose-body">本文</label>
                <textarea
                  id="project-propose-body"
                  rows={16}
                  value={draftBody}
                  onChange={(event) => setDraftBody(event.target.value)}
                />
              </div>
            </article>
            <div className="topbar-actions" style={{ marginTop: 16 }}>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void onSendProposeDraft()}>
                {busy ? "送信中…" : "送信"}
              </button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={onCancelProposePreview}>
                キャンセル
              </button>
            </div>
          </Panel>
        </div>
      ) : null}
      {talentDrafts && talentDrafts.length > 0 ? (
        <div ref={proposePanelRef}>
          <Panel title="案件紹介メールの確認・編集">
            <p className="muted">
              選択した要員の紹介メールへ、案件取込メールのコア原文をテンプレートに載せて返信します（1人1通）。内容を確認してから送信してください。
            </p>
            {talentDrafts.map((row, index) => (
              <article key={row.talent_id || row.match_id} className="propose-draft-card">
                <h3>{row.talent_name || row.talent_id || "人材"}</h3>
                {row.warning ? <p className="notice">{row.warning}</p> : null}
                <div className="field">
                  <label htmlFor={`talent-introduce-to-${index}`}>宛先</label>
                  <input
                    id={`talent-introduce-to-${index}`}
                    type="email"
                    value={row.to_address || ""}
                    onChange={(event) => updateTalentDraft(index, { to_address: event.target.value })}
                    placeholder="to@example.com"
                  />
                </div>
                <div className="field">
                  <label htmlFor={`talent-introduce-cc-${index}`}>CC（カンマ区切り）</label>
                  <input
                    id={`talent-introduce-cc-${index}`}
                    type="text"
                    value={talentDraftCcTexts[index] ?? ""}
                    onChange={(event) => {
                      const value = event.target.value;
                      setTalentDraftCcTexts((current) => {
                        const next = [...current];
                        next[index] = value;
                        return next;
                      });
                    }}
                    placeholder="cc1@example.com, cc2@example.com"
                  />
                </div>
                <dl className="kv-list">
                  <Kv label="件名" value={row.subject} />
                </dl>
                <div className="field">
                  <label htmlFor={`talent-introduce-body-${index}`}>本文</label>
                  <textarea
                    id={`talent-introduce-body-${index}`}
                    rows={14}
                    value={row.body_text || ""}
                    onChange={(event) => updateTalentDraft(index, { body_text: event.target.value })}
                  />
                </div>
              </article>
            ))}
            <div className="topbar-actions" style={{ marginTop: 16 }}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={() => void onSendTalentIntroduceDrafts()}
              >
                {busy ? "送信中…" : "送信"}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busy}
                onClick={onCancelTalentIntroducePreview}
              >
                キャンセル
              </button>
            </div>
          </Panel>
        </div>
      ) : null}
      <CollapsiblePanel title="案件情報" className="detail-info-collapse">
        <section className="detail-layout">
          <article className="detail-card detail-card--nested">
            <div className="detail-card-header">
              <h3>案件詳細</h3>
              {!editing ? (
                <button type="button" className="btn btn-secondary btn-compact" disabled={busy} onClick={onStartEdit}>
                  編集
                </button>
              ) : (
                <div className="topbar-actions">
                  <button type="button" className="btn btn-primary btn-compact" disabled={busy} onClick={() => void onSaveProject()}>
                    {busy ? "保存中…" : "保存"}
                  </button>
                  <button type="button" className="btn btn-ghost btn-compact" disabled={busy} onClick={onCancelEdit}>
                    キャンセル
                  </button>
                </div>
              )}
            </div>
            {editing ? (
              <form
                className="form-grid"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onSaveProject();
                }}
              >
                <Field label="案件名">
                  <input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} required />
                </Field>
                <Field label="案件コード">
                  <input value={editProjectCode} onChange={(event) => setEditProjectCode(event.target.value)} />
                </Field>
                <Field label="必須スキル（改行またはカンマ区切り）">
                  <textarea rows={4} value={editSkills} onChange={(event) => setEditSkills(event.target.value)} />
                </Field>
                <Field label="単価下限（万円）">
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    value={editRateMin}
                    onChange={(event) => setEditRateMin(event.target.value)}
                  />
                </Field>
                <Field label="単価上限（万円）">
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    value={editRateMax}
                    onChange={(event) => setEditRateMax(event.target.value)}
                  />
                </Field>
                <Field label="勤務地">
                  <input value={editLocation} onChange={(event) => setEditLocation(event.target.value)} />
                </Field>
                <Field label="勤務形態">
                  <input value={editWorkStyle} onChange={(event) => setEditWorkStyle(event.target.value)} />
                </Field>
                <Field label="勤務時間">
                  <input
                    value={editWorkingHours}
                    onChange={(event) => setEditWorkingHours(event.target.value)}
                    placeholder="例: 10:00〜19:00"
                  />
                </Field>
                <Field label="開始時期">
                  <input value={editStartDate} onChange={(event) => setEditStartDate(event.target.value)} />
                </Field>
                <Field label="外国籍">
                  <select
                    value={editForeignNg}
                    onChange={(event) =>
                      setEditForeignNg(event.target.value as "unknown" | "ok" | "ng")
                    }
                  >
                    <option value="unknown">未記入</option>
                    <option value="ok">可・不問</option>
                    <option value="ng">不可</option>
                  </select>
                </Field>
                <Field label="商流制限">
                  <input
                    value={editCommerceFlowLimit}
                    onChange={(event) => setEditCommerceFlowLimit(event.target.value)}
                    placeholder="一社先まで など"
                  />
                </Field>
                <Field label="精算幅">
                  <input
                    value={editSettlementRange}
                    onChange={(event) => setEditSettlementRange(event.target.value)}
                    placeholder="例: 140〜180h"
                  />
                </Field>
                <Field label="面談回数">
                  <input
                    type="number"
                    min={0}
                    max={20}
                    value={editInterviewCount}
                    onChange={(event) => setEditInterviewCount(event.target.value)}
                    placeholder="例: 2"
                  />
                </Field>
                <Field label="人数">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={editHeadcount}
                    onChange={(event) => setEditHeadcount(event.target.value)}
                    placeholder="例: 1"
                  />
                </Field>
                <Field label="状態">
                  <select
                    value={editStatus}
                    onChange={(event) => setEditStatus(event.target.value as "open" | "closed")}
                  >
                    <option value="open">募集中</option>
                    <option value="closed">終了</option>
                  </select>
                </Field>
                <Field label="業務内容">
                  <textarea rows={4} value={editSummary} onChange={(event) => setEditSummary(event.target.value)} />
                </Field>
                <Field label="提案CC（カンマ区切り）">
                  <input
                    type="text"
                    value={editProposalCc}
                    onChange={(event) => setEditProposalCc(event.target.value)}
                    placeholder="cc1@example.com, cc2@example.com"
                  />
                </Field>
              </form>
            ) : (
              <dl className="kv-list">
                <Kv label="必須スキル" value={formatSkills(project.required_skills)} />
                <Kv
                  label="配信元会社"
                  value={
                    project.distributor_company_id ? (
                      <Link href={`/companies/${project.distributor_company_id}`}>
                        {project.distributor_company_name || project.distributor_company_id.slice(0, 8)}
                      </Link>
                    ) : (
                      project.distributor_company_name || "-"
                    )
                  }
                />
                <Kv label="単価" value={rateLabel} />
                <Kv label="勤務地" value={project.location || "-"} />
                <Kv label="勤務形態" value={project.work_style || "-"} />
                <Kv label="勤務時間" value={project.working_hours || "-"} />
                <Kv label="開始時期" value={project.start_date || "-"} />
                <Kv
                  label="外国籍"
                  value={
                    project.foreign_nationality_ng === true
                      ? "不可"
                      : project.foreign_nationality_ng === false
                        ? "可・不問"
                        : "-"
                  }
                />
                <Kv label="商流制限" value={project.commerce_flow_limit || "-"} />
                <Kv label="精算幅" value={project.settlement_range || "-"} />
                <Kv
                  label="面談回数"
                  value={project.interview_count != null ? `${project.interview_count}回` : "-"}
                />
                <Kv label="人数" value={project.headcount != null ? `${project.headcount}名` : "-"} />
                <Kv label="状態" value={formatProjectStatusLabel(project.status)} />
                <Kv label="業務内容" value={project.summary || "-"} />
                <Kv
                  label="提案CC"
                  value={
                    project.proposal_cc_emails && project.proposal_cc_emails.length > 0
                      ? project.proposal_cc_emails.join(", ")
                      : "-"
                  }
                />
              </dl>
            )}
          </article>
          <SourceEmailCard
            emailId={project.email_id}
            subject={project.email_subject}
            fromAddress={project.email_from}
            label={project.email_label}
            receivedAt={project.email_received_at}
          />
        </section>
      </CollapsiblePanel>
      <KeywordChipFilter
        action={`/projects/${projectId}`}
        keyword={keyword}
        keywordPlaceholder="氏名 / 所属 / 配信元 / スキル / 営業コメント / 理由"
        rateMin={rateMin}
        rateMax={rateMax}
        selectedSkills={selectedSkills}
        skillGroups={skillGroups}
        skillsInitiallyClosed
        proposedFilter={proposedFilter}
        okFilter={okFilter}
        showOutreachFilters
        showSkillSheetFilter
        skillSheetHas={skillSheetHas}
        skillSheetNone={skillSheetNone}
      />
      <Panel
        title="要員の採点結果"
        meta={
          <span className="muted">
            {filteredMatches.length}件 / {matches.length}件
            {selectedIds.length > 0 ? ` · ${selectedIds.length}件選択中` : ""}
            {matchSortKey === "score" && matchSortDir === "desc" ? " · ルールスコア降順" : ""}
          </span>
        }
      >
        <p className="muted">
          人材を選択して AI採点、または案件配信メールへの人材紹介送信ができます（複数選択時は1通にまとめます）。
          提案結果は「紹介元へ」（案件提案）と「配信元へ」（人材提案）を分けて表示します。送信後は編集でき、同期した返信は「本文」から確認できます。
        </p>
        {matchesError ? <p className="notice">{matchesError}</p> : null}
        {!matchesError && matches.length === 0 ? (
          <p className="muted">まだ採点結果がありません。案件一覧からルール採点を実行してください。</p>
        ) : null}
        {!matchesError && matches.length > 0 && filteredMatches.length === 0 ? (
          <p className="muted">条件に一致する要員がありません。検索条件を変えるかクリアしてください。</p>
        ) : null}
        {filteredMatches.length > 0 ? (
          <div className="list-filter-actions" style={{ marginBottom: 10 }}>
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              disabled={busy || sortedMatches.length === 0}
              onClick={onSelectAllVisibleMatches}
            >
              全選択
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              disabled={busy || selectedIds.length === 0}
              onClick={onClearMatchSelection}
            >
              全解除
            </button>
          </div>
        ) : null}
        {filteredMatches.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th></th>
                  <th>順位</th>
                  <SortableTh
                    label="ルールスコア"
                    sortKey="score"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <SortableTh
                    label="AI"
                    sortKey="ai_score"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <SortableTh
                    label="要員"
                    sortKey="display_name"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <SortableTh
                    label="配信元"
                    sortKey="source_company_name"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <SortableTh
                    label="スキルシート"
                    sortKey="has_skill_sheet"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <SortableTh
                    label="スキル"
                    sortKey="skills"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <SortableTh
                    label="希望単価"
                    sortKey="desired_rate"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                  />
                  <th className="col-proposal-result">
                    <span className="th-with-help">
                      <SortableThButton
                        label="提案結果"
                        sortKey="proposal"
                        activeKey={matchSortKey}
                        dir={matchSortDir}
                        onSort={onMatchSort}
                      />
                      <HelpTooltip label="提案結果の見方">
                        <p>
                          <strong>紹介元へ</strong> … 人材紹介メールへ案件を提案した結果
                        </p>
                        <p>
                          <strong>配信元へ</strong> … 案件配信元へ人材を提案した結果
                        </p>
                        <p>未送信 / 返信待ち / 承諾 / 見送り / 不明</p>
                      </HelpTooltip>
                    </span>
                  </th>
                  <SortableTh
                    label="理由"
                    sortKey="reason"
                    activeKey={matchSortKey}
                    dir={matchSortDir}
                    onSort={onMatchSort}
                    className="col-reason"
                  />
                </tr>
              </thead>
              <tbody>
                {sortedMatches.map((row, index) => (
                  <tr key={row.match_id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(selected[row.match_id])}
                        onChange={(event) =>
                          setSelected((current) => ({ ...current, [row.match_id]: event.target.checked }))
                        }
                      />
                    </td>
                    <td>{index + 1}</td>
                    <td>
                      <ScoreHover score={row.score} breakdown={row.score_breakdown} />
                    </td>
                    <td>{row.ai_score ?? "-"}</td>
                    <td>
                      <Link href={`/talents/${row.talent_id}`}>
                        {row.display_name || row.talent_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td>
                      {row.introducer_company_id ? (
                        <Link href={`/companies/${row.introducer_company_id}`}>
                          {row.source_company_name || row.introducer_company_id.slice(0, 8)}
                        </Link>
                      ) : (
                        row.source_company_name || "-"
                      )}
                    </td>
                    <td>
                      {row.has_skill_sheet ? (
                        <Badge tone="ok">あり</Badge>
                      ) : (
                        <span className="muted">なし</span>
                      )}
                    </td>
                    <td>
                      <MatchedSkillsCell skills={row.skills} requiredSkills={project.required_skills} />
                    </td>
                    <td>{formatRate(row.desired_rate)}</td>
                    <td className="col-proposal-result">
                      <MatchProposalResults
                        matchId={row.match_id}
                        disabled={busy}
                        talentProposal={{
                          status: row.talent_proposal_status ?? "none",
                          replyJudgment: row.talent_proposal_reply_judgment,
                          replyBody: row.talent_proposal_reply_body,
                          replyReceivedAt: row.talent_proposal_reply_received_at,
                        }}
                        projectProposal={{
                          status: row.project_proposal_status ?? "none",
                          replyJudgment: row.project_proposal_reply_judgment,
                          replyBody: row.project_proposal_reply_body,
                          replyReceivedAt: row.project_proposal_reply_received_at,
                        }}
                        onUpdated={(next) => {
                          setMatches((current) =>
                            current.map((item) =>
                              item.match_id === row.match_id
                                ? {
                                    ...item,
                                    talent_proposal_status: next.talent_proposal_status,
                                    project_proposal_status: next.project_proposal_status,
                                    outreach_status: next.outreach_status,
                                    ...(next.kind === "talent_proposal"
                                      ? {
                                          talent_proposal_reply_judgment: next.judgment,
                                          talent_proposal_reply_id: next.reply_id,
                                          talent_proposal_reply_body: next.reply_body,
                                          talent_proposal_reply_received_at: next.reply_received_at,
                                        }
                                      : {
                                          project_proposal_reply_judgment: next.judgment,
                                          project_proposal_reply_id: next.reply_id,
                                          project_proposal_reply_body: next.reply_body,
                                          project_proposal_reply_received_at: next.reply_received_at,
                                        }),
                                  }
                                : item,
                            ),
                          );
                        }}
                        onError={(msg) => setActionError(msg)}
                      />
                    </td>
                    <td className="col-reason">{row.reason || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>
    </>
  );
}

function companyKindLabel(kind: string): string {
  if (kind === "introducer") return "紹介元";
  if (kind === "distributor") return "配信元";
  return "紹介元/配信元";
}

function CompaniesScreen() {
  const [rows, setRows] = useState<CompanyDto[]>([]);
  const [q, setQ] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = (query?: string) => {
    fetchCompanies(query)
      .then(setRows)
      .catch(() => setLoadError("企業一覧の取得に失敗しました"));
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <>
      <Topbar
        title="企業一覧"
        description="人材紹介元・案件配信元の企業マスタ"
        actions={
          <>
            <ButtonLink href="/contacts">担当者一覧</ButtonLink>
            <ButtonLink href="/companies/new" variant="primary">
              企業を追加
            </ButtonLink>
          </>
        }
      />
      {loadError ? <p className="notice">{loadError}</p> : null}
      <Panel
        title="企業"
        meta={
          <form
            className="inline-search"
            onSubmit={(event) => {
              event.preventDefault();
              reload(q);
            }}
          >
            <input
              type="search"
              placeholder="会社名・ドメイン"
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
            <button type="submit" className="btn btn-secondary">
              検索
            </button>
          </form>
        }
      >
        {rows.length === 0 ? (
          <p className="muted">企業がありません。メール取込、または手動追加してください。</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>企業名</th>
                  <th>種別</th>
                  <th>ドメイン</th>
                  <th>既定メール</th>
                  <th>担当者数</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link href={`/companies/${row.id}`}>{row.name}</Link>
                    </td>
                    <td>{companyKindLabel(row.kind)}</td>
                    <td>{row.domain || "-"}</td>
                    <td>{row.default_email || "-"}</td>
                    <td>{row.contact_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function CompanyDetailScreen({ companyId }: { companyId: string }) {
  const router = useRouter();
  const [company, setCompany] = useState<CompanyDto | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!companyId) {
      setLoadError("企業 ID が不正です");
      return;
    }
    fetchCompany(companyId)
      .then(setCompany)
      .catch(() => setLoadError("企業詳細の取得に失敗しました"));
  }, [companyId]);

  const onDeleteCompany = async () => {
    if (!company) {
      return;
    }
    const contactCount = company.contacts?.length ?? company.contact_count ?? 0;
    const ok = window.confirm(
      `企業「${company.name}」を削除しますか？\n担当者 ${contactCount} 件も削除されます。\n人材・案件からの企業紐づけは解除されます（人材・案件自体は残ります）。`,
    );
    if (!ok) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteCompany(company.id);
      router.push("/companies");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "企業の削除に失敗しました");
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <Panel title="企業詳細">
        <p className="muted">{loadError}</p>
      </Panel>
    );
  }
  if (!company) {
    return (
      <Panel title="企業詳細">
        <p className="muted">読み込み中...</p>
      </Panel>
    );
  }

  return (
    <>
      <Topbar
        title={company.name}
        description="企業情報・担当者"
        actions={
          <>
            <ButtonLink href={`/companies/${company.id}/edit`}>編集</ButtonLink>
            <ButtonLink href={`/contacts/new?company_id=${company.id}`} variant="primary">
              担当者を追加
            </ButtonLink>
            <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void onDeleteCompany()}>
              {busy ? "削除中…" : "削除"}
            </button>
            <ButtonLink href="/companies">一覧へ</ButtonLink>
          </>
        }
      />
      {actionError ? <p className="notice">{actionError}</p> : null}
      <section className="detail-layout">
        <article className="detail-card">
          <h2>基本情報</h2>
          <dl className="kv-list">
            <Kv label="企業名" value={company.name} />
            <Kv label="種別" value={companyKindLabel(company.kind)} />
            <Kv label="ドメイン" value={company.domain || "-"} />
            <Kv label="既定メール" value={company.default_email || "-"} />
            <Kv label="備考" value={company.notes || "-"} />
          </dl>
        </article>
        <Panel title="メールテンプレート">
          <p className="muted">
            提案メールの文面は全企業共通です。設定画面で「人材提案用」「案件提案用」の2種を編集できます。
          </p>
          <p>
            <ButtonLink href="/settings">設定でテンプレートを編集</ButtonLink>
          </p>
        </Panel>
      </section>
      <Panel title="担当者" meta={<span className="muted">{company.contacts?.length ?? 0}件</span>}>
        {(company.contacts?.length ?? 0) === 0 ? (
          <p className="muted">担当者がありません。</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>氏名</th>
                  <th>メール</th>
                  <th>役割</th>
                  <th>電話</th>
                  <th>状態</th>
                </tr>
              </thead>
              <tbody>
                {(company.contacts ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link href={`/contacts/${row.id}/edit`}>{row.name}</Link>
                    </td>
                    <td>{row.email}</td>
                    <td>{formatContactRoleLabel(row.role)}</td>
                    <td>{row.phone || "-"}</td>
                    <td>{row.is_active ? "有効" : "無効"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function TalentFormScreen() {
  const [title, setTitle] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const subject = title.trim();
    const body = bodyText.trim();
    if (!subject) {
      setError("タイトルを入力してください");
      return;
    }
    if (!body) {
      setError("本文を入力してください");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await createTalent({ title: subject, body });
      window.location.href = `/talents/${saved.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "人材の登録に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Topbar
        title="人材を登録"
        description="タイトルと本文を入力すると、メール取込と同様に AI 要約〜ルール採点まで実行します。"
        actions={<ButtonLink href="/talents">一覧へ戻る</ButtonLink>}
      />
      {error ? <p className="notice">{error}</p> : null}
      <Panel title="登録内容">
        <p className="muted field-help-block">
          メールの件名と本文を貼り付けてください。スキル・単価などは AI が抽出します（登録後に詳細画面で修正できます）。
        </p>
        <form className="form-grid" onSubmit={(event) => void onSubmit(event)} noValidate>
          <Field label="タイトル" required grow>
            <input
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                if (error) {
                  setError(null);
                }
              }}
              placeholder="メール件名や要員名など"
              disabled={busy}
            />
          </Field>
          <Field label="本文" required grow>
            <textarea
              rows={16}
              value={bodyText}
              onChange={(event) => {
                setBodyText(event.target.value);
                if (error) {
                  setError(null);
                }
              }}
              placeholder="人材紹介メールの本文を貼り付け"
              disabled={busy}
            />
          </Field>
          <div className="topbar-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "AI要約・採点中…" : "登録"}
            </button>
            <ButtonLink href="/talents">キャンセル</ButtonLink>
          </div>
        </form>
      </Panel>
    </>
  );
}

function ProjectFormScreen() {
  const [title, setTitle] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const subject = title.trim();
    const body = bodyText.trim();
    if (!subject) {
      setError("タイトルを入力してください");
      return;
    }
    if (!body) {
      setError("本文を入力してください");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await createProject({ title: subject, body });
      window.location.href = `/projects/${saved.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "案件の登録に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Topbar
        title="案件を登録"
        description="タイトルと本文を入力すると、メール取込と同様に AI 要約〜ルール採点まで実行します。"
        actions={<ButtonLink href="/projects">一覧へ戻る</ButtonLink>}
      />
      {error ? <p className="notice">{error}</p> : null}
      <Panel title="登録内容">
        <p className="muted field-help-block">
          メールの件名と本文を貼り付けてください。スキル・単価などは AI が抽出します（登録後に詳細画面で修正できます）。
        </p>
        <form className="form-grid" onSubmit={(event) => void onSubmit(event)} noValidate>
          <Field label="タイトル" required grow>
            <input
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                if (error) {
                  setError(null);
                }
              }}
              placeholder="メール件名や案件名など"
              disabled={busy}
            />
          </Field>
          <Field label="本文" required grow>
            <textarea
              rows={16}
              value={bodyText}
              onChange={(event) => {
                setBodyText(event.target.value);
                if (error) {
                  setError(null);
                }
              }}
              placeholder="案件配信メールの本文を貼り付け"
              disabled={busy}
            />
          </Field>
          <div className="topbar-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "AI要約・採点中…" : "登録"}
            </button>
            <ButtonLink href="/projects">キャンセル</ButtonLink>
          </div>
        </form>
      </Panel>
    </>
  );
}

function CompanyFormScreen({ mode, companyId }: { mode: "new" | "edit"; companyId?: string }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("both");
  const [domain, setDomain] = useState("");
  const [defaultEmail, setDefaultEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== "edit" || !companyId) return;
    fetchCompany(companyId)
      .then((row) => {
        setName(row.name);
        setKind(row.kind);
        setDomain(row.domain || "");
        setDefaultEmail(row.default_email || "");
        setNotes(row.notes || "");
      })
      .catch(() => setLoadError("企業情報の取得に失敗しました"));
  }, [mode, companyId]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setError("企業名は必須です");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        kind,
        domain: domain.trim() || null,
        default_email: defaultEmail.trim() || null,
        notes: notes.trim() || null,
      };
      const saved =
        mode === "edit" && companyId
          ? await updateCompany(companyId, payload)
          : await createCompany(payload);
      window.location.href = `/companies/${saved.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <Panel title="企業情報編集">
        <p className="muted">{loadError}</p>
      </Panel>
    );
  }

  return (
    <>
      <Topbar
        title={mode === "new" ? "企業を追加" : "企業情報編集"}
        description="企業マスタ基本情報を入力します"
        actions={<ButtonLink href="/companies">一覧へ戻る</ButtonLink>}
      />
      {error ? <p className="notice">{error}</p> : null}
      <Panel title="基本情報">
        <form className="form-grid" onSubmit={(event) => void onSubmit(event)}>
          <Field label="企業名">
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="種別">
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="introducer">紹介元</option>
              <option value="distributor">配信元</option>
              <option value="both">紹介元/配信元</option>
            </select>
          </Field>
          <Field label="ドメイン">
            <input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="example.co.jp" />
          </Field>
          <Field label="既定メール">
            <input
              type="email"
              value={defaultEmail}
              onChange={(event) => setDefaultEmail(event.target.value)}
            />
          </Field>
          <Field label="備考">
            <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={4} />
          </Field>
          <div className="topbar-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </Panel>
    </>
  );
}

function ContactsScreen() {
  const [rows, setRows] = useState<ContactDto[]>([]);
  const [q, setQ] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = (query?: string) => {
    fetchContacts({ q: query })
      .then(setRows)
      .catch(() => setLoadError("担当者一覧の取得に失敗しました"));
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <>
      <Topbar
        title="担当者一覧"
        description="企業別担当者の検索・一覧"
        actions={
          <>
            <ButtonLink href="/companies">企業一覧</ButtonLink>
            <ButtonLink href="/contacts/new" variant="primary">
              担当者を追加
            </ButtonLink>
          </>
        }
      />
      {loadError ? <p className="notice">{loadError}</p> : null}
      <Panel
        title="担当者"
        meta={
          <form
            className="inline-search"
            onSubmit={(event) => {
              event.preventDefault();
              reload(q);
            }}
          >
            <input
              type="search"
              placeholder="氏名・メール・企業名"
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
            <button type="submit" className="btn btn-secondary">
              検索
            </button>
          </form>
        }
      >
        {rows.length === 0 ? (
          <p className="muted">担当者がありません。メール取込、または手動追加してください。</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>氏名</th>
                  <th>企業</th>
                  <th>メール</th>
                  <th>役割</th>
                  <th>状態</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link href={`/contacts/${row.id}/edit`}>{row.name}</Link>
                    </td>
                    <td>
                      <Link href={`/companies/${row.company_id}`}>{row.company_name || row.company_id.slice(0, 8)}</Link>
                    </td>
                    <td>{row.email}</td>
                    <td>{formatContactRoleLabel(row.role)}</td>
                    <td>{row.is_active ? "有効" : "無効"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function ContactFormScreen({
  mode,
  contactId,
  searchParams = {},
}: {
  mode: "new" | "edit";
  contactId?: string;
  searchParams?: SearchParams;
}) {
  const rawCompany = searchParams.company_id;
  const initialCompanyId = Array.isArray(rawCompany) ? rawCompany[0] || "" : rawCompany || "";
  const [companies, setCompanies] = useState<CompanyDto[]>([]);
  const [companyId, setCompanyId] = useState(initialCompanyId);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("primary");
  const [phone, setPhone] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchCompanies()
      .then(setCompanies)
      .catch(() => setLoadError("企業一覧の取得に失敗しました"));
  }, []);

  useEffect(() => {
    if (mode !== "edit" || !contactId) return;
    fetchContact(contactId)
      .then((row) => {
        setCompanyId(row.company_id);
        setName(row.name);
        setEmail(row.email);
        setRole(row.role);
        setPhone(row.phone || "");
        setIsActive(row.is_active);
      })
      .catch(() => setLoadError("担当者情報の取得に失敗しました"));
  }, [mode, contactId]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!companyId || !name.trim() || !email.trim()) {
      setError("企業・氏名・メールは必須です");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = {
        company_id: companyId,
        name: name.trim(),
        email: email.trim(),
        role,
        phone: phone.trim() || null,
        is_active: isActive,
      };
      if (mode === "edit" && contactId) {
        await updateContact(contactId, payload);
      } else {
        await createContact(payload);
      }
      window.location.href = `/companies/${companyId}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <Panel title="担当者">
        <p className="muted">{loadError}</p>
      </Panel>
    );
  }

  return (
    <>
      <Topbar
        title={mode === "new" ? "担当者追加" : "担当者情報編集"}
        description="企業に紐づく担当者情報を入力します"
        actions={<ButtonLink href="/contacts">一覧へ戻る</ButtonLink>}
      />
      {error ? <p className="notice">{error}</p> : null}
      <Panel title="担当者情報">
        <form className="form-grid" onSubmit={(event) => void onSubmit(event)}>
          <Field label="所属企業">
            <select value={companyId} onChange={(event) => setCompanyId(event.target.value)} required>
              <option value="">選択してください</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="氏名">
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="メール">
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </Field>
          <Field label="役割">
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="primary">主担当</option>
              <option value="secondary">副担当</option>
            </select>
          </Field>
          <Field label="電話">
            <input value={phone} onChange={(event) => setPhone(event.target.value)} />
          </Field>
          <label className="field-checkbox">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(event) => setIsActive(event.target.checked)}
            />
            有効
          </label>
          <div className="topbar-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </Panel>
    </>
  );
}

function EmailsScreen() {
  const [emails, setEmails] = useState<EmailDto[]>([]);
  const [isRunningReplySync, setIsRunningReplySync] = useState(false);
  const [selectedEmailId, setSelectedEmailId] = useState<string | null>(null);
  const [emailDetail, setEmailDetail] = useState<EmailDetailDto | null>(null);
  const [isLoadingBody, setIsLoadingBody] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const bodyRequestIdRef = useRef(0);
  const bodyPanelRef = useRef<HTMLDivElement | null>(null);

  const reload = () =>
    fetchEmails()
      .then(setEmails)
      .catch(() => setLoadError("メール一覧の取得に失敗しました"));

  const {
    progress: mailIngestProgress,
    isRunning: isRunningMailIngest,
    startMailIngest,
  } = useMailIngestProgress({
    onCompleted: async () => {
      setNotice("取込・ルール採点・返信同期が完了しました");
      await reload();
    },
    onFailed: (failedProgress) => {
      setError({
        code: failedProgress.error_code ?? "ERR-0030",
        message: failedProgress.error_message ?? "メール取込・ルール採点・返信同期の実行に失敗しました",
      });
    },
  });

  const isRunning = isRunningMailIngest || isRunningReplySync;

  useEffect(() => {
    reload();
  }, []);

  useEffect(() => {
    if (!selectedEmailId || isLoadingBody) {
      return;
    }
    bodyPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedEmailId, isLoadingBody, emailDetail]);

  function closeEmailBody() {
    bodyRequestIdRef.current += 1;
    setSelectedEmailId(null);
    setEmailDetail(null);
    setIsLoadingBody(false);
  }

  async function openEmailBody(emailId: string) {
    if (selectedEmailId === emailId) {
      closeEmailBody();
      return;
    }
    const requestId = bodyRequestIdRef.current + 1;
    bodyRequestIdRef.current = requestId;
    setSelectedEmailId(emailId);
    setEmailDetail(null);
    setIsLoadingBody(true);
    setError(null);
    try {
      const detail = await fetchEmailDetail(emailId);
      if (bodyRequestIdRef.current !== requestId) {
        return;
      }
      setEmailDetail(detail);
    } catch {
      if (bodyRequestIdRef.current !== requestId) {
        return;
      }
      setEmailDetail(null);
      setError({ code: "ERR-0030", message: "メール本文の取得に失敗しました" });
    } finally {
      if (bodyRequestIdRef.current === requestId) {
        setIsLoadingBody(false);
      }
    }
  }

  async function handleIngest() {
    setError(null);
    setNotice(null);
    try {
      await startMailIngest();
    } catch (err) {
      if (err instanceof BatchRunError) {
        setError({ code: err.errorCode, message: err.errorMessage });
      } else {
        setError({ code: "ERR-0030", message: "メール取込・ルール採点・返信同期の開始に失敗しました" });
      }
    }
  }

  async function handleReplySync() {
    setIsRunningReplySync(true);
    setError(null);
    setNotice(null);
    try {
      const result = await syncOutreachReplies();
      setNotice(result.message || "返信同期が完了しました");
    } catch (err) {
      if (err instanceof BatchRunError) {
        setError({ code: err.errorCode, message: err.errorMessage });
      } else {
        setError({ code: "ERR-0030", message: err instanceof Error ? err.message : "返信同期に失敗しました" });
      }
    } finally {
      setIsRunningReplySync(false);
    }
  }

  const renderBodyPanel = () => (
    <div ref={bodyPanelRef} className="email-body-inline">
      <div className="email-body-inline-head">
        <strong>メール本文</strong>
        <button className="btn btn-ghost" type="button" onClick={closeEmailBody}>
          閉じる
        </button>
      </div>
      {isLoadingBody ? (
        <p className="muted">読み込み中...</p>
      ) : emailDetail ? (
        <>
          <dl className="kv-list">
            <Kv label="件名" value={emailDetail.subject} />
            <Kv label="From" value={emailDetail.from_address} />
            <Kv label="ラベル" value={emailDetail.label} />
          </dl>
          {(emailDetail.body_text ?? "").trim() ? (
            <pre className="email-body">{emailDetail.body_text}</pre>
          ) : (
            <p className="muted">本文が保存されていません。</p>
          )}
        </>
      ) : (
        <p className="muted">本文を表示できません。</p>
      )}
    </div>
  );

  return (
    <>
      <Topbar
        title="メール取込"
        description="設定した Gmail ラベルから人材 / 案件を取り込み、ルール採点・返信同期を実行します"
        actions={<ButtonLink href="/settings">設定へ</ButtonLink>}
      />
      {error ? <p className="notice">{error.code}: {error.message}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      {loadError ? <p className="notice">{loadError}</p> : null}
      {mailIngestProgress && mailIngestProgress.status !== "not_found" ? (
        <MailIngestProgressPanel progress={mailIngestProgress} />
      ) : null}

      <Panel
        title="取込状況"
        meta={
          <div className="topbar-actions">
            <button
              className="btn btn-secondary"
              type="button"
              disabled={isRunning}
              onClick={() => void handleReplySync()}
            >
              {isRunningReplySync ? "実行中..." : "返信同期のみ"}
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={isRunning}
              onClick={() => void handleIngest()}
            >
              {isRunningMailIngest ? "取込中..." : "取込・採点・返信同期"}
            </button>
          </div>
        }
      >
        <table className="table">
          <thead><tr><th>ID</th><th>件名</th><th>ラベル</th><th>状態</th><th>登録先</th><th>操作</th></tr></thead>
          <tbody>
            {emails.map((mail) => {
              const isOpen = selectedEmailId === mail.id;
              return (
                <Fragment key={mail.id}>
                  <tr className={isOpen ? "is-selected" : undefined}>
                    <td>{mail.id.slice(0, 8)}</td>
                    <td>{mail.subject}</td>
                    <td>{mail.label}</td>
                    <td><Badge tone={mail.status === "pending" || mail.status === "failed" || mail.status === "needs_review" ? "warn" : "ok"}>{formatEmailStatusLabel(mail.status)}</Badge></td>
                    <td>
                      {mail.talent_id ? (
                        <Link href={`/talents/${mail.talent_id}`}>人材</Link>
                      ) : mail.project_id ? (
                        <Link href={`/projects/${mail.project_id}`}>案件</Link>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={isLoadingBody && !isOpen}
                        onClick={() => void openEmailBody(mail.id)}
                      >
                        {isOpen ? "本文を閉じる" : "本文"}
                      </button>
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="email-body-row">
                      <td colSpan={6}>{renderBodyPanel()}</td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
            {emails.length === 0 ? (
              <tr><td colSpan={6}><span className="muted">取込メールはまだありません。</span></td></tr>
            ) : null}
          </tbody>
        </table>
      </Panel>
    </>
  );
}

function SettingsScreen({ searchParams }: { searchParams: SearchParams }) {
  const [aiAssistEnabled, setAiAssistEnabled] = useState(false);
  const [aiJudgementTopN, setAiJudgementTopN] = useState(5);
  const [ownCompanyName, setOwnCompanyName] = useState("");
  const [applyFromAddress, setApplyFromAddress] = useState("");
  const [replyKeywordsOk, setReplyKeywordsOk] = useState("よろしくお願いします\n前向き\n候補として\nご提案ください");
  const [replyKeywordsNg, setReplyKeywordsNg] = useState("見送り\n他決\n辞退\n今回は結構");
  const [templateProjectPropose, setTemplateProjectPropose] = useState("");
  const [templateTalentPropose, setTemplateTalentPropose] = useState("");
  const [talentProposeRateMarkup, setTalentProposeRateMarkup] = useState(0);
  const [skillSheetDriveFolderId, setSkillSheetDriveFolderId] = useState("");
  const [ingestDataRetentionDays, setIngestDataRetentionDays] = useState(settings.ingestDataRetentionDays);
  const [gmailIngestTalentLabel, setGmailIngestTalentLabel] = useState(settings.ingestTalentLabel);
  const [gmailIngestProjectLabel, setGmailIngestProjectLabel] = useState(settings.ingestProjectLabel);
  const [gmailConnectedAccount, setGmailConnectedAccount] = useState<string | null>(settings.gmailAccount);
  const [gmailAuthStatus, setGmailAuthStatus] = useState<SettingsPayload["gmail_auth_status"]>("disconnected");
  const [gmailLastCheckedAt, setGmailLastCheckedAt] = useState<string | null>(null);
  const [gmailErrorCode, setGmailErrorCode] = useState<string | null>(null);
  const [gmailSetupRequired, setGmailSetupRequired] = useState(false);
  const [gmailSetupMessage, setGmailSetupMessage] = useState<string | null>(null);
  const [gmailOAuthClientConfigured, setGmailOAuthClientConfigured] = useState(false);
  const [gmailOAuthClientId, setGmailOAuthClientId] = useState("");
  const [gmailOAuthClientSecret, setGmailOAuthClientSecret] = useState("");
  const [gmailOAuthProjectId, setGmailOAuthProjectId] = useState("matching-service");
  const [gmailOAuthRedirectUri, setGmailOAuthRedirectUri] = useState(buildGmailOAuthRedirectUri());
  const [isConnectingGmail, setIsConnectingGmail] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isLoadingSettings, setIsLoadingSettings] = useState(true);

  const applySettings = (data: Partial<SettingsPayload>) => {
    setIngestDataRetentionDays(
      typeof data.ingest_data_retention_days === "number" ? data.ingest_data_retention_days : settings.ingestDataRetentionDays,
    );
    setGmailIngestTalentLabel(data.gmail_sort_label_talent ?? settings.ingestTalentLabel);
    setGmailIngestProjectLabel(data.gmail_sort_label_project ?? settings.ingestProjectLabel);
    setAiAssistEnabled(Boolean(data.ai_assist_enabled));
    setAiJudgementTopN(typeof data.ai_judgement_top_n === "number" ? data.ai_judgement_top_n : 5);
    setOwnCompanyName(data.own_company_name ?? "");
    setApplyFromAddress(data.apply_from_address ?? "");
    setReplyKeywordsOk(data.reply_keywords_ok ?? "よろしくお願いします\n前向き\n候補として\nご提案ください");
    setReplyKeywordsNg(data.reply_keywords_ng ?? "見送り\n他決\n辞退\n今回は結構");
    setTemplateProjectPropose(data.outreach_template_project_propose ?? "");
    setTemplateTalentPropose(data.outreach_template_talent_propose ?? "");
    setTalentProposeRateMarkup(
      typeof data.talent_propose_rate_markup_man_yen === "number" ? data.talent_propose_rate_markup_man_yen : 0,
    );
    setSkillSheetDriveFolderId(data.skill_sheet_drive_folder_id ?? "");
    setGmailConnectedAccount(data.gmail_connected_account ?? null);
    setGmailAuthStatus(data.gmail_auth_status ?? "disconnected");
    setGmailLastCheckedAt(data.gmail_last_checked_at ?? null);
    setGmailErrorCode(data.gmail_error_code ?? null);
    setGmailSetupRequired(data.gmail_setup_required ?? false);
    setGmailSetupMessage(data.gmail_setup_message ?? null);
    setGmailOAuthClientConfigured(data.gmail_oauth_client_configured ?? false);
    setGmailOAuthRedirectUri(data.gmail_oauth_redirect_uri ?? buildGmailOAuthRedirectUri());
    if (data.gmail_oauth_client_id) {
      setGmailOAuthClientId(data.gmail_oauth_client_id);
    }
  };

  useEffect(() => {
    fetchSettings()
      .then((data) => applySettings(data))
      .catch(() => {
        // API 未起動時はモックの初期値を利用
      })
      .finally(() => setIsLoadingSettings(false));
  }, []);

  useEffect(() => {
    const gmailResult = searchParams.gmail;
    const result = Array.isArray(gmailResult) ? gmailResult[0] : gmailResult;
    if (!result) {
      return;
    }
    if (result === "linked") {
      setSettingsMessage("Gmail の連携が完了しました");
      fetchSettings()
        .then((data) => applySettings(data))
        .catch(() => setSettingsMessage("連携は完了しましたが設定の再取得に失敗しました"));
      return;
    }
    if (result === "error") {
      const errorCode = searchParams.error_code;
      const code = Array.isArray(errorCode) ? errorCode[0] : errorCode;
      if (code === "ERR-0018") {
        setSettingsMessage("Gmail OAuth クライアントが未設定です。下のフォームから Client ID / Secret を入力してください。");
      } else {
        setSettingsMessage(code ? `Gmail 連携に失敗しました（${code}）` : "Gmail 連携に失敗しました");
      }
      fetchSettings()
        .then((data) => applySettings(data))
        .catch(() => undefined);
    }
  }, [searchParams]);

  const saveSettings = async () => {
    setIsSavingSettings(true);
    setSettingsMessage(null);
    try {
      const saved = await updateSettings({
        ingest_data_retention_days: ingestDataRetentionDays,
        gmail_sort_label_talent: gmailIngestTalentLabel,
        gmail_sort_label_project: gmailIngestProjectLabel,
        ai_assist_enabled: aiAssistEnabled,
        ai_judgement_top_n: aiJudgementTopN,
        own_company_name: ownCompanyName,
        apply_from_address: applyFromAddress,
        reply_keywords_ok: replyKeywordsOk,
        reply_keywords_ng: replyKeywordsNg,
        outreach_template_project_propose: templateProjectPropose,
        outreach_template_talent_propose: templateTalentPropose,
        talent_propose_rate_markup_man_yen: talentProposeRateMarkup,
        skill_sheet_drive_folder_id: skillSheetDriveFolderId,
      });
      applySettings(saved);
      setSettingsMessage("保存しました");
    } catch {
      setSettingsMessage("保存に失敗しました");
    } finally {
      setIsSavingSettings(false);
    }
  };

  const connectGmail = async () => {
    if (!gmailOAuthClientConfigured) {
      if (!gmailOAuthClientId.trim() || !gmailOAuthClientSecret.trim()) {
        setSettingsMessage("Client ID と Client Secret を入力してください");
        return;
      }
      setIsConnectingGmail(true);
      setSettingsMessage(null);
      try {
        await connectGmailFromWeb({
          gmail_oauth_client_id: gmailOAuthClientId.trim(),
          gmail_oauth_client_secret: gmailOAuthClientSecret.trim(),
          gmail_oauth_project_id: gmailOAuthProjectId.trim() || "matching-service",
        });
      } catch {
        setSettingsMessage("Gmail 連携の開始に失敗しました");
        setIsConnectingGmail(false);
      }
      return;
    }
    startGmailOAuth();
  };

  const gmailBadgeTone = gmailAuthStatus === "connected" ? "ok" : "warn";
  const gmailBadgeLabel =
    gmailAuthStatus === "connected"
      ? "Gmail 連携済み"
      : gmailAuthStatus === "expired"
        ? "Gmail 再連携が必要"
        : "Gmail 未連携";

  return (
    <>
      <Topbar
        title="設定"
        description="手動取込・ルール採点・提案メール・Gmail 連携の設定"
        actions={
          <button className="btn btn-primary" type="button" disabled={isSavingSettings || isLoadingSettings} onClick={saveSettings}>
            {isSavingSettings ? "保存中..." : "保存"}
          </button>
        }
      />
      {settingsMessage ? <p className="notice">{settingsMessage}</p> : null}
      <section className="grid-2">
        <article className="detail-card">
          <h2>バッチ / 提案・返信</h2>
          <div className="field">
            <label htmlFor="own-company-name">自社名</label>
            <input
              id="own-company-name"
              value={ownCompanyName}
              onChange={(event) => setOwnCompanyName(event.target.value)}
              placeholder="例: 株式会社Kanana"
            />
            <p className="muted field-help-block">
              人材提案メールの商流表示と、ルール採点の商流制限判定に使います。配信会社が自社名と一致すれば「プロパー」、それ以外は商流を1社先にして所属（例: 正社員 → 一社先正社員）を付与します。人材詳細のプロフィール表示は変わりません。
            </p>
          </div>
          <div className="toggle-row">
            <div className="toggle-copy">
              <strong>ルール上位候補にAI判定を行う</strong>
              <span>ON の場合は取込パイプラインのルール採点完了後に自動実行。OFF の場合は詳細画面から手動実行します。</span>
            </div>
            <label className="switch" title="AI補助判定">
              <input
                type="checkbox"
                checked={aiAssistEnabled}
                onChange={(event) => setAiAssistEnabled(event.target.checked)}
              />
              <span></span>
            </label>
          </div>
          {aiAssistEnabled ? (
            <div className="ai-assist-options">
              <div className="score-threshold-box">
                <div className="field score-threshold-field">
                  <label htmlFor="ai-top-n">AI判定対象（案件ごと）</label>
                  <div className="score-input-row">
                    <span className="score-input-prefix">ルールスコア上位</span>
                    <input
                      id="ai-top-n"
                      type="number"
                      min={1}
                      max={20}
                      value={aiJudgementTopN}
                      onChange={(event) => setAiJudgementTopN(Number(event.target.value))}
                    />
                    <span className="score-input-suffix">人</span>
                  </div>
                  <p className="muted score-threshold-note">
                    案件ごとにルールスコア上位 N 人だけ LLM 判定します（返信 NG は除外・スコア 0）。詳細画面の「選択をAI採点」ではこの制限は使いません。
                  </p>
                </div>
              </div>
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="reply-ok">OK 判定キーワード（改行区切り）</label>
            <textarea id="reply-ok" rows={4} value={replyKeywordsOk} onChange={(event) => setReplyKeywordsOk(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="reply-ng">NG 判定キーワード（改行区切り）</label>
            <textarea id="reply-ng" rows={4} value={replyKeywordsNg} onChange={(event) => setReplyKeywordsNg(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="tpl-project-propose">案件提案用テンプレート（人材紹介メールへ案件を送る）</label>
            <textarea
              id="tpl-project-propose"
              rows={10}
              value={templateProjectPropose}
              onChange={(event) => setTemplateProjectPropose(event.target.value)}
            />
            <p className="muted field-help-block">
              プレースホルダ: {"{{company_name}}"}（企業名）, {"{{contact_name}}"}（担当者名）, {"{{items}}"}（案件コア原文ブロック）
            </p>
            <p className="muted field-help-block">
              {"{{items}}"} には各案件について【連番】案件名の下に、取込元案件メールからヘッダー／フッター／署名等を除いたコア原文を載せます（下書き作成時に LLM 抽出・キャッシュ）。要約はしません。下書き画面で編集してから送信できます。
            </p>
          </div>
          <div className="field">
            <label htmlFor="tpl-talent-propose">人材提案用テンプレート（案件メールへ要員を送る）</label>
            <textarea
              id="tpl-talent-propose"
              rows={10}
              value={templateTalentPropose}
              onChange={(event) => setTemplateTalentPropose(event.target.value)}
            />
            <p className="muted field-help-block">
              プレースホルダ: {"{{company_name}}"}（企業名）, {"{{contact_name}}"}（担当者名）, {"{{project_title}}"}（案件名）, {"{{items}}"}（要員一覧ブロック）
            </p>
            <p className="muted field-help-block">
              {"{{items}}"} の各要員には【連番】表示名の下に、スキル / 単価 / 稼働 / 国籍 / 商流 / おすすめポイント（AI採点で保存した内容。未採点時は省略）を出力します。単価は人材の希望単価です。値がない項目は行ごと省略されます。商流は自社名設定に基づき、自社なら「プロパー」、他社なら1社先＋所属を表示します。
            </p>
          </div>
          <div className="field">
            <label htmlFor="talent-propose-rate-markup">案件提案メールの単価帯調整（万円）</label>
            <div className="score-input-row">
              <span className="score-input-prefix">調整額 N =</span>
              <input
                id="talent-propose-rate-markup"
                type="number"
                min={0}
                max={100}
                value={talentProposeRateMarkup}
                onChange={(event) => setTalentProposeRateMarkup(Number(event.target.value))}
              />
              <span className="score-input-suffix">万円</span>
            </div>
            <p className="muted field-help-block">
              案件提案メールで構造化の単価帯を出す場合の調整額です（現状の下書きは案件メールのコア原文を載せるため、通常は使いません）。例: 60〜70万・N=5 → 55〜65万。0 で調整なし。
            </p>
          </div>
          <div className="field">
            <label htmlFor="skill-sheet-drive-folder-id">スキルシート共有ドライブ フォルダ ID</label>
            <input
              id="skill-sheet-drive-folder-id"
              type="text"
              value={skillSheetDriveFolderId}
              onChange={(event) => setSkillSheetDriveFolderId(event.target.value)}
              placeholder="共有ドライブ内の親フォルダ ID"
            />
            <p className="muted field-help-block">
              共有ドライブ上でスキルシートの親になるフォルダの ID です。配下に自動で「スキルシート／所属会社」フォルダを作成します。未設定の場合はスキルシートの取込・添付をスキップします（メール取込・提案本文送信は継続）。
            </p>
            <p className="muted field-help-block">
              Drive 連携には OAuth の再承認が必要です。スコープに <code>gmail.modify</code> に加え <code>https://www.googleapis.com/auth/drive</code> を追加し、設定画面から Gmail を再連携してください。
            </p>
          </div>
          <div className="field retention-settings">
            <label htmlFor="ingest-retention-days">取込データの保持</label>
            <div className="score-input-row">
              <input
                id="ingest-retention-days"
                type="number"
                min="0"
                max="3650"
                value={ingestDataRetentionDays}
                onChange={(event) => setIngestDataRetentionDays(Number(event.target.value))}
              />
              <span className="score-input-suffix">日前より古いデータを削除</span>
            </div>
            <p className="muted field-help-block">
              0 を指定すると削除しません。「メール取り込み」実行時のパイプラインで、保持期間を超えた取込データ（emails）を自動削除します。送信済みの案件提案・要員提案に紐づく人材・案件（およびその取込元メール）は削除対象外です。
            </p>
          </div>
        </article>
        <article className="detail-card">
          <h2>Gmail / AI</h2>

          {gmailSetupRequired ? (
            <div className="settings-subsection">
              <h3 className="settings-subsection-title">
                Gmail 初回連携
                <HelpTooltip label="Gmail 初回連携の手順">
                  <strong>Google Cloud Console での準備</strong>
                  <ol>
                    <li>
                      <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer">
                        Google Cloud Console
                      </a>
                      にアクセスします。
                      <ul>
                        <li>
                          <strong>個人で試す場合</strong>は「新しいプロジェクト」を作成し、そのプロジェクトを選択してください（作成者は自動的にオーナーになります）。
                        </li>
                        <li>
                          <strong>会社のプロジェクトを使う場合</strong>は、あなたの Google アカウントに<strong>編集者</strong>以上の権限が必要です。権限がない場合は GCP 管理者に依頼してください。
                        </li>
                      </ul>
                    </li>
                    <li>
                      下の欄に表示される <strong>リダイレクト URI</strong> を確認します。
                      ローカル開発では <code>http://localhost:8000/api/gmail/oauth/callback</code> が自動表示されます。
                      本番では <code>.env</code> の <strong>API_PUBLIC_BASE_URL</strong> から自動生成されます。
                    </li>
                    <li>「API とサービス」→「ライブラリ」で <strong>Gmail API</strong> を検索し、有効化します。</li>
                    <li>
                      「API とサービス」→「OAuth 同意画面」でアプリ名・サポートメールを設定します。
                      左メニューの <strong>データアクセス</strong> でスコープに Gmail の読み書き（<code>gmail.modify</code>）と Google Drive（<code>https://www.googleapis.com/auth/drive</code>）を追加します。スキルシート連携を有効にする場合は Drive スコープ必須です（既存連携済みの場合は再連携が必要です）。
                    </li>
                    <li>
                      左メニューの <strong>対象</strong>（英語 UI では Audience）を開きます。
                      <ul>
                        <li>
                          <strong>ユーザーの種類</strong>は個人 Gmail（<code>@gmail.com</code>）なら <strong>外部</strong> を選択します。
                        </li>
                        <li>
                          画面上部の <strong>公開ステータス</strong> を確認します。
                          初期状態は <strong>テスト中</strong> です（英語 UI では Testing）。
                        </li>
                        <li>
                          テスト中のときは、同じ画面の <strong>テストユーザー</strong> に
                          連携する Gmail アドレスを <strong>必ず追加</strong> してください。
                          未登録だと Google 側で <em>エラー 403: access_denied</em> になります。
                        </li>
                      </ul>
                    </li>
                    <li>
                      「認証情報」→「認証情報を作成」→「OAuth クライアント ID」→ アプリケーションの種類は
                      <strong> Web アプリケーション</strong> を選択します。
                    </li>
                    <li>
                      「承認済みのリダイレクト URI」に、下の欄に表示されている URI を
                      <strong>コピーしてそのまま登録</strong>します。
                    </li>
                    <li>作成完了後に表示される <strong>Client ID</strong> と <strong>Client Secret</strong> を下のフォームへ入力します。</li>
                    <li>「Gmailと連携する」を押すと Google の認可画面が開きます。連携する Gmail アカウントでログインし、アクセスを許可してください。</li>
                    <li>設定画面に戻り「Gmail 連携済み」と表示されれば完了です。Gmail 側で人材 / 案件用ラベルをフィルタで付与する設定も行ってください。</li>
                  </ol>
                  <strong>「追加のアクセス権が必要です」と表示される場合</strong>
                  <p>
                    「API とサービス」画面で <em>追加のアクセス権が必要です</em> や <em>resourcemanager.projects.get（権限がありません）</em> が出るときは、
                    選択中の GCP プロジェクトにあなたのアカウントの権限がありません。他人が作成したプロジェクトや権限の剥がされたプロジェクトを開いている可能性があります。
                  </p>
                  <ul>
                    <li>個人利用なら、<strong>新しいプロジェクトを作成</strong>してそちらで設定し直すのが最も簡単です。</li>
                    <li>既存の会社プロジェクトを使う必要がある場合は、管理者に<strong>編集者</strong>ロールの付与を依頼してください。</li>
                  </ul>
                  <strong>「エラー 403: access_denied」と表示される場合</strong>
                  <p>Google の認可画面で拒否されたときに出ます。次を確認してください。</p>
                  <ul>
                    <li>
                      OAuth 同意画面の <strong>対象</strong> → <strong>テストユーザー</strong> に、
                      連携する Gmail アドレスが登録されているか（公開ステータスが <strong>テスト中</strong> のとき必須）
                    </li>
                    <li>ユーザーの種類が <strong>外部</strong> になっているか（個人 Gmail の場合）</li>
                    <li>同意画面で <strong>許可</strong> を押したか（未検証アプリは「詳細」→「（安全ではないページ）に移動」が必要な場合あり）</li>
                    <li>会社の Gmail（Google Workspace）の場合は、管理者によるアプリ許可が必要なことがあります</li>
                  </ul>
                </HelpTooltip>
              </h3>
              <CopyableReadonlyField
                label="リダイレクト URI（Google Cloud に登録）"
                value={gmailOAuthRedirectUri}
                hint="編集できません。ローカル開発時は localhost の URI が自動表示されます。コピーして Google Cloud の OAuth クライアントに登録してください。"
              />
              <Field label="OAuth Client ID">
                <input
                  value={gmailOAuthClientId}
                  onChange={(event) => setGmailOAuthClientId(event.target.value)}
                  placeholder="xxxx.apps.googleusercontent.com"
                />
              </Field>
              <Field label="OAuth Client Secret">
                <input
                  type="password"
                  value={gmailOAuthClientSecret}
                  onChange={(event) => setGmailOAuthClientSecret(event.target.value)}
                  placeholder="GOCSPX-..."
                />
              </Field>
              <Field label="Google Cloud Project ID（任意）">
                <input
                  value={gmailOAuthProjectId}
                  onChange={(event) => setGmailOAuthProjectId(event.target.value)}
                  placeholder="matching-service"
                />
              </Field>
              <button
                className="btn btn-primary"
                type="button"
                disabled={isConnectingGmail || isLoadingSettings}
                onClick={connectGmail}
              >
                {isConnectingGmail ? "連携準備中..." : "Gmailと連携する"}
              </button>
            </div>
          ) : null}

          <div className="integration-status">
            <div>
              <Badge tone={gmailBadgeTone}>{gmailBadgeLabel}</Badge>
              <strong>{gmailConnectedAccount ?? "未連携"}</strong>
              <small>最終確認: {formatGmailCheckedAt(gmailLastCheckedAt)}</small>
              {gmailErrorCode ? <small>エラー: {gmailErrorCode}</small> : null}
            </div>
            {!gmailSetupRequired ? (
              <button className="btn btn-ghost" type="button" onClick={connectGmail} disabled={isConnectingGmail}>
                {gmailAuthStatus === "connected" ? "再連携" : "Gmailと連携する"}
              </button>
            ) : null}
          </div>

          <div className="settings-subsection">
            <h3>メール取込（BAT-002）</h3>
            <p className="muted field-help-block">
              Gmail フィルタで付与したラベル名を指定してください。取込時はこれらのラベル付きメールを DB に登録し、処理後は「ラベル名（処理済み）」へ移動します。「ラベル名返信」は提案送信時に自動作成されます。
            </p>
            <div className="settings-field-grid">
              <Field label="人材取込ラベル">
                <input
                  value={gmailIngestTalentLabel}
                  onChange={(event) => setGmailIngestTalentLabel(event.target.value)}
                  placeholder="SES人材紹介"
                />
              </Field>
              <Field label="案件取込ラベル">
                <input
                  value={gmailIngestProjectLabel}
                  onChange={(event) => setGmailIngestProjectLabel(event.target.value)}
                  placeholder="SES案件配信"
                />
              </Field>
            </div>
          </div>

          <div className="field">
            <label htmlFor="apply-from-address">応募メール送信元</label>
            <input
              id="apply-from-address"
              type="email"
              value={applyFromAddress}
              onChange={(event) => setApplyFromAddress(event.target.value)}
              placeholder="例: matching@kanana.com"
            />
            <p className="muted field-help-block">
              提案メールの From に使います。未設定のときは連携 Gmail のプライマリアドレスから送信します。指定する場合は、Gmail の「名前で送信」に登録済みのアドレスにしてください。設定変更後に Gmail 再連携が必要な場合があります。
            </p>
          </div>
        </article>
      </section>
      <SkillMasterPanel />
    </>
  );
}

function NotFoundScreen() {
  return (
    <>
      <Topbar title="画面が見つかりません" description="指定された画面はモックに存在しません" actions={<ButtonLink href="/">戻る</ButtonLink>} />
      <Panel><p className="muted">設計書の画面マップから対象画面を選択してください。</p></Panel>
    </>
  );
}

function SkillMasterPanel() {
  const [categories, setCategories] = useState<SkillCategoryDto[]>([]);
  const [skills, setSkills] = useState<SkillMasterItemDto[]>([]);
  const [openCategoryIds, setOpenCategoryIds] = useState<Set<string>>(new Set());
  const [newCategoryName, setNewCategoryName] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    const [cats, items] = await Promise.all([fetchSkillCategories(), fetchSkillMaster()]);
    setCategories(cats);
    setSkills(items);
    setOpenCategoryIds((current) => {
      if (current.size === 0) {
        return current;
      }
      return new Set(cats.filter((category) => current.has(category.id)).map((category) => category.id));
    });
  };

  useEffect(() => {
    reload()
      .catch(() => setError("スキルマスタの取得に失敗しました"))
      .finally(() => setLoading(false));
  }, []);

  const onAddCategory = async () => {
    const name = newCategoryName.trim();
    if (!name) {
      setError("カテゴリ名を入力してください");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await createSkillCategory(name);
      setNewCategoryName("");
      await reload();
      setMessage(`カテゴリ「${name}」を追加しました`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "カテゴリの追加に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const startEditCategory = (category: SkillCategoryDto) => {
    if (category.is_uncategorized) {
      return;
    }
    setEditingCategoryId(category.id);
    setEditingName(category.name);
    setError(null);
    setMessage(null);
  };

  const cancelEditCategory = () => {
    setEditingCategoryId(null);
    setEditingName("");
  };

  const onSaveCategoryName = async (category: SkillCategoryDto) => {
    const name = editingName.trim();
    if (!name) {
      setError("カテゴリ名を入力してください");
      return;
    }
    if (name === category.name) {
      cancelEditCategory();
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await updateSkillCategory(category.id, { name });
      cancelEditCategory();
      await reload();
      setMessage(`カテゴリ名を「${name}」に更新しました`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "カテゴリ名の更新に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onMoveCategory = async (categoryId: string, direction: -1 | 1) => {
    const index = categories.findIndex((category) => category.id === categoryId);
    const swapIndex = index + direction;
    if (index < 0 || swapIndex < 0 || swapIndex >= categories.length) {
      return;
    }
    const current = categories[index];
    const neighbor = categories[swapIndex];
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (current.sort_order === neighbor.sort_order) {
        await updateSkillCategory(current.id, { sort_order: swapIndex * 10 });
        await updateSkillCategory(neighbor.id, { sort_order: index * 10 });
      } else {
        await updateSkillCategory(current.id, { sort_order: neighbor.sort_order });
        await updateSkillCategory(neighbor.id, { sort_order: current.sort_order });
      }
      await reload();
      setMessage("カテゴリの並び順を更新しました");
    } catch (err) {
      setError(err instanceof Error ? err.message : "並び順の更新に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onDeleteCategory = async (category: SkillCategoryDto) => {
    if (category.is_uncategorized) {
      return;
    }
    if (!window.confirm(`カテゴリ「${category.name}」を削除しますか？配下のスキルは「未分類」へ移します。`)) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await deleteSkillCategory(category.id);
      if (editingCategoryId === category.id) {
        cancelEditCategory();
      }
      await reload();
      setMessage(`カテゴリ「${category.name}」を削除し、スキルを未分類へ移しました`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "カテゴリの削除に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const onChangeSkillCategory = async (skillId: string, categoryId: string) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await updateSkillCategoryId(skillId, categoryId);
      await reload();
      setOpenCategoryIds((current) => new Set([...current, categoryId]));
      setMessage("スキルのカテゴリを更新しました");
    } catch (err) {
      setError(err instanceof Error ? err.message : "カテゴリ変更に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const toggleCategory = (categoryId: string, nextOpen: boolean) => {
    setOpenCategoryIds((current) => {
      const next = new Set(current);
      if (nextOpen) {
        next.add(categoryId);
      } else {
        next.delete(categoryId);
      }
      return next;
    });
  };

  return (
    <Panel title="スキルマスタ" meta={<span className="muted">取込時に自動追加 / 検索フォームへ反映</span>}>
      {loading ? <p className="muted">読み込み中…</p> : null}
      {message ? <p>{message}</p> : null}
      {error ? <p className="muted">{error}</p> : null}
      {!loading && categories.length === 0 ? (
        <p className="muted">カテゴリがありません。</p>
      ) : null}
      <div className="skill-master-panel">
        <div className="checkbox-groups skill-master-groups">
          {categories.map((category, index) => {
            const categorySkills = skills.filter((skill) => skill.category_id === category.id);
            const isOpen = openCategoryIds.has(category.id);
            const isEditing = editingCategoryId === category.id;

            return (
              <details
                className="checkbox-group"
                key={category.id}
                open={isOpen}
                onToggle={(event) => {
                  toggleCategory(category.id, event.currentTarget.open);
                }}
              >
                <summary>
                  <span className="skill-master-category-title">{category.name}</span>
                  <span className="selected-count">{categorySkills.length}</span>
                  {category.is_uncategorized ? <span className="badge badge-muted">固定</span> : null}
                  <span className="skill-master-category-actions">
                    <button
                      type="button"
                      className="btn btn-ghost skill-master-action"
                      disabled={busy || index === 0}
                      aria-label="上へ移動"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void onMoveCategory(category.id, -1);
                      }}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost skill-master-action"
                      disabled={busy || index === categories.length - 1}
                      aria-label="下へ移動"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void onMoveCategory(category.id, 1);
                      }}
                    >
                      ↓
                    </button>
                    {!category.is_uncategorized ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-ghost skill-master-action"
                          disabled={busy}
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            if (isEditing) {
                              cancelEditCategory();
                            } else {
                              startEditCategory(category);
                              if (!isOpen) {
                                toggleCategory(category.id, true);
                              }
                            }
                          }}
                        >
                          {isEditing ? "取消" : "名前変更"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost skill-master-delete"
                          disabled={busy}
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            void onDeleteCategory(category);
                          }}
                        >
                          削除
                        </button>
                      </>
                    ) : null}
                  </span>
                </summary>
                {isEditing ? (
                  <div className="skill-master-rename">
                    <input
                      type="text"
                      value={editingName}
                      disabled={busy}
                      aria-label="カテゴリ名"
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => setEditingName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void onSaveCategoryName(category);
                        }
                        if (event.key === "Escape") {
                          event.preventDefault();
                          cancelEditCategory();
                        }
                      }}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={busy}
                      onClick={() => void onSaveCategoryName(category)}
                    >
                      保存
                    </button>
                  </div>
                ) : null}
                <div className="skill-master-skill-list">
                  {categorySkills.length === 0 ? (
                    <p className="muted">このカテゴリにスキルはまだありません。</p>
                  ) : (
                    categorySkills.map((skill) => (
                      <div className="skill-master-skill-row" key={skill.id}>
                        <span className="skill-master-skill-name">{skill.name}</span>
                        <label className="skill-master-skill-move">
                          <span className="sr-only">カテゴリ変更</span>
                          <select
                            value={skill.category_id}
                            disabled={busy}
                            onChange={(event) => void onChangeSkillCategory(skill.id, event.target.value)}
                          >
                            {categories.map((option) => (
                              <option key={option.id} value={option.id}>
                                {option.name}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                    ))
                  )}
                </div>
              </details>
            );
          })}
        </div>
        <div className="skill-category-add">
          <input
            type="text"
            placeholder="新しいカテゴリ名"
            value={newCategoryName}
            onChange={(event) => setNewCategoryName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void onAddCategory();
              }
            }}
          />
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void onAddCategory()}>
            カテゴリ追加
          </button>
        </div>
      </div>
    </Panel>
  );
}

function SkillFilterGroup({
  label,
  options,
  selectedSkills,
  selectedCount,
  initiallyOpen,
}: {
  label: string;
  options: string[];
  selectedSkills: string[];
  selectedCount: number;
  initiallyOpen: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);

  return (
    <details
      className="checkbox-group"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span>{label}</span>
        <span className="selected-count">{selectedCount}</span>
      </summary>
      <div className="checkbox-options">
        {options.map((skill) => (
          <label className="checkbox-option" key={skill}>
            <input
              name="skills"
              type="checkbox"
              value={skill}
              defaultChecked={selectedSkills.includes(skill)}
            />
            <span>{skill}</span>
          </label>
        ))}
      </div>
    </details>
  );
}

function KeywordChipFilter({
  action,
  keyword,
  keywordPlaceholder,
  rateMin,
  rateMax,
  selectedSkills,
  skillGroups,
  skillsInitiallyClosed = false,
  showOutreachFilters = false,
  proposedFilter = "",
  okFilter = "",
  showForeignNationalityFilter = false,
  foreignNationalityFilter = "",
  showSkillSheetFilter = false,
  skillSheetHas = false,
  skillSheetNone = false,
}: {
  action: string;
  keyword: string;
  keywordPlaceholder: string;
  rateMin: string;
  rateMax: string;
  selectedSkills: string[];
  skillGroups: { label: string; options: string[] }[];
  skillsInitiallyClosed?: boolean;
  showOutreachFilters?: boolean;
  proposedFilter?: string;
  okFilter?: string;
  showForeignNationalityFilter?: boolean;
  foreignNationalityFilter?: string;
  showSkillSheetFilter?: boolean;
  skillSheetHas?: boolean;
  skillSheetNone?: boolean;
}) {
  return (
    <form className="list-filter" action={action} method="get">
      <div className="list-filter-main">
        <label className="list-filter-keyword">
          <span className="sr-only">キーワード</span>
          <input
            name="q"
            type="search"
            placeholder={keywordPlaceholder}
            defaultValue={keyword}
          />
        </label>
        <div className="rate-inline rate-range">
          <span className="chip-group-label">単価</span>
          <label className="rate-inline-field">
            <span className="sr-only">下限</span>
            <input
              name="rate_min"
              type="number"
              min="0"
              max="999"
              placeholder="下限"
              defaultValue={rateMin}
            />
          </label>
          <span>〜</span>
          <label className="rate-inline-field">
            <span className="sr-only">上限</span>
            <input
              name="rate_max"
              type="number"
              min="0"
              max="999"
              placeholder="上限"
              defaultValue={rateMax}
            />
          </label>
          <span>万円</span>
        </div>
        {showOutreachFilters ? (
          <>
            <label className="list-filter-select">
              <span className="chip-group-label">提案</span>
              <select name="proposed" defaultValue={proposedFilter || ""}>
                <option value="">すべて</option>
                <option value="yes">あり</option>
                <option value="no">なし</option>
              </select>
            </label>
            <label className="list-filter-select">
              <span className="chip-group-label">OK</span>
              <select name="ok" defaultValue={okFilter || ""}>
                <option value="">すべて</option>
                <option value="yes">あり</option>
                <option value="no">なし</option>
              </select>
            </label>
          </>
        ) : null}
        {showForeignNationalityFilter ? (
          <label className="list-filter-select">
            <span className="chip-group-label">外国籍</span>
            <select name="foreign_nationality_ng" defaultValue={foreignNationalityFilter || ""}>
              <option value="">すべて</option>
              <option value="ok">可・不問</option>
              <option value="ng">不可</option>
              <option value="unknown">未記入</option>
            </select>
          </label>
        ) : null}
        {showSkillSheetFilter ? (
          <div className="list-filter-skill-sheet" role="group" aria-labelledby="skill-sheet-filter-label">
            <span className="chip-group-label" id="skill-sheet-filter-label">
              スキルシート
            </span>
            <label className="list-filter-check">
              <input
                type="checkbox"
                name="skill_sheet_has"
                value="1"
                defaultChecked={skillSheetHas}
              />
              あり
            </label>
            <label className="list-filter-check">
              <input
                type="checkbox"
                name="skill_sheet_none"
                value="1"
                defaultChecked={skillSheetNone}
              />
              なし
            </label>
          </div>
        ) : null}
        <div className="list-filter-actions">
          <button className="btn btn-primary" type="submit">
            検索
          </button>
          <ButtonLink href={action} variant="ghost">
            クリア
          </ButtonLink>
        </div>
      </div>
      <div className="list-filter-skills">
        <span className="chip-group-label">スキル（複数選択可）</span>
        <div className="checkbox-groups">
          {skillGroups.map((group, groupIndex) => {
            const selectedCount = group.options.filter((skill) => selectedSkills.includes(skill)).length;
            const initiallyOpen =
              !skillsInitiallyClosed && (groupIndex === 0 || selectedCount > 0);

            return (
              <SkillFilterGroup
                key={group.label}
                label={group.label}
                options={group.options}
                selectedSkills={selectedSkills}
                selectedCount={selectedCount}
                initiallyOpen={initiallyOpen}
              />
            );
          })}
        </div>
      </div>
    </form>
  );
}

function formatTalentNationality(value: boolean | null | undefined): string {
  if (value === true) {
    return "外国籍";
  }
  if (value === false) {
    return "日本国籍";
  }
  return "-";
}

function nationalitySortValue(value: boolean | null | undefined): number {
  if (value === false) {
    return 1;
  }
  if (value === true) {
    return 2;
  }
  return 0;
}

type TalentSortKey =
  | "id"
  | "display_name"
  | "source_company_name"
  | "affiliation"
  | "age"
  | "nearest_station"
  | "nationality"
  | "available_from"
  | "has_skill_sheet"
  | "skills"
  | "desired_rate"
  | "proposed"
  | "status"
  | "email_received_at";

type SortDir = "asc" | "desc";

type ProjectMatchSortKey =
  | "score"
  | "ai_score"
  | "display_name"
  | "source_company_name"
  | "has_skill_sheet"
  | "skills"
  | "desired_rate"
  | "proposal"
  | "reason";

function SortableThButton<T extends string>({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
}: {
  label: string;
  sortKey: T;
  activeKey: T | null;
  dir: SortDir;
  onSort: (key: T) => void;
}) {
  const active = activeKey === sortKey;
  return (
    <button
      type="button"
      className={`th-sort${active ? " is-active" : ""}`}
      onClick={() => onSort(sortKey)}
      aria-label={`${label}で並び替え`}
    >
      <span>{label}</span>
      <span className="th-sort-indicator" aria-hidden>
        {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
      </span>
    </button>
  );
}

function SortableTh<T extends string>({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  className,
}: {
  label: string;
  sortKey: T;
  activeKey: T | null;
  dir: SortDir;
  onSort: (key: T) => void;
  className?: string;
}) {
  return (
    <th className={className}>
      <SortableThButton label={label} sortKey={sortKey} activeKey={activeKey} dir={dir} onSort={onSort} />
    </th>
  );
}

function compareProjectMatches(
  a: ProjectMatchItemDto,
  b: ProjectMatchItemDto,
  key: ProjectMatchSortKey,
): number {
  switch (key) {
    case "score":
      return a.score - b.score;
    case "ai_score":
      return compareNullableNumber(a.ai_score, b.ai_score);
    case "display_name":
      return compareNullableString(a.display_name, b.display_name);
    case "source_company_name":
      return compareNullableString(a.source_company_name, b.source_company_name);
    case "has_skill_sheet":
      return Number(Boolean(a.has_skill_sheet)) - Number(Boolean(b.has_skill_sheet));
    case "skills":
      return (a.skills ?? []).join("\u0001").localeCompare((b.skills ?? []).join("\u0001"), "ja");
    case "desired_rate":
      return compareNullableNumber(a.desired_rate, b.desired_rate);
    case "proposal":
      return compareNullableString(
        `${a.talent_proposal_status ?? "none"}|${a.project_proposal_status ?? "none"}`,
        `${b.talent_proposal_status ?? "none"}|${b.project_proposal_status ?? "none"}`,
      );
    case "reason":
      return compareNullableString(a.reason, b.reason);
    default:
      return 0;
  }
}

function compareNullableString(a: string | null | undefined, b: string | null | undefined): number {
  const left = (a || "").trim();
  const right = (b || "").trim();
  if (!left && !right) {
    return 0;
  }
  if (!left) {
    return 1;
  }
  if (!right) {
    return -1;
  }
  return left.localeCompare(right, "ja");
}

function compareNullableNumber(a: number | null | undefined, b: number | null | undefined): number {
  if (a == null && b == null) {
    return 0;
  }
  if (a == null) {
    return 1;
  }
  if (b == null) {
    return -1;
  }
  return a - b;
}

function orderedTalentSkills(
  skills: string[],
  skillGroups: { label: string; options: string[] }[],
): string[] {
  return groupSkillsByCatalog(skills, skillGroups).flatMap((group) => group.items);
}

function compareTalents(
  a: TalentDto,
  b: TalentDto,
  key: TalentSortKey,
  skillGroups: { label: string; options: string[] }[],
): number {
  switch (key) {
    case "id":
      return a.id.localeCompare(b.id);
    case "display_name":
      return compareNullableString(a.display_name, b.display_name);
    case "source_company_name":
      return compareNullableString(a.source_company_name, b.source_company_name);
    case "affiliation":
      return compareNullableString(a.affiliation, b.affiliation);
    case "age":
      return compareNullableNumber(a.age, b.age);
    case "nearest_station":
      return compareNullableString(a.nearest_station, b.nearest_station);
    case "nationality":
      return nationalitySortValue(a.is_foreign_national) - nationalitySortValue(b.is_foreign_national);
    case "available_from":
      return compareNullableString(a.available_from, b.available_from);
    case "has_skill_sheet":
      return Number(Boolean(a.has_skill_sheet)) - Number(Boolean(b.has_skill_sheet));
    case "skills": {
      const left = orderedTalentSkills(a.skills ?? [], skillGroups).join("\u0001");
      const right = orderedTalentSkills(b.skills ?? [], skillGroups).join("\u0001");
      return left.localeCompare(right, "ja");
    }
    case "desired_rate":
      return compareNullableNumber(a.desired_rate, b.desired_rate);
    case "proposed":
      return (a.proposed_project_count ?? 0) - (b.proposed_project_count ?? 0);
    case "status":
      return compareNullableString(a.status, b.status);
    case "email_received_at":
      return compareNullableString(a.email_received_at, b.email_received_at);
    default:
      return 0;
  }
}

function SimpleTalentTable({
  compact,
  rows = [],
  skillGroups = [],
  onDelete,
}: {
  compact?: boolean;
  rows?: TalentDto[];
  skillGroups?: { label: string; options: string[] }[];
  onDelete?: (talent: TalentDto) => void;
}) {
  const [sortKey, setSortKey] = useState<TalentSortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const onSort = (key: TalentSortKey) => {
    if (sortKey === key) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir("asc");
  };

  const sortedRows = useMemo(() => {
    if (!sortKey) {
      return rows;
    }
    const factor = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => factor * compareTalents(a, b, sortKey, skillGroups));
  }, [rows, sortKey, sortDir, skillGroups]);

  const colSpan = compact ? 5 : 15;

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <SortableTh label="ID" sortKey="id" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            <SortableTh label="氏名" sortKey="display_name" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            {!compact ? (
              <SortableTh
                label="配信元"
                sortKey="source_company_name"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
            ) : null}
            {!compact ? (
              <SortableTh label="所属" sortKey="affiliation" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            ) : null}
            {!compact ? (
              <SortableTh label="年齢" sortKey="age" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            ) : null}
            {!compact ? (
              <SortableTh
                label="最寄駅"
                sortKey="nearest_station"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
            ) : null}
            {!compact ? (
              <SortableTh label="国籍" sortKey="nationality" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            ) : null}
            {!compact ? (
              <SortableTh
                label="稼働時期"
                sortKey="available_from"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
            ) : null}
            {!compact ? (
              <SortableTh
                label="スキルシート"
                sortKey="has_skill_sheet"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
            ) : null}
            {!compact ? (
              <SortableTh label="スキル" sortKey="skills" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            ) : null}
            <SortableTh label="単価" sortKey="desired_rate" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            {!compact ? (
              <SortableTh label="提案状況" sortKey="proposed" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            ) : null}
            <SortableTh label="状態" sortKey="status" activeKey={sortKey} dir={sortDir} onSort={onSort} />
            {!compact ? (
              <SortableTh
                label="受信日"
                sortKey="email_received_at"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
            ) : null}
            <th />
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((talent) => {
            const proposedCount = talent.proposed_project_count ?? 0;
            const noReplyCount = talent.proposed_no_reply_count ?? 0;
            const okCount = talent.proposed_ok_count ?? 0;
            const ngCount = talent.proposed_ng_count ?? 0;
            return (
              <tr key={talent.id}>
                <td>{talent.id.slice(0, 8)}</td>
                <td>
                  <Link href={`/talents/${talent.id}`}>{talent.display_name}</Link>
                </td>
                {!compact ? (
                  <td>
                    {talent.introducer_company_id ? (
                      <Link href={`/companies/${talent.introducer_company_id}`}>
                        {talent.source_company_name || talent.introducer_company_id.slice(0, 8)}
                      </Link>
                    ) : (
                      talent.source_company_name || "-"
                    )}
                  </td>
                ) : null}
                {!compact ? <td>{talent.affiliation || "-"}</td> : null}
                {!compact ? <td>{talent.age != null ? `${talent.age}歳` : "-"}</td> : null}
                {!compact ? <td>{talent.nearest_station || "-"}</td> : null}
                {!compact ? <td>{formatTalentNationality(talent.is_foreign_national)}</td> : null}
                {!compact ? <td>{talent.available_from || "-"}</td> : null}
                {!compact ? (
                  <td>
                    {talent.has_skill_sheet ? (
                      <Badge tone="ok">あり</Badge>
                    ) : (
                      <span className="muted">なし</span>
                    )}
                  </td>
                ) : null}
                {!compact ? (
                  <td>
                    <TalentSkillsCell skills={talent.skills ?? []} skillGroups={skillGroups} />
                  </td>
                ) : null}
                <td>{formatRate(talent.desired_rate)}</td>
                {!compact ? (
                  <td>
                    {proposedCount > 0 ? (
                      <div className="proposal-stats" title="提案済み / 返信待ち / OK / NG">
                        <Badge tone="brand">提案 {proposedCount}</Badge>
                        {noReplyCount > 0 ? <Badge tone="warn">返信待ち {noReplyCount}</Badge> : null}
                        {okCount > 0 ? <Badge tone="ok">OK {okCount}</Badge> : null}
                        {ngCount > 0 ? <Badge tone="danger">NG {ngCount}</Badge> : null}
                      </div>
                    ) : (
                      <span className="muted">未提案</span>
                    )}
                  </td>
                ) : null}
                <td>
                  <Badge tone={talent.status === "active" ? "brand" : "muted"}>
                    {formatTalentStatusLabel(talent.status)}
                  </Badge>
                </td>
                {!compact ? (
                  <td>{talent.email_received_at ? formatReceivedDate(talent.email_received_at) : "-"}</td>
                ) : null}
                <td>
                  <div className="table-actions">
                    {!compact && onDelete ? (
                      <button
                        type="button"
                        className="btn btn-danger btn-compact"
                        onClick={() => onDelete(talent)}
                      >
                        削除
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
          {sortedRows.length === 0 ? (
            <tr>
              <td colSpan={colSpan}>
                <span className="muted">人材データはまだありません。</span>
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function SimpleProjectTable({
  compact,
  rows = [],
  onDelete,
}: {
  compact?: boolean;
  rows?: ProjectDto[];
  onDelete?: (project: ProjectDto) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>案件名</th>
            {!compact ? <th>配信元</th> : null}
            {!compact ? <th>勤務地</th> : null}
            <th>必須スキル</th>
            <th>単価</th>
            {!compact ? <th>提案状況</th> : null}
            <th>状態</th>
            {!compact ? <th>受信日</th> : null}
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((project) => {
            const proposedCount = project.proposed_talent_count ?? 0;
            const noReplyCount = project.proposed_no_reply_count ?? 0;
            const okCount = project.proposed_ok_count ?? 0;
            const ngCount = project.proposed_ng_count ?? 0;
            return (
              <tr key={project.id}>
                <td>{project.project_code || project.id.slice(0, 8)}</td>
                <td>
                  <Link href={`/projects/${project.id}`}>{project.title}</Link>
                </td>
                {!compact ? (
                  <td>
                    {project.distributor_company_id ? (
                      <Link href={`/companies/${project.distributor_company_id}`}>
                        {project.distributor_company_name || project.distributor_company_id.slice(0, 8)}
                      </Link>
                    ) : (
                      project.distributor_company_name || "-"
                    )}
                  </td>
                ) : null}
                {!compact ? <td>{project.location || "-"}</td> : null}
                <td>{formatSkills(project.required_skills)}</td>
                <td>
                  {project.rate_min != null || project.rate_max != null
                    ? formatRateRange(project.rate_min, project.rate_max)
                    : "-"}
                </td>
                {!compact ? (
                  <td>
                    {proposedCount > 0 ? (
                      <div className="proposal-stats" title="提案済み / 返信待ち / OK / NG">
                        <Badge tone="brand">提案 {proposedCount}</Badge>
                        {noReplyCount > 0 ? <Badge tone="warn">返信待ち {noReplyCount}</Badge> : null}
                        {okCount > 0 ? <Badge tone="ok">OK {okCount}</Badge> : null}
                        {ngCount > 0 ? <Badge tone="danger">NG {ngCount}</Badge> : null}
                      </div>
                    ) : (
                      <span className="muted">未提案</span>
                    )}
                  </td>
                ) : null}
                <td>
                  <Badge tone={project.status === "open" ? "brand" : "muted"}>
                    {formatProjectStatusLabel(project.status)}
                  </Badge>
                </td>
                {!compact ? (
                  <td>{project.email_received_at ? formatReceivedDate(project.email_received_at) : "-"}</td>
                ) : null}
                <td>
                  <div className="table-actions">
                    {!compact && onDelete ? (
                      <button
                        type="button"
                        className="btn btn-danger btn-compact"
                        onClick={() => onDelete(project)}
                      >
                        削除
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={compact ? 6 : 10}>
                <span className="muted">案件データはまだありません。</span>
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function ScoreHover({
  score,
  breakdown,
}: {
  score: number;
  breakdown?: Record<string, unknown> | null;
}) {
  const lines = formatScoreBreakdownLines(breakdown);
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null);
  const anchorRef = useRef<HTMLSpanElement | null>(null);

  if (lines.length === 0) {
    return <span>{score}</span>;
  }

  const showPanel = () => {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    const width = Math.min(320, window.innerWidth - 24);
    let left = rect.left;
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12);
    }
    const preferBelow = rect.bottom + 8;
    const estimatedHeight = 28 + lines.length * 22;
    const top =
      preferBelow + estimatedHeight > window.innerHeight - 12
        ? Math.max(12, rect.top - estimatedHeight - 8)
        : preferBelow;
    setPanelStyle({
      position: "fixed",
      top,
      left,
      width,
      zIndex: 1000,
    });
  };

  const hidePanel = () => setPanelStyle(null);

  return (
    <span
      ref={anchorRef}
      className="score-hover"
      tabIndex={0}
      onMouseEnter={showPanel}
      onMouseLeave={hidePanel}
      onFocus={showPanel}
      onBlur={hidePanel}
    >
      <span className="score-hover-value">{score}</span>
      {panelStyle ? (
        <span className="score-hover-panel is-open" role="tooltip" style={panelStyle}>
          <strong>ルール採点内訳</strong>
          <ul>
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </span>
      ) : null}
    </span>
  );
}

type OutreachStatusUpdate = {
  kind: "talent_proposal" | "project_proposal";
  judgment: string;
  reply_id: string;
  reply_body: string | null;
  reply_received_at: string | null;
  outreach_status: string;
  talent_proposal_status: string;
  project_proposal_status: string;
};

type ProposalSideView = {
  status: string;
  replyJudgment?: string | null;
  replyBody?: string | null;
  replyReceivedAt?: string | null;
};

function MatchProposalResults({
  matchId,
  talentProposal,
  projectProposal,
  disabled = false,
  onUpdated,
  onError,
}: {
  matchId: string;
  talentProposal: ProposalSideView;
  projectProposal: ProposalSideView;
  disabled?: boolean;
  onUpdated: (next: OutreachStatusUpdate) => void;
  onError: (message: string) => void;
}) {
  return (
    <div className="proposal-result-stack">
      <OutreachStatusCell
        matchId={matchId}
        kind="talent_proposal"
        directionLabel="紹介元へ"
        directionHint="人材紹介メールへ案件を提案"
        outreachStatus={talentProposal.status}
        replyJudgment={talentProposal.replyJudgment}
        replyBody={talentProposal.replyBody}
        replyReceivedAt={talentProposal.replyReceivedAt}
        disabled={disabled}
        onUpdated={onUpdated}
        onError={onError}
      />
      <OutreachStatusCell
        matchId={matchId}
        kind="project_proposal"
        directionLabel="配信元へ"
        directionHint="案件配信元へ人材を提案"
        outreachStatus={projectProposal.status}
        replyJudgment={projectProposal.replyJudgment}
        replyBody={projectProposal.replyBody}
        replyReceivedAt={projectProposal.replyReceivedAt}
        disabled={disabled}
        onUpdated={onUpdated}
        onError={onError}
      />
    </div>
  );
}

function OutreachStatusCell({
  matchId,
  kind,
  directionLabel,
  directionHint,
  outreachStatus,
  replyJudgment,
  replyBody,
  replyReceivedAt,
  disabled = false,
  onUpdated,
  onError,
}: {
  matchId: string;
  kind: "talent_proposal" | "project_proposal";
  directionLabel: string;
  directionHint: string;
  outreachStatus: string;
  replyJudgment?: string | null;
  replyBody?: string | null;
  replyReceivedAt?: string | null;
  disabled?: boolean;
  onUpdated: (next: OutreachStatusUpdate) => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [showBody, setShowBody] = useState(false);
  const canEdit = outreachStatus !== "none";
  const selectValue =
    outreachStatus.startsWith("reply_")
      ? outreachStatus.slice("reply_".length)
      : replyJudgment && ["ok", "ng", "unknown"].includes(replyJudgment)
        ? replyJudgment
        : "";
  const hasReplyBody = Boolean(replyBody && replyBody.trim());
  const statusLabel = formatOutreachStatusLabel(outreachStatus, replyJudgment);
  const tone = outreachStatusTone(outreachStatus, replyJudgment);

  const onChange = async (value: string) => {
    if (!value || (value !== "ok" && value !== "ng" && value !== "unknown")) {
      return;
    }
    if (value === selectValue) {
      return;
    }
    setBusy(true);
    try {
      const result = await updateMatchOutreachStatus(matchId, value, kind);
      onUpdated({
        kind,
        judgment: result.judgment,
        reply_id: result.reply_id,
        reply_body: result.reply_body,
        reply_received_at: result.reply_received_at,
        outreach_status: result.outreach_status,
        talent_proposal_status: result.talent_proposal_status ?? "none",
        project_proposal_status: result.project_proposal_status ?? "none",
      });
    } catch (err) {
      onError(err instanceof Error ? err.message : "ステータスの更新に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="proposal-result-row" title={directionHint}>
      <span className="proposal-result-direction">{directionLabel}</span>
      <div className="outreach-status-cell">
        {canEdit ? (
          <select
            className={`outreach-status-select badge badge-${tone}`}
            value={selectValue}
            disabled={disabled || busy}
            onChange={(event) => void onChange(event.target.value)}
            aria-label={`${directionLabel}の提案結果`}
          >
            {selectValue === "" ? <option value="">返信待ち</option> : null}
            <option value="ok">承諾</option>
            <option value="ng">見送り</option>
            <option value="unknown">不明</option>
          </select>
        ) : (
          <Badge tone={tone}>{statusLabel}</Badge>
        )}
        {hasReplyBody ? (
          <button
            type="button"
            className="btn btn-secondary outreach-status-body-btn"
            disabled={disabled || busy}
            onClick={() => setShowBody(true)}
          >
            本文
          </button>
        ) : null}
      </div>
      {showBody && hasReplyBody ? (
        <ReplyBodyModal
          title={`${directionLabel}の返信本文`}
          body={replyBody || ""}
          receivedAt={replyReceivedAt}
          onClose={() => setShowBody(false)}
        />
      ) : null}
    </div>
  );
}

function SourceEmailCard({
  emailId,
  subject,
  fromAddress,
  label,
  receivedAt,
}: {
  emailId?: string | null;
  subject?: string | null;
  fromAddress?: string | null;
  label?: string | null;
  receivedAt?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);

  async function toggleBody() {
    if (open) {
      setOpen(false);
      return;
    }
    if (!emailId) {
      setError("取込元メールがありません");
      setOpen(true);
      return;
    }
    if (body !== null) {
      setOpen(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const detail = await fetchEmailDetail(emailId);
      setBody(detail.body_text ?? "");
      setOpen(true);
    } catch {
      setError("メール本文の取得に失敗しました");
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <article className="detail-card detail-card--nested">
      <div className="detail-card-header">
        <h3>取込元メール</h3>
        <button
          type="button"
          className="btn btn-secondary btn-compact"
          disabled={loading || !emailId}
          onClick={() => void toggleBody()}
        >
          {loading ? "読込中…" : open ? "本文を閉じる" : "本文を表示"}
        </button>
      </div>
      <dl className="kv-list">
        <Kv label="件名" value={subject || "-"} />
        <Kv label="From" value={fromAddress || "-"} />
        <Kv label="ラベル" value={label || "-"} />
        <Kv label="受信日時" value={receivedAt ? formatGmailCheckedAt(receivedAt) : "-"} />
      </dl>
      {open ? (
        <div className="source-email-body">
          {error ? <p className="muted">{error}</p> : null}
          {!error ? (
            <pre className="email-body">{(body ?? "").trim() ? body : "（本文なし）"}</pre>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function ReplyBodyModal({
  title,
  body,
  receivedAt,
  onClose,
}: {
  title: string;
  body: string;
  receivedAt?: string | null;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2>{title}</h2>
            {receivedAt ? <p className="muted">受信: {formatGmailCheckedAt(receivedAt)}</p> : null}
          </div>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            閉じる
          </button>
        </div>
        <pre className="email-body">{body.trim() ? body : "（本文なし）"}</pre>
      </div>
    </div>
  );
}

/** 採点ロジックに近い簡易正規化（表示用マッチ判定）。 */
function normalizeSkillLabel(raw: string): string {
  return raw
    .normalize("NFKC")
    .trim()
    .toLowerCase()
    .replace(/[\s　_\-]+/g, " ")
    .replace(/．/g, ".")
    .trim();
}

function isSkillMatchedToRequired(talentSkill: string, requiredSkills: string[]): boolean {
  const talent = normalizeSkillLabel(talentSkill);
  if (!talent) {
    return false;
  }
  return requiredSkills.some((required) => {
    const req = normalizeSkillLabel(required);
    if (!req) {
      return false;
    }
    return talent === req || talent.includes(req) || req.includes(talent);
  });
}

function splitSkillsByProjectMatch(
  skills: string[],
  requiredSkills: string[] | undefined,
): { matched: string[]; others: string[] } {
  if (!skills.length) {
    return { matched: [], others: [] };
  }
  const required = requiredSkills ?? [];
  if (required.length === 0) {
    return { matched: [], others: skills };
  }
  const matched: string[] = [];
  const others: string[] = [];
  for (const skill of skills) {
    if (isSkillMatchedToRequired(skill, required)) {
      matched.push(skill);
    } else {
      others.push(skill);
    }
  }
  return { matched, others };
}

function groupSkillsByCatalog(
  skills: string[],
  catalog: { label: string; options: string[] }[],
): { label: string; items: string[] }[] {
  if (!skills.length) {
    return [];
  }
  if (!catalog.length) {
    return [{ label: "その他", items: [...skills] }];
  }
  const remaining = [...skills];
  const take = (option: string) => {
    const idx = remaining.findIndex(
      (skill) => skill === option || skill.includes(option) || option.includes(skill),
    );
    if (idx < 0) {
      return null;
    }
    return remaining.splice(idx, 1)[0];
  };
  const grouped: { label: string; items: string[] }[] = [];
  for (const category of catalog) {
    const items: string[] = [];
    for (const option of category.options) {
      const hit = take(option);
      if (hit) {
        items.push(hit);
      }
    }
    if (items.length > 0) {
      grouped.push({ label: category.label, items });
    }
  }
  if (remaining.length > 0) {
    grouped.push({ label: "その他", items: remaining });
  }
  return grouped;
}

function TalentSkillsCell({
  skills,
  skillGroups,
}: {
  skills: string[];
  skillGroups: { label: string; options: string[] }[];
}) {
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null);
  const anchorRef = useRef<HTMLSpanElement | null>(null);

  if (!skills.length) {
    return <span className="muted">-</span>;
  }

  const groups = groupSkillsByCatalog(skills, skillGroups);
  const ordered = groups.flatMap((group) => group.items);
  const visible = ordered.slice(0, 3);
  const restCount = Math.max(0, ordered.length - visible.length);
  const skillLineCount = groups.reduce((sum, group) => sum + group.items.length, 0);

  const showPanel = () => {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    const width = Math.min(420, window.innerWidth - 24);
    let left = rect.left;
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12);
    }
    const estimatedHeight = Math.min(48 + groups.length * 28 + skillLineCount * 18, window.innerHeight - 24);
    const preferBelow = rect.bottom + 8;
    const top =
      preferBelow + estimatedHeight > window.innerHeight - 12
        ? Math.max(12, rect.top - estimatedHeight - 8)
        : preferBelow;
    setPanelStyle({
      position: "fixed",
      top,
      left,
      width,
      maxHeight: Math.min(estimatedHeight, window.innerHeight - top - 12),
      overflowY: "auto",
      zIndex: 1000,
    });
  };

  const hidePanel = () => setPanelStyle(null);

  return (
    <span
      ref={anchorRef}
      className="skill-count-hover skill-preview-hover"
      tabIndex={0}
      onMouseEnter={showPanel}
      onMouseLeave={hidePanel}
      onFocus={showPanel}
      onBlur={hidePanel}
    >
      <span className="skill-preview-summary">
        <span className="skill-preview-list">{visible.join("、")}</span>
        {restCount > 0 ? <span className="skill-preview-more">その他{restCount}</span> : null}
      </span>
      {panelStyle ? (
        <span className="score-hover-panel is-open skill-count-panel" role="tooltip" style={panelStyle}>
          {groups.map((group) => (
            <span className="skill-count-panel-group" key={group.label}>
              <span className="skill-count-panel-label">
                {group.label}（{group.items.length}）
              </span>
              <span>{group.items.join("、")}</span>
            </span>
          ))}
        </span>
      ) : null}
    </span>
  );
}

function SkillTags({ skills }: { skills: string[] }) {
  const [groups, setGroups] = useState<{ label: string; items: string[] }[] | null>(null);

  useEffect(() => {
    if (!skills.length) {
      setGroups([]);
      return;
    }
    let cancelled = false;
    fetchSkillCatalog()
      .then((catalog) => {
        if (cancelled) {
          return;
        }
        setGroups(groupSkillsByCatalog(skills, catalog));
      })
      .catch(() => {
        if (!cancelled) {
          setGroups([{ label: "", items: skills }]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [skills.join("\u0001")]);

  if (!skills.length) {
    return <span className="muted">-</span>;
  }

  if (groups == null) {
    return (
      <div className="skill-tags">
        {skills.map((skill) => (
          <span className="skill-tag" key={skill}>
            {skill}
          </span>
        ))}
      </div>
    );
  }

  if (groups.length === 1 && !groups[0].label) {
    return (
      <div className="skill-tags">
        {groups[0].items.map((skill) => (
          <span className="skill-tag" key={skill}>
            {skill}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="skill-tag-groups">
      {groups.map((group) => (
        <div className="skill-tag-group" key={group.label || "all"}>
          {group.label ? <span className="skill-tag-group-label">{group.label}</span> : null}
          <div className="skill-tags">
            {group.items.map((skill) => (
              <span className="skill-tag" key={skill}>
                {skill}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function MatchedSkillsCell({
  skills,
  requiredSkills,
}: {
  skills: string[];
  requiredSkills?: string[];
}) {
  const { matched, others } = splitSkillsByProjectMatch(skills, requiredSkills);
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null);
  const anchorRef = useRef<HTMLSpanElement | null>(null);

  if (matched.length === 0 && others.length === 0) {
    return <span className="muted">-</span>;
  }

  const showOthers = () => {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    const width = Math.min(280, window.innerWidth - 24);
    let left = rect.left;
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12);
    }
    const preferBelow = rect.bottom + 8;
    const estimatedHeight = 36 + others.length * 20;
    const top =
      preferBelow + estimatedHeight > window.innerHeight - 12
        ? Math.max(12, rect.top - estimatedHeight - 8)
        : preferBelow;
    setPanelStyle({
      position: "fixed",
      top,
      left,
      width,
      zIndex: 1000,
    });
  };

  const hideOthers = () => setPanelStyle(null);

  return (
    <span className="matched-skills">
      {matched.length > 0 ? (
        <span>{matched.join(" / ")}</span>
      ) : (
        <span className="muted">一致なし</span>
      )}
      {others.length > 0 ? (
        <>
          {matched.length > 0 ? <span className="muted"> · </span> : null}
          <span
            ref={anchorRef}
            className="skill-others-trigger"
            tabIndex={0}
            onMouseEnter={showOthers}
            onMouseLeave={hideOthers}
            onFocus={showOthers}
            onBlur={hideOthers}
          >
            その他(+{others.length})
          </span>
          {panelStyle ? (
            <span className="score-hover-panel is-open" role="tooltip" style={panelStyle}>
              <strong>その他のスキル</strong>
              <ul>
                {others.map((skill) => (
                  <li key={skill}>{skill}</li>
                ))}
              </ul>
            </span>
          ) : null}
        </>
      ) : null}
    </span>
  );
}

function Kv({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="kv-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function FormPanel({ children, submitLabel }: { children: ReactNode; submitLabel: string }) {
  return (
    <Panel>
      <div className="grid-2">{children}</div>
      <div className="topbar-actions" style={{ marginTop: 16 }}>
        <button className="btn btn-primary">{submitLabel}</button>
        <ButtonLink href="/companies" variant="ghost">キャンセル</ButtonLink>
      </div>
    </Panel>
  );
}

function ComposeCard() {
  return (
    <article className="compose-card">
      <h2>メール本文</h2>
      <Field label="件名"><input defaultValue="【ご提案】基幹刷新案件向け要員のご紹介" /></Field>
      <Field label="本文"><textarea defaultValue={"ご担当者様\n\n以下の要員をご提案いたします。\n・山田 太郎 / Java / Spring / AWS\n・高橋 健 / Java / Kotlin\n\nご確認のほどよろしくお願いいたします。"} /></Field>
    </article>
  );
}

function asString(value: string | string[] | undefined) {
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}

function asArray(value: string | string[] | undefined) {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function parseRateFilter(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** DB 値が円でも万円でも、フィルタ比較用に万円へ揃える。 */
function toManYenForFilter(value: number): number {
  return value >= 10000 ? Math.round(value / 10000) : value;
}

function isQueryFlag(value: string | string[] | undefined): boolean {
  const text = asString(value);
  return text === "1" || text === "true" || text === "yes" || text === "on";
}

function matchesSkillSheetFilter(
  hasSkillSheet: boolean | undefined,
  hasChecked: boolean,
  noneChecked: boolean,
): boolean {
  if (!hasChecked && !noneChecked) {
    return true;
  }
  if (hasChecked && noneChecked) {
    return true;
  }
  const present = Boolean(hasSkillSheet);
  if (hasChecked) {
    return present;
  }
  return !present;
}

function matchesYesNoFilter(value: number, filter: string): boolean {
  if (filter === "yes") {
    return value > 0;
  }
  if (filter === "no") {
    return value <= 0;
  }
  return true;
}

function matchesForeignNationalityNgFilter(
  value: boolean | null | undefined,
  filter: string,
): boolean {
  if (filter === "ok") {
    return value === false;
  }
  if (filter === "ng") {
    return value === true;
  }
  if (filter === "unknown") {
    return value == null;
  }
  return true;
}

function matchSideProposedFilter(status: string | undefined, filter: string): boolean {
  const proposed = Boolean(status && status !== "none");
  if (filter === "yes") {
    return proposed;
  }
  if (filter === "no") {
    return !proposed;
  }
  return true;
}

function matchSideOkFilter(judgment: string | null | undefined, filter: string): boolean {
  const ok = judgment === "ok";
  if (filter === "yes") {
    return ok;
  }
  if (filter === "no") {
    return !ok;
  }
  return true;
}

function filterProjectMatches(
  matches: ProjectMatchItemDto[],
  {
    keyword,
    rateMin,
    rateMax,
    skills,
    proposed = "",
    ok = "",
    skillSheetHas = false,
    skillSheetNone = false,
  }: {
    keyword: string;
    rateMin: string;
    rateMax: string;
    skills: string[];
    proposed?: string;
    ok?: string;
    skillSheetHas?: boolean;
    skillSheetNone?: boolean;
  },
) {
  const query = normalize(keyword);
  const minRate = parseRateFilter(rateMin);
  const maxRate = parseRateFilter(rateMax);
  const selectedSkills = skills.filter(Boolean);

  return matches.filter((row) => {
    const haystack = normalize(
      [
        row.display_name,
        row.affiliation,
        row.source_company_name,
        row.summary,
        row.reason,
        ...(row.skills ?? []),
      ]
        .filter(Boolean)
        .join(" "),
    );
    const matchesKeyword = query ? haystack.includes(query) : true;
    const desired = row.desired_rate == null ? null : toManYenForFilter(row.desired_rate);
    const matchesRate =
      desired == null
        ? true
        : (minRate == null || desired >= minRate) && (maxRate == null || desired <= maxRate);
    const matchesSkills =
      selectedSkills.length > 0
        ? selectedSkills.every((skill) => row.skills.some((item) => item.includes(skill)))
        : true;
    const matchesProposed = matchSideProposedFilter(row.project_proposal_status, proposed);
    const matchesOk = matchSideOkFilter(row.project_proposal_reply_judgment, ok);
    const matchesSkillSheet = matchesSkillSheetFilter(
      row.has_skill_sheet,
      skillSheetHas,
      skillSheetNone,
    );

    return (
      matchesKeyword &&
      matchesRate &&
      matchesSkills &&
      matchesProposed &&
      matchesOk &&
      matchesSkillSheet
    );
  });
}

function filterTalentMatches(
  matches: TalentMatchItemDto[],
  {
    keyword,
    rateMin,
    rateMax,
    skills,
    proposed = "",
    ok = "",
  }: {
    keyword: string;
    rateMin: string;
    rateMax: string;
    skills: string[];
    proposed?: string;
    ok?: string;
  },
) {
  const query = normalize(keyword);
  const minRate = parseRateFilter(rateMin);
  const maxRate = parseRateFilter(rateMax);
  const selectedSkills = skills.filter(Boolean);

  return matches.filter((row) => {
    const haystack = normalize(
      [
        row.project_title,
        row.project_code,
        row.location,
        row.distributor_company_name,
        row.reason,
        ...(row.required_skills ?? []),
      ]
        .filter(Boolean)
        .join(" "),
    );
    const matchesKeyword = query ? haystack.includes(query) : true;
    const projectMin = row.rate_min == null ? null : toManYenForFilter(row.rate_min);
    const projectMax =
      row.rate_max == null ? projectMin : toManYenForFilter(row.rate_max);
    const matchesRate =
      (minRate == null || projectMax == null || projectMax >= minRate) &&
      (maxRate == null || projectMin == null || projectMin <= maxRate);
    const matchesSkills =
      selectedSkills.length > 0
        ? selectedSkills.every((skill) =>
            (row.required_skills ?? []).some((item) => item.includes(skill)),
          )
        : true;
    const matchesProposed = matchSideProposedFilter(row.talent_proposal_status, proposed);
    const matchesOk = matchSideOkFilter(row.talent_proposal_reply_judgment, ok);

    return matchesKeyword && matchesRate && matchesSkills && matchesProposed && matchesOk;
  });
}

function filterTalents(
  talents: TalentDto[],
  {
    keyword,
    rateMin,
    rateMax,
    skills,
    proposed = "",
    ok = "",
    skillSheetHas = false,
    skillSheetNone = false,
  }: {
    keyword: string;
    rateMin: string;
    rateMax: string;
    skills: string[];
    proposed?: string;
    ok?: string;
    skillSheetHas?: boolean;
    skillSheetNone?: boolean;
  },
) {
  const query = normalize(keyword);
  const minRate = parseRateFilter(rateMin);
  const maxRate = parseRateFilter(rateMax);
  const selectedSkills = skills.filter(Boolean);

  return talents.filter((talent) => {
    const haystack = normalize(
      [
        talent.display_name,
        talent.affiliation,
        talent.source_company_name,
        talent.summary,
        ...(talent.skills ?? []),
      ]
        .filter(Boolean)
        .join(" "),
    );
    const matchesKeyword = query ? haystack.includes(query) : true;
    const desired =
      talent.desired_rate == null ? null : toManYenForFilter(talent.desired_rate);
    const matchesRate =
      desired == null
        ? true
        : (minRate == null || desired >= minRate) && (maxRate == null || desired <= maxRate);
    const matchesSkills =
      selectedSkills.length > 0
        ? selectedSkills.every((skill) => talent.skills.some((item) => item.includes(skill)))
        : true;
    const matchesProposed = matchesYesNoFilter(talent.proposed_project_count ?? 0, proposed);
    const matchesOk = matchesYesNoFilter(talent.proposed_ok_count ?? 0, ok);
    const matchesSkillSheet = matchesSkillSheetFilter(
      talent.has_skill_sheet,
      skillSheetHas,
      skillSheetNone,
    );

    return (
      matchesKeyword &&
      matchesRate &&
      matchesSkills &&
      matchesProposed &&
      matchesOk &&
      matchesSkillSheet
    );
  });
}

function filterProjects(
  projects: ProjectDto[],
  {
    keyword,
    rateMin,
    rateMax,
    skills,
    proposed = "",
    ok = "",
    foreignNationalityNg = "",
  }: {
    keyword: string;
    rateMin: string;
    rateMax: string;
    skills: string[];
    proposed?: string;
    ok?: string;
    foreignNationalityNg?: string;
  },
) {
  const query = normalize(keyword);
  const minRate = parseRateFilter(rateMin);
  const maxRate = parseRateFilter(rateMax);
  const selectedSkills = skills.filter(Boolean);

  return projects.filter((project) => {
    const haystack = normalize(
      [
        project.title,
        project.project_code,
        project.location,
        project.work_style,
        project.working_hours,
        project.settlement_range,
        project.summary,
        project.distributor_company_name,
        ...(project.required_skills ?? []),
      ]
        .filter(Boolean)
        .join(" "),
    );
    const matchesKeyword = query ? haystack.includes(query) : true;
    const projectMin =
      project.rate_min == null ? null : toManYenForFilter(project.rate_min);
    const projectMax =
      project.rate_max == null
        ? projectMin
        : toManYenForFilter(project.rate_max);
    const matchesRate =
      (minRate == null || projectMax == null || projectMax >= minRate) &&
      (maxRate == null || projectMin == null || projectMin <= maxRate);
    const matchesSkills =
      selectedSkills.length > 0
        ? selectedSkills.every((skill) =>
            (project.required_skills ?? []).some((item) => item.includes(skill)),
          )
        : true;
    const matchesProposed = matchesYesNoFilter(project.proposed_talent_count ?? 0, proposed);
    const matchesOk = matchesYesNoFilter(project.proposed_ok_count ?? 0, ok);
    const matchesForeignNationality = matchesForeignNationalityNgFilter(
      project.foreign_nationality_ng,
      foreignNationalityNg,
    );

    return (
      matchesKeyword &&
      matchesRate &&
      matchesSkills &&
      matchesProposed &&
      matchesOk &&
      matchesForeignNationality
    );
  });
}

