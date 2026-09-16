const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type GmailAuthStatus = "connected" | "disconnected" | "expired";

export type SettingsPayload = {
  ingest_data_retention_days: number;
  gmail_sort_label_talent: string;
  gmail_sort_label_project: string;
  ai_assist_enabled: boolean;
  ai_judgement_top_n: number;
  dashboard_rule_score_min: number;
  own_company_name: string;
  apply_from_address: string;
  reply_keywords_ok: string;
  reply_keywords_ng: string;
  outreach_template_project_propose: string;
  outreach_template_talent_propose: string;
  talent_propose_rate_markup_man_yen: number;
  skill_sheet_drive_folder_id: string;
  gmail_connected_account: string | null;
  gmail_auth_status: GmailAuthStatus;
  gmail_last_checked_at: string | null;
  gmail_error_code: string | null;
  gmail_setup_required: boolean;
  gmail_setup_message: string | null;
  gmail_oauth_client_configured: boolean;
  gmail_oauth_client_id: string | null;
  gmail_oauth_redirect_uri: string;
};

export type SettingsUpdatePayload = Partial<
  Pick<
    SettingsPayload,
    | "ingest_data_retention_days"
    | "gmail_sort_label_talent"
    | "gmail_sort_label_project"
    | "ai_assist_enabled"
    | "ai_judgement_top_n"
    | "dashboard_rule_score_min"
    | "own_company_name"
    | "apply_from_address"
    | "reply_keywords_ok"
    | "reply_keywords_ng"
    | "outreach_template_project_propose"
    | "outreach_template_talent_propose"
    | "talent_propose_rate_markup_man_yen"
    | "skill_sheet_drive_folder_id"
  >
> & {
  gmail_oauth_client_id?: string;
  gmail_oauth_client_secret?: string;
  gmail_oauth_project_id?: string;
};

export async function fetchSettings(): Promise<SettingsPayload> {
  const response = await fetch(`${API_BASE_URL}/api/settings`);
  if (!response.ok) {
    throw new Error("設定の取得に失敗しました");
  }
  const data = (await response.json()) as Partial<SettingsPayload>;
  return {
    ingest_data_retention_days: data.ingest_data_retention_days ?? 0,
    gmail_sort_label_talent: data.gmail_sort_label_talent ?? "SES人材紹介",
    gmail_sort_label_project: data.gmail_sort_label_project ?? "SES案件配信",
    ai_assist_enabled: data.ai_assist_enabled ?? false,
    ai_judgement_top_n: data.ai_judgement_top_n ?? 5,
    dashboard_rule_score_min:
      typeof data.dashboard_rule_score_min === "number" ? data.dashboard_rule_score_min : 50,
    own_company_name: data.own_company_name ?? "",
    apply_from_address: data.apply_from_address ?? "",
    reply_keywords_ok: data.reply_keywords_ok ?? "よろしくお願いします\n前向き\n候補として\nご提案ください",
    reply_keywords_ng: data.reply_keywords_ng ?? "見送り\n他決\n辞退\n今回は結構",
    outreach_template_project_propose:
      data.outreach_template_project_propose ??
      "{{company_name}}\n{{contact_name}} 様ご関係各位\n\nお世話になっております。マッチング結果に基づき、以下の案件をご提案いたします。\n\n{{items}}ご検討のほど、よろしくお願いいたします。\n",
    outreach_template_talent_propose:
      data.outreach_template_talent_propose ??
      "{{company_name}}\n{{contact_name}} 様\n\nお世話になっております。以下の要員をご提案いたします。\n\n■ 案件: {{project_title}}\n\n{{items}}ご検討のほど、よろしくお願いいたします。\n",
    talent_propose_rate_markup_man_yen:
      typeof data.talent_propose_rate_markup_man_yen === "number" ? data.talent_propose_rate_markup_man_yen : 0,
    skill_sheet_drive_folder_id: data.skill_sheet_drive_folder_id ?? "",
    gmail_connected_account: data.gmail_connected_account ?? null,
    gmail_auth_status: data.gmail_auth_status ?? "disconnected",
    gmail_last_checked_at: data.gmail_last_checked_at ?? null,
    gmail_error_code: data.gmail_error_code ?? null,
    gmail_setup_required: data.gmail_setup_required ?? false,
    gmail_setup_message: data.gmail_setup_message ?? null,
    gmail_oauth_client_configured: data.gmail_oauth_client_configured ?? false,
    gmail_oauth_client_id: data.gmail_oauth_client_id ?? null,
    gmail_oauth_redirect_uri: data.gmail_oauth_redirect_uri ?? "",
  };
}

export async function updateSettings(payload: SettingsUpdatePayload): Promise<SettingsPayload> {
  const response = await fetch(`${API_BASE_URL}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("設定の保存に失敗しました");
  }
  return response.json();
}

export type SkillCatalogGroupDto = {
  id: string;
  label: string;
  sort_order: number;
  is_uncategorized: boolean;
  options: string[];
};

export type SkillCategoryDto = {
  id: string;
  name: string;
  sort_order: number;
  is_uncategorized: boolean;
  skill_count: number;
};

export type SkillMasterItemDto = {
  id: string;
  name: string;
  category_id: string;
  category_name: string;
};

export async function fetchSkillCatalog(): Promise<SkillCatalogGroupDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/skills/catalog`);
  if (!response.ok) {
    throw new Error("スキルカタログの取得に失敗しました");
  }
  return response.json();
}

export async function fetchSkillCategories(): Promise<SkillCategoryDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/skills/categories`);
  if (!response.ok) {
    throw new Error("スキルカテゴリの取得に失敗しました");
  }
  return response.json();
}

export async function fetchSkillMaster(): Promise<SkillMasterItemDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/skills`);
  if (!response.ok) {
    throw new Error("スキルマスタの取得に失敗しました");
  }
  return response.json();
}

