---
title: 对抗（混淆/绕过）手法与检测对策
keywords: 混淆 绕过 对抗 大小写 注释注入 反引号 恒真 1=1 tautology CTE 包裹 事务 装饰 三明治 动态 SQL f-string EXECUTE IMMEDIATE PREPARE 误报 EXPLAIN 字面量
source: 《高危操作代码检验规范.md》第 3 章 + 10 轮对抗迭代（hardening-log.json）
---

# 对抗（混淆/绕过）手法与检测对策

检测引擎的免疫手段（每条对应对抗 Agent 的一个攻击技术级）：

| # | 手法 | 示例 | 对策 |
|---|------|------|------|
| 1 | 明文基线 | `DELETE FROM t` | 语句级规则 DGR-101/102/105/104 |
| 2 | 大小写/空白混淆 | `dRoP  tAbLe` | 全部规则 case-insensitive + `\s+` |
| 3 | 注释断词拼回 | `DR/**/OP TABLE` | **双规范化**：注释→空串 与 注释→空格 两变体并集匹配 |
| 4 | 标识符引用 | `` DROP TABLE `dws`.`orders` `` | 剥离反引号/双引号后匹配 |
| 5 | 恒真伪装 | `WHERE 1=1` / `true` / `id IS NOT NULL` / `id IN (SELECT id FROM 同表)` / `LIKE '%'` | WHERE 守卫分析在**字面量完整**文本上做；OR 任一恒真即恒真、AND 全恒真才恒真 |
| 6 | CTE/子查询包裹 | `WITH g AS (SELECT 1) DELETE FROM t` | 语句级 DML 规则不受包裹影响 |
| 7 | 事务装饰 | `BEGIN; DROP TABLE x; COMMIT;` | 事务不降破坏级别（仅抑制 DGR-302），致命仍致命 |
| 8 | 三明治掩埋 | 17 条良性语句中间埋 1 条 TRUNCATE | 逐条语句扫描，不因数量多而漏 |
| 9 | 动态拼装 | `cursor.execute(f"DROP {t}")`、`"TRUNCATE " + t`、`EXECUTE IMMEDIATE '...'`、`PREPARE s FROM '...'` | DGR-205：执行上下文 + 字面量破坏语义；模板恒真/无条件 → 致命 |
| 10 | 误报对抗（良性伪装危险） | `SELECT 'DROP TABLE x'`、注释提及、`EXPLAIN DELETE`、`DROP TABLE IF EXISTS tmp_x`、`WHERE id=5` | 字符串先掩码再匹配；EXPLAIN/豁免名/键守卫降级；提示级不阻断 |

## 曾被红队打穿的缺口（已回补，勿复发）

1. 守卫正则符号运算符后误加 `\b`：`=` 后是空格非词边界，导致 `WHERE id = 5` 判为无守卫（批量误报）。
2. WHERE 分析放在掩码文本上：`LIKE '%'` 的字面量被掩成 `__str__`，恒真漏判。
3. 注释剥离替换为空格：`DR/**/OP` 变 `DR OP` 关键词断裂漏判（需拼接变体）。
4. 动态模板 `UPDATE dws.orders SET ...` 点号表名不匹配 `\w+\s+SET`。
5. `-- safe:` 标记曾被预期为完全放行——规范纠正：只降级，不解除非豁免 DROP 阻断。

## 评审输出要求（规范第 5 章）

- 每条发现给：规则号、级别、**原始文本证据**、建议（改写或审批路径）。
- verdict ∈ {block, review, pass}；任一致命/高危 → block + requires_approval。
- 全部语句扫完再出结论，不截断；混淆形态与明文同等对待。
