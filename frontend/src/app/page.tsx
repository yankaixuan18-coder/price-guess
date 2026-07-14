"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, fmtNum, fmtPct, fmtX } from "@/lib/api";
import { ConfidenceBadge, ErrorBox, Loading, UpsideBadge } from "@/components/shared";

const MARKETS = [
  { v: "", label: "全部市场" },
  { v: "CN", label: "A股" },
  { v: "US", label: "美股" },
  { v: "HK", label: "港股" },
];

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [market, setMarket] = useState("");
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState("");

  const load = async (query: string, mkt: string) => {
    try {
      // 用筛选器接口拿到含估值摘要的完整行
      const data = await apiGet(`/screeners${mkt ? `?market=${mkt}` : ""}`);
      let items = data.items as any[];
      if (query) {
        const s = await apiGet(`/companies/search?q=${encodeURIComponent(query)}`);
        const ids = new Set(s.items.map((i: any) => i.company_id));
        items = items.filter((r) => ids.has(r.company_id));
      }
      setRows(items);
    } catch (e: any) {
      setErr(e.message);
    }
  };

  useEffect(() => {
    load("", "");
  }, []);

  if (err) return <ErrorBox message={err} />;

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="搜索名称 / 代码，如 茅台、AAPL、0700"
          className="w-72"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(q, market)}
        />
        <select
          className="border border-[#d8d6d0] rounded-md px-2 py-1 text-sm bg-white"
          value={market}
          onChange={(e) => {
            setMarket(e.target.value);
            load(q, e.target.value);
          }}
        >
          {MARKETS.map((m) => (
            <option key={m.v} value={m.v}>{m.label}</option>
          ))}
        </select>
        <button className="btn-primary" onClick={() => load(q, market)}>搜索</button>
        <span className="text-xs text-ink-muted ml-auto">
          估值吸引力与质量/风险独立展示；低估 ≠ 买入信号
        </span>
      </div>

      {!rows ? (
        <Loading />
      ) : (
        <div className="card overflow-x-auto !p-0">
          <table className="w-full">
            <thead className="border-b border-[#e7e5e0]">
              <tr>
                <th className="th">公司</th>
                <th className="th">市场</th>
                <th className="th">行业</th>
                <th className="th text-right">PE</th>
                <th className="th text-right">PB</th>
                <th className="th text-right">EV/EBITDA</th>
                <th className="th text-right">ROE</th>
                <th className="th text-right">营收3年CAGR</th>
                <th className="th text-right">股息率</th>
                <th className="th text-right">上行空间</th>
                <th className="th text-right">可信度</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.company_id} className="border-b border-[#f0efec] hover:bg-surface-2">
                  <td className="td">
                    <Link href={`/company/${r.company_id}`} className="text-series-1 font-medium hover:underline">
                      {r.name_zh}
                    </Link>
                    <span className="text-xs text-ink-muted ml-2">{r.ticker}</span>
                  </td>
                  <td className="td">{{ CN: "A股", US: "美股", HK: "港股" }[r.market as string] ?? r.market}</td>
                  <td className="td">{r.industry_name}</td>
                  <td className="td text-right">{fmtX(r.pe)}</td>
                  <td className="td text-right">{fmtX(r.pb)}</td>
                  <td className="td text-right">{fmtX(r.ev_ebitda)}</td>
                  <td className="td text-right">{fmtPct(r.roe)}</td>
                  <td className="td text-right">{fmtPct(r.revenue_cagr_3y)}</td>
                  <td className="td text-right">{fmtPct(r.dividend_yield)}</td>
                  <td className="td text-right"><UpsideBadge upside={r.upside} /></td>
                  <td className="td text-right"><ConfidenceBadge score={r.confidence} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="p-8 text-center text-sm text-ink-muted">无匹配公司</div>}
        </div>
      )}
      <p className="text-xs text-ink-muted">
        提示：上行空间来自最近一次估值运行的加权合理价值（行业权重融合，非算术平均）；表中数值为 {fmtNum(rows?.length ?? 0, 0)} 家样例公司。
      </p>
    </div>
  );
}
