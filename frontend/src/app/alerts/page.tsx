"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { ErrorBox, Loading } from "@/components/shared";
import { STATUS } from "@/lib/palette";

const RULE_NAMES: Record<string, string> = {
  price_in_value_range: "股价进入合理价值区间",
  price_below_pessimistic: "股价低于悲观情景价值",
  margin_of_safety_above_target: "安全边际超过设定阈值",
  valuation_change_gt_10pct: "估值变化超过 10%",
};

/** 估值监控页（方案 12.6）。 */
export default function AlertsPage() {
  const [items, setItems] = useState<any[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (refresh: boolean) => {
    setBusy(true);
    try {
      const d = await apiGet(`/alerts${refresh ? "?refresh=true" : ""}`);
      setItems(d.items);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }, []);

  useEffect(() => { load(true); }, [load]);

  if (err) return <ErrorBox message={err} />;

  return (
    <div className="space-y-4">
      <div className="card flex items-center gap-3">
        <div className="text-sm text-ink-secondary">
          监控规则：股价进入价值区间 / 安全边际达标 / 相邻两次估值变化 &gt;10% / 财务数据质量异常。
          仅对自选股生效。
        </div>
        <button className="btn-primary ml-auto" onClick={() => load(true)} disabled={busy}>
          {busy ? "评估中…" : "重新评估"}
        </button>
      </div>
      {!items ? <Loading /> : items.length === 0 ? (
        <div className="card text-sm text-ink-muted">
          暂无触发的提醒。请先将公司加入自选股并运行估值。
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((a) => {
            const color = a.severity === "risk" ? STATUS.critical : a.severity === "warn" ? "#8a6400" : STATUS.good;
            const bg = a.severity === "risk" ? `${STATUS.critical}14` : a.severity === "warn" ? `${STATUS.warning}22` : `${STATUS.good}14`;
            return (
              <div key={a.id} className="card flex items-start gap-3">
                <span className="badge shrink-0 mt-0.5" style={{ background: bg, color }}>
                  {a.severity === "risk" ? "风险" : a.severity === "warn" ? "关注" : "机会"}
                </span>
                <div>
                  <div className="text-sm">
                    <Link href={`/company/${a.company_id}`} className="font-medium text-series-1 hover:underline">
                      {a.company_name}
                    </Link>
                    <span className="ml-2 text-ink-secondary">{RULE_NAMES[a.rule] ?? a.rule}</span>
                  </div>
                  <div className="text-sm text-ink-primary mt-0.5">{a.message}</div>
                  <div className="text-xs text-ink-muted mt-0.5">{a.triggered_at.replace("T", " ").slice(0, 19)}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
