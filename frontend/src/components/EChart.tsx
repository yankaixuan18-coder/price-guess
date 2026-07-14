"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { GRID_LINE, INK, SURFACE } from "@/lib/palette";

/** ECharts 封装：统一浅色主题、退隐网格、自动 resize。 */
export default function EChart({
  option,
  height = 300,
  onReady,
}: {
  option: echarts.EChartsOption;
  height?: number;
  onReady?: (chart: echarts.ECharts) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const base: echarts.EChartsOption = {
      backgroundColor: "transparent",
      textStyle: { color: INK.secondary, fontSize: 12 },
      grid: { left: 56, right: 20, top: 32, bottom: 32, containLabel: false },
      tooltip: {
        trigger: "axis",
        backgroundColor: SURFACE,
        borderColor: GRID_LINE,
        textStyle: { color: INK.primary, fontSize: 12 },
      },
    };
    chart.setOption({ ...base, ...option }, true);
    onReady?.(chart);
  }, [option, onReady]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}

/** 通用坐标轴样式：退隐网格线、次要墨色标签。 */
export const axisDefaults = {
  axisLine: { lineStyle: { color: GRID_LINE } },
  axisTick: { show: false },
  axisLabel: { color: INK.muted },
  splitLine: { lineStyle: { color: GRID_LINE, type: "dashed" as const } },
};
