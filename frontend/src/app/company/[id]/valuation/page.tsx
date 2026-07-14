"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import EChart, { axisDefaults } from "@/components/EChart";
import { ErrorBox, Loading, ValueRangeBar } from "@/components/shared";
import { apiPost, fmtNum, fmtPct, fmtYi, MODEL_NAMES, PARAM_LABELS, SCENARIO_NAMES } from "@/lib/api";
import { DIVERGING, INK } from "@/lib/palette";

const EDITABLE = ["revenue_growth_5y", "terminal_ebit_margin", "wacc", "terminal_growth",
                  "tax_rate", "capex_pct_revenue"] as const;
const SCN = ["pessimistic", "base", "optimistic"] as const;

/** 估值模型页（方案 12.3）：参数、预测表、计算过程、终值占比、敏感性、修改入口。 */
export default function ValuationPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [savedMsg, setSavedMsg] = useState("");

  const run = useCallback(async (save: boolean, ov: Record<string, string>) => {
    setBusy(true); setSavedMsg("");
    try {
      const baseOverride: Record<string, number> = {};
      for (const [k, v] of Object.entries(ov)) {
        if (v !== "") baseOverride[k] = parseFloat(v);
      }
      const body: any = { company_id: id, save };
      if (Object.keys(baseOverride).length) body.assumptions = { base: baseOverride };
      const r = await apiPost("/valuations/run", body);
      setReport(r);
      if (save) setSavedMsg(`已保存估值运行 ${r.run_id.slice(0, 8)}…（可完整复现）`);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }, [id]);

  useEffect(() => { run(false, {}); }, [run]);

  const heatmap = useMemo(() => {
    if (!report?.sensitivity) return null;
    const s = report.sensitivity;
    const price = report.market_snapshot.price_report_ccy;
    const cells: [number, number, number | null][] = [];
    s.values.forEach((row: (number | null)[], yi: number) =>
      row.forEach((v, xi) => cells.push([xi, yi, v])));
    const vals = cells.map((c) => c[2]).filter((v): v is number => v != null);
    const vmax = Math.max(...vals.map((v) => Math.abs(v / price - 1)));
    return {
      tooltip: {
        position: "top" as const,
        formatter: (p: any) =>
          p.value[2] == null
            ? "WACC ≤ g，禁止计算"
            : `每股价值 ${fmtNum(p.value[2])}（较现价 ${fmtPct(p.value[2] / price - 1)}）`,
      },
      grid: { left: 70, right: 90, top: 30, bottom: 40 },
      xAxis: { type: "category" as const, name: "永续增长率", nameTextStyle: { color: INK.muted },
               data: s.x_values.map((v: number) => fmtPct(v, 2)), ...axisDefaults, splitLine: { show: false } },
      yAxis: { type: "category" as const, name: "WACC", nameTextStyle: { color: INK.muted },
               data: s.y_values.map((v: number) => fmtPct(v, 2)), ...axisDefaults, splitLine: { show: false } },
      visualMap: {
        min: -vmax, max: vmax, calculable: false, orient: "vertical" as const,
        right: 0, top: "center", itemHeight: 120,
        text: ["高于现价", "低于现价"], textStyle: { color: INK.muted, fontSize: 10 },
        inRange: { color: [DIVERGING.low, DIVERGING.mid, DIVERGING.high] },
        formatter: (v: number) => fmtPct(v, 0),
      },
      series: [{
        type: "heatmap" as const,
        data: cells.map(([x, y, v]) => ({
          value: [x, y, v == null ? null : +(v / price - 1).toFixed(4)],
          label: { show: true, color: INK.primary, fontSize: 10,
                   formatter: () => (v == null ? "×" : fmtNum(v, 0)) },
        })),
        itemStyle: { borderColor: "#fcfcfb", borderWidth: 2 },
      }],
    };
  }, [report]);

  if (err) return <ErrorBox message={err} />;
  if (!report) return <Loading text="估值计算中…" />;

  const fusion = report.fusion;
  const snap = report.market_snapshot;
  const models = Object.keys(report.model_values_per_share || {});
  const fcffBase = report.models?.fcff?.base;
  const assum = report.assumptions;

  return (
    <div className="space-y-4">
      {/* 参数修改入口 */}
      <div className="card">
        <div className="section-title">基准情景参数（可修改后重算；未填写使用系统默认，来源见下表）</div>
        <div className="flex flex-wrap gap-4 items-end">
          {EDITABLE.map((k) => (
            <label key={k} className="text-xs text-ink-secondary">
              {PARAM_LABELS[k]}
              <div className="flex items-center gap-1 mt-1">
                <input
                  type="number" step="0.005" className="w-24"
                  placeholder={fmtNum(assum.base[k], 4)}
                  value={overrides[k] ?? ""}
                  onChange={(e) => setOverrides({ ...overrides, [k]: e.target.value })}
                />
              </div>
            </label>
          ))}
          <button className="btn-primary" disabled={busy} onClick={() => run(false, overrides)}>
            {busy ? "计算中…" : "重新计算（预览）"}
          </button>
          <button className="btn-ghost" disabled={busy} onClick={() => run(true, overrides)}>
            保存本次估值
          </button>
          {savedMsg && <span className="text-xs text-status-good">{savedMsg}</span>}
        </div>
        <div className="text-xs text-ink-muted mt-2">
          WACC 明细：Ke {fmtPct(report.wacc_detail?.ke)}（CAPM）、Kd {fmtPct(report.wacc_detail?.kd)}、
          股权权重 {fmtPct(report.wacc_detail?.weight_equity)} → WACC {fmtPct(report.wacc_detail?.wacc)}
          （受行业区间约束后取 {fmtPct(assum.base.wacc)}）
        </div>
      </div>

      {/* 三情景 × 模型结果 */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="card overflow-x-auto">
          <div className="section-title">各模型 × 三情景 每股价值（{snap.trading_currency}）</div>
          <table className="w-full">
            <thead><tr>
              <th className="th">模型</th>
              {SCN.map((s) => <th key={s} className="th text-right">{SCENARIO_NAMES[s]}</th>)}
              <th className="th text-right">融合权重</th>
            </tr></thead>
            <tbody>
              {models.map((m) => {
                const fx = snap.fx_trading_to_report;
                const w = fusion.weights_used?.base?.[m];
                return (
                  <tr key={m} className="border-t border-[#f0efec]">
                    <td className="td font-medium">{MODEL_NAMES[m] ?? m}</td>
                    {SCN.map((s) => {
                      const v = report.model_values_per_share[m]?.[s];
                      return <td key={s} className="td text-right">{v != null ? fmtNum(v / fx) : "不适用"}</td>;
                    })}
                    <td className="td text-right">{w != null ? fmtPct(w) : "—"}</td>
                  </tr>
                );
              })}
              <tr className="border-t-2 border-[#d8d6d0] font-semibold">
                <td className="td">融合（行业权重）</td>
                <td className="td text-right">{fmtNum(fusion.value_pessimistic_trading_ccy)}</td>
                <td className="td text-right text-series-1">{fmtNum(fusion.weighted_fair_value_trading_ccy)}</td>
                <td className="td text-right">{fmtNum(fusion.value_optimistic_trading_ccy)}</td>
                <td className="td text-right">100%</td>
              </tr>
            </tbody>
          </table>
          <div className="text-xs text-ink-muted mt-2">
            权重来自行业模板 {report.industry.name}（方案第九/十章），模型不可用时自动重新归一；
            模型分歧度 {fmtPct(fusion.model_divergence)}。
          </div>
        </div>
        <div className="card">
          <div className="section-title">融合价值区间 vs 现价</div>
          <ValueRangeBar
            pessimistic={fusion.value_pessimistic_trading_ccy}
            base={fusion.weighted_fair_value_trading_ccy}
            optimistic={fusion.value_optimistic_trading_ccy}
            price={snap.price}
            currency={snap.trading_currency}
          />
          {report.warnings.length > 0 && (
            <div className="mt-3">
              <div className="text-xs font-medium text-ink-secondary mb-1">模型警告</div>
              <ul className="text-xs text-ink-secondary space-y-1 max-h-40 overflow-y-auto">
                {report.warnings.map((w: string, i: number) => <li key={i}>⚠ {w}</li>)}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* FCFF 明细 */}
      {fcffBase && !fcffBase.error && (
        <div className="card overflow-x-auto">
          <div className="section-title">
            FCFF 预测表（基准情景，单位：亿 {snap.report_currency}）
            — 终值占比 <b>{fmtPct(fcffBase.terminal_value_share)}</b>
            ，永续增长法终值 {fmtYi(fcffBase.terminal_value_gordon)}
            {fcffBase.terminal_value_exit != null && <>，退出倍数法终值 {fmtYi(fcffBase.terminal_value_exit)}</>}
          </div>
          <table className="w-full">
            <thead><tr>
              <th className="th">年份</th><th className="th text-right">营收</th>
              <th className="th text-right">增速</th><th className="th text-right">EBIT率</th>
              <th className="th text-right">NOPAT</th><th className="th text-right">折旧摊销</th>
              <th className="th text-right">资本开支</th><th className="th text-right">ΔWC</th>
              <th className="th text-right">FCFF</th><th className="th text-right">折现因子</th>
              <th className="th text-right">现值</th>
            </tr></thead>
            <tbody>
              {fcffBase.forecast_table.map((r: any) => (
                <tr key={r.year} className="border-t border-[#f0efec]">
                  <td className="td">T+{r.year}</td>
                  <td className="td text-right">{fmtYi(r.revenue)}</td>
                  <td className="td text-right">{fmtPct(r.revenue_growth)}</td>
                  <td className="td text-right">{fmtPct(r.ebit_margin)}</td>
                  <td className="td text-right">{fmtYi(r.nopat)}</td>
                  <td className="td text-right">{fmtYi(r.da)}</td>
                  <td className="td text-right">{fmtYi(r.capex)}</td>
                  <td className="td text-right">{fmtYi(r.delta_wc)}</td>
                  <td className="td text-right font-medium">{fmtYi(r.fcff)}</td>
                  <td className="td text-right">{fmtNum(r.discount_factor, 3)}</td>
                  <td className="td text-right">{fmtYi(r.pv_fcff)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-xs text-ink-muted mt-2">
            企业价值 {fmtYi(fcffBase.enterprise_value)} = 预测期现值 {fmtYi(fcffBase.pv_explicit)} + 终值现值 {fmtYi(fcffBase.pv_terminal)}；
            股权价值 {fmtYi(fcffBase.equity_value)} = 企业价值 − 净债务 {fmtYi(snap.net_debt)} − 少数股东权益/优先股 + 非经营资产；
            每股 {fmtNum(fcffBase.value_per_share)} {snap.report_currency}（稀释股本 {fmtNum(snap.diluted_shares, 0)} 百万股）。
          </div>
        </div>
      )}

      {/* 敏感性矩阵 */}
      {heatmap && (
        <div className="card">
          <div className="section-title">敏感性矩阵：WACC × 永续增长率（颜色 = 相对现价的偏离，× 为禁止计算区）</div>
          <EChart option={heatmap as any} height={300} />
        </div>
      )}

      {/* 三情景假设与来源 */}
      <div className="card overflow-x-auto">
        <div className="section-title">三情景完整假设（source=user_override 表示手动修改）</div>
        <table className="w-full">
          <thead><tr>
            <th className="th">参数</th>
            {SCN.map((s) => <th key={s} className="th text-right">{SCENARIO_NAMES[s]}</th>)}
            <th className="th">来源（基准）</th>
          </tr></thead>
          <tbody>
            {Object.keys(assum.base).map((k) => (
              <tr key={k} className="border-t border-[#f0efec]">
                <td className="td">{PARAM_LABELS[k] ?? k}</td>
                {SCN.map((s) => (
                  <td key={s} className="td text-right">
                    {k === "forecast_years" ? assum[s][k] : fmtNum(assum[s][k], 4)}
                  </td>
                ))}
                <td className="td text-xs">
                  {report.assumption_sources.base[k] === "user_override"
                    ? <span className="text-status-serious font-medium">手动修改</span>
                    : "系统默认"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 计算日志 */}
      <details className="card">
        <summary className="cursor-pointer text-sm font-medium text-ink-secondary">
          计算日志（估值可追溯，run_id: {report.run_id}）
        </summary>
        <ol className="mt-3 text-xs text-ink-secondary space-y-1 list-decimal ml-5">
          {report.calculation_log.map((l: any) => (
            <li key={l.seq}><b>{l.step}</b> — {l.message}</li>
          ))}
        </ol>
      </details>
    </div>
  );
}
