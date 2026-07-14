"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import EChart, { axisDefaults } from "@/components/EChart";
import { ErrorBox, Loading, StatTile } from "@/components/shared";
import { apiGet, fmtNum, fmtPct, PARAM_LABELS } from "@/lib/api";
import { INK, SERIES } from "@/lib/palette";

/** 反向估值页（方案 8.7 / 12.4）：现价隐含了怎样的增长预期？ */
export default function ReverseDcfPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiGet(`/companies/${id}/reverse-dcf`).then(setData).catch((e) => setErr(e.message));
  }, [id]);

  const chart = useMemo(() => {
    if (!data) return null;
    const ig = data.reverse_dcf.implied_revenue_growth_5y;
    const h = data.reverse_dcf.history;
    const rows = [
      { label: "现价隐含增速（5年）", v: ig.implied_growth, color: SERIES[0] },
      { label: "近3年实际增速", v: h.revenue_cagr_3y, color: SERIES[1] },
      { label: "近5年实际增速", v: h.revenue_cagr_5y, color: SERIES[1] },
      { label: "同行增速中位", v: h.peer_growth_median, color: SERIES[2] },
    ].filter((r) => r.v != null);
    return {
      grid: { left: 140, right: 60, top: 10, bottom: 30 },
      tooltip: { trigger: "axis" as const, formatter: (p: any) => `${p[0].name}: ${fmtPct(p[0].value / 100)}` },
      xAxis: { type: "value" as const, ...axisDefaults, name: "%", nameTextStyle: { color: INK.muted } },
      yAxis: { type: "category" as const, data: rows.map((r) => r.label), ...axisDefaults, splitLine: { show: false } },
      series: [{
        type: "bar" as const, barMaxWidth: 22,
        data: rows.map((r) => ({
          value: +(r.v * 100).toFixed(2),
          itemStyle: { color: r.color, borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: "right" as const, color: INK.primary, formatter: ({ value }: any) => `${value}%` },
        })),
      }],
    };
  }, [data]);

  if (err) return <ErrorBox message={err} />;
  if (!data) return <Loading text="反向 DCF 求解中…" />;

  const rd = data.reverse_dcf;
  const ig = rd.implied_revenue_growth_5y;
  const itg = rd.implied_terminal_growth;
  const snap = data.market_snapshot;

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="section-title">反向 DCF：从现价反推市场隐含假设（不预测目标价）</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <StatTile
            label="现价隐含 5 年收入复合增速"
            value={ig.implied_growth != null ? fmtPct(ig.implied_growth) : "未求解"}
            sub={ig.solved ? `模型价值收敛于现价 ${fmtNum(snap.price_report_ccy)} ${snap.report_currency}` : ig.reason}
            tone={ig.implied_growth != null && rd.history.revenue_cagr_3y != null
              ? (ig.implied_growth > rd.history.revenue_cagr_3y ? "bad" : "good") : "neutral"}
          />
          <StatTile
            label="现价隐含永续增长率"
            value={itg.implied_terminal_growth != null ? fmtPct(itg.implied_terminal_growth) : "未求解"}
            sub={itg.solved ? `上限为 WACC − 0.5%` : itg.reason}
          />
          <StatTile
            label="判读"
            value={rd.verdict ? "见下" : "—"}
            sub={rd.verdict ?? "数据不足"}
          />
        </div>
      </div>

      <div className="card">
        <div className="section-title">隐含增速 vs 实际增速</div>
        {chart && <EChart option={chart as any} height={220} />}
        <p className="text-xs text-ink-muted mt-2">
          隐含增速显著高于历史增速 ⇒ 现价已定价加速增长；显著低于 ⇒ 市场定价减速/衰退。
        </p>
      </div>

      <div className="card overflow-x-auto">
        <div className="section-title">求解时固定的假设（其余参数与基准情景一致）</div>
        <table className="w-full max-w-xl">
          <tbody>
            {Object.entries(rd.held_constant).map(([k, v]) => (
              <tr key={k} className="border-t border-[#f0efec]">
                <td className="td text-ink-secondary">{PARAM_LABELS[k] ?? k}</td>
                <td className="td text-right">{fmtPct(v as number, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
