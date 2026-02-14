# Implementation Plan - Command Packaging

## 1. 结构迁移 (Structural Migration)
- [ ] 创建 `commands/lxc/` 目录
- [ ] 将 `commands/lxc.py` 迁移至 `commands/lxc/main.py`
- [ ] 从 `skills/concept-cli-factory/references/features-manifest.json` 提取 `lxc` 相关特性，生成 `commands/lxc/manifest.json`
- [ ] 在 `commands/lxc/manifest.json` 中注入 `data_context: "sources/lexicon"`

## 2. 代码动态化 (Code Dynamization)
- [ ] 修改 `main.py`：动态读取同目录下的 `manifest.json` 加载 `SUPPORTED_FEATURES`
- [ ] 修改 `main.py`：确保 `features` 命令读取本地 `manifest.json` 而非全局模板

## 3. 功能补全与修复 (Feature Polish)
- [ ] **权重排序**: 在 `search` SQL 中加入 `ORDER BY CAST(freq AS INTEGER) DESC`
- [ ] **状态更新**: 将已验证特性的 `status` 更新为 `implemented`
- [ ] **环境清理**: 确保 `.gitignore` 不会屏蔽 `commands/` 下的 JSON 文件

## 4. 验证与交付 (Verification)
- [ ] 运行 `python3 commands/lxc/main.py features` 验证状态
- [ ] 运行 `python3 commands/lxc/main.py search` 验证排序
