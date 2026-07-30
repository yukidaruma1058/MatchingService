/** 設定画面のフォールバック初期値（entity モックは廃止）。 */
export const settings = {
  autoMatch: true,
  scoreThreshold: 70,
  autoSend: false,
  ingestDataRetentionDays: 0,
  sortSourceLabel: "SES未振り分け",
  sortTalentLabel: "SES人材紹介",
  sortProjectLabel: "SES案件配信",
  sortUnknownLabel: "SES要確認",
  sortKeywordsTalent: "人材\n要員\nスキルシート\nご紹介",
  sortKeywordsProject: "案件\n募集\n開発\nお問い合わせ",
  gmailAccount: null as string | null,
  from: "",
};

export const scoreBands = [
  { label: "0-10", count: 0 },
  { label: "11-20", count: 0 },
  { label: "21-30", count: 0 },
  { label: "31-40", count: 0 },
  { label: "41-50", count: 0 },
  { label: "51-60", count: 0 },
] as const;
