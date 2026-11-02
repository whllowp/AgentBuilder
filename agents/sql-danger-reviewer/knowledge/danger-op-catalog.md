---
title: 高危操作目录（DGR 规则分级与豁免）
keywords: 高危操作 危险操作 全表更新 删库 删表 DROP TABLE DROP DATABASE TRUNCATE DELETE UPDATE 无 WHERE mutation DROP PARTITION rm -rf 豁免 tmp staging safe 标记 审批
source: 《高危操作代码检验规范.md》第 2/4 章
---

# 高危操作目录（DGR 规则分级与豁免）

## 致命（一票否决，verdict=block）

| 规则 | 触发 | 例外 |
|------|------|------|
| DGR-101 DELETE 无 WHERE | `DELETE FROM t` | 有真实守卫 WHERE → 走 DGR-403/203 |
| DGR-102 UPDATE 无 WHERE | `UPDATE t SET ...` | 同上 |
| DGR-103 恒真条件 | `WHERE 1=1` / `true` / `id IS NOT NULL` / `id IN (SELECT id FROM 同表)` / `LIKE '%'`；OR 任一恒真即恒真，AND 全恒真才恒真 | 出现真值过滤即视为有守卫 |
| DGR-104 DROP DATABASE/SCHEMA | 含 CASCADE 一律致命 | 无（生产禁用） |
| DGR-105 DROP TABLE 非豁免名 | 表名不以 tmp_/_staging 开头 | 豁免名 → DGR-401 提示 |

## 高危（阻断合入，需 DBA 复核 + 授权）

| 规则 | 触发 |
|------|------|
| DGR-201 TRUNCATE TABLE | 任何 TRUNCATE（含简写 `TRUNCATE t`） |
| DGR-202 ALTER 破坏性子句 | DROP COLUMN / DROP PARTITION / DETACH PARTITION / MODIFY COLUMN / DROP CONSTRAINT |
| DGR-204 ClickHouse mutation | `ALTER TABLE ... DELETE/UPDATE`；恒真/无条件升致命（重写整个 part） |
| DGR-205 动态拼装破坏语句 | `cursor.execute(f"DROP {t}")`、字符串拼接、EXECUTE IMMEDIATE、PREPARE FROM、sp_executesql |
| DGR-206 权限变更 | GRANT ALL / TO PUBLIC / REVOKE |

## 中危（review）

| 规则 | 触发 |
|------|------|
| DGR-203 非键条件的批量 UPDATE/DELETE | 有 WHERE 但条件列名不含 id/key/uid/code |
| DGR-301 RENAME/EXCHANGE TABLES | 对象级替换影响下游 |
| DGR-302 破坏操作未包事务 | 无 BEGIN...COMMIT |
| DGR-303 OPTIMIZE FINAL / VACUUM FULL | 重操作窗口 |

## 提示（pass，人工确认）

| 规则 | 触发 |
|------|------|
| DGR-401 豁免名 DROP/TRUNCATE | tmp_ / _staging 前缀 |
| DGR-402 字面量/注释中的危险词 | `SELECT 'DROP TABLE x'`、注释提及：不执行 |
| DGR-403 EXPLAIN 前缀 / 键等值守卫 | EXPLAIN 不执行；`WHERE id = 5` 视为有守卫 |

## 脚本类

| 规则 | 触发 |
|------|------|
| DGR-501 rm -rf | 目标为 / ~ 或含 $ 变量 → 致命；其他 → 高危 |
| DGR-502 客户端 -q/-e 直连执行破坏语句 | clickhouse-client/psql/mysql/beeline |

## 豁免与放行机制（规范第 4 章）

1. 命名豁免：tmp_ / _staging 前缀表的 DROP/TRUNCATE → 提示级。
2. `-- safe: <原因+工单号>` 标记：降**一级**（致命→高危），**不解除**非豁免 DROP 的阻断——注释不可单独授权删生产表。
3. 守卫判定：WHERE 含键列（id/key/uid/code）等值/IN 字面量 → 不触发致命类。
4. 任何致命/高危 → requires_approval=true，输出"审批-备份-回滚-窗口"四件套要求。
