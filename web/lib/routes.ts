export type NavRoute = {
  href: string;
  label: string;
};

export const navRoutes: NavRoute[] = [
  { href: "/", label: "ダッシュボード" },
  { href: "/talents", label: "人材一覧" },
  { href: "/projects", label: "案件一覧" },
  { href: "/companies", label: "企業一覧" },
  { href: "/settings", label: "設定" },
];

export function isActiveRoute(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

