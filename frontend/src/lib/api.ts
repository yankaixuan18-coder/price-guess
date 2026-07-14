/** 后端 API 访问与通用格式化。 */

export async function apiGet<T = any>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 ${res.status}`);
  }
  return res.json();
}

export async function apiPost<T = any>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `请求失败 ${res.status}`);
  }
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`/api${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`请求失败 ${res.status}`);
}

// ---------------- 格式化 ----------------

/** 百万 → “x.xx 亿”（报告币种）。 */
export function fmtYi(millions: number | null | undefined, digits = 1): string {
  if (millions === null || millions === undefined || Number.isNaN(millions)) return "—";
  return `${(millions / 100).toLocaleString("zh-CN", { maximumFractionDigits: digits })} 亿`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtX(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}×`;
}

export const CCY_SYMBOL: Record<string, string> = { CNY: "¥", USD: "$", HKD: "HK$" };

export const MODEL_NAMES: Record<string, string> = {
  fcff: "FCFF 折现",
  relative_pe: "PE 相对估值",
  relative_ev_ebitda: "EV/EBITDA",
  relative_pb: "PB 相对估值",
};

export const SCENARIO_NAMES: Record<string, string> = {
  pessimistic: "悲观",
  base: "基准",
  optimistic: "乐观",
};

export const PARAM_LABELS: Record<string, string> = {
  revenue_growth_5y: "收入增速（5年）",
  terminal_ebit_margin: "稳态 EBIT 利润率",
  wacc: "WACC",
  terminal_growth: "永续增长率",
  tax_rate: "有效税率",
  da_pct_revenue: "折旧摊销/收入",
  capex_pct_revenue: "资本开支/收入",
  wc_pct_revenue: "营运资本/收入",
  multiple_shift: "估值倍数偏移",
  forecast_years: "预测年数",
};
