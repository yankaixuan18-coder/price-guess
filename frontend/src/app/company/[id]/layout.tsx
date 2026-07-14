"use client";
import Link from "next/link";
import { usePathname, useParams } from "next/navigation";

const TABS = [
  { seg: "", label: "总览" },
  { seg: "financials", label: "财务趋势" },
  { seg: "valuation", label: "估值模型" },
  { seg: "reverse-dcf", label: "反向 DCF" },
];

export default function CompanyLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <div className="flex gap-1 mb-4 border-b border-[#e7e5e0]">
        {TABS.map((t) => {
          const href = `/company/${id}${t.seg ? `/${t.seg}` : ""}`;
          const active = t.seg === "" ? path === `/company/${id}` : path.endsWith(`/${t.seg}`);
          return (
            <Link
              key={t.seg}
              href={href}
              className={`px-4 py-2 text-sm -mb-px border-b-2 ${
                active
                  ? "border-series-1 text-series-1 font-medium"
                  : "border-transparent text-ink-secondary hover:text-ink-primary"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
      </div>
      {children}
    </div>
  );
}
