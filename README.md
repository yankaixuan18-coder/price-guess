# 股票估值系统（A股 · 美股 · 港股）

按《A股、美股、港股上市公司股票估值系统建设方案》实现的估值分析系统 **MVP**。

系统回答的不是"这只股票便宜不便宜"，而是：

> 在当前盈利能力、增长预期、资本结构和市场风险条件下，公司合理价值是多少？
> 当前价格隐含了怎样的增长预期？如果关键假设发生变化，估值会如何变化？

**⚠ 声明**：仓库内置的 9 家公司财务/行情数据为根据公开信息整理的**近似样例**（质量等级 D=推算数据），
仅用于演示估值流程，不构成投资建议。生产环境应通过阶段 2 数据管道接入官方披露源。

---

## 快速开始

### 方式一：Windows 一键启动（推荐）

装好 [Python 3.11+](https://www.python.org/downloads/)（安装时勾选 *Add python.exe to PATH*）和
[Node.js LTS](https://nodejs.org/) 后，**双击仓库根目录的 `start.bat`** 即可：
脚本会自动安装依赖（首次约几分钟）、同时启动前后端、并打开浏览器。
退出时关闭弹出的"后端""前端"两个窗口即可；之后每次双击几秒就能启动。

### 方式二：本地手动运行（SQLite，零配置）

```bash
# 后端（Python 3.11+）
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000        # 首次启动自动建表并导入样例数据

# 前端（Node 20+，另开终端）
cd frontend
npm install
npm run dev                              # http://localhost:3000
```

### 方式三：Docker Compose（PostgreSQL）

```bash
docker compose up --build               # 前端 :3000 / 后端 API :8000 / PostgreSQL
```

### 运行测试

```bash
cd backend && python -m pytest tests/ -q   # 40 项估值公式与 API 验收测试
```

---

## MVP 功能范围（方案第十九章）

| 模块 | 内容 |
|---|---|
| 市场 | A股（茅台/美的/长江电力）、美股（AAPL/MSFT/KO）、港股（腾讯/小米/中电控股）样例 |
| 估值模型 | FCFF 折现（双终值法）、PE / EV-EBITDA / PB 相对估值、历史估值分位、**反向 DCF**、三情景敏感性 |
| 页面 | 公司搜索、公司总览、财务趋势、估值模型、反向 DCF、同行对比、自选股、估值提醒 |
| 输出 | 悲观/基准/乐观价值区间、加权合理价值、安全边际、模型分歧度、**估值可信度 0-100** |

## 核心设计如何落实方案要求

| 方案要求 | 实现 |
|---|---|
| 估值可解释（2.1） | 每次估值生成唯一 `valuation_run_id`，落库全部输入参数（含来源 default/user_override）、逐模型输出明细、敏感性矩阵、计算日志；`GET /valuations/runs/{run_id}` 可完整复现 |
| 多模型 + 行业权重（2.2/9/10） | `industry_config.py` 行业模板（消费/制造/软件/互联网/公用事业 + 银行保险占位）；融合按行业权重，模型不可用自动归一，绝不简单平均 |
| 估值与选股分离（2.3） | 筛选器输出估值吸引力、质量、增长、风险、可信度等独立维度，无"综合买入分" |
| 时点数据（2.4） | 报告期含 `period_end / published_at / effective_at / ingested_at / revision_version` 五要素；任何 as_of 查询只用当时已披露版本；内置长江电力 2022 年报**追溯重述**（v1/v2）演示 |
| 统一财务口径（5） | Canonical Schema 宽表 + 科目映射表（source_tag → canonical_metric，5 种映射方式）+ 准则字段（CAS/US_GAAP/IFRS/HKFRS） |
| 三个利润口径（5.3） | 报告净利润 / 标准化净利润（扣非）/ 可持续经营利润，腾讯样例展示 IFRS 与 Non-IFRS 差异 |
| 指标体系（6） | 盈利（ROIC=NOPAT/投入资本）、增长、现金流质量、资产负债风险、股东收益率 |
| 三情景（7.2） | 从历史趋势自动生成悲观/基准/乐观默认假设（增速低中高、WACC 高中低），支持手动覆盖、模板保存（`POST /valuations/scenarios`） |
| 模型硬校验（20） | WACC ≤ 永续增长率**禁止计算**；终值占比 >70% 告警；双终值法差异 >35% 提示；每股价值用**稀释股本**；同输入同输出（测试覆盖） |
| 可信度评分（11） | 7 因素加权（数据完整性 20/盈利稳定 15/现金流稳定 15/模型适配 15/预测误差 15/会计复杂度 10/模型一致性 10）+ 降分原因清单 |
| 反向 DCF（8.7） | 二分法解现价隐含 5 年收入增速与隐含永续增长率，对照历史/同行增速给出判读 |
| 数据质量（15） | 导入后自动执行资产负债勾稽、现金流勾稽、同比异常检查；异常入审核队列不删除；来源优先级与 A-E 质量等级 |
| 多币种（3） | 报告币种 ≠ 交易币种时自动换算（腾讯/小米：CNY 报告、HKD 交易） |
| 估值监控（12.6） | 股价进入价值区间、安全边际达标、相邻估值变化 >10%、质量异常四类提醒 |

## 架构（方案第四/十四章：模块化单体）

```
backend/  FastAPI + SQLAlchemy 2.0 + Pydantic（SQLite 默认 / DATABASE_URL 切 PostgreSQL）
  app/models/       companies·securities·listings（一司多市）/ 财务时点宽表 / 行情股本汇率利率 /
                    valuation_runs·inputs·outputs·sensitivity·calculation_logs / watchlist·alerts
  app/services/     standardize（口径）· metrics（指标）· quality（勾稽）· forecast（三情景）
  app/services/valuation/  fcff · relative · reverse_dcf · sensitivity · fusion · confidence ·
                           industry_config · engine（编排+落库）
  app/api/          方案第十七章全部接口 + watchlist/compare/industries
  app/seed/         样例数据 + CSV 导入工具（模板见 seed/templates/）
frontend/ Next.js 14 + TypeScript + Tailwind + ECharts（色板经 CVD 验证）
```

## 主要接口（方案第十七章）

```
GET  /companies/search?q=&market=        GET  /companies/{id}
GET  /companies/{id}/financials?as_of=   GET  /companies/{id}/metrics
GET  /companies/{id}/filings             GET  /companies/{id}/peers
GET  /companies/{id}/valuation/latest    GET  /companies/{id}/valuation/history
GET  /companies/{id}/reverse-dcf         GET  /companies/{id}/multiple-history
POST /valuations/run                     POST /valuations/scenarios
GET  /valuations/runs/{run_id}           GET  /screeners?min_upside=&max_pe=
GET  /compare?ids=a,b,c                  GET  /alerts?refresh=true
POST /watchlist                          GET  /industries
```

估值执行示例：

```bash
curl -X POST localhost:8000/valuations/run -H 'Content-Type: application/json' -d '{
  "company_id": "moutai",
  "valuation_date": "2025-07-11",
  "assumptions": {"base": {"wacc": 0.09, "terminal_growth": 0.025}}
}'
```

## 添加新公司 / 新数据

详见 **[docs/数据接入指南.md](docs/数据接入指南.md)**。三种方式：

```bash
cd backend
# ① 美股一键抓取（SEC EDGAR 官方结构化数据 + stooq 行情，全自动）
python -m app.seed.fetch_us NVDA --company-id nvda --industry manufacturing --contact 你的邮箱

# ② CSV 数据包（任何市场：主数据+财务+股本+行情+分红，模板在 app/seed/templates/）
python -m app.seed.csv_import --dir path/to/package_dir

# ③ 仅追加财务报表（公司已存在时）
python -m app.seed.csv_import path/to/financials.csv
```

A股/港股可用 AKShare / 巨潮 / HKEXnews 等免费源取数后按模板整理（指南内有映射示例）。

## 路线图（对应方案第十八章）

- **阶段 2 数据管道**：SEC EDGAR / 巨潮 / HKEXnews 适配器，XBRL 映射，定时更新（当前为 CSV/样例导入）
- **阶段 3 行业模型**：银行 PB-ROE/剩余收益、保险 P/EV、REITs NAV/P-FFO、资源 NAV、SOTP（行业配置已留位）
- **阶段 4 回测评分**：Point-in-time 数据库已就绪，待接入分组回测、Rank IC、模型误差校准（可信度中"预测误差"因子当前取中性值）
- **阶段 5 生产化**：权限、审批、任务监控、数据许可合规

## 合规提示（方案第二十一章）

公开披露文件与实时行情的使用许可不同；样例行情为演示数据。商用/再分发前请确认交易所与数据供应商许可。
估值公式与股本计算全部由确定性程序完成，未使用 LLM 生成数值。
