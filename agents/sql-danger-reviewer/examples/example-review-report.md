# 高危操作代码评审报告

## 扫描结论

- 结论：**⛔ block（阻断合入）**，requires_approval = True
- 共 5 条语句，发现 6 处：致命1 / 高危3 / 中危1 / 提示1；verdict=block
- 放行四件套：审批：变更工单（影响表、行数预估、执行人、复核人）；备份：目标表 RENAME 归档或快照/导出，保留可回滚时长；回滚：写好逆向 DDL/DML 并在预发演练通过；窗口：业务低峰执行；DML 分批 + 事务；ClickHouse mutation 配 mutations_sync=0 并监控 system.mutations

## 发现明细

| 级别 | 规则 | 证据（原文） | 建议 |
| --- | --- | --- | --- |
| 🔴 致命 | DGR-102 UPDATE WHERE 为恒真条件 | `... WHERE 1=1` | 恒真条件（1=1/true/IS NOT NULL/自引用 IN/LIKE '%%'）等效无守卫，改为真实过滤。 |
| 🟠 高危 | DGR-105 DROP TABLE dws.orders | `线上工单里的变更脚本，帮忙评审： sql DROP TABLE dws.orders；-- safe 标记降为 高危（清理旧表），仍需人工核对` | 删表需：新表迁移评审或 RENAME 归档备份 + 审批工单 + 回滚 DDL。 |
| 🟠 高危 | DGR-201 TRUNCATE TABLE dws.events | `TRUNCATE TABLE dws.events` | 全表清空不可逆：改 DELETE + 分批，或走审批 + 备份。 |
| 🟠 高危 | DGR-205 动态拼装/执行破坏语句 | `cursor.execute(f"ALTER TABLE dws.events DELETE WHERE event_date < '` | 参数化或移出动态 SQL |
| 🟡 中危 | DGR-302 破坏性操作未包裹事务 | `-` | DML 类操作放 BEGIN...ROLLBACK 可回滚窗口内验证 |
| 🔵 提示 | DGR-403 DELETE 带键条件 | `... WHERE id = 5` | 键等值条件视为有守卫 |

## 改写建议

- 🔴 **DGR-102 UPDATE WHERE 为恒真条件（等效全表 dws.orders）**
  - 恒真条件（1=1/true/IS NOT NULL/自引用 IN/LIKE '%%'）等效无守卫，改为真实过滤。
- 🟠 **DGR-105 DROP TABLE dws.orders（非豁免名）**
  - 删表需：新表迁移评审或 RENAME 归档备份 + 审批工单 + 回滚 DDL。；-- safe 标记降为 高危（清理旧表），仍需人工核对
- 🟠 **DGR-201 TRUNCATE TABLE dws.events**
  - 全表清空不可逆：改 DELETE + 分批，或走审批 + 备份。
- 🟠 **DGR-205 动态拼装/执行破坏语句（ALTER 破坏性子句）**
  - 参数化或移出动态 SQL；确需动态对象名时走白名单校验 + 审批。

## 放行路径

1. 确认不可用更安全写法替代（键等值 WHERE / RENAME 归档 / 轻量删除）。
2. 走变更审批（工单：影响表、行数预估、执行人、复核人）。
3. 备份（RENAME 归档或快照）+ 回滚演练。
4. 低峰窗口分批执行；注意：`-- safe:` 注释只降一级，不构成放行。

## 规范依据（知识库命中）

- **高危操作目录（DGR 规则分级与豁免）**（danger-op-catalog.md）：## 致命（一票否决，verdict=block）

| 规则 | 触发 | 例外 |
|------|------|------|
| DGR-101 DELETE 无 WHERE | `DELETE FROM t` | 有真实守卫 WHERE → 走 DGR-403/203 …
- **对抗（混淆/绕过）手法与检测对策**（evasion-patterns.md）：# 对抗（混淆/绕过）手法与检测对策

检测引擎的免疫手段（每条对应对抗 Agent 的一个攻击技术级）：

| # | 手法 | 示例 | 对策 |
|---|------|------|------|
| 1 | 明文基线 | `DELETE FROM t` | 语句级规则 …

完整规范见《高危操作代码检验规范.md》（Agent 根目录）。

---
*本报告由 sql-danger-reviewer 离线管线生成（未调用 LLM）；LLM 模式可获得交互式评审。*