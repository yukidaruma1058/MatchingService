import Link from "next/link";
import type { ReactNode } from "react";
import { navRoutes } from "@/lib/routes";

type AppShellProps = {
  activePath: string;
  children: ReactNode;
};

export function AppShell({ activePath, children }: AppShellProps) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">MS</span>
          <div>
            <strong>MatchingService</strong>
            <small>フロントエンド</small>
          </div>
        </div>
        <nav className="nav">
          {navRoutes.map((route) => {
            const isActive =
              route.href === "/" ? activePath === "/" : activePath.startsWith(route.href);
            return (
              <Link
                key={route.href}
                className={`nav-item${isActive ? " is-active" : ""}`}
                href={route.href}
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

