import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 经过 CVD 验证的分类色板（dataviz 参考色板，浅色模式）
        series: {
          1: "#2a78d6",
          2: "#1baf7a",
          3: "#eda100",
          4: "#008300",
          5: "#4a3aa7",
          6: "#e34948",
        },
        status: {
          good: "#0ca30c",
          warning: "#fab219",
          serious: "#ec835a",
          critical: "#d03b3b",
        },
        ink: {
          primary: "#0b0b0b",
          secondary: "#52514e",
          muted: "#8a8985",
        },
        surface: {
          1: "#fcfcfb",
          2: "#f5f4f1",
          3: "#edecea",
        },
      },
    },
  },
  plugins: [],
};
export default config;
