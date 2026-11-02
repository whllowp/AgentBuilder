---
title: 默认规则要点（按语言的确定性检查与 LLM 聚焦规则）
keywords: 默认规则 Java P3C 线程池 Executors SimpleDateFormat JavaScript debugger console.log var === Python 裸except 可变默认参数 Go error SQL 测试 配置 凭据 TODO severity
source: rule_engine.DEFAULT_RULES + static_scan 检查清单
---

# 默认规则要点

## 通用（**/*）

| 检查 | category/severity |
|------|-------------------|
| 硬编码凭据（password/secret/token/api_key 赋值） | security / critical |
| 冲突标记（<<<<<<< / >>>>>>>） | bug / critical |
| `debugger;` | bug / high |
| console.log/print 调试输出（非测试路径） | style / low（默认丢弃） |
| TODO/FIXME 未标负责人 | maintainability / low |
| 单文件 diff > 2000 行 | maintainability / medium（建议拆分） |

## Java（参考《阿里巴巴 Java 开发手册》）

| 检查 | category/severity |
|------|-------------------|
| `Executors.new*ThreadPool`（应手动 ThreadPoolExecutor 明确参数） | performance / medium |
| `static SimpleDateFormat`（线程不安全） | bug / medium |
| `e.printStackTrace()`（不入日志体系） | bug / medium |
| 空 catch 块 | bug / high |

## JavaScript / TypeScript

`debugger`（high）；`console.log/debug`（low）；宽松相等 `==`/`!=`（bug/low，建议 ===）；`var` 声明（low）；TS `any` 扩散（low）。

## Python

裸 `except:`（bug/high，吞 KeyboardInterrupt）；`except Exception` + `pass` 吞异常（high）；可变默认参数 `=[]/{}/set()`（medium）；print 调试（low）。

## Go

显式 `_ = err` 忽略错误（low，需注释原因）；规则文本另含 goroutine 退出与 defer-in-loop 聚焦点。

## SQL

破坏性 DDL/DML（全表 UPDATE/DELETE、DROP/TRUNCATE）须标注审批工单；避免 SELECT *；深度检查转 sql-danger-reviewer Agent（DGR-101~502）。

## 测试 / 配置

- `**/test*/**`：新业务逻辑伴随测试、覆盖异常分支、断言具体化（LLM 聚焦）。
- `**/*.{yaml,yml,toml,json,properties}`：敏感项不明文入库；配置变更评估影响与回滚（LLM 聚焦）。

## rule.json 覆盖/合并

```json
{"rules": [{"path": "src/**/*.java", "rule": "<专属规则文本>", "merge_system_rule": true}]}
```
优先级：--rule > 仓库 `.opencodereview/rule.json` > `~/.opencodereview/rule.json` > 内置；命中用户条目默认替换内置，`merge_system_rule: true` 合并。
