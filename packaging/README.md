# Ubuntu 22.04 package

## 安装与日常使用

在项目根目录运行：

```bash
sudo apt install ./dist/tavernlab_0.1.0~alpha1-3_amd64.deb
```

安装后，从应用菜单打开 **TavernLab-HSsim**，启动器会打开本机浏览器界面。
重复点击会复用正在运行的服务。关闭浏览器后服务仍会运行；可使用桌面入口的
“Stop TavernLab-HSsim”操作，或运行 `tavernlab --stop` 停止服务。
`tavernlab --status` 查看服务状态，`journalctl --user -u tavernlab.service` 查看日志。
如果 8765 端口被其他程序占用，启动器会报错，不会打开其他程序的页面。

账号、卡组和对局数据继续保存在 `~/.local/state/fireplace/`（或已有的 XDG 状态目录）。
卸载不会删除这些个人数据。升级前先运行 `tavernlab --stop`，安装新版后重新打开应用，
确保服务加载完整的新版本代码。这个安装包针对 Ubuntu 22.04 / Python 3.10 / amd64；
其他发行版和 Python 小版本需要调整构建配置并重新验证。

桌面服务使用 systemd 用户会话的环境。如果原来的启动脚本设置了自定义
`TAVERNLAB_*` 或 `FIREPLACE_*` 存储路径，可使用 `systemctl --user edit tavernlab.service`
添加相应的 `[Service]` / `Environment=变量名=路径`，或继续通过 `tavernlab-web` 前台启动。

Codex 连接是可选功能。安装包不包含 Codex CLI、App Server SDK 或其他 Codex
运行时；普通启动、AI/MCTS 对局和非 Codex 对局不会启动 Codex 子进程。需要使用
Codex 时，请先按照[官方 CLI 文档](https://learn.chatgpt.com/docs/codex/cli)
自行安装 CLI。如果本机 CLI 还没有账号，请在终端运行 `codex login` 并完成官方
浏览器流程；安装包不会替你下载或安装 CLI。然后在游戏中选择 Codex 座位，先按
面板中的“检查 CLI”读取已有 CLI 登录，再按“测试连接”验证模型。面板里的
“登录本机 CLI 账号”也会写入同一个 CLI 账号，用于检查发现尚未登录时的显式登录。

游戏的代理和连接设置保存在游戏状态目录：默认是
`$XDG_STATE_HOME/fireplace/codex`（未设置时为 `~/.local/state/fireplace/codex`）。
设置文件会以 `0600` 权限保存。默认从 `CODEX_HOME`（若设置）或普通的 `~/.codex`
读取 CLI 身份验证，不会把身份验证文件复制到游戏状态目录；面板中的“退出本机 CLI
账号”也会退出这个本机 CLI 账号。

如需独立的 Codex 身份验证配置，可在启动服务前设置 `TAVERNLAB_CODEX_HOME`；显式
注入的 Codex home 也使用独立配置。它不会改变游戏状态目录中的代理和设置，独立模式
退出时只影响该独立配置。面板中的代理只接受不带用户名、密码和路径的
`http://` 或 `https://` 地址；留空则沿用服务环境中的代理变量。请不要把代理密码
或账号凭据填入面板。

## Build

The package is built for the Ubuntu 22.04 Python 3.10 runtime.  It installs
the application and its pinned Python dependency closure in
`/opt/venvs/tavernlab`, and therefore an Ubuntu 24.04 host must rebuild the
package for its newer Python minor version instead of reusing this artifact.

The preferred build uses the dedicated Dockerfile and stages only the paths
listed in `source-manifest.txt`.  It does not read the developer virtualenv,
account files, generated game logs, or the unrelated Rust GUI tree.

```bash
./packaging/build-deb.sh
sudo apt install ./dist/tavernlab_0.1.0~alpha1-3_amd64.deb
```

The builder defaults to `ubuntu:22.04`. To use a cached local Ubuntu 22.04
base image, set `TAVERNLAB_DEB_BASE_IMAGE`; for example:

```bash
TAVERNLAB_DEB_BASE_IMAGE=tavernlab-ubuntu-base:22.04 \
  ./packaging/build-deb.sh
```

The script uses Docker's host network by default and forwards configured
`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` (and lowercase equivalents) as build
arguments and as environment variables in the package build container.
Proxy values are not baked into the image. Override `TAVERNLAB_DOCKER_NETWORK` when a different Docker
network is required.

For a direct Ubuntu 22.04 build, install the `Build-Depends` from
`debian/control`, verify that both card XML files are real XML rather than Git
LFS pointers, and run:

```bash
dpkg-buildpackage -us -uc -b
sudo apt install ../tavernlab_0.1.0~alpha1-3_amd64.deb
```

The installed `tavernlab.service` is a systemd user service.  It is shipped
disabled and is never enabled by package installation; start it explicitly
with `systemctl --user start tavernlab.service` or launch `tavernlab` from the
desktop entry.  `tavernlab-web` remains available for the direct web GUI
entry point and accepts the same command-line flags.

Installed-package verification, in an isolated Ubuntu 22.04 environment with
the package installed and using an unprivileged account:

```bash
cd /tmp
python3 /path/to/tests/deb_install_smoke.py
```

This check uses temporary account/state directories and verifies installed
resources, replay signatures, HTTP routes, and account/deck persistence.
It does not use personal game saves.
