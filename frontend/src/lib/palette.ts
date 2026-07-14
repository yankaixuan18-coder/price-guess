/** 数据可视化色板（已通过 CVD/对比度验证的参考色板，浅色模式）。
 *  分类色按固定顺序分配，绝不循环；状态色专用，不用作系列色。 */
export const SERIES = [
  "#2a78d6", // 1 blue
  "#1baf7a", // 2 aqua
  "#eda100", // 3 yellow
  "#008300", // 4 green
  "#4a3aa7", // 5 violet
  "#e34948", // 6 red
  "#e87ba4", // 7 magenta
  "#eb6834", // 8 orange
] as const;

export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;

/** 发散对：blue ↔ red，中点中性灰（敏感性矩阵：高于/低于现价） */
export const DIVERGING = { low: "#e34948", mid: "#f0efec", high: "#2a78d6" } as const;

export const INK = { primary: "#0b0b0b", secondary: "#52514e", muted: "#8a8985" } as const;
export const SURFACE = "#fcfcfb";
export const GRID_LINE = "#e7e5e0";
