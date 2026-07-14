import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "股票估值系统",
  description: "A股、美股、港股上市公司估值分析系统（MVP）",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Nav />
        <main className="max-w-6xl mx-auto px-6 py-6">{children}</main>
        <footer className="max-w-6xl mx-auto px-6 pb-8 text-xs text-ink-muted">
          估值结果输出的是合理价值区间与市场隐含预期，不是买入建议；低估≠值得买入（方案 2.3）。
          样例财务数据为近似整理（质量等级 D），生产环境请接入官方披露源。
        </footer>
      </body>
    </html>
  );
}
