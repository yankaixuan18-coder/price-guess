"use client";
import { useEffect, useMemo, useState } from "react";
import EChart, { axisDefaults } from "@/components/EChart";
import { ErrorBox, Loading, UpsideBadge } from "@/components/shared";
import { apiGet, fmtPct, fmtX } from "@/lib/api";
import { INK, SERIES } from "@/lib/palette";

/** 公司对比页（方案 12.5）：质量/增长/估值/回报/杠杆/现金流/股东回报。 */
export default function ComparePage() {
  const [all, setAll] = useState<any[]>([]);
  const [selected, setSelected] = useState<string[]>(["moutai", "ko", "tencent"]);
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiGet("/companies/search").then((d) => setAll(d.items)).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    if (selected.length === 0) { setRows([]); return; }
    apiGet(`/compare?ids=${selected.join(",")}`).then((d) => setRows(d.items)).catch((e) => setErr(e.message));
  }, [selected]);

  const toggle = (cid: string) =>
    setSelected((s) => (s.includes(cid) ? s.filter((x) => x !== cid) : s.length < 10 ? [...s, cid] : s));

  // 小倍数图：每个指标一张横向条形图（单轴原则，不混用双轴）
  const smallMultiples = useMemo(() => {
    if (!rows || rows.length === 0) return [];
    const metrics: [string, string, boolean][] = [
      ["ROE", "roe", true], ["ROIC", "roic", true],
      ["营收3年CAGR", "revenue_cagr_3y", true], ["净利3年CAGR", "net_income_cagr_3y", true],
      ["毛利率", "gross_margin", true], ["OCF/净利润", "ocf_to_net_income", true],
      ["PE", "pe", false], ["EV/EBITDA", "ev_ebitda", false],
      ["股息率", "dividend_yield", true], ["FCF收益率", "fcf_yield", true],
    ];
    return metrics.map(([title, key, isPct]) => {
      const data = rows.map((r, i) => ({
        name: r.name_zh,
        value: r[key] != null ? +(isPct ? r[key] * 100 : r[key]).toFixed(2) : null,
        itemStyle: { color: SERIES[i % SERIES.length], borderRadius: [0, 4, 4, 0] },
      }));
      return {
        title,
        option: {
          grid: { left: 80, right: 48, top: 8, bottom: 24 },
          tooltip: { trigger: "axis" as const },
          xAxis: { type: "value" as const, ...axisDefaults, axisLabel: { color: INK.muted, formatter: (v: number) => (isPct ? `${v}%` : v) } },
          yAxis: { type: "category" as const, data: rows.map((r) => r.name_zh), ...axisDefaults, splitLine: { show: false } },
          series: [{
            type: "bar" as const, barMaxWidth: 18, data,
            label: { show: true, position: "right" as const, color: INK.primary, fontSize: 10,
                     formatter: ({ value }: any) => (value == null ? "—" : isPct ? `${value}%` : value) },
          }],
        },
      };
    });
  }, [rows]);

  if (err) return <ErrorBox message={err} />;

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="section-title">选择对比公司（最多 10 家）</div>
        <div className="flex flex-wrap gap-2">
          {all.map((c) => (
            <button
              key={c.company_id}
              onClick={() => toggle(c.company_id)}
              className={`btn text-xs ${selected.includes(c.company_id)
                ? "bg-series-1 text-white border-series-1"
                : "bg-white text-ink-secondary border-[#d8d6d0]"}`}
            >
              {c.name_zh}
            </button>
          ))}
        </div>
      </div>

      {!rows ? <Loading /> : rows.length === 0 ? (
        <div className="card text-sm text-ink-muted">请选择至少一家公司</div>
      ) : (
        <>
          <div className="card overflow-x-auto !p-0">
            <table className="w-full">
              <thead className="border-b border-[#e7e5e0]">
                <tr>
                  <th className="th">指标</th>
                  {rows.map((r) => <th key={r.company_id} className="th text-right">{r.name_zh}</th>)}
                </tr>
              </thead>
              <tbody>
                {([
                  ["市场", (r: any) => ({ CN: "A股", US: "美股", HK: "港股" }[r.market as string] ?? r.market)],
                  ["PE", (r: any) => fmtX(r.pe)],
                  ["PB", (r: any) => fmtX(r.pb)],
                  ["EV/EBITDA", (r: any) => fmtX(r.ev_ebitda)],
                  ["ROE", (r: any) => fmtPct(r.roe)],
                  ["ROIC", (r: any) => fmtPct(r.roic)],
                  ["毛利率", (r: any) => fmtPct(r.gross_margin)],
                  ["净利率", (r: any) => fmtPct(r.net_margin)],
                  ["营收3年CAGR", (r: any) => fmtPct(r.revenue_cagr_3y)],
                  ["OCF/净利润", (r: any) => fmtPct(r.ocf_to_net_income)],
                  ["净债务/EBITDA", (r: any) => (r.net_debt_to_ebitda != null ? r.net_debt_to_ebitda.toFixed(1) : "净现金")],
                  ["股息率", (r: any) => fmtPct(r.dividend_yield)],
                  ["分红支付率", (r: any) => fmtPct(r.payout_ratio)],
                  ["股本稀释(年化)", (r: any) => fmtPct(r.share_dilution_cagr)],
                  ["估值上行空间", (r: any) => <UpsideBadge key={r.company_id} upside={r.upside} />],
                  ["估值可信度", (r: any) => (r.confidence != null ? r.confidence.toFixed(0) : "—")],
                ] as [string, (r: any) => any][]).map(([label, fn]) => (
                  <tr key={label} className="border-b border-[#f0efec]">
                    <td className="td text-ink-secondary">{label}</td>
                    {rows.map((r) => <td key={r.company_id} className="td text-right">{fn(r)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            {smallMultiples.map((m) => (
              <div className="card" key={m.title}>
                <div className="section-title">{m.title}</div>
                <EChart option={m.option as any} height={Math.max(120, rows.length * 40 + 40)} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