export async function createSkillCategory(name: string, sortOrder?: number): Promise<SkillCategoryDto> {
  const response = await fetch(`${API_BASE_URL}/api/skills/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, sort_order: sortOrder }),
  });
  if (!response.ok) {
    throw new Error("カテゴリの追加に失敗しました");
  }
  return response.json();
}

export async function updateSkillCategory(
  categoryId: string,
  payload: { name?: string; sort_order?: number },
): Promise<SkillCategoryDto> {
  const response = await fetch(`${API_BASE_URL}/api/skills/categories/${categoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    if (response.status === 409) {
      throw new Error("同じ名前のカテゴリが既にあります");
    }
    throw new Error("カテゴリの更新に失敗しました");
  }
  return response.json();
}

export async function deleteSkillCategory(categoryId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/skills/categories/${categoryId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error("カテゴリの削除に失敗しました");
  }
}

export async function updateSkillCategoryId(skillId: string, categoryId: string): Promise<SkillMasterItemDto> {
  const response = await fetch(`${API_BASE_URL}/api/skills/${skillId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_id: categoryId }),
  });
  if (!response.ok) {
    throw new Error("スキルのカテゴリ変更に失敗しました");
  }
  return response.json();
}

export function buildGmailOAuthRedirectUri(apiBase: string = API_BASE_URL): string {
  return `${apiBase.replace(/\/$/, "")}/api/gmail/oauth/callback`;
}

export function startGmailOAuth(): void {
  window.location.href = `${API_BASE_URL}/api/gmail/oauth/start`;
}

export async function connectGmailFromWeb(payload: {
  gmail_oauth_client_id: string;
  gmail_oauth_client_secret: string;
  gmail_oauth_project_id?: string;
}): Promise<void> {
  await updateSettings(payload);
  startGmailOAuth();
}

export function formatGmailCheckedAt(iso: string | null): string {
  if (!iso) {
    return "未確認";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString("ja-JP");
}

export function formatReceivedDate(iso: string | null | undefined): string {
  if (!iso) {
    return "-";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleDateString("ja-JP");
}

export class BatchRunError extends Error {
  errorCode: string;
  errorMessage: string;

  constructor(errorCode: string, errorMessage: string) {
    super(errorMessage);
    this.name = "BatchRunError";
    this.errorCode = errorCode;
    this.errorMessage = errorMessage;
  }
}

export type BatchStartDto = {
  status: string;
  job: string;
  message: string;
  job_id?: string | null;
};

export type PipelineStepProgressDto = {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed";
  progress_percent: number;
  elapsed_seconds: number;
  eta_seconds: number | null;
  eta_label: string | null;
  detail: string | null;
  weight: number;
};

export type PipelineProgressDto = {
  job_id: string;
  status: "not_found" | "running" | "completed" | "failed";
  phase: string;
  phase_label: string;
  current_step: number;
  total_steps: number;
  progress_percent: number;
  processed_messages: number;
  total_messages: number | null;
  ingested: number;
  skipped: number;
  failed: number;
  started_at: string | null;
  updated_at: string | null;
  elapsed_seconds: number;
  eta_seconds: number | null;
  eta_label: string | null;
  total_estimated_seconds: number | null;
  error_code: string | null;
  error_message: string | null;
  detail: string | null;
  steps: PipelineStepProgressDto[];
};

export async function runGmailPipelineBatch(): Promise<BatchStartDto> {
  const response = await fetch(`${API_BASE_URL}/api/batches/gmail-pipeline`, {
    method: "POST",
  });
  if (!response.ok) {
    try {
      const body = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = body.detail;
      if (detail && typeof detail === "object" && detail.error_code && detail.error_message) {
        throw new BatchRunError(detail.error_code, detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new BatchRunError("ERR-0030", detail);
      }
    } catch (error) {
      if (error instanceof BatchRunError) {
        throw error;
      }
    }
    throw new BatchRunError("ERR-0030", "メール取込の開始に失敗しました");
  }
  return response.json() as Promise<BatchStartDto>;
}

export async function fetchGmailPipelineProgress(jobId?: string): Promise<PipelineProgressDto> {
  const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  const response = await fetch(`${API_BASE_URL}/api/batches/gmail-pipeline/progress${query}`);
  if (!response.ok) {
    throw new Error("メール取込の進捗取得に失敗しました");
  }
  return response.json() as Promise<PipelineProgressDto>;
}

export type RunningBatchJobDto = {
  pid: number;
  job: string;
  job_label: string;
};

export type BatchRunningDto = {
  running: boolean;
  jobs: RunningBatchJobDto[];
};

export type BatchStopDto = {
  stopped: boolean;
  killed_count: number;
  jobs: RunningBatchJobDto[];
  message: string;
};

export async function fetchRunningBatchJobs(): Promise<BatchRunningDto> {
  const response = await fetch(`${API_BASE_URL}/api/batches/running`);
  if (!response.ok) {
    throw new Error("実行中バッチの取得に失敗しました");
  }
  return response.json() as Promise<BatchRunningDto>;
}

export async function stopRunningBatchJobs(): Promise<BatchStopDto> {
  const response = await fetch(`${API_BASE_URL}/api/batches/stop`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("バッチ処理の停止に失敗しました");
  }
  return response.json() as Promise<BatchStopDto>;
}

export type PurgeIngestDto = {
  deleted_emails: number;
  deleted_talents: number;
  deleted_projects: number;
  deleted_matches: number;
  deleted_match_runs: number;
  deleted_outreach_messages: number;
  deleted_outreach_replies: number;
  deleted_talent_skill_sheets: number;
  message: string;
};

export async function purgeAllIngestData(): Promise<PurgeIngestDto> {
  const response = await fetch(`${API_BASE_URL}/api/batches/purge-ingest-data`, {
    method: "POST",
  });
  if (!response.ok) {
    try {
      const body = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = body.detail;
      if (detail && typeof detail === "object" && detail.error_code && detail.error_message) {
        throw new BatchRunError(detail.error_code, detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new BatchRunError("ERR-0030", detail);
      }
    } catch (error) {
      if (error instanceof BatchRunError) {
        throw error;
      }
    }
    throw new BatchRunError("ERR-0030", "取込データの全削除に失敗しました");
  }
  return response.json() as Promise<PurgeIngestDto>;
}

export async function runIngestCleanupBatch(): Promise<{ status: string; job: string; message: string }> {
  return runBatchJob("/api/batches/ingest-cleanup", "過去取込データの削除に失敗しました");
}

export type MatchRunDto = {
  id: string;
  trigger: string;
  status: string;
  ai_judgement_top_n: number | null;
  stats: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
};

export async function runMatchScoreBatch(options?: {
  force?: boolean;
  talentId?: string;
  projectId?: string;
}): Promise<MatchRunDto> {
  const response = await fetch(`${API_BASE_URL}/api/match-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      force: Boolean(options?.force),
      talent_id: options?.talentId || undefined,
      project_id: options?.projectId || undefined,
    }),
  });
  if (!response.ok) {
    try {
      const body = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = body.detail;
      if (detail && typeof detail === "object" && detail.error_code && detail.error_message) {
        throw new BatchRunError(detail.error_code, detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new BatchRunError("ERR-0030", detail);
      }
    } catch (error) {
      if (error instanceof BatchRunError) {
        throw error;
      }
    }
    throw new BatchRunError("ERR-0030", "ルールスコア採点の実行に失敗しました");
  }
  return response.json() as Promise<MatchRunDto>;
}

