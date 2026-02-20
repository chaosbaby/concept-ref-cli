# Plan: Shell Completion Manager for ac CLI

## Phase 1: Implement `completion` Command
- [x] 在 `commands/ac/main.py` 中添加 `completion` 命令组。
- [x] 实现 `completion show` 子命令，根据用户的 Shell 类型生成补全脚本。
- [x] 实现 `completion install` 子命令，自动将补全脚本添加到用户的 Shell 配置文件中（如 `.bashrc`, `.zshrc`）。

## Phase 2: Implement Dynamic Completers
- [x] 为 `search --source` 参数实现动态补全函数，从数据库中获取所有 `source`。
- [x] 为 `config set/get` 的 `key` 参数实现动态补全函数 (已部分实现，需确认)。
- [x] 将动态补全函数应用到 `click` 的参数中。

## Phase 3: Verification
- [x] 手动测试 `completion show` 生成的脚本。
- [x] 测试 `completion install` 是否能正确更新配置文件。
- [x] 在 Shell 中重新加载配置后，测试 `ac search --source <TAB>` 是否能触发动态补全。
