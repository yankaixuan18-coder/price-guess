"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import EChart, { axisDefaults } from "@/components/EChart";
import { ConfidenceBadge, ErrorBox, Loading, StatTile, ValueRangeBar } from "@/components/shared";
import { apiGet, apiPost, CCY_SYMBOL, fmtNum, fmtPct, fmtX, fmtYi } from "@/lib/api";
import { GRID_LINE, INK, SERIES, STATUS } from "@/lib/palette";

export default function OverviewPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [prices, setPrices] = useState<any>(null);
  const [peHist, setPeHist] = useState<any>(null);
  const [peers, setPeers] = useState<any>(null);
  const [err, setErr] = useState("");
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const [o, p, m, pe] = await Promise.all([
        apiGet(`/companies/${id}`),
        apiGet(`/companies/${id}/prices`),
        apiGet(`/companies/${id}/multiple-history`),
        apiGet(`/companies/${id}/peers`),
      ]);
      setData(o); setPrices(p); setPeHist(m); setPeers(pe);
    } catch (e: any) { setErr(e.message); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const runValuation = async () => {
    setRunning(true);
    try {
      await apiPost("/valuations/run", { company_id: id });
      await load();
    } catch (e: any) { setErr(e.message); }
    setRunning(false);
  };

  const priceOption = useMemo(() => {
    if (!prices) return null;
    return {
      tooltip: { trigger: "axis" as const },
      xAxis: { type: "category" as const, data: prices.items.map((i: any) => i.date), ...axisDefaults, splitLine: { show: false } },
      yAxis: { type: "value" as const, scale: true, ...axisDefaults, name: prices.currency, nameTextStyle: { color: INK.muted } },
      series: [{
        name: "收盘价", type: "line" as const, data: prices.items.map((i: any) => i.close),
        showSymbol: false, lineStyle: { width: 2, color: SERIES[0] }, itemStyle: { color: SERIES[0] },
      }],
    };
  }, [prices]);

  const peOption = useMemo(() => {
    if (!peHist || peHist.pe.length === 0 || !data) return null;
    const q = data.multiple_percentiles?.pe?.quantiles;
    const mark = q
      ? {
          silent: true,
          symbol: "none",
          label: { color: INK.muted, fontSize: 10, position: "insideEndTop" as const },
          lineStyle: { color: GRID_LINE, type: "dashed" as const, width: 1 },
          data: [
            { yAxis: q.p25, label: { formatter: "P25" } },
            { yAxis: q.p50, label: { formatter: "中位" }, lineStyle: { color: INK.muted } },
            { yAxis: q.p75, label: { formatter: "P75" } },
          ],
        }
      : undefined;
    return {
      tooltip: { trigger: "axis" as const },
      xAxis: { type: "category" as const, data: peHist.pe.map((i: any) => i.date), ...axisDefaults, splitLine: { show: false } },
      yAxis: { type: "value" as const, scale: true, ...axisDefaults, name: "PE（标准化）", nameTextStyle: { color: INK.muted } },
      series: [{
        name: "PE", type: "line" as const, data: peHist.pe.map((i: any) => i.value.toFixed(1)),
        showSymbol: false, lineStyle: { width: 2, color: SERIES[1] }, itemStyle: { color: SERIES[1] },
        markLine: mark,
      }],
    };
  }, [peHist, data]);

  if (err) return <ErrorBox message={err} />;
  if (!data) return <Loading />;

  const c = data.company;
  const snap = data.market_snapshot;
  const mult = data.current_multiples || {};
  const pct = data.multiple_percentiles || {};
  const km = data.key_metrics || {};
  const val = data.latest_valuation;
  const fusion = val?.fusion;
  const ccy = CCY_SYMBOL[snap?.trading_currency] ?? snap?.trading_currency;

  return (
    <div className="space-y-4">
      {/* 抬头 */}
      <div className="card flex flex-wrap items-start gap-6">
        <div>
          <h1 className="text-2xl font-bold">
            {c.name_zh} <span className="text-base font-normal text-ink-muted">{c.ticker} · {c.industry_name}</span>
          </h1>
          <p className="text-sm text-ink-secondary mt-1 max-w-xl">{c.description}</p>
          <div className="flex gap-2 mt-2 text-xs text-ink-muted">
            <span>最新报告 FY{snap?.latest_period?.fiscal_year}（{snap?.latest_period?.published_at} 披露，{snap?.latest_period?.accounting_standard}）</span>
            <span>· 数据质量 {snap?.latest_period?.quality_grade} 级</span>
            {val && <span>· 估值更新 {val.valuation_date}</span>}
          </div>
        </div>
        <div className="ml-auto text-right">
          <div className="text-3xl font-bold tabular-nums">{ccy}{fmtNum(snap?.price)}</div>
          <div className="text-xs text-ink-muted">{snap?.price_date} 收盘</div>
          <div className="mt-2 flex gap-2 justify-end">
            {val && <ConfidenceBadge score={val.confidence?.score} />}
            <button className="btn-primary" onClick={runValuation} disabled={running}>
              {running ? "估值计算中…" : val ? "重新估值" : "运行估值"}
            </button>
          </div>
        </div>
      </div>

      {/* 价值区间 */}
      <div className="card">
        <div className="section-title">合理价值区间（行业权重融合：{val ? "已估值" : "未估值"}）</div>
        <ValueRangeBar
          pessimistic={fusion?.value_pessimistic_trading_ccy ?? null}
          base={fusion?.weighted_fair_value_trading_ccy ?? null}
          optimistic={fusion?.value_optimistic_trading_ccy ?? null}
          price={snap?.price ?? null}
          currency={snap?.trading_currency}
        />
        {fusion && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-sm">
            <div>上行空间 <b className={fusion.upside > 0 ? "text-status-good" : "text-status-critical"}>{fmtPct(fusion.upside)}</b></div>
            <div>安全边际 <b>{fmtPct(fusion.safety_margin)}</b></div>
            <div>模型分歧度 <b>{fmtPct(fusion.model_divergence)}</b></div>
            <div>悲观情景对应 <b>{fmtPct(fusion.downside_to_pessimistic)}</b></div>
          </div>
        )}
        {val?.confidence?.reasons?.length > 0 && (
          <ul className="mt-3 text-xs text-ink-secondary space-y-1">
            {val.confidence.reasons.map((r: string, i: number) => (
              <li key={i}>⚠ {r}</li>
            ))}
          </ul>
        )}
      </div>

      {/* 关键指标 */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatTile label="市值" value={fmtYi(mult.market_cap)} sub={`企业价值 ${fmtYi(mult.enterprise_value)}`} />
        <StatTile label="PE（标准化）" value={fmtX(mult.pe)} sub={`历史分位 ${fmtPct(pct.pe?.percentile)}`} />
        <StatTile label="PB" value={fmtX(mult.pb)} sub={`历史分位 ${fmtPct(pct.pb?.percentile)}`} />
        <StatTile label="EV/EBITDA" value={fmtX(mult.ev_ebitda)} sub={`历史分位 ${fmtPct(pct.ev_ebitda?.percentile)}`} />
        <StatTile label="ROE / ROIC" value={`${fmtPct(km.roe)} / ${fmtPct(km.roic)}`} />
        <StatTile label="股息率 / FCF收益率" value={`${fmtPct(mult.dividend_yield)} / ${fmtPct(mult.fcf_yield)}`} />
      </div>

      {/* 走势图 */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="section-title">股价走势（原始收盘价）</div>
          {priceOption && <EChart option={priceOption as any} height={260} />}
        </div>
        <div className="card">
          <div className="section-title">历史 PE 与分位带（时点口径：只用当时已披露年报）</div>
          {peOption ? <EChart option={peOption as any} height={260} /> : <Loading text="历史倍数不足" />}
        </div>
      </div>

      {/* 风险提示 + 同行 */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="section-title">财务风险提示（数据质量检查）</div>
          {data.risk_flags.length === 0 ? (
            <div className="text-sm text-status-good">✓ 勾稽与异常检查全部通过</div>
          ) : (
            <ul className="text-sm space-y-2">
              {data.risk_flags.map((f: any, i: number) => (
                <li key={i} className="flex gap-2">
                  <span className="badge shrink-0" style={{
                    background: f.severity === "risk" ? `${STATUS.critical}22` : `${STATUS.warning}33`,
                    color: f.severity === "risk" ? STATUS.critical : "#8a6400",
                  }}>{f.severity === "risk" ? "风险" : "关注"}</span>
                  <span className="text-ink-secondary">{f.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card overflow-x-auto">
          <div className="section-title">可比公司（含入选理由，非仅行业代码）</div>
          <table className="w-full">
            <thead><tr>
              <th className="th">公司</th><th className="th text-right">PE</th>
              <th className="th text-right">PB</th><th className="th text-right">EV/EBITDA</th>
              <th className="th text-right">ROE</th><th className="th text-right">营收CAGR</th>
            </tr></thead>
            <tbody>
              {(peers?.peers ?? []).map((p: any) => (
                <tr key={p.company_id} className="border-t border-[#f0efec]" title={p.rule}>
                  <td className="td">{p.name}</td>
                  <td className="td text-right">{fmtX(p.pe)}</td>
                  <td className="td text-right">{fmtX(p.pb)}</td>
                  <td className="td text-right">{fmtX(p.ev_ebitda)}</td>
                  <td className="td text-right">{fmtPct(p.roe)}</td>
                  <td className="td text-right">{fmtPct(p.revenue_cagr_3y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
