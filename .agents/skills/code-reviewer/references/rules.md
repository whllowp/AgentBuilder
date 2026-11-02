# 默认规则与 rule.json 定制

来源：`agents/code-reviewer/tools/review_tools/rule_engine.py`（DEFAULT_RULES）+ static_scan 检查清单。

## 通用（**/*）

| 检查 | category/severity |
|------|-------------------|
| 硬编码凭据（DB_PASSWORD = "..." / api_key: xxx 等，含下划线标识符） | security / critical |
| 冲突标记 | bug / critical |
| `debugger;` | bug / high |
| console.log/print 调试（非测试路径） | style / low（默认丢弃） |
| TODO/FIXME 未带负责人工单 | maintainability / low |
| 单文件 diff > 2000 行 | maintainability / medium |

## 语言专项

- **Java**（《阿里巴巴 Java 开发手册》要点）：`Executors.new*ThreadPool`（performance/medium，应手动 ThreadPoolExecutor）；`static SimpleDateFormat`（bug/medium，线程不安全）；`e.printStackTrace()`（bug/medium）；空 catch（bug/high）。
- **JS/TS**：debugger（high）；console.log（low）；`==`/`!=`（bug/low）；`var`（low）；TS `any`（low）。
- **Python**：裸 `except:`（high）；`except Exception` + `pass` 吞异常（high）；可变默认参数（medium）；print 调试（low）。
- **Go**：`_ = err` 显式忽略（low，需注释）；规则文本另含 goroutine 退出/defer-in-loop。
- **SQL**：破坏性 DDL/DML 须带审批工单；避免 SELECT *；深检转 sql-danger-reviewer（DGR-101~502）。
- **测试**（test_*.py、*Test.java、*.spec.ts 等 + test/ 目录）：新业务逻辑伴随测试、异常分支、断言具体化。
- **配置**（yaml/toml/json/properties）：敏感项不明文；评估影响与回滚。

## rule.json 定制（与 open-code-review 语义一致）

```json
{
  "rules": [
    {"path": "src/**/*.java", "rule": "本项目 Java 规则：……", "merge_system_rule": true}
  ]
}
```

- 优先级：`--rule` > 仓库 `.opencodereview/rule.json` > `~/.opencodereview/rule.json` > 内置。
- 命中用户条目默认**替换**内置；`merge_system_rule: true` 则合并（内置在前，用户在后）。
- 多条命中取并集；`path` 为 glob（fnmatch 语义，**不支持 `{}` 花括号**，逐条列后缀）。
