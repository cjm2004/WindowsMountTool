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
<img width="1352" height="940" alt="image" src="https://github.com/user-attachments/assets/196323ab-c494-4d0e-8ca4-dfdfaeccdb72" />
<img width="716" height="520" alt="image" src="https://github.com/user-attachments/assets/2530b419-8665-4663-a65f-93024df14919" />

## 下载和运行

建议从 GitHub Releases 下载正式版本。源码仓库与发布附件分开管理：本仓库只提交源码、测试脚本、文档、配置模板和公开资源；正式程序及 Alist、rclone、WinFsp 等运行依赖不放入 Git 历史，而是作为 Release 附件提供。

1. 从 [Releases](https://github.com/cjm2004/WindowsMountTool/releases) 下载 `CloudMountSetup.exe`。
2. 以普通方式启动安装器，按提示选择安装目录。
3. 如果安装 WinFsp 后系统提示重启，请先重启 Windows。
4. 启动安装后的“云盘挂载向导”。
5. 按向导配置 WebDAV 或 Alist/OpenList 连接。
6. 选择未被占用的盘符后执行挂载。

也可以直接运行 `mount_wizard.exe` 进行配置，但完整安装流程建议使用安装器。

## 项目结构

```text
winmount/
├─ .gitignore                    # Git 忽略规则：排除本地配置、缓存、日志和二进制构建产物
├─ LICENSE                       # 本项目 MIT 许可证
├─ README.md                     # 项目介绍、构建、测试和安全说明
├─ ui_theme.py                   # 公共 UI 主题模块
├─ py_src/                       # 安装器 Python 源码与 PyInstaller 配置
│  ├─ installer.py               # 安装器主程序
│  ├─ uninstaller.py             # 卸载器程序
│  ├─ test_ui.py                 # 安装器界面辅助测试
│  ├─ ui_theme.py                # 安装器使用的主题模块
│  ├─ CloudMountSetup.spec       # 安装器打包配置
│  ├─ uninstall.spec             # 卸载器打包配置
│  ├─ icon.ico                   # 安装器图标
│  └─ payload/
│     └─ THIRD_PARTY_NOTICES.txt # 随发布版本提供的第三方组件声明
├─ py_src_wizard/                # 配置向导 Python 源码与 PyInstaller 配置
│  ├─ app.py                     # 配置向导主程序
│  ├─ ui_theme.py                # 向导使用的主题模块
│  ├─ mount_wizard.spec          # 向导打包配置
│  ├─ icon.ico                   # 向导图标
│  └─ payload/source/
│     ├─ assets/                 # 关于页公开资源（捐赠二维码）
│     └─ config/rclone.conf      # 不含真实密码的 rclone 配置模板
├─ tests/                        # 安装、挂载、卸载和接口诊断脚本
│  ├─ 01_install.ps1
│  ├─ 02_mount.ps1
│  ├─ 03_uninstall.ps1
│  ├─ comprehensive_test.ps1
│  ├─ full_functional_test.ps1
│  ├─ diag_mount.ps1
│  └─ probe_alist_api.ps1
└─ docs/                         # 项目文档、开发记录和目录说明
   ├─ DEV_LOG.md
   ├─ FIXES_PRIORITY.md
   ├─ HOW_TO_ADD_ICON.md
   ├─ ICON_SOLUTION.md
   ├─ QA_REPORT.md
   ├─ Windows挂载网盘器_优化后提示词.md
   ├─ 目录说明.md
   ├─ 项目文件保留与清理审查报告_2026-09-13.md
   └─ replace_icon.txt
```

以下内容属于本地开发或发布环境，**不在本 GitHub 源码仓库中**：

- 根目录的 `CloudMountSetup.exe`、`mount_wizard.exe` 以及其他构建输出；
- `runtime/`、`data/`、`config/`、`profiles.json` 和运行日志；
- `_archive/`、`*_extracted/`、`build/`、`dist/` 等历史归档、解包目录和构建缓存；
- `tools/` 下的本地构建辅助工具及 WinFsp 安装包。

更详细的本地目录边界说明请参阅 [`docs/目录说明.md`](docs/目录说明.md)。

## 从源码构建

### 环境

- Windows 10/11 x64
- Python 3.12 或兼容版本，并包含 Tkinter
- PyInstaller
- 可选：已安装 WinFsp，用于真实挂载回归测试

当前构建链分为两步，必须先构建配置向导，再更新安装器 payload。请注意：源码仓库不包含 Alist、rclone、WinFsp 和已构建的向导 EXE；从源码构建前，需要从 [v1.0.0 Release](https://github.com/cjm2004/WindowsMountTool/releases/tag/v1.0.0) 获取并按现有 `.spec` 文件要求放置这些运行依赖。

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

发布版本随附 `THIRD_PARTY_NOTICES.txt`。源码仓库中的同名文件位于 `py_src/payload/`；Release 附件中也单独提供该文件。完整许可证和再分发条件以各组件官方项目为准。

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
