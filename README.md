# WindowsMountTool

Windows 云盘挂载向导：通过 Alist / OpenList、rclone 和 WinFsp，将 WebDAV 或其他支持的网盘服务挂载为 Windows 本地盘符。

> 当前项目主要面向 Windows x64。程序界面保留 Tkinter 桌面向导，并提供暗色/浅色主题、驱动状态检测、多配置管理、挂载/卸载、开机自启、健康检查和关于页面。

## 功能

- 使用 Alist / OpenList 提供本机 WebDAV 服务。
- 使用 rclone 执行 WebDAV 到本地盘符的挂载。
- 使用 WinFsp 提供 Windows 用户态文件系统支持。
- 支持多个挂载配置和盘符管理。
- 支持 WebDAV 直连，以及通过 Alist/OpenList 聚合网盘。
- 支持挂载、卸载、状态检测、日志查看和故障诊断。
- 支持开机自启和健康检查。
- 安装器可释放 Alist、rclone 和 WinFsp 相关资源。
- 配置向导提供暗色/浅色主题和“关于”页面。

## 下载和运行

建议从 GitHub Releases 下载正式版本。仓库源码与发布附件分开管理：源码仓库不直接提交超过 GitHub 普通 Git 文件上限的二进制，正式程序和运行依赖放在 Release 附件中。

1. 下载 `CloudMountSetup.exe`。
2. 以普通方式启动安装器，按提示选择安装目录。
3. 如果安装 WinFsp 后系统提示重启，请先重启 Windows。
4. 启动安装后的“云盘挂载向导”。
5. 按向导配置 WebDAV 或 Alist/OpenList 连接。
6. 选择未被占用的盘符后执行挂载。

也可以直接运行 `mount_wizard.exe` 进行配置，但完整安装流程建议使用安装器。

### 配置安全

- 不要把真实密码、令牌、Cookie 或个人 WebDAV 地址提交到公开仓库。
- rclone 密码应使用内置 `rclone obscure` 处理后再写入配置。
- `runtime\`、`data\`、`config\` 和运行日志可能包含本机信息或个人配置，应妥善保管。
- 挂载成功必须以 Windows 中真实盘符出现为准，不能只依据命令返回码判断。

## 项目结构

```text
winmount/
├─ CloudMountSetup.exe          # 正式安装器
├─ mount_wizard.exe             # 正式配置向导
├─ py_src/                      # 安装器 Python 源码与 PyInstaller 配置
│  ├─ installer.py
│  ├─ uninstaller.py
│  ├─ CloudMountSetup.spec
│  ├─ uninstall.spec
│  └─ payload/                  # 安装器内嵌的向导、WinFsp 和许可声明
├─ py_src_wizard/               # 配置向导 Python 源码与 PyInstaller 配置
│  ├─ app.py
│  ├─ mount_wizard.spec
│  └─ payload/source/           # Alist、rclone、配置模板和关于页资源
├─ tests/                       # 安装、挂载、卸载和接口诊断脚本
├─ docs/                        # 项目文档、开发记录和目录说明
├─ tools/                       # WinFsp 安装包及本地构建辅助工具
└─ logs/                        # 本地构建和测试记录，不建议直接公开
```

更详细的说明请参阅 [`docs/目录说明.md`](docs/目录说明.md) 和 [`docs/项目文件保留与清理审查报告_2026-09-13.md`](docs/项目文件保留与清理审查报告_2026-09-13.md)。

## 从源码构建

### 环境

- Windows 10/11 x64
- Python 3.12 或兼容版本，并包含 Tkinter
- PyInstaller
- 可选：已安装 WinFsp，用于真实挂载回归测试

当前构建链分为两步，必须先构建配置向导，再更新安装器 payload：

```powershell
# 1. 构建配置向导
Set-Location py_src_wizard
python -m PyInstaller --noconfirm mount_wizard.spec

# 2. 将通过测试的配置向导复制到安装器 payload
Copy-Item .\dist\mount_wizard.exe ..\py_src\payload\mount_wizard.exe -Force

# 3. 构建安装器
Set-Location ..\py_src
python -m PyInstaller --noconfirm CloudMountSetup.spec
```

构建输出：

```text
py_src_wizard\dist\mount_wizard.exe
py_src\dist\CloudMountSetup.exe
```

构建后应完成启动、主题切换、关于页、驱动检测、安装、挂载、卸载和正式副本校验，再将验收后的文件用于 Release。

## 测试

测试脚本位于 `tests\`：

- `01_install.ps1`：安装测试
- `02_mount.ps1`：挂载测试
- `03_uninstall.ps1`：卸载测试
- `comprehensive_test.ps1`：综合测试
- `full_functional_test.ps1`：完整功能测试
- `diag_mount.ps1`：挂载诊断
- `probe_alist_api.ps1`：Alist 管理接口探测

部分测试会启动 Alist/rclone、创建计划任务、安装 WinFsp 或操作盘符。请先确认测试目标目录，并不要在包含重要数据的正式安装环境中直接运行。

## 组件和许可证

本项目自身采用 MIT License，详见 [`LICENSE`](LICENSE)。第三方组件仍受各自许可证约束。

本项目使用或再分发以下第三方组件：

- Alist：AGPLv3
- rclone：GPLv3
- WinFsp：GPLv3，含其项目许可例外条款
- Python、Tkinter、PyInstaller、pywinstyles 等构建或运行组件

发布版本随附 `py_src/payload/THIRD_PARTY_NOTICES.txt`。完整许可证和再分发条件以各组件官方项目为准。项目本身的许可证尚未在本仓库中单独声明；如需允许他人修改和再分发，请在发布前选择并添加合适的项目许可证文件。

由于 Alist、rclone 和打包程序体积较大，发布版本中的二进制文件会作为 GitHub Release 附件提供，不全部放入源码提交历史。

## 已知限制

- WinFsp 新安装后可能需要重启 Windows，部分环境还需要重新加载文件系统驱动。
- 真实网盘挂载依赖网络、Alist/OpenList 配置、rclone 配置和 WinFsp 状态。
- 运行配置和日志可能含有本机路径、用户名、接口返回或远端地址，不适合直接公开。
- 当前版本主要针对 Windows x64，尚未提供 Linux/macOS 版本。

## 反馈问题

提交 Issue 时请说明：

- Windows 版本和系统架构
- 软件版本和安装方式
- 使用的远端类型（请隐藏账号、密码、令牌和私人地址）
- 复现步骤
- 相关错误信息或脱敏后的日志片段

请不要上传真实的 `rclone.conf`、Alist 数据目录、个人配置文件或完整运行日志。
