"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "公司搜索" },
  { href: "/compare", label: "公司对比" },
  { href: "/watchlist", label: "自选股" },
  { href: "/alerts", label: "估值提醒" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <header className="bg-surface-1 border-b border-[#e7e5e0]">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-8">
        <Link href="/" className="font-bold text-ink-primary">
          估值系统 <span className="text-xs font-normal text-ink-muted">A股 · 美股 · 港股</span>
        </Link>
        <nav className="flex gap-1 text-sm">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`px-3 py-1.5 rounded-md ${
                  active ? "bg-surface-3 text-ink-primary font-medium" : "text-ink-secondary hover:text-ink-primary"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <span className="ml-auto text-xs text-ink-muted">样例数据 · 仅供演示，不构成投资建议</span>
      </div>
    </header>
  );
}
