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
  return path.resolve(process.cwd(), "..", "batch", "tmp", "pending_project_propose_bodies.json");
}

async function removePendingBodiesFile(): Promise<void> {
  try {
    await unlink(resolvePendingBodiesPath());
  } catch {
    /* missing is fine */
  }
}

/**
 * ブラウザ → Next → API のプロキシ。
 * 本文・宛先・CC は batch/tmp の pending ファイル経由で渡し、API には project_id / match_ids のみ送る。
 */
export async function POST(request: Request) {
  let payload: {
    project_id?: string;
    match_ids?: string[];
    body_text?: string;
    to_address?: string | null;
    cc_addresses?: string[] | null;
  };
  try {
    payload = (await request.json()) as {
      project_id?: string;
      match_ids?: string[];
      body_text?: string;
      to_address?: string | null;
      cc_addresses?: string[] | null;
    };
  } catch {
    return NextResponse.json(
      { detail: { error_code: "ERR-0001", error_message: "JSON が不正です。" } },
      { status: 400 },
    );
  }

  const projectId = typeof payload.project_id === "string" ? payload.project_id : "";
  const matchIds = Array.isArray(payload.match_ids) ? payload.match_ids : [];
  if (!projectId) {
    return NextResponse.json(
      { detail: { error_code: "ERR-0001", error_message: "project_id が空です。" } },
      { status: 400 },
    );
  }
  if (matchIds.length === 0) {
    return NextResponse.json(
      { detail: { error_code: "ERR-0001", error_message: "match_ids が空です。" } },
      { status: 400 },
    );
  }

  const bodyText = typeof payload.body_text === "string" ? payload.body_text : "";
  const pendingPath = resolvePendingBodiesPath();
  const draftMap: Record<string, unknown> = {};
  if (bodyText.trim()) {
    draftMap.body = bodyText;
  }
  if (typeof payload.to_address === "string" && payload.to_address.trim()) {
    draftMap.to_address = payload.to_address.trim();
  }
  if (Array.isArray(payload.cc_addresses)) {
    draftMap.cc_addresses = payload.cc_addresses
      .map((addr) => String(addr).trim())
      .filter((addr) => addr.length > 0);
  }
  if (Object.keys(draftMap).length > 0) {
    if (!bodyText.trim()) {
      return NextResponse.json(
        { detail: { error_code: "ERR-0001", error_message: "本文が空です。" } },
        { status: 400 },
      );
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
      const response = await fetch(`${base}/api/outreach/project-propose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, match_ids: matchIds }),
        cache: "no-store",
      });
      const text = await response.text();
      let data: unknown = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { detail: text || "送信に失敗しました" };
      }
      await removePendingBodiesFile();
      if (!response.ok) {
        return NextResponse.json(data ?? { detail: "人材提案の送信に失敗しました" }, {
          status: response.status,
        });
      }
      if (data && typeof data === "object" && !Array.isArray(data)) {
        return NextResponse.json({
          ...(data as Record<string, unknown>),
          message: "人材提案を送信しました",
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
