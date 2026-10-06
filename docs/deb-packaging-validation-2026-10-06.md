# TavernLab Debian 安装包验证记录

验证日期：2026-10-06。目标：Ubuntu 22.04、amd64、系统 Python 3.10。

产物：`dist/tavernlab_0.1.0~alpha1-1_amd64.deb`，30,317,768 字节。
SHA256：`032b5f52f3266923f213ea28a706e1775e27f712603b9f1115f2f1b7c64fa6d7`。
校验文件为 `dist/SHA256SUMS`；在 `dist` 目录执行 `sha256sum -c SHA256SUMS`。

## 验证结果

- 140 项现有网页、卡牌资源、账号、竞技场历史数据及回放兼容测试通过；8 项桌面启动器测试通过。
- Ubuntu 22.04 容器中的 `dh-virtualenv` 构建成功；调用者 UID 构建、输出权限和临时目录清理正常。
- 在校验过官方 Ubuntu Base 22.04.5 根文件系统的独立容器中安装，使用普通用户从 `/tmp` 启动已安装程序。
- 安装资源、HTML/JS/CSS/WEBP 响应、通灵学园卡牌及质量报告标签检查通过。
- 临时账号、登录会话和卡组在服务重启后保留；重新安装后，已有测试账号数据库 SHA256 不变且仍可登录。
- 清除安装包后，测试账号数据库仍存在，SHA256 保持不变。
- 使用提取后的私有环境和临时 systemd 用户服务验证启动、浏览器地址、重复启动复用 PID、状态查询、SIGINT 停止和端口占用拒绝；测试服务已清理。
- 归档清单包含 2,858 个文件，安装所有权为 root；包含桌面入口、用户服务、pixmaps 图标和质量 CSV。
- 安装后的规则代码签名与源码一致：`5dc890666bc2782a0f7dca5a1d04d23c9260f7090cca6f3001bd14002988e048`。

## 使用与重新验证

安装、启动、停止和构建方法见 [打包说明](../packaging/README.md)。
私有环境包含 `hearthstone==9.21.1`、`hearthstone-data==251952.1` 及固定版本的依赖。
其他 Python 小版本和发行版需要单独调整构建配置并验证。

安装检查脚本：`tests/deb_install_smoke.py`。它使用临时状态目录，需以普通用户运行。
当前机器可使用已有构建工具镜像重新构建：

```bash
TAVERNLAB_DEB_BASE_IMAGE=tavernlab-deb-tools:22.04 ./packaging/build-deb.sh
```

最终归档使用 `dpkg-deb` 完成图标目录调整和校验和更新；图标路径与当前 `debian/rules` 一致。
