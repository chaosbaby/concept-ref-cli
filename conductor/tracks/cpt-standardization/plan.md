# Track: CPT 标准化升级

## 阶段 1：缺陷修复与数据完整性
- [ ] 修复 init 中的 fp 指纹变量未定义 Bug
- [ ] 补全 schema 命令（自省数据库结构）
- [ ] 补全 doctor 命令（数据库健康诊断）
- [ ] **测试**：运行 cpt doctor 和 cpt schema

## 阶段 2：协议对齐与交互增强
- [ ] 将 random_one 重构为 pick --count
- [ ] 新增 sql 直连命令
- [ ] 补全 completion (Shell 补全安装)
- [ ] **测试**：执行 cpt pick --count 3 和 cpt sql "SELECT count(*) FROM poetry"

## 阶段 3：特性矩阵同步
- [ ] 更新 commands/cp/manifest.json 状态
- [ ] 运行 cpt features 验证所有特性状态
