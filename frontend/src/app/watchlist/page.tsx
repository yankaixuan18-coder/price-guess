"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiDelete, apiGet, apiPost, fmtNum, fmtPct } from "@/lib/api";
import { ConfidenceBadge, ErrorBox, Loading, UpsideBadge } from "@/components/shared";

export default function WatchlistPage() {
  const [items, setItems] = useState<any[] | null>(null);
  const [all, setAll] = useState<any[]>([]);
  const [adding, setAdding] = useState("");
  const [mos, setMos] = useState("0.2");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [w, c] = await Promise.all([apiGet("/watchlist"), apiGet("/companies/search")]);
      setItems(w.items);
      setAll(c.items);
    } catch (e: any) { setErr(e.message); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    if (!adding) return;
    await apiPost("/watchlist", { company_id: adding, target_margin_of_safety: parseFloat(mos) || 0.2 });
    setAdding("");
    load();
  };
  const remove = async (cid: string) => { await apiDelete(`/watchlist/${cid}`); load(); };

  if (err) return <ErrorBox message={err} />;
  if (!items) return <Loading />;

  const inList = new Set(items.map((i) => i.company_id));

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-end gap-3">
        <label className="text-xs text-ink-secondary">
          添加公司
          <select className="block mt-1 border border-[#d8d6d0] rounded-md px-2 py-1 text-sm bg-white"
                  value={adding} onChange={(e) => setAdding(e.target.value)}>
            <option value="">选择…</option>
            {all.filter((c) => !inList.has(c.company_id)).map((c) => (
              <option key={c.company_id} value={c.company_id}>{c.name_zh}（{c.ticker}）</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-secondary">
          安全边际提醒阈值
          <input type="number" step="0.05" className="block mt-1 w-24" value={mos}
                 onChange={(e) => setMos(e.target.value)} />
        </label>
        <button className="btn-primary" onClick={add} disabled={!adding}>加入自选</button>
        <span className="text-xs text-ink-muted ml-auto">安全边际超过阈值时会在「估值提醒」中触发</span>
      </div>

      <div className="card overflow-x-auto !p-0">
        <table className="w-full">
          <thead className="border-b border-[#e7e5e0]"><tr>
            <th className="th">公司</th><th className="th text-right">现价</th>
            <th className="th text-right">合理价值</th><th className="th text-right">上行空间</th>
            <th className="th text-right">安全边际</th><th className="th text-right">阈值</th>
            <th className="th text-right">可信度</th><th className="th"></th>
          </tr></thead>
          <tbody>
            {items.map((w) => {
              const s = w.snapshot || {};
              return (
                <tr key={w.company_id} className="border-b border-[#f0efec]">
                  <td className="td">
                    <Link href={`/company/${w.company_id}`} className="text-series-1 font-medium hover:underline">
                      {s.name_zh ?? w.company_id}
                    </Link>
                  </td>
                  <td className="td text-right">{fmtNum(s.price_used)}</td>
                  <td className="td text-right">{fmtNum(s.fair_value_trading_ccy)}</td>
                  <td className="td text-right"><UpsideBadge upside={s.upside} /></td>
                  <td className="td text-right">{fmtPct(s.safety_margin)}</td>
                  <td className="td text-right">{fmtPct(w.target_margin_of_safety)}</td>
                  <td className="td text-right"><ConfidenceBadge score={s.confidence} /></td>
                  <td className="td text-right">
                    <button className="btn-ghost !py-0.5 text-xs" onClick={() => remove(w.company_id)}>移除</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {items.length === 0 && <div className="p-8 text-center text-sm text-ink-muted">自选股为空，请添加公司</div>}
      </div>
    </div>
  );
}
