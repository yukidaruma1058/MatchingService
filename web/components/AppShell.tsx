"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { navRoutes } from "@/lib/routes";

type AppShellProps = {
  activePath: string;
  children: ReactNode;
};

export function AppShell({ activePath, children }: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [activePath]);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  return (
    <div className={`shell${menuOpen ? " is-menu-open" : ""}`}>
      <header className="app-header">
        <button
          type="button"
          className="menu-toggle"
          aria-label={menuOpen ? "メニューを閉じる" : "メニューを開く"}
          aria-expanded={menuOpen}
          aria-controls="app-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="menu-toggle-bars" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
        </button>
        <div className="brand brand--compact">
          <span className="brand-mark">MS</span>
          <div>
            <strong>MatchingService</strong>
            <small>フロントエンド</small>
          </div>
        </div>
      </header>

      <button
        type="button"
        className="sidebar-backdrop"
        aria-label="メニューを閉じる"
        tabIndex={menuOpen ? 0 : -1}
        onClick={() => setMenuOpen(false)}
      />

      <aside className={`sidebar${menuOpen ? " is-open" : ""}`} id="app-nav">
        <nav className="nav">
          {navRoutes.map((route) => {
            const isActive =
              route.href === "/" ? activePath === "/" : activePath.startsWith(route.href);
            return (
              <Link
                key={route.href}
                className={`nav-item${isActive ? " is-active" : ""}`}
                href={route.href}
                onClick={() => setMenuOpen(false)}
              >
                {route.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <main className="main">{children}</main>
    </div>
  );
}
