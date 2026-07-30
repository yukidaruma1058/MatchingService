"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

export function Topbar({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="topbar">
      <div>
        <h1>{title}</h1>
        <p className="muted">{description}</p>
      </div>
      {actions ? <div className="topbar-actions">{actions}</div> : null}
    </header>
  );
}

export function ButtonLink({
  href,
  children,
  variant = "secondary",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
}) {
  return (
    <Link className={`btn btn-${variant}`} href={href}>
      {children}
    </Link>
  );
}

export function Panel({
  title,
  meta,
  children,
  className = "",
}: {
  title?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel${className ? ` ${className}` : ""}`}>
      {title || meta ? (
        <div className="panel-head">
          {title ? <h2>{title}</h2> : <span />}
          {meta}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** タイトルクリックで開閉できるパネル（詳細画面の補足情報向け）。 */
export function CollapsiblePanel({
  title,
  meta,
  children,
  defaultOpen = true,
  className = "",
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      className={`panel collapsible-panel${className ? ` ${className}` : ""}`}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="collapsible-panel-summary">
        <span className="collapsible-panel-title">{title}</span>
        <span className="collapsible-panel-meta">
          {meta}
          <span className="collapsible-panel-chevron" aria-hidden="true">
            {open ? "▼" : "▶"}
          </span>
        </span>
      </summary>
      <div className="collapsible-panel-body">{children}</div>
    </details>
  );
}

export function Badge({
  children,
  tone = "brand",
}: {
  children: ReactNode;
  tone?: "brand" | "ok" | "warn" | "muted" | "danger";
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Field({
  label,
  children,
  grow,
}: {
  label: string;
  children: ReactNode;
  grow?: boolean;
}) {
  return (
    <div className={`field${grow ? " grow" : ""}`}>
      <label>{label}</label>
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  meta,
}: {
  label: string;
  value: string | number;
  meta: ReactNode;
}) {
  return (
    <article className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      <span className="stat-meta">{meta}</span>
    </article>
  );
}

export function MiniBars({ values }: { values: number[] }) {
  return (
    <div className="mini-bars">
      {values.map((value, index) => (
        <span key={`${value}-${index}`} style={{ height: `${value}%` }} />
      ))}
    </div>
  );
}

export function ScoreChart({ bands }: { bands: readonly (readonly [string, number, number])[] }) {
  return (
    <div className="score-chart" aria-label="ルールスコア帯ごとの人数棒グラフ">
      {bands.map(([label, count, width]) => (
        <div className="score-bar-row" key={label}>
          <span className="score-bar-label">{label}</span>
          <div className="score-bar-track">
            <span className="score-bar-fill" style={{ width: `${width}%` }} />
          </div>
          <span className="score-bar-count">{count}</span>
        </div>
      ))}
    </div>
  );
}

export function HelpTooltip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null);
  const anchorRef = useRef<HTMLSpanElement | null>(null);

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
    const estimatedHeight = 280;
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
      zIndex: 1100,
    });
  };

  const hidePanel = () => setPanelStyle(null);

  return (
    <span
      ref={anchorRef}
      className="help-tooltip"
      onMouseEnter={showPanel}
      onMouseLeave={hidePanel}
      onFocus={showPanel}
      onBlur={hidePanel}
    >
      <button type="button" className="help-tooltip-trigger" aria-label={label}>
        ?
      </button>
      {panelStyle ? (
        <span className="help-tooltip-panel is-open" role="tooltip" style={panelStyle}>
          {children}
        </span>
      ) : null}
    </span>
  );
}

export function CopyableReadonlyField({
  label,
  value,
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  hint?: string;
  placeholder?: string;
}) {
  const [copied, setCopied] = useState(false);
  const canCopy = value.trim().length > 0;

  const handleCopy = async () => {
    if (!canCopy) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="field">
      <label>{label}</label>
      <div className="copyable-readonly">
        <input value={value} placeholder={placeholder} readOnly tabIndex={-1} aria-readonly="true" />
        <button type="button" className="btn btn-secondary" onClick={handleCopy} disabled={!canCopy}>
          {copied ? "コピー済" : "コピー"}
        </button>
      </div>
      {hint ? <span className="field-help">{hint}</span> : null}
    </div>
  );
}

