import { mkdir, unlink, writeFile } from "fs/promises";
import path from "path";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

function resolveApiBase(): string {
  return (
    process.env.API_INTERNAL_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000"
  );
}

function resolvePendingBodiesPath(): string {
  // web/ → repo root → batch/tmp/...
  return path.resolve(process.cwd(), "..", "batch", "tmp", "pending_talent_propose_bodies.json");
}

async function removePendingBodiesFile(): Promise<void> {
  try {
    await unlink(resolvePendingBodiesPath());
  } catch {
    /* missing is fine */
  }
}

type Draft = {
  match_id: string;
  body_text: string;
  to_address?: string | null;
  cc_addresses?: string[] | null;
};

/**
 * ブラウザ → Next → API のプロキシ。
 * 旧 API は drafts 付きだと一時ファイル書き込みで 500（CORS なし）になるため、
 * 本文・宛先・CC は batch/tmp の pending ファイル経由で渡し、API には match_ids のみ送る。
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
  const pendingPath = resolvePendingBodiesPath();
  if (drafts.length > 0 || payload.to_address || payload.cc_addresses) {
    const draftMap: Record<string, unknown> = {};
    const first = drafts.find((d) => (d.body_text ?? "").trim()) ?? drafts[0];
    const text = (first?.body_text ?? "").trim();
    if (drafts.length > 0 && !text) {
      return NextResponse.json(
        { detail: { error_code: "ERR-0001", error_message: "本文が空です。" } },
        { status: 400 },
      );
    }
    if (first?.body_text) {
      draftMap.body = first.body_text;
    }
    const toAddress =
      (typeof first?.to_address === "string" && first.to_address.trim()) ||
      (typeof payload.to_address === "string" && payload.to_address.trim()) ||
      "";
    if (toAddress) {
      draftMap.to_address = toAddress;
    }
    const ccSource =
      first?.cc_addresses !== undefined
        ? first.cc_addresses
        : payload.cc_addresses !== undefined
          ? payload.cc_addresses
          : undefined;
    if (Array.isArray(ccSource)) {
      draftMap.cc_addresses = ccSource
        .map((addr) => String(addr).trim())
        .filter((addr) => addr.length > 0);
    }
    await mkdir(path.dirname(pendingPath), { recursive: true });
    await writeFile(pendingPath, JSON.stringify(draftMap), "utf-8");
  } else {
    await removePendingBodiesFile();
  }

  const apiBases = Array.from(
    new Set(
      [
        resolveApiBase(),
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
        body: JSON.stringify({ match_ids: matchIds }),
        cache: "no-store",
      });
      const text = await response.text();
      let data: unknown = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { detail: text || "送信に失敗しました" };
      }
      // コンテナ側が :ro だと pending を消せないので、ホスト側（Next）で必ず消す
      await removePendingBodiesFile();
      if (!response.ok) {
        return NextResponse.json(data ?? { detail: "案件提案の送信に失敗しました" }, {
          status: response.status,
        });
      }
      if (data && typeof data === "object" && !Array.isArray(data)) {
        return NextResponse.json({
          ...(data as Record<string, unknown>),
          message: "案件提案を送信しました",
        });
      }
      return NextResponse.json(data);
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }

  await removePendingBodiesFile();
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
