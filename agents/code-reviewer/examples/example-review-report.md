# 代码评审报告（code-reviewer）

> 管线参考 alibaba/open-code-review：文件筛选 → 智能打包 → 规则匹配 → 行级定位；low 项默认丢弃备查。

## 概览

- 文件：5（评审 4 / 过滤 1），+11/-0 行
- 评审单元（打包）：3 个
- 已过滤：yarn.lock
- 分类统计：{"security": 1, "bug": 1, "performance": 1}
- 结论：⛔ 阻断：存在 critical 问题

## 评审意见（按严重度）

### CRITICAL（1）

- 🔴 **[security] `src/main/java/com/x/config/AppConfig.java:2`** 疑似硬编码凭据：新增行包含 password/secret/token/api_key 等敏感赋值，凭据必须走密钥管理，禁止入库
  - 原文：`    static final String DB_PASSWORD = "prod-Passw0rd-2026";`
  - 建议：`<从环境变量/密钥服务读取，并轮换已泄露凭据>`

### HIGH（1）

- 🟠 **[bug] `frontend/app/pay.js:5`** 调试语句 debugger 不得合入
  - 原文：`  debugger;`
  - 建议：`删除该行`

### MEDIUM（1）

- 🟡 **[performance] `src/main/java/com/x/PayService.java:14`** 使用 Executors 创建线程池（阿里手册禁止）：队列无界可致 OOM，应手动 new ThreadPoolExecutor 并明确参数
  - 原文：`        ExecutorService pool = Executors.newFixedThreadPool(4);`
  - 建议：`new ThreadPoolExecutor(core, max, keepAlive, unit, new LinkedBlockingQueue<>(cap), threadFactory, ne`

## 已忽略的 low 项（疑似误报备查，共 2）

- [style] `frontend/app/pay.js:6` console.log/debug 调试输出不应合入生产代码
- [maintainability] `src/test/java/com/x/PayServiceTest.java:1` 新增 TODO/FIXME 需带负责人与工单（如 TODO(owner): xxx #工单号）

## 规则匹配（LLM 模式的聚焦规则）

- `src/main/java/com/x/PayService.java`：2 条规则（通用：新增代码中不得引入硬编码凭据（password/secret/token/api_key）；不…）
- `src/main/java/com/x/config/AppConfig.java`：2 条规则（通用：新增代码中不得引入硬编码凭据（password/secret/token/api_key）；不…）
- `src/test/java/com/x/PayServiceTest.java`：4 条规则（通用：新增代码中不得引入硬编码凭据（password/secret/token/api_key）；不…）
- `frontend/app/pay.js`：2 条规则（通用：新增代码中不得引入硬编码凭据（password/secret/token/api_key）；不…）

```bash
# 深度评审（语义层问题）：
# python agents/code-reviewer/src/code_review_agent/cli.py "<diff>"   # LLM 模式
```

---
*本报告由 code-reviewer 离线确定性管线生成（未调用 LLM）。*