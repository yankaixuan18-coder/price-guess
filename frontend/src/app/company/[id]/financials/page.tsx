"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import EChart, { axisDefaults } from "@/components/EChart";
import { ErrorBox, Loading } from "@/components/shared";
import { apiGet, fmtPct, fmtYi } from "@/lib/api";
import { INK, SERIES } from "@/lib/palette";

/** 财务分析页（方案 12.2）：近年营收/利润/利润率/回报率/现金流/负债/股东回报。 */
export default function FinancialsPage() {
  const { id } = useParams<{ id: string }>();
  const [metrics, setMetrics] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiGet(`/companies/${id}/metrics`).then(setMetrics).catch((e) => setErr(e.message));
  }, [id]);

  const charts = useMemo(() => {
    if (!metrics) return null;
    const a = metrics.annual as any[];
    const years = a.map((m) => `FY${m.fiscal_year}`);
    const bar = (name: string, key: string, color: string) => ({
      name, type: "bar" as const, data: a.map((m) => m[key] != null ? +(m[key] / 100).toFixed(1) : null),
      itemStyle: { color, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 28,
    });
    const line = (name: string, key: string, color: string, pct = true) => ({
      name, type: "line" as const,
      data: a.map((m) => (m[key] != null ? +(m[key] * (pct ? 100 : 1)).toFixed(2) : null)),
      showSymbol: true, symbolSize: 8, lineStyle: { width: 2, color }, itemStyle: { color },
    });
    const catAxis = { type: "category" as const, data: years, ...axisDefaults, splitLine: { show: false } };
    const yiAxis = { type: "value" as const, ...axisDefaults, name: "亿（报告币种）", nameTextStyle: { color: INK.muted } };
    const pctAxis = { type: "value" as const, ...axisDefaults, name: "%", nameTextStyle: { color: INK.muted }, scale: true };
    const legend = { top: 0, textStyle: { color: INK.secondary, fontSize: 12 }, itemWidth: 14, itemHeight: 8 };
    return {
      revenue: {
        legend, xAxis: catAxis, yAxis: yiAxis,
        series: [bar("营业收入", "revenue", SERIES[0]), bar("毛利", "gross_profit", SERIES[1])],
      },
      profit: {
        legend, xAxis: catAxis, yAxis: yiAxis,
        series: [
          bar("报告净利润(归母)", "net_income_parent", SERIES[0]),
          bar("标准化净利润(扣非)", "net_income_normalized", SERIES[2]),
        ],
      },
      margins: {
        legend, xAxis: catAxis, yAxis: pctAxis,
        series: [
          line("毛利率", "gross_margin", SERIES[0]),
          line("EBIT利润率", "ebit_margin", SERIES[1]),
          line("净利率", "net_margin", SERIES[2]),
        ],
      },
      returns: {
        legend, xAxis: catAxis, yAxis: pctAxis,
        series: [line("ROE", "roe", SERIES[0]), line("ROIC", "roic", SERIES[1])],
      },
      cash: {
        legend, xAxis: catAxis, yAxis: yiAxis,
        series: [
          bar("经营现金流", "ocf", SERIES[0]),
          bar("自由现金流", "fcf", SERIES[1]),
          bar("净利润", "net_income_parent", SERIES[2]),
        ],
      },
      debt: {
        legend, xAxis: catAxis, yAxis: yiAxis,
        series: [bar("净债务", "net_debt", SERIES[4])],
      },
      payout: {
        legend, xAxis: catAxis, yAxis: yiAxis,
        series: [
          { ...bar("分红", "dps", SERIES[0]), data: a.map((m) => m.dps != null && m.dilution_shares ? +((m.dps * m.dilution_shares) / 100).toFixed(1) : null), stack: "sh" },
          { ...bar("回购", "buyback", SERIES[1]), stack: "sh", itemStyle: { color: SERIES[1], borderRadius: [4, 4, 0, 0], borderColor: "#fcfcfb", borderWidth: 2 } },
        ],
      },
      shares: {
        legend, xAxis: catAxis,
        yAxis: { type: "value" as const, ...axisDefaults, scale: true, name: "百万股", nameTextStyle: { color: INK.muted } },
        series: [line("稀释股本", "dilution_shares", SERIES[5], false)],
      },
    };
  }, [metrics]);

  if (err) return <ErrorBox message={err} />;
  if (!metrics || !charts) return <Loading />;
  const s = metrics.summary;

  const blocks: [string, any, string?][] = [
    ["营收与毛利", charts.revenue],
    ["利润：报告 vs 标准化口径（扣非）", charts.profit, "两条口径差异大说明非经常损益占比高"],
    ["利润率", charts.margins],
    ["资本回报率", charts.returns],
    ["现金流 vs 净利润（含金量）", charts.cash],
    ["净债务", charts.debt],
    ["股东回报：分红 + 回购", charts.payout],
    ["稀释股本变化", charts.shares, "股本持续上升会稀释每股价值"],
  ];

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div>营收 3 年 CAGR <b>{fmtPct(s.revenue_cagr_3y)}</b></div>
        <div>营收 5 年 CAGR <b>{fmtPct(s.revenue_cagr_5y)}</b></div>
        <div>净利 3 年 CAGR <b>{fmtPct(s.net_income_cagr_3y)}</b></div>
        <div>OCF/净利润均值 <b>{fmtPct(s.ocf_to_net_income_stat?.mean)}</b></div>
        <div>净利率均值 <b>{fmtPct(s.net_margin_stat?.mean)}</b>（σ {fmtPct(s.net_margin_stat?.std)}）</div>
        <div>亏损年数 <b>{s.loss_years}/{s.total_years}</b></div>
        <div>FCF 为负年数 <b>{s.negative_fcf_years}/{s.total_years}</b></div>
        <div>股本稀释率(年化) <b>{fmtPct(s.share_dilution_cagr)}</b></div>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {blocks.map(([title, opt, note]) => (
          <div className="card" key={title}>
            <div className="section-title">{title}</div>
            <EChart option={opt} height={240} />
            {note && <div className="text-xs text-ink-muted mt-1">{note}</div>}
          </div>
        ))}
      </div>
      <div className="card overflow-x-auto">
        <div className="section-title">逐年明细（单位：亿，报告币种）</div>
        <table className="w-full">
          <thead><tr>
            <th className="th">财年</th><th className="th text-right">营收</th>
            <th className="th text-right">同比</th><th className="th text-right">EBIT</th>
            <th className="th text-right">归母净利</th><th className="th text-right">扣非净利</th>
            <th className="th text-right">OCF</th><th className="th text-right">FCF</th>
            <th className="th text-right">ROE</th><th className="th text-right">ROIC</th>
            <th className="th text-right">净债务/EBITDA</th>
          </tr></thead>
          <tbody>
            {metrics.annual.map((m: any) => (
              <tr key={m.fiscal_year} className="border-t border-[#f0efec]">
                <td className="td">FY{m.fiscal_year}</td>
                <td className="td text-right">{fmtYi(m.revenue)}</td>
                <td className="td text-right">{fmtPct(m.revenue_yoy)}</td>
                <td className="td text-right">{fmtYi(m.operating_profit)}</td>
                <td className="td text-right">{fmtYi(m.net_income_parent)}</td>
                <td className="td text-right">{fmtYi(m.net_income_normalized)}</td>
                <td className="td text-right">{fmtYi(m.ocf)}</td>
                <td className="td text-right">{fmtYi(m.fcf)}</td>
                <td className="td text-right">{fmtPct(m.roe)}</td>
                <td className="td text-right">{fmtPct(m.roic)}</td>
                <td className="td text-right">{m.net_debt_to_ebitda != null ? m.net_debt_to_ebitda.toFixed(1) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
