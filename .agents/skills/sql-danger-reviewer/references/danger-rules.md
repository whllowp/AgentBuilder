# DGR 规则目录（分级/豁免/对抗对策）

来源：《高危操作代码检验规范.md》。级别：致命/高危 → block；中危 → review；提示 → pass。

## 致命（block）

| 规则 | 触发 | 例外 |
|------|------|------|
| DGR-101/102 DELETE/UPDATE 无 WHERE | `DELETE FROM t` / `UPDATE t SET ...` | 真值守卫 → 403/203 |
| DGR-103 恒真条件 | `1=1`/`true`/`'t'`/`id IS NOT NULL`/`id IN (SELECT id FROM 同表)`/`LIKE '%'`；OR 任一恒真即恒真、AND 全恒真才恒真 | 有真值过滤即视为有守卫 |
| DGR-104 DROP DATABASE/SCHEMA | 含 CASCADE 一律 | 无 |
| DGR-105 DROP TABLE 非豁免名 | 表名非 tmp_/_staging | 豁免名 → 401 |
| DGR-204 mutation 恒真/无条件 | CK `ALTER ... DELETE/UPDATE` 无有效 WHERE | 有条件 → 高危 |
| DGR-205 无守卫动态破坏语句 | execute 模板无 WHERE/恒真 | 有守卫 → 高危 |
| DGR-501 rm -rf 危险路径 | `/`、`~`、含 `$` | 其他路径 → 高危 |

## 高危（block + DBA 复核）

DGR-201 TRUNCATE；DGR-202 ALTER DROP COLUMN/PARTITION/DETACH/MODIFY/DROP CONSTRAINT；DGR-204 有条件 mutation；DGR-205 动态拼装（`cursor.execute(f"...")`、拼接、EXECUTE IMMEDIATE、PREPARE FROM、sp_executesql）；DGR-206 GRANT ALL/TO PUBLIC/REVOKE；DGR-502 客户端 -q/-e 直连执行破坏语句；DGR-501 其他 rm -rf。

## 中危（review）

DGR-203 非键条件批量 UPDATE/DELETE（条件列名不含 id/key/uid/code）；DGR-301 RENAME/EXCHANGE TABLES；DGR-302 破坏操作未包事务；DGR-303 OPTIMIZE FINAL/VACUUM FULL。

## 提示（pass）

DGR-401 豁免名（tmp_/_staging）DROP/TRUNCATE；DGR-402 字面量/注释中的危险词（`SELECT 'DROP TABLE x'`）；DGR-403 EXPLAIN 前缀、键等值守卫。

## 对抗混淆对策（引擎已免疫，评审时同标准）

| 手法 | 对策 |
|------|------|
| 大小写/空白 `dRoP  tAbLe` | 全规则 case-insensitive + `\s+` |
| 注释断词 `DR/**/OP TABLE` | 双规范化：注释→空串 与 →空格 两变体并集 |
| 反引号/引号标识符 | 剥离后匹配 |
| 恒真伪装 | WHERE 分析在字面量完整文本上做 |
| CTE/子查询包裹 | 语句级规则不受包裹影响 |
| 事务装饰 BEGIN...COMMIT | 不降级别，仅抑制 DGR-302 |
| 三明治掩埋 | 逐条语句扫描 |
| 动态拼装 | 执行上下文 + 字面量破坏语义（DGR-205） |
| 良性伪装危险 | 字符串先掩码；EXPLAIN/豁免名/键守卫降级 |

## 放行四件套（requires_approval 时输出）

1. 审批：变更工单（影响表、行数预估、执行人、复核人）
2. 备份：RENAME 归档或快照，保留可回滚时长
3. 回滚：逆向 DDL/DML 并在预发演练
4. 窗口：低峰分批 + 事务；CK mutation 配 mutations_sync=0 + system.mutations 监控