export async function fetchMatchRuns(): Promise<MatchRunDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/match-runs`);
  if (!response.ok) {
    throw new Error("マッチング実行履歴の取得に失敗しました");
  }
  return response.json() as Promise<MatchRunDto[]>;
}

export type MatchListItemDto = {
  id: string;
  talent_id: string;
  project_id: string;
  score: number;
  score_band: string | null;
  score_breakdown: Record<string, unknown> | null;
  display_name: string | null;
  project_title: string | null;
  desired_rate: number | null;
  skills: string[];
  ai_score: number | null;
  reason: string | null;
  reply_judgment: string | null;
  reply_id: string | null;
  talent_sent_at: string | null;
  project_sent_at: string | null;
  outreach_status: string;
};

export async function fetchMatchesForRun(matchRunId: string): Promise<MatchListItemDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/match-runs/${matchRunId}/matches`);
  if (!response.ok) {
    throw new Error("マッチ結果の取得に失敗しました");
  }
  return response.json() as Promise<MatchListItemDto[]>;
}

export async function runAiJudge(
  matchRunId: string,
  options?: { projectId?: string; matchIds?: string[] },
): Promise<MatchRunDto> {
  const body: { project_id?: string; match_ids?: string[] } = {};
  if (options?.projectId) {
    body.project_id = options.projectId;
  }
  if (options?.matchIds && options.matchIds.length > 0) {
    body.match_ids = options.matchIds;
  }
  const response = await fetch(`${API_BASE_URL}/api/match-runs/${matchRunId}/ai-judge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = payload.detail;
      if (detail && typeof detail === "object" && detail.error_code && detail.error_message) {
        throw new BatchRunError(detail.error_code, detail.error_message);
      }
    } catch (error) {
      if (error instanceof BatchRunError) {
        throw error;
      }
    }
    throw new BatchRunError("ERR-0030", "AI判定の実行に失敗しました");
  }
  return response.json() as Promise<MatchRunDto>;
}

export type TalentProposeDraftDto = {
  match_ids: string[];
  match_id: string;
  project_ids: string[];
  project_id: string;
  project_titles: string[];
  project_title: string | null;
  talent_id?: string | null;
  talent_name?: string | null;
  to_address: string | null;
  cc_addresses?: string[];
  subject: string;
  body_text: string;
  already_sent: boolean;
  warning?: string | null;
};

export async function previewTalentPropose(matchIds: string[]): Promise<TalentProposeDraftDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/outreach/talent-propose/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ match_ids: matchIds }),
  });
  if (!response.ok) {
    let detail = "提案下書きの取得に失敗しました";
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_message?: string };
      };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (payload.detail && typeof payload.detail === "object" && payload.detail.error_message) {
        detail = payload.detail.error_message;
      } else if (response.status === 404) {
        detail = "提案プレビュー API が見つかりません。API を再起動してください。";
      }
    } catch {
      if (response.status === 404) {
        detail = "提案プレビュー API が見つかりません。API を再起動してください。";
      }
    }
    throw new Error(detail);
  }
  const payload = (await response.json()) as { drafts: TalentProposeDraftDto[] };
  return (payload.drafts ?? []).map((row) => ({
    ...row,
    match_ids: row.match_ids?.length ? row.match_ids : [row.match_id],
    project_ids: row.project_ids?.length ? row.project_ids : [row.project_id],
    project_titles: row.project_titles?.length
      ? row.project_titles
      : row.project_title
        ? [row.project_title]
        : [],
  }));
}

export async function proposeTalents(
  matchIds: string[],
  drafts?: {
    match_id: string;
    match_ids?: string[];
    body_text: string;
    to_address?: string | null;
    cc_addresses?: string[] | null;
  }[],
): Promise<{ status: string; message: string }> {
  const body: {
    match_ids: string[];
    drafts?: {
      match_id: string;
      match_ids?: string[];
      body_text: string;
      to_address?: string | null;
      cc_addresses?: string[] | null;
    }[];
  } = {
    match_ids: matchIds,
  };
  if (drafts && drafts.length > 0) {
    body.drafts = drafts;
  }
  // Same-origin Next プロキシ経由（CORS / drafts 転送を Next 側で扱う）
  let response: Response;
  try {
    response = await fetch(`/api/outreach/talent-propose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      throw new Error(
        "送信APIに接続できませんでした。Web（Next.js）が起動しているか確認してください。",
      );
    }
    throw err instanceof Error ? err : new Error(String(err));
  }
  if (!response.ok) {
    let detail = "案件提案の送信に失敗しました";
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_message?: string; error_code?: string };
      };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (
        payload.detail &&
        typeof payload.detail === "object" &&
        payload.detail.error_message
      ) {
        detail = payload.detail.error_message;
      }
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return response.json();
}

export type ProjectProposeAttachmentDto = {
  talent_id: string;
  talent_name: string | null;
  filename: string;
  original_filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  web_view_link: string | null;
};

