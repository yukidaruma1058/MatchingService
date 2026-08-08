import { NextResponse } from "next/server";

export const runtime = "nodejs";

function resolveApiBase(): string {
  return (
    process.env.API_INTERNAL_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000"
  );
}

type Draft = {
  match_id: string;
  match_ids?: string[];
  body_text: string;
  to_address?: string | null;
  cc_addresses?: string[] | null;
};

/**
 * ブラウザ → Next → API のプロキシ。
 * API は drafts / OUTREACH_BODIES_JSON を直接受け取るため、pending ファイルは使わない。
 * （Web コンテナから /batch/tmp へ書けず drafts 付きが 500 になる問題の修正）
 */
export async function POST(request: Request) {
  let payload: {
    match_ids?: string[];
    drafts?: Draft[];
    to_address?: string | null;
    cc_addresses?: string[] | null;
  };
  try {
    payload = (await request.json()) as {
      match_ids?: string[];
      drafts?: Draft[];
      to_address?: string | null;
      cc_addresses?: string[] | null;
    };
  } catch {
    return NextResponse.json(
      { detail: { error_code: "ERR-0001", error_message: "JSON が不正です。" } },
      { status: 400 },
    );
  }

  const matchIds = Array.isArray(payload.match_ids) ? payload.match_ids : [];
  if (matchIds.length === 0) {
    return NextResponse.json(
      { detail: { error_code: "ERR-0001", error_message: "match_ids が空です。" } },
      { status: 400 },
    );
  }

  const drafts = Array.isArray(payload.drafts) ? payload.drafts : [];
  if (drafts.length > 0) {
    const empty = drafts.find((d) => !(d.body_text ?? "").trim());
    if (empty) {
      return NextResponse.json(
        { detail: { error_code: "ERR-0001", error_message: "本文が空です。" } },
        { status: 400 },
      );
    }
  }

  const apiBody: Record<string, unknown> = { match_ids: matchIds };
  if (drafts.length > 0) {
    apiBody.drafts = drafts.map((d) => ({
      match_id: d.match_id,
      match_ids: d.match_ids?.length ? d.match_ids : [d.match_id],
      body_text: d.body_text,
      to_address: d.to_address ?? null,
      cc_addresses: d.cc_addresses ?? null,
    }));
  }
  if (typeof payload.to_address === "string" && payload.to_address.trim()) {
    apiBody.to_address = payload.to_address.trim();
  }
  if (Array.isArray(payload.cc_addresses)) {
    apiBody.cc_addresses = payload.cc_addresses
      .map((addr) => String(addr).trim())
      .filter((addr) => addr.length > 0);
  }

  const apiBases = Array.from(
    new Set(
      [
        resolveApiBase(),
        "http://api:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://172.18.0.1:8000",
      ].filter(Boolean),
    ),
  );

  let lastError = "API に接続できませんでした。";
  for (const base of apiBases) {
    try {
      const response = await fetch(`${base}/api/outreach/talent-propose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(apiBody),
        cache: "no-store",
      });
      const text = await response.text();
      let data: unknown = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { detail: text || "送信に失敗しました" };
      }
      if (!response.ok) {
        return NextResponse.json(
          data ?? { detail: "案件提案の送信に失敗しました" },
          { status: response.status },
        );
      }
      if (data && typeof data === "object" && !Array.isArray(data)) {
        return NextResponse.json({
          ...(data as Record<string, unknown>),
          message:
            typeof (data as { message?: unknown }).message === "string"
              ? (data as { message: string }).message
              : "案件提案を送信しました",
        });
      }
      return NextResponse.json(data);
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }

  return NextResponse.json(
    {
      detail: {
        error_code: "ERR-0030",
        error_message: `API（${apiBases.join(", ")}）に接続できませんでした: ${lastError}`,
      },
    },
    { status: 502 },
  );
}
