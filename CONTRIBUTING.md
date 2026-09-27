# Contributing to TavernLab-HSsim

Thank you for helping improve TavernLab-HSsim. The project is a local
Hearthstone simulator and AI/agent experimentation platform built on top of
[HearthSim Fireplace](https://github.com/jleclanche/fireplace). Please keep
the upstream attribution and the existing AGPL-3.0-or-later licensing notices
when changing code that comes from Fireplace.

The repository and product are named **TavernLab-HSsim**. The Python package
and import paths remain `fireplace`. Use `tavernlab-web` to start the installed
web app; `fireplace-web` remains available for compatibility.

## 开始贡献

感谢你为 TavernLab-HSsim 做贡献。本项目是在
[HearthSim Fireplace](https://github.com/jleclanche/fireplace) 基础上开发的
本地《炉石传说》模拟与 AI/Agent 实验项目。修改 Fireplace 来源的代码时，
请保留上游归属说明和 AGPL-3.0-or-later 许可信息。

仓库和产品名称是 **TavernLab-HSsim**。为了兼容上游代码和已有用户，Python
包名及导入路径仍然是 `fireplace`。安装后可以用 `tavernlab-web` 启动 Web
应用；`fireplace-web` 作为兼容入口继续保留。

## Development setup / 开发环境

You need Python 3.10 or newer, Git, and Git LFS. `CardDefs.xml` is tracked by
Git LFS; make sure it is downloaded before running tests or the application.

需要 Python 3.10 或更新版本、Git 和 Git LFS。`CardDefs.xml` 使用 Git LFS
管理；运行测试或应用前，请确认文件已经下载，而不是只留下 LFS 指针文件。

```bash
git lfs install
git clone https://github.com/Hanqi-b/TavernLab-HSsim.git
cd TavernLab-HSsim
git lfs pull

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
```

On Windows, create the virtual environment with `py -3.10 -m venv venv` and
activate it with `venv\\Scripts\\Activate.ps1`. The remaining `python -m pip`
commands are the same.

Windows 用户可以用 `py -3.10 -m venv venv` 创建环境，再用
`venv\\Scripts\\Activate.ps1` 激活；其余 `python -m pip` 命令相同。

## Testing and local checks / 测试与本地检查

Run the complete Python test suite from the repository root:

```bash
PYTHONPATH=tests:. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests
```

从仓库根目录运行完整 Python 测试：

```bash
PYTHONPATH=tests:. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests
```

GitHub Actions also verifies that Git LFS downloaded `CardDefs.xml` and that
the package can be built as a wheel. Before opening a pull request, run:

```bash
test "$(wc -c < fireplace/cards/CardDefs.xml)" -gt 1000000
python -m pip wheel --no-deps --wheel-dir /tmp/tavernlab-wheels .
```

GitHub Actions 还会确认 Git LFS 已下载 `CardDefs.xml`，并检查能否构建 wheel。
提交 PR 前请运行：

```bash
test "$(wc -c < fireplace/cards/CardDefs.xml)" -gt 1000000
python -m pip wheel --no-deps --wheel-dir /tmp/tavernlab-wheels .
```

Useful focused checks include:

```bash
PYTHONPATH=tests:. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_controller.py tests/test_replay.py
python tests/full_game.py
```

常用的针对性检查包括：

```bash
PYTHONPATH=tests:. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_controller.py tests/test_replay.py
python tests/full_game.py
```

For a manual browser check, start the loopback server and open the printed URL:

```bash
python -m fireplace.web_gui --seed 7 --port 8765
```

手动检查浏览器界面时，启动本机回环服务器并打开终端输出的 URL：

```bash
python -m fireplace.web_gui --seed 7 --port 8765
```

The server is local-only by design. Stop it with `Ctrl+C`. Do not commit
account data, generated logs, or local cache files. Commit screenshots only when
they are intentional documentation assets.

服务器按设计只监听本机回环地址，用 `Ctrl+C` 停止。请不要提交账号数据、
生成的对局日志或本地缓存文件；截图只有在明确作为文档资源时才提交。

## Making changes / 编写代码

- Keep Python support at 3.10+ and avoid introducing a newer-only syntax or
  library without documenting the reason.
- Keep formatting changes separate from behavior changes where practical.
- Add or update focused tests for behavior changes. For engine and card
  changes, prefer tests that describe the observable game rule.
- Treat `CardDefs.xml` as an LFS-managed data file. Do not replace it with a
  pointer, generated copy, or unrelated card-data version.
- Preserve hidden-information boundaries in observations and browser/API
  responses. Opponent hands, pending choices, and private card data must not
  be exposed to the other player.
- Keep the `fireplace` package name and compatibility entry points unless a
  change explicitly includes a migration plan.

提交代码时请遵循以下原则：

- Python 支持范围保持为 3.10+；如果必须使用更新版本才有的语法或库，
  请在变更说明中解释原因。
- 可以的话，把纯格式调整与功能改动分开。
- 功能行为变化要补充或更新针对性测试；引擎和卡牌改动优先用能描述实际
  游戏规则的测试覆盖。
- `CardDefs.xml` 是由 LFS 管理的数据文件，不要把它替换成指针文件、生成
  文件或无关版本的卡牌数据。
- 保持 observation 和浏览器/API 返回值的隐藏信息边界；不能把对手手牌、
  待处理选择或私有卡牌数据泄露给另一位玩家。
- 除非变更同时包含迁移方案，否则保留 `fireplace` 包名和兼容入口。

## Commits and pull requests / 提交与合并请求

Create a branch from `master`, keep each commit focused, and describe the
user-visible effect in the pull request. Include the commands you ran and any
environment-specific limitation. Documentation-only changes should still
state which links or commands were checked.

从 `master` 创建分支，每个提交保持单一目的，并在 PR 中说明用户能看到的
变化。请列出运行过的命令和环境限制；即使只是文档改动，也请说明检查过的
链接或命令。

Before submitting, check the diff for accidental generated files and confirm
that `git diff --check` is clean. If a change affects the local web GUI, include
the relevant manual or automated browser check in the PR description.

提交前请检查 diff 中没有意外生成的文件，并确认 `git diff --check` 没有输出。
如果改动影响本地 Web 界面，请在 PR 描述中列出对应的手动或自动浏览器检查。

## Issues and questions / 问题反馈

Use the [TavernLab-HSsim issue tracker](https://github.com/Hanqi-b/TavernLab-HSsim/issues)
for reproducible bugs and feature proposals. Include the commit or release,
Python version, operating system, exact command, and a short reproduction. Do
not include passwords, account data, or private logs.

可复现的 Bug 和功能建议请提交到
[TavernLab-HSsim Issue 区](https://github.com/Hanqi-b/TavernLab-HSsim/issues)。
请附上提交或 Release、Python 版本、操作系统、完整命令和简短复现步骤；不要
上传密码、账号数据或包含隐私的日志。

For questions about inherited engine behavior, consult the upstream
[Fireplace repository](https://github.com/jleclanche/fireplace) as well as this
repository's tests and documentation. TavernLab-specific changes should be
reported in the TavernLab-HSsim tracker so they can be maintained here.

对于继承自上游引擎的行为，可以同时参考上游
[Fireplace 仓库](https://github.com/jleclanche/fireplace)以及本仓库的测试和文档。
TavernLab 自身的改动请提交到 TavernLab-HSsim Issue 区，方便在本项目中维护。

## License and attribution / 许可与归属

TavernLab-HSsim is distributed under the
[GNU AGPL-3.0-or-later](LICENSE). It retains the contribution history and
attribution of HearthSim Fireplace while adding current TavernLab-HSsim
maintenance. By submitting a contribution, you agree that it may be
distributed under the applicable project license.

TavernLab-HSsim 按
[GNU AGPL-3.0-or-later](LICENSE) 发布。项目保留 HearthSim Fireplace 的贡献
历史和归属信息，同时由 TavernLab-HSsim 当前维护者继续维护。提交贡献即表示
同意按照项目适用许可分发该贡献。