export type ProjectProposeDraftDto = {
  project_id: string;
  match_ids: string[];
  talent_ids: string[];
  talent_names: string[];
  to_address: string | null;
  cc_addresses?: string[];
  subject: string;
  body_text: string;
  already_sent: boolean;
  attachments?: ProjectProposeAttachmentDto[];
  attachments_total_bytes?: number;
  attachments_over_size_limit?: boolean;
  attachments_note?: string | null;
};

export async function previewProjectPropose(
  projectId: string,
  matchIds: string[],
): Promise<ProjectProposeDraftDto> {
  const response = await fetch(`${API_BASE_URL}/api/outreach/project-propose/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, match_ids: matchIds }),
  });
  if (!response.ok) {
    let detail = "提案下書きの取得に失敗しました";
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_message?: string };
      };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (payload.detail && typeof payload.detail === "object" && payload.detail.error_message) {
        detail = payload.detail.error_message;
      } else if (response.status === 404) {
        detail = "提案プレビュー API が見つかりません。API を再起動してください。";
      }
    } catch {
      if (response.status === 404) {
        detail = "提案プレビュー API が見つかりません。API を再起動してください。";
      }
    }
    throw new Error(detail);
  }
  const payload = (await response.json()) as { draft: ProjectProposeDraftDto };
  return payload.draft;
}

export async function proposeToProject(
  projectId: string,
  matchIds: string[],
  bodyText?: string,
  options?: { to_address?: string | null; cc_addresses?: string[] | null },
): Promise<{ status: string; message: string }> {
  const body: {
    project_id: string;
    match_ids: string[];
    body_text?: string;
    to_address?: string | null;
    cc_addresses?: string[] | null;
  } = {
    project_id: projectId,
    match_ids: matchIds,
  };
  if (bodyText != null) {
    body.body_text = bodyText;
  }
  if (options?.to_address != null) {
    body.to_address = options.to_address;
  }
  if (options?.cc_addresses != null) {
    body.cc_addresses = options.cc_addresses;
  }
  let response: Response;
  try {
    response = await fetch(`/api/outreach/project-propose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      throw new Error(
        "送信APIに接続できませんでした。Web（Next.js）が起動しているか確認してください。",
      );
    }
    throw err instanceof Error ? err : new Error(String(err));
  }
  if (!response.ok) {
    let detail = "人材提案の送信に失敗しました";
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_message?: string };
      };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (payload.detail && typeof payload.detail === "object" && payload.detail.error_message) {
        detail = payload.detail.error_message;
      }
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function syncOutreachReplies(
  kind: "talent_proposal" | "project_proposal" | "all" = "all",
): Promise<{ status: string; message: string }> {
  const params = new URLSearchParams({ kind });
  const response = await fetch(`${API_BASE_URL}/api/outreach/reply-sync?${params.toString()}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("返信同期に失敗しました");
  }
  return response.json();
}

export type MatchOutreachStatusUpdateDto = {
  match_id: string;
  kind?: "talent_proposal" | "project_proposal";
  judgment: string;
  judgment_source: string;
  reply_id: string;
  reply_body: string | null;
  reply_received_at: string | null;
  outreach_status: string;
  talent_proposal_status?: string;
  project_proposal_status?: string;
  message: string;
};

export async function updateMatchOutreachStatus(
  matchId: string,
  judgment: "ok" | "ng" | "unknown",
  kind: "talent_proposal" | "project_proposal" = "talent_proposal",
): Promise<MatchOutreachStatusUpdateDto> {
  const response = await fetch(`${API_BASE_URL}/api/outreach/matches/${encodeURIComponent(matchId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ judgment, kind }),
  });
  if (!response.ok) {
    let message = "ステータスの更新に失敗しました";
    try {
      const data = (await response.json()) as { detail?: { error_message?: string } | string };
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail?.error_message) {
        message = data.detail.error_message;
      }
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return response.json();
}

async function runBatchJob(path: string, fallbackMessage: string): Promise<{ status: string; job: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
  });
  if (!response.ok) {
    try {
      const body = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = body.detail;
      if (detail && typeof detail === "object" && detail.error_code && detail.error_message) {
        throw new BatchRunError(detail.error_code, detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new BatchRunError("ERR-0030", detail);
      }
    } catch (error) {
      if (error instanceof BatchRunError) {
        throw error;
      }
    }
    throw new BatchRunError("ERR-0030", fallbackMessage);
  }
  return response.json();
}

export type TalentDto = {
  id: string;
  display_name: string;
  skills: string[];
  desired_rate: number | null;
  available_from: string | null;
  work_style: string | null;
  nearest_station: string | null;
  is_foreign_national?: boolean | null;
  commerce_flow?: string | null;
  summary: string | null;
  status: string;
  email_id: string;
  created_at: string;
  affiliation?: string | null;
  age?: number | null;
  gender?: string | null;
  experience_years?: number | null;
  source_company_name?: string | null;
  introducer_company_id?: string | null;
  proposal_cc_emails?: string[];
  proposed_project_count?: number;
  proposed_no_reply_count?: number;
  proposed_ok_count?: number;
  proposed_ng_count?: number;
  has_skill_sheet?: boolean;
  email_subject?: string | null;
  email_from?: string | null;
  email_label?: string | null;
  email_received_at?: string | null;
  skill_sheets?: TalentSkillSheetDto[];
};

export type TalentSkillSheetDto = {
  id: string;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
  source_type: string;
  access_status: string;
  web_view_link: string | null;
  error_message: string | null;
  experience_extract_status?: string | null;
};

export type ProjectDto = {
  id: string;
  title: string;
  project_code: string | null;
  required_skills: string[];
  preferred_skills?: string[];
  rate_min: number | null;
  rate_max: number | null;
  location: string | null;
  work_style: string | null;
  working_hours?: string | null;
  start_date: string | null;
  foreign_nationality_ng?: boolean | null;
  commerce_flow_limit?: string | null;
  settlement_range?: string | null;
  interview_count?: number | null;
  headcount?: number | null;
  summary: string | null;
  status: string;
  email_id: string;
  created_at: string;
  distributor_company_id?: string | null;
  distributor_company_name?: string | null;
  proposal_cc_emails?: string[];
  proposed_talent_count?: number;
  proposed_no_reply_count?: number;
  proposed_ok_count?: number;
  proposed_ng_count?: number;
  email_subject?: string | null;
  email_from?: string | null;
  email_label?: string | null;
  email_received_at?: string | null;
};

