"use client";
import { STATUS } from "@/lib/palette";
import { fmtNum, fmtPct } from "@/lib/api";

/** 指标卡（hero number / stat tile）。 */
export function StatTile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad" | "neutral";
}) {
  const color =
    tone === "good" ? "text-status-good" : tone === "bad" ? "text-status-critical" : "text-ink-primary";
  return (
    <div className="card !p-4">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className={`text-xl font-semibold mt-1 tabular-nums ${color}`}>{value}</div>
      {sub && <div className="text-xs text-ink-muted mt-1">{sub}</div>}
    </div>
  );
}

/** 价格 vs 合理价值区间 横条（悲观—基准—乐观 + 现价标记）。 */
export function ValueRangeBar({
  pessimistic,
  base,
  optimistic,
  price,
  currency,
}: {
  pessimistic: number | null;
  base: number | null;
  optimistic: number | null;
  price: number | null;
  currency: string;
}) {
  if (pessimistic == null || base == null || optimistic == null || price == null) {
    return <div className="text-sm text-ink-muted">暂无估值区间，请先执行估值。</div>;
  }
  const lo = Math.min(pessimistic, price) * 0.92;
  const hi = Math.max(optimistic, price) * 1.08;
  const pos = (v: number) => `${(((v - lo) / (hi - lo)) * 100).toFixed(1)}%`;
  const width = `${(((optimistic - pessimistic) / (hi - lo)) * 100).toFixed(1)}%`;
  return (
    <div>
      <div className="relative h-9">
        {/* 区间带 */}
        <div
          className="absolute top-3 h-3 rounded-full bg-series-1/25"
          style={{ left: pos(pessimistic), width }}
        />
        {/* 基准值刻度 */}
        <div className="absolute top-2 h-5 w-0.5 bg-series-1" style={{ left: pos(base) }} />
        {/* 现价标记 */}
        <div className="absolute top-0" style={{ left: pos(price) }}>
          <div className="w-3 h-3 rounded-full border-2 border-white shadow -ml-1.5"
               style={{ background: price <= base ? STATUS.good : STATUS.serious }} />
          <div className="h-6 w-px bg-ink-muted/60 ml-0" />
        </div>
      </div>
      <div className="flex justify-between text-xs text-ink-muted tabular-nums">
        <span>悲观 {fmtNum(pessimistic)}</span>
        <span className="text-series-1 font-medium">基准 {fmtNum(base)}</span>
        <span>乐观 {fmtNum(optimistic)} {currency}</span>
      </div>
      <div className="text-xs mt-1 text-ink-secondary">
        现价 <b className="tabular-nums">{fmtNum(price)}</b>（圆点）
        {price <= base ? "：低于基准合理价值" : "：高于基准合理价值"}
      </div>
    </div>
  );
}

/** 可信度徽章（0-100）。 */
export function ConfidenceBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  const tone = score >= 70 ? "bg-status-good/15 text-status-good"
    : score >= 50 ? "bg-status-warning/20 text-[#8a6400]"
    : "bg-status-critical/15 text-status-critical";
  return <span className={`badge ${tone}`}>可信度 {fmtNum(score, 0)}/100</span>;
}

export function UpsideBadge({ upside }: { upside: number | null | undefined }) {
  if (upside == null) return <span className="badge bg-surface-3 text-ink-muted">未估值</span>;
  const tone = upside > 0 ? "bg-status-good/15 text-status-good" : "bg-status-critical/15 text-status-critical";
  return <span className={`badge ${tone}`}>{upside > 0 ? "+" : ""}{fmtPct(upside)}</span>;
}

export function Loading({ text = "加载中…" }: { text?: string }) {
  return <div className="py-16 text-center text-ink-muted text-sm">{text}</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="card border-status-critical/40 text-sm text-status-critical">⚠ {message}</div>
  );
}
