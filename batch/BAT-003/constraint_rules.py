"""外国籍・商流の制約判定（抽出・採点で共用）。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "").strip().lower()


def parse_project_foreign_nationality_ng(raw: Any) -> bool | None:
    """案件側: 外国籍不可なら True、可・不問なら False、未記載は None。"""
    if isinstance(raw, bool):
        return raw
    text = _norm(str(raw) if raw is not None else "")
    if not text:
        return None
    if any(k in text for k in ("外国籍可", "国籍不問", "外国籍ok", "外国籍ｏｋ", "外国籍不問")):
        return False
    if any(
        k in text
        for k in (
            "外国籍不可",
            "外国籍ng",
            "外国籍ｎｇ",
            "外国人不可",
            "日本人のみ",
            "日本国籍のみ",
            "国籍:日本",
            "国籍：日本",
        )
    ):
        return True
    # 【外国籍】：不可 / 可 のような短い値
    if text in ("不可", "ng", "ｎｇ", "×", "x"):
        return True
    if text in ("可", "ok", "ｏｋ", "不問", "○", "o"):
        return False
    return None


def parse_talent_is_foreign_national(raw: Any) -> bool | None:
    """人材側: 外国籍なら True、日本国籍なら False、不明は None。"""
    if isinstance(raw, bool):
        return raw
    text = _norm(str(raw) if raw is not None else "")
    if not text:
        return None
    if any(k in text for k in ("日本国籍", "日本人", "国内籍")):
        return False
    if any(k in text for k in ("外国籍", "外国人", "永住権", "就労ビザ", "ビザ")):
        return True
    return None


def parse_commerce_flow_max_depth(raw: Any) -> int | None:
    """案件の商流上限。

    人材側深度（自社視点）との比較用:
      0=エンド直 / 貴社まで（自社プロパーのみ）
      1=一社先まで
      2=二社先まで
    制限なし/不明は None。
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    text = _norm(str(raw))
    if not text:
        return None
    if any(k in text for k in ("制限なし", "不問", "商流なし", "制約なし")):
        return None
    if any(k in text for k in ("三社先", "3社先", "三次")):
        return 3
    if any(k in text for k in ("二社先", "2社先", "二次")):
        return 2
    # 「貴社まで」は自社プロパーのみ。一社先より先に判定する
    if any(k in text for k in ("貴社まで", "貴社のみ", "弊社まで", "自社まで", "貴社プロパー")):
        return 0
    if any(k in text for k in ("一社先", "1社先", "一次請", "一次受け", "一次まで")):
        return 1
    if any(k in text for k in ("エンド直", "エンドのみ", "元請のみ", "元請けのみ", "直請", "直契約")):
        return 0
    # 「商流: エンド」など短文
    if "エンド" in text and "先" not in text:
        return 0
    return None


def parse_talent_commerce_depth(*, commerce_flow: Any = None, affiliation: Any = None) -> int | None:
    """人材の商流深度。0=プロパー/自社, 1=一社先, 2=二社先。不明は None。"""
    text = _norm(f"{commerce_flow or ''} {affiliation or ''}")
    if not text:
        return None
    if any(k in text for k in ("三社先", "3社先")):
        return 3
    if any(k in text for k in ("二社先", "2社先", "二次請", "二次受け")):
        return 2
    if any(k in text for k in ("一社先", "1社先", "一次請", "一次受け", "一社専属")):
        return 1
    if any(k in text for k in ("プロパー", "自社", "正社員", "社員", "専属(自社", "弊社所属")):
        return 0
    if "フリーランス" in text or "個人事業" in text:
        # フリーランスは一社先扱いに近いが、案件による。不明扱いにせず 1 とする
        return 1
    return None


def format_commerce_flow_limit_label(limit_text: str | None, max_depth: int | None) -> str:
    if limit_text and str(limit_text).strip():
        return str(limit_text).strip()
    if max_depth is None:
        return "制限なし / 不明"
    labels = {0: "エンド直 / 貴社まで", 1: "一社先まで", 2: "二社先まで", 3: "三社先まで"}
    return labels.get(max_depth, f"深度{max_depth}まで")


def hard_constraint_reject_reason(
    *,
    project_foreign_nationality_ng: bool,
    talent_is_foreign_national: bool | None,
    project_commerce_flow_limit: str | None,
    talent_commerce_flow: str | None,
    talent_affiliation: str | None,
) -> str | None:
    """不一致なら拒否理由コードを返す。OK なら None。"""
    if project_foreign_nationality_ng and talent_is_foreign_national is True:
        return "foreign_nationality"
    max_depth = parse_commerce_flow_max_depth(project_commerce_flow_limit)
    talent_depth = parse_talent_commerce_depth(
        commerce_flow=talent_commerce_flow,
        affiliation=talent_affiliation,
    )
    if max_depth is not None and talent_depth is not None and talent_depth > max_depth:
        return "commerce_flow"
    return None


def hard_reject_label(code: str | None) -> str | None:
    if code == "foreign_nationality":
        return "外国籍不可のため除外"
    if code == "commerce_flow":
        return "商流制限のため除外"
    return None


def extract_project_constraint_fields(fields: dict[str, str], body: str) -> tuple[bool | None, str | None]:
    """【項目】と本文から案件の外国籍不可・商流制限を取る。"""
    from_keys = ""
    for key, value in fields.items():
        nk = _norm(key)
        if any(k in nk for k in ("外国籍", "国籍", "外国人")):
            # 「【外国籍】不可」のようにキーと値が分かれていても判定できるようにする
            from_keys += f" {key}{value} {value}"
    foreign_ng = parse_project_foreign_nationality_ng(from_keys)
    if foreign_ng is None:
        foreign_ng = parse_project_foreign_nationality_ng(body)

    commerce: str | None = None
    for key, value in fields.items():
        nk = _norm(key)
        if any(k in nk for k in ("商流", "仲介", "参入")):
            commerce = (value or "").strip()[:64] or None
            break
    if commerce is None:
        match = re.search(r"(?:商流|参入)\s*[:：]?\s*([^\n】]{1,40})", body)
        if match:
            commerce = match.group(1).strip()[:64] or None
    return foreign_ng, commerce


def extract_talent_constraint_fields(
    fields: dict[str, str],
    body: str,
    *,
    affiliation: str | None,
) -> tuple[bool | None, str | None]:
    """人材の外国籍フラグ・商流テキストを取る。"""
    nationality_blob = ""
    for key, value in fields.items():
        nk = _norm(key)
        if any(k in nk for k in ("外国籍", "国籍", "外国人")):
            nationality_blob += f" {value}"
    is_foreign = parse_talent_is_foreign_national(nationality_blob)
    if is_foreign is None:
        is_foreign = parse_talent_is_foreign_national(body[:2000])

    commerce: str | None = None
    for key, value in fields.items():
        nk = _norm(key)
        if any(k in nk for k in ("商流", "所属形態", "立場")):
            commerce = (value or "").strip()[:64] or None
            break
    if commerce is None and affiliation:
        commerce = affiliation[:64]
    return is_foreign, commerce