export type EmailDto = {
  id: string;
  gmail_message_id: string;
  subject: string;
  from_address: string;
  label: string;
  email_type: string;
  status: string;
  received_at: string;
  talent_id: string | null;
  project_id: string | null;
};

export type DashboardPeriodRange = "week" | "month" | "half_year" | "year";

export type DashboardDailyPointDto = {
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

export type DashboardCompanyIngestDto = {
  company_id: string | null;
  company_name: string;
  emails_project: number;
  emails_talent: number;
  emails_total: number;
};

export type DashboardFunnelDto = {
  ingested: number;
  proposable: number;
  proposed: number;
  replied: number;
  ok: number;
  constraint_loss: {
    foreign_nationality: number;
    commerce_flow: number;
    other_zero: number;
    total: number;
  };
};

export type DashboardScoreBandOkDto = {
  score_band: string;
  proposed_count: number;
  ok_count: number;
  ok_rate: number;
};

export type DashboardHighScoreMatchDto = {
  match_id: string;
  talent_id: string;
  talent_name: string;
  project_id: string;
  project_title: string;
  project_code?: string | null;
  score: number;
  score_band?: string | null;
  proposed?: boolean;
};

export type DashboardDto = {
  talent_count: number;
  project_count: number;
  pending_email_count: number;
  gmail_ingest_talent_label?: string;
  gmail_ingest_project_label?: string;
  gmail_ingest_talent_count?: number | null;
  gmail_ingest_project_count?: number | null;
  gmail_ingest_talent_count_capped?: boolean;
  gmail_ingest_project_count_capped?: boolean;
  talent_proposal_sent_count: number;
  project_proposal_sent_count: number;
  unscored_talent_count?: number;
  unscored_project_count?: number;
  period_range: DashboardPeriodRange | string;
  period_days: number;
  period_start: string;
  period_end: string;
  can_go_forward: boolean;
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
  project_proposed_rate: number;
  talent_proposed_rate: number;
  daily: DashboardDailyPointDto[];
  by_company: DashboardCompanyIngestDto[];
  funnel: DashboardFunnelDto;
  ok_by_score_band: DashboardScoreBandOkDto[];
  rule_score_min?: number;
  high_score_match_count?: number;
  high_score_matches?: DashboardHighScoreMatchDto[];
};

export async function fetchDashboard(options?: {
  range?: DashboardPeriodRange;
  end?: string;
}): Promise<DashboardDto> {
  const params = new URLSearchParams();
  if (options?.range) {
    params.set("range", options.range);
  }
  if (options?.end) {
    params.set("end", options.end);
  }
  const query = params.toString();
  const response = await fetch(`${API_BASE_URL}/api/dashboard${query ? `?${query}` : ""}`);
  if (!response.ok) {
    throw new Error("ダッシュボードの取得に失敗しました");
  }
  return response.json();
}

export async function setDashboardHighScoreMatchProposed(options: {
  talentId: string;
  projectId: string;
  proposed: boolean;
}): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/dashboard/high-score-matches/display`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      talent_id: options.talentId,
      project_id: options.projectId,
      proposed: options.proposed,
    }),
  });
  if (!response.ok) {
    throw new Error("組み合わせの表示更新に失敗しました");
  }
}

export async function fetchEmails(): Promise<EmailDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/emails`);
  if (!response.ok) {
    throw new Error("メール一覧の取得に失敗しました");
  }
  return response.json();
}

export type EmailDetailDto = {
  id: string;
  gmail_message_id: string;
  subject: string;
  from_address: string;
  label: string;
  email_type: string;
  status: string;
  received_at: string;
  body_text: string;
};

export async function fetchEmailDetail(emailId: string): Promise<EmailDetailDto> {
  const response = await fetch(`${API_BASE_URL}/api/emails/${emailId}`);
  if (!response.ok) {
    throw new Error("メール詳細の取得に失敗しました");
  }
  return response.json();
}

export async function fetchTalents(): Promise<TalentDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/talents`);
  if (!response.ok) {
    throw new Error("人材一覧の取得に失敗しました");
  }
  return response.json();
}

export async function fetchTalent(id: string): Promise<TalentDto> {
  const response = await fetch(`${API_BASE_URL}/api/talents/${id}`);
  if (!response.ok) {
    throw new Error("人材詳細の取得に失敗しました");
  }
  return response.json();
}

export type TalentUpdatePayload = {
  display_name?: string;
  affiliation?: string | null;
  age?: number | null;
  gender?: string | null;
  experience_years?: number | null;
  desired_rate?: number | null;
  available_from?: string | null;
  work_style?: string | null;
  nearest_station?: string | null;
  skills?: string[];
  source_company_name?: string | null;
  is_foreign_national?: boolean | null;
  commerce_flow?: string | null;
  summary?: string | null;
  proposal_cc_emails?: string[];
  status?: "active" | "inactive";
};

export type TalentCreatePayload = {
  title: string;
  body: string;
  from_address?: string;
};

async function readApiErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: string | { error_code?: string; error_message?: string };
    };
    const detail = payload.detail;
    if (detail && typeof detail === "object" && detail.error_message) {
      return detail.error_message;
    }
    if (typeof detail === "string" && detail) {
      return detail;
    }
  } catch {
    // ignore
  }
  return fallback;
}

export async function createTalent(body: TalentCreatePayload): Promise<TalentDto> {
  const response = await fetch(`${API_BASE_URL}/api/talents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response, "人材の登録に失敗しました"));
  }
  return response.json() as Promise<TalentDto>;
}

