# 攻击技术体系（T1~T10）与判定标准

来源：`agents/sql-danger-adversary/tools/adversary_tools/attack_gen.py`（确定性生成器）+ 10 轮迭代验证。

## 技术级

| 级 | 技术 | 代表 payload | 判定 |
|----|------|--------------|------|
| T1 | 明文基线 | `DELETE FROM dws.orders` | danger→block |
| T2 | 大小写/空白 | `dRoP   tAbLe dws.orders` | danger→block |
| T3 | 注释断词 | `DR/**/OP TABLE dws.orders`（行注释前缀） | danger→block |
| T4 | 标识符引用 | `` DELETE FROM `dws`.`orders` ``（配良性键守卫对照） | 混合 |
| T5 | 恒真伪装 | `WHERE 1=1` / `true` / `id IS NOT NULL` / `id IN (SELECT id FROM 同表)` / `LIKE '%'` / `1=1 OR id=5` | danger→block；`id=5 OR id=6` 为 benign→pass |
| T6 | CTE/包裹 | `WITH g AS (SELECT 1) DELETE FROM t` | danger→block |
| T7 | 事务装饰 | `BEGIN; DROP TABLE x; COMMIT;` | danger→block；键守卫事务为 benign |
| T8 | 三明治掩埋 | 17 条良语句中埋 1 条 TRUNCATE | danger→block |
| T9 | 动态拼装 | `cursor.execute(f"DROP {t}")`、`"TRUNCATE "+t`、`EXECUTE IMMEDIATE`、`PREPARE FROM` | danger→block；参数化查询 benign |
| T10 | 误报对抗 | `SELECT 'DROP TABLE x'`、注释提及、`EXPLAIN DELETE`、`DROP TABLE IF EXISTS tmp_x`、`WHERE order_key='A3'` | benign→pass；safe 标记的 DROP 仍 danger→block |

## 判定标准

- 漏报攻击（expect=danger）：verdict 必须为 block（发现最高级别 ∈ {致命, 高危}）。
- 误报攻击（expect=benign）：verdict 必须为 pass（提示级发现允许）。

## 曾打穿的缺口（回补记录，防复发）

1. 守卫正则符号运算符后误加 `\b` → `WHERE id = 5` 全部误判。
2. WHERE 分析在掩码文本上 → `LIKE '%'` 恒真漏判。
3. 注释剥离替换为空格 → `DR/**/OP` 关键词断裂漏判（需拼接变体并集）。
4. 动态模板 `UPDATE dws.orders SET` 点号表名不匹配 `\w+\s+SET`。
5. 误把 `-- safe:` 当完全放行 → 规范纠正为只降级。

## 迭代 harness

```bash
python agents/sql-danger-adversary/harness/iterate.py --rounds 10
# 报告：agents/sql-danger-adversary/reports/iteration-report.md
# 加固历史：agents/sql-danger-adversary/reports/hardening-log.json
```