export async function updateTalent(id: string, body: TalentUpdatePayload): Promise<TalentDto> {
  const response = await fetch(`${API_BASE_URL}/api/talents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = payload.detail;
      if (detail && typeof detail === "object" && detail.error_message) {
        throw new Error(detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new Error(detail);
      }
    } catch (error) {
      if (error instanceof Error && error.message !== "人材の更新に失敗しました") {
        throw error;
      }
    }
    throw new Error("人材の更新に失敗しました");
  }
  return response.json() as Promise<TalentDto>;
}

export type ProjectUpdatePayload = {
  title?: string;
  project_code?: string | null;
  required_skills?: string[];
  preferred_skills?: string[];
  rate_min?: number | null;
  rate_max?: number | null;
  location?: string | null;
  work_style?: string | null;
  working_hours?: string | null;
  start_date?: string | null;
  foreign_nationality_ng?: boolean | null;
  commerce_flow_limit?: string | null;
  settlement_range?: string | null;
  interview_count?: number | null;
  headcount?: number | null;
  summary?: string | null;
  proposal_cc_emails?: string[];
  status?: "open" | "closed";
};

export type ProjectCreatePayload = {
  title: string;
  body: string;
  from_address?: string;
};

export async function createProject(body: ProjectCreatePayload): Promise<ProjectDto> {
  const response = await fetch(`${API_BASE_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response, "案件の登録に失敗しました"));
  }
  return response.json() as Promise<ProjectDto>;
}

export async function updateProject(id: string, body: ProjectUpdatePayload): Promise<ProjectDto> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = payload.detail;
      if (detail && typeof detail === "object" && detail.error_message) {
        throw new Error(detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new Error(detail);
      }
    } catch (error) {
      if (error instanceof Error && error.message !== "案件の更新に失敗しました") {
        throw error;
      }
    }
    throw new Error("案件の更新に失敗しました");
  }
  return response.json() as Promise<ProjectDto>;
}

export async function deleteTalent(id: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/talents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    let message = "人材の削除に失敗しました";
    try {
      const data = (await response.json()) as { detail?: { error_message?: string } | string };
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail?.error_message) {
        message = data.detail.error_message;
      }
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return response.json();
}

export async function fetchProjects(): Promise<ProjectDto[]> {
  const response = await fetch(`${API_BASE_URL}/api/projects`);
  if (!response.ok) {
    throw new Error("案件一覧の取得に失敗しました");
  }
  return response.json();
}

export async function fetchProject(id: string): Promise<ProjectDto> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${id}`);
  if (!response.ok) {
    throw new Error("案件詳細の取得に失敗しました");
  }
  return response.json();
}

export async function deleteProject(id: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    let message = "案件の削除に失敗しました";
    try {
      const data = (await response.json()) as { detail?: { error_message?: string } | string };
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail?.error_message) {
        message = data.detail.error_message;
      }
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return response.json();
}

export type CompanyDto = {
  id: string;
  name: string;
  kind: string;
  domain: string | null;
  default_email: string | null;
  notes: string | null;
  contact_count: number;
  created_at: string;
  contacts?: ContactDto[];
};

export type ContactDto = {
  id: string;
  company_id: string;
  company_name?: string | null;
  name: string;
  email: string;
  role: string;
  phone: string | null;
  is_active: boolean;
  created_at?: string;
};

export async function fetchCompanies(q?: string): Promise<CompanyDto[]> {
  const path = q?.trim()
    ? `/api/companies?q=${encodeURIComponent(q.trim())}`
    : "/api/companies";
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error("企業一覧の取得に失敗しました");
  }
  return response.json();
}

export async function fetchCompany(id: string): Promise<CompanyDto> {
  const response = await fetch(`${API_BASE_URL}/api/companies/${id}`);
  if (!response.ok) {
    throw new Error("企業詳細の取得に失敗しました");
  }
  return response.json();
}

export async function createCompany(body: {
  name: string;
  kind: string;
  domain?: string | null;
  default_email?: string | null;
  notes?: string | null;
}): Promise<CompanyDto> {
  const response = await fetch(`${API_BASE_URL}/api/companies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error("企業の作成に失敗しました");
  }
  return response.json();
}

export async function updateCompany(
  id: string,
  body: {
    name?: string;
    kind?: string;
    domain?: string | null;
    default_email?: string | null;
    notes?: string | null;
  },
): Promise<CompanyDto> {
  const response = await fetch(`${API_BASE_URL}/api/companies/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error("企業の更新に失敗しました");
  }
  return response.json();
}

export async function deleteCompany(id: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/api/companies/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    try {
      const payload = (await response.json()) as {
        detail?: string | { error_code?: string; error_message?: string };
      };
      const detail = payload.detail;
      if (detail && typeof detail === "object" && detail.error_message) {
        throw new Error(detail.error_message);
      }
      if (typeof detail === "string" && detail) {
        throw new Error(detail);
      }
    } catch (error) {
      if (error instanceof Error && error.message !== "企業の削除に失敗しました") {
        throw error;
      }
    }
    throw new Error("企業の削除に失敗しました");
  }
  return response.json();
}

export async function fetchContacts(params?: {
  companyId?: string;
  q?: string;
}): Promise<ContactDto[]> {
  const query = new URLSearchParams();
  if (params?.companyId) query.set("company_id", params.companyId);
  if (params?.q?.trim()) query.set("q", params.q.trim());
  const qs = query.toString();
  const response = await fetch(`${API_BASE_URL}/api/contacts${qs ? `?${qs}` : ""}`);
  if (!response.ok) {
    throw new Error("担当者一覧の取得に失敗しました");
  }
  return response.json();
}

export async function fetchContact(id: string): Promise<ContactDto> {
  const response = await fetch(`${API_BASE_URL}/api/contacts/${id}`);
  if (!response.ok) {
    throw new Error("担当者詳細の取得に失敗しました");
  }
  return response.json();
}

export async function createContact(body: {
  company_id: string;
  name: string;
  email: string;
  role?: string;
  phone?: string | null;
  is_active?: boolean;
}): Promise<ContactDto> {
  const response = await fetch(`${API_BASE_URL}/api/contacts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = "担当者の作成に失敗しました";
    try {
      const payload = (await response.json()) as { detail?: { error_message?: string } };
      if (payload.detail?.error_message) detail = payload.detail.error_message;
    } catch {
      /* keep */
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function updateContact(
  id: string,
  body: {
    company_id?: string;
    name?: string;
    email?: string;
    role?: string;
    phone?: string | null;
    is_active?: boolean;
  },
): Promise<ContactDto> {
  const response = await fetch(`${API_BASE_URL}/api/contacts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = "担当者の更新に失敗しました";
    try {
      const payload = (await response.json()) as { detail?: { error_message?: string } };
      if (payload.detail?.error_message) detail = payload.detail.error_message;
    } catch {
      /* keep */
    }
    throw new Error(detail);
  }
  return response.json();
}

export type ProjectMatchItemDto = {
  match_id: string;
  match_run_id: string;
  talent_id: string;
  display_name: string | null;
  affiliation?: string | null;
  summary?: string | null;
  source_company_name?: string | null;
  introducer_company_id?: string | null;
  skills: string[];
  desired_rate: number | null;
  has_skill_sheet?: boolean;
  score: number;
  score_band: string | null;
  score_breakdown: Record<string, unknown> | null;
  ai_score: number | null;
  reason: string | null;
  reply_judgment: string | null;
  reply_id?: string | null;
  reply_body?: string | null;
  reply_received_at?: string | null;
  outreach_status: string;
  talent_proposal_status?: string;
  talent_proposal_reply_judgment?: string | null;
  talent_proposal_reply_id?: string | null;
  talent_proposal_reply_body?: string | null;
  talent_proposal_reply_received_at?: string | null;
  project_proposal_status?: string;
  project_proposal_reply_judgment?: string | null;
  project_proposal_reply_id?: string | null;
  project_proposal_reply_body?: string | null;
  project_proposal_reply_received_at?: string | null;
};

/**
 * 案件の採点一覧。
 * 専用 API（/projects/{id}/matches）が無い古い API でも動くよう、
 * 直近 match_run の matches を client 側で絞り込む。
 */
export async function fetchProjectMatches(projectId: string): Promise<ProjectMatchItemDto[]> {
  const dedicated = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}/matches`);
  if (dedicated.ok) {
    return dedicated.json() as Promise<ProjectMatchItemDto[]>;
  }

  const runs = await fetchMatchRuns();
  const latest = runs[0];
  if (!latest) {
    return [];
  }
  const matches = await fetchMatchesForRun(latest.id);
  return matches
    .filter((row) => row.project_id === projectId)
    .sort((a, b) => b.score - a.score)
    .map((row) => ({
      match_id: row.id,
      match_run_id: latest.id,
      talent_id: row.talent_id,
      display_name: row.display_name,
      skills: row.skills,
      desired_rate: row.desired_rate,
      has_skill_sheet: false,
      score: row.score,
      score_band: row.score_band,
      score_breakdown: row.score_breakdown ?? null,
      ai_score: row.ai_score ?? null,
      reason: row.reason ?? null,
      reply_judgment: row.reply_judgment ?? null,
      reply_id: row.reply_id ?? null,
      reply_body: null,
      reply_received_at: null,
      outreach_status: row.outreach_status ?? "none",
    }));
}

export type TalentMatchItemDto = {
  match_id: string;
  match_run_id: string;
  project_id: string;
  project_title: string | null;
  project_code?: string | null;
  location?: string | null;
  rate_min?: number | null;
  rate_max?: number | null;
  required_skills?: string[];
  distributor_company_id?: string | null;
  distributor_company_name?: string | null;
  score: number;
  score_band: string | null;
  score_breakdown: Record<string, unknown> | null;
  ai_score: number | null;
  reason: string | null;
  reply_judgment: string | null;
  reply_id?: string | null;
  reply_body?: string | null;
  reply_received_at?: string | null;
  outreach_status: string;
  talent_proposal_status?: string;
  talent_proposal_reply_judgment?: string | null;
  talent_proposal_reply_id?: string | null;
  talent_proposal_reply_body?: string | null;
  talent_proposal_reply_received_at?: string | null;
  project_proposal_status?: string;
  project_proposal_reply_judgment?: string | null;
  project_proposal_reply_id?: string | null;
  project_proposal_reply_body?: string | null;
  project_proposal_reply_received_at?: string | null;
};

/** 人材に紐づく採点案件一覧（ルールスコア降順）。 */
export async function fetchTalentMatches(talentId: string): Promise<TalentMatchItemDto[]> {
  const dedicated = await fetch(`${API_BASE_URL}/api/talents/${encodeURIComponent(talentId)}/matches`);
  if (dedicated.ok) {
    return dedicated.json() as Promise<TalentMatchItemDto[]>;
  }

  const runs = await fetchMatchRuns();
  const latest = runs[0];
  if (!latest) {
    return [];
  }
  const matches = await fetchMatchesForRun(latest.id);
  return matches
    .filter((row) => row.talent_id === talentId)
    .sort((a, b) => b.score - a.score)
    .map((row) => ({
      match_id: row.id,
      match_run_id: latest.id,
      project_id: row.project_id,
      project_title: row.project_title,
      score: row.score,
      score_band: row.score_band,
      score_breakdown: row.score_breakdown ?? null,
      ai_score: row.ai_score ?? null,
      reason: row.reason ?? null,
      reply_judgment: row.reply_judgment ?? null,
      reply_id: row.reply_id ?? null,
      reply_body: null,
      reply_received_at: null,
      outreach_status: row.outreach_status ?? "none",
    }));
}

/** outreach 進行ステータスの表示ラベル。 */
export function formatOutreachStatusLabel(
  status: string | null | undefined,
  replyJudgment?: string | null,
): string {
  const normalized = status || "none";
  if (normalized === "project_sent" || normalized === "talent_sent") {
    return "返信待ち";
  }
  if (normalized === "reply_ok" || replyJudgment === "ok") {
    return "承諾";
  }
  if (normalized === "reply_ng" || replyJudgment === "ng") {
    return "見送り";
  }
  if (normalized === "reply_unknown" || replyJudgment === "unknown") {
    return "不明";
  }
  return "未送信";
}

export function outreachStatusTone(
  status: string | null | undefined,
  replyJudgment?: string | null,
): "brand" | "ok" | "warn" | "muted" | "danger" {
  const normalized = status || "none";
  if (normalized === "reply_ok" || replyJudgment === "ok") {
    return "ok";
  }
  if (normalized === "reply_ng" || replyJudgment === "ng") {
    return "danger";
  }
  if (normalized === "reply_unknown" || replyJudgment === "unknown") {
    return "warn";
  }
  if (normalized === "project_sent" || normalized === "talent_sent") {
    return "brand";
  }
  return "muted";
}

/** 取込メール status の表示ラベル。 */
export function formatEmailStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "pending":
      return "未処理";
    case "summarized":
      return "要約済";
    case "needs_review":
      return "要確認";
    case "failed":
      return "失敗";
    case "skipped":
      return "スキップ";
    default:
      return status ? String(status) : "-";
  }
}

export function formatSkillSheetExperienceExtractLabel(
  status: string | null | undefined,
): string {
  switch (status) {
    case "ok":
      return "経験抽出: 成功";
    case "empty":
      return "経験抽出: 空（スキャンPDF等）";
    case "unsupported":
      return "経験抽出: 非対応形式";
    case "failed":
      return "経験抽出: 失敗";
    default:
      return "経験抽出: 未実施";
  }
}

/** 人材 status の表示ラベル。 */
export function formatTalentStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "active":
      return "有効";
    case "inactive":
      return "無効";
    default:
      return status ? String(status) : "-";
  }
}

/** 案件 status の表示ラベル。 */
export function formatProjectStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "open":
      return "募集中";
    case "closed":
      return "終了";
    default:
      return status ? String(status) : "-";
  }
}

/** マッチング実行 status の表示ラベル。 */
export function formatMatchRunStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "running":
      return "実行中";
    case "completed":
      return "完了";
    case "failed":
      return "失敗";
    case "ok":
      return "完了";
    default:
      return status ? String(status) : "-";
  }
}

/** 担当者役割の表示ラベル。 */
export function formatContactRoleLabel(role: string | null | undefined): string {
  if (role === "primary") {
    return "主担当";
  }
  if (role === "secondary") {
    return "副担当";
  }
  return role ? String(role) : "-";
}

function formatCommuteStatusLabel(status: string): string {
  switch (status) {
    case "ok":
      return "算出済";
    case "no_api_key":
      return "APIキー未設定";
    case "missing_place":
      return "場所情報不足";
    case "no_route":
      return "経路なし";
    case "bad_duration":
      return "所要時間不正";
    case "full_remote":
      return "フルリモート";
    default:
      return status;
  }
}

/** ルールスコア内訳をホバー表示用の行テキストに整形する。 */
export function formatScoreBreakdownLines(
  breakdown: Record<string, unknown> | null | undefined,
): string[] {
  if (!breakdown) {
    return [];
  }
  const lines: string[] = [];
  const asNum = (key: string): number | null => {
    const value = breakdown[key];
    return typeof value === "number" ? value : null;
  };

  const hardRejectLabel =
    typeof breakdown.hard_reject_label === "string" ? breakdown.hard_reject_label : null;
  if (hardRejectLabel) {
    lines.push(`除外: ${hardRejectLabel}`);
  }

  const skill = asNum("skill");
  if (skill != null) {
    const requiredPoints = asNum("skill_required");
    const preferredPoints = asNum("skill_preferred");
    const hits = Array.isArray(breakdown.skill_hits)
      ? breakdown.skill_hits.map(String).filter(Boolean)
      : [];
    const preferredHits = Array.isArray(breakdown.preferred_hits)
      ? breakdown.preferred_hits.map(String).filter(Boolean)
      : [];
    lines.push(`スキル: ${skill}/45`);
    if (requiredPoints != null) {
      lines.push(
        `必須: ${requiredPoints}/30${hits.length ? `（一致: ${hits.join(", ")}）` : ""}`,
      );
    } else if (hits.length) {
      lines.push(`一致: ${hits.join(", ")}`);
    }
    if (preferredPoints != null) {
      lines.push(
        `尚可: ${preferredPoints}/15${preferredHits.length ? `（一致: ${preferredHits.join(", ")}）` : ""}`,
      );
    }
  }
  const rate = asNum("rate");
  if (rate != null) {
    lines.push(`単価: ${rate}/30`);
  }
  const availability = asNum("availability");
  if (availability != null) {
    lines.push(`稼働開始: ${availability}/15`);
  }
  const workStyle = asNum("work_style");
  if (workStyle != null) {
    lines.push(`勤務形態: ${workStyle}/10`);
  }
  const commute = asNum("commute");
  if (commute != null) {
    let note = "";
    if (breakdown.commute_skip === "full_remote") {
      note = "（フルリモート）";
    } else if (typeof breakdown.commute_minutes === "number") {
      note = `（${breakdown.commute_minutes}分）`;
    } else if (typeof breakdown.commute_status === "string" && breakdown.commute_status) {
      note = `（${formatCommuteStatusLabel(breakdown.commute_status)}）`;
    }
    lines.push(`通勤: ${commute}/10${note}`);
  }
  return lines;
}

/** DB 値が円（例: 600000）でも万円（例: 60）でも「万円」表示に揃える。 */
function toManYen(value: number): number {
  if (value >= 10000) {
    return Math.round(value / 10000);
  }
  return value;
}

export function formatRate(value: number | null | undefined): string {
  if (value == null) {
    return "-";
  }
  return `${toManYen(value)}万円`;
}

/** 案件単価帯など、min/max をまとめて「60〜70万円」と表示する。 */
export function formatRateRange(
  min: number | null | undefined,
  max: number | null | undefined,
): string {
  if (min == null && max == null) {
    return "-";
  }
  const lo = min != null ? toManYen(min) : null;
  const hi = max != null ? toManYen(max) : null;
  if (lo != null && hi != null) {
    if (lo === hi) {
      return `${lo}万円`;
    }
    return `${lo}〜${hi}万円`;
  }
  if (lo != null) {
    return `${lo}万円〜`;
  }
  return `〜${hi}万円`;
}

export function formatSkills(skills: string[] | undefined): string {
  if (!skills || skills.length === 0) {
    return "-";
  }
  return skills.join(" / ");
}
