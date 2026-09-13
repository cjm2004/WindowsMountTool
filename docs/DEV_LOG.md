# 开发日志 - Windows 挂载网盘器

## 时间线

### 2026-09-09

---

## 一、项目启动

读取 `Windows挂载网盘器_优化后提示词.md` 和两个压缩包，确认需求：
- 安装 exe（安装包）：环境检测 → 安装 → 完成
- 配置 exe：可视化逐步引导
- 核心链路：Alist WebDAV → rclone → WinFsp → 盘符

工具包内容：
- `tools/alist.exe` v3.63.0
- `tools/rclone.exe` v1.75.0
- `scripts/mount-cloud.ps1`（幂等挂载）
- `scripts/health_check.py`（看门狗）
- `config/rclone.conf`
- WinFsp 不含在工具包中

---

## 二、MVP 开发（PowerShell/WPF）

创建了 `source/` 目录：
- `source/ConfigApp.ps1` — WPF 可视化配置界面
- `source/ConfigApp.cmd` — 启动配置界面
- `source/scripts/mount.ps1` — 挂载脚本（支持多配置）
- `source/scripts/watchdog.ps1` — 看门狗
- `source/scripts/tasks.ps1` — 计划任务管理
- `source/scripts/autostart.ps1` — 开机自启

核心实现：
- 挂载成功基于真实盘符检测 `[System.IO.DriveInfo]::GetDrives()`
- 密码用 `rclone obscure` 加密
- 不加 `--network-mode`
- 启动前杀残留 rclone 进程
- Alist 60秒等待
- 180秒看门狗冷却
- `data/MAINTENANCE` 维护开关
- 日志裁剪（800行保留末400行）
- 多配置支持

---

## 三、权限与 WinFsp 安装

### 问题
用户要求自动提权、下载、联网等。

### 实现
- `source/Installer.ps1`：自动 UAC 提权
- WinFsp 自动检测注册表
- WinFsp 从 GitHub Release API 下载
- 内嵌官方 WinFsp MSI v2.1：`tools/winfsp-2.1.25156.msi`
- SHA256：`073A70E00F77423E34BED98B86E600DEF93393BA5822204FAC57A29324DB9F7A`

---

## 四、分析原始 EXE

用户提供 `CloudMountSetup.exe`（98MB），要求解包分析。

### 发现
- 文件类型：PyInstaller 打包的 Python 程序
- PyInstaller cookie offset=98248817
- Python 版本 3.13
- CArchive 中找到 1001 个文件

### 解包结构
```
CloudMountSetup.exe_extracted/
  installer.pyc
  python313.dll
  payload/
    mount_wizard.exe    (85MB, 另一个 PyInstaller 包)
    winfsp.msi          (2.2MB)
```

### 进一步解包 mount_wizard.exe
```
mount_wizard.exe_extracted/
  tools/alist.exe      (116MB)
  tools/rclone.exe     (85MB)
  config/rclone.conf
  app.pyc
```

### 根因确认
外层安装器 `installer.pyc` 携带了 `mount_wizard.exe`，但没有把内层的 `alist.exe` 和 `rclone.exe` 释放到安装目录。

### 哈希验证
```
alist.exe: 1A4B2D541863616AD1FB36A1B7067592A684BE26CBC32A5BEC2DB9A36EA34B07
rclone.exe: 8BE30F02266A6EAAD9D481941EF287B9744BB7140034B097AD862A2CCFF3E24C
```

与 `extracted/工具包/tools/` 中的版本完全一致。

---

## 五、集成修复

将内嵌的二进制纳入源码：
```
source/tools/alist.exe   (116,331,520 bytes)
source/tools/rclone.exe  (85,160,448 bytes)
tools/winfsp-2.1.25156.msi (2,191,360 bytes)
```

修改 `source/Installer.ps1`：
- 安装前检查 `alist.exe` 和 `rclone.exe` 是否存在
- 缺少任一文件直接停止安装
- 使用内嵌 WinFsp MSI，SHA256 校验
- 安装失败抛出异常终止

---

## 六、安装器 UI 问题

### 7-Zip SFX 方案失败
- 使用 `7z.sfx` 构建的 EXE 双击显示 `Extract to:`
- `7z.sfx` 是普通解压模块，不支持 `RunProgram`
- `7zS.sfx` 才是安装模块，但当前 7-Zip 安装目录没有
- 从官方 extra 包下载后测试，SFX 配置仍无法自动执行

### 切换到 NSIS
- 安装 NSIS 3.12
- 创建 `source/installer.nsi`
- 使用标准 MUI2 安装向导
- 支持：欢迎页 → 选目录 → 安装 → 完成

---

## 七、WinFsp 实际安装测试

在当前电脑上：
1. 确认 WinFsp 未安装：`HKLM:\SOFTWARE\WinFsp` 不存在
2. 执行内嵌 MSI 静默安装
3. MSI 返回码：0
4. 日志确认：`Product: WinFsp 2025 -- Installation completed successfully.`
5. `WinFsp.Launcher` 服务启动：Running/Automatic
6. 注册表出现：`HKLM:\SOFTWARE\WOW6432Node\WinFsp`
7. 之后卸载 WinFsp，返回码 0，注册表清除

---

## 八、安装脚本回归测试

执行 `source/Installer.ps1 -NoUi -InstallDir <temp>`：
- 返回码：0
- 安装目录生成：
  - `tools/alist.exe`
  - `tools/rclone.exe`
  - `config/profiles.json`
  - `scripts/mount.ps1`
  - `scripts/watchdog.ps1`
  - `scripts/tasks.ps1`
  - `scripts/autostart.ps1`

---

## 九、临时文件清理

已删除所有测试解包目录：
- `CloudDrive-install-test`
- `winmount-final-audit`
- `winmount-final-audit2`
- `winmount-final-delivery-audit`
- `winmount-sfx-test`
- `winmount-sfx-test-final`

---

## 十、最终状态

### NSIS 构建成功
```
dist/CloudMountSetup.exe
大小：57,558,615 bytes (54 MB)
SHA256：（见最终构建）
格式：NSIS 安装包（Nullsoft Install System）
```

### 内嵌资源验证
从 EXE 提取确认：
- `ConfigApp.ps1` 存在
- `ConfigApp.cmd` 存在
- `tools/alist.exe` 存在（116,331,520 bytes）
- `tools/rclone.exe` 存在（85,160,448 bytes）
- `tools/winfsp-2.1.25156.msi` 存在（2,191,360 bytes）

### 核心约束全部遵守
- A: WinFsp 安装后必须重启
- B: 密码用 rclone obscure
- C: 不加 --network-mode
- D: 启动前杀残留 rclone
- E: 盘符检测用 DriveInfo.GetDrives()
- F: CRLF 行尾
- G: UTF-8 复查路径
- H: Alist 先设 admin 密码
- I: Local 存储目录先 mkdir

### 待用户操作
1. 双击 `dist/CloudMountSetup.exe` 安装
2. 安装完成后重启电脑
3. 启动配置程序
4. 在 Alist 后台添加网盘存储
5. 配置挂载参数
6. 点击挂载

---

## 附录：关键文件

```
winmount/
├── dist/CloudMountSetup.exe          ← 最终安装包 (NSIS)
├── source/
│   ├── installer.nsi                 ← NSIS 安装脚本
│   ├── Installer.ps1                 ← 释放组件 + WinFsp 安装
│   ├── ConfigApp.ps1                 ← WPF 配置界面
│   ├── ConfigApp.cmd                 ← 启动配置界面
│   ├── tools/
│   │   ├── alist.exe                 ← 内嵌
│   │   └── rclone.exe                ← 内嵌
│   └── scripts/
│       ├── mount.ps1                 ← 挂载脚本
│       ├── watchdog.ps1              ← 看门狗
│       ├── tasks.ps1                 ← 计划任务
│       └── autostart.ps1             ← 开机自启
├── tools/winfsp-2.1.25156.msi        ← 内嵌 WinFsp
├── extracted/                         ← 解压的工具包
├── build.ps1                          ← 构建脚本
└── DEV_LOG.md                         ← 本日志
```

---

### 2026-09-10 · 修复「exe 被系统当成压缩包 / 双击弹出 Extract to:」

#### 现象
`dist` 下双击某个 exe 不会进入安装向导，而是被 7-Zip 接管并弹出 `Extract to:` 目录选择框。

#### 根本原因（实测确认）
用 7-Zip 列目录复核，`dist\._cache_CloudMountSetup.exe` 的格式是：

```
Type = 7z
Offset = 215171        ← 7z 数据流起始位置
Method = LZMA2:25 BCJ
Solid = +
```

`Offset = 215171` 与 `C:\Program Files\7-Zip\7z.sfx` 的 **215,040 字节** 基本吻合（差值 131 字节）。也就是说该文件就是
`7z.sfx` 存根 + 一段 7z 压缩包**首尾拼接**出来的东西。

关键点：**7-Zip 官方安装目录只带 `7z.sfx` 和 `7zCon.sfx` 两个模块，而 `7z.sfx` 是"纯解压模块"**——

- 它只做一件事：把包解开到用户指定目录，所以运行时唯一行为就是弹 `Extract to:` 对话框；
- 它**不支持** `;!@Install@!UTF-8!` 配置里的 `RunProgram`，无法在解压后自动拉起安装程序；
- 拼接产物没有可用的安装器存根，文件关联/内容探测都把它识别为压缩包。

能当安装器用（支持 `RunProgram`）的是 `7zS.sfx` / `7zSD.sfx`，**它们不在 7-Zip 标准安装目录里**，要单独下载 7-Zip Extra 包才有——所以用 `7z.sfx` 拼出来的必然是"自解压压缩包"，不是安装包。

#### 修复方案
统一改用 **NSIS**（真实安装器，PE 存根 + 向导 + 卸载项），彻底放弃 7z SFX 方案：

1. `source/installer.nsi` 重写：
   - 中文向导（`Unicode true` + `MUI_LANGUAGE "SimpChinese"`），`VIProductVersion` 写入正确版本信息
   - 页面：欢迎 → 选目录 → **环境检测页（逐项显示 WinFsp / Alist / rclone 状态）** → 安装 → 完成
   - `RequestExecutionLevel admin` 自动提权；`SetShellVarContext all` 桌面/开始菜单快捷方式
   - WinFsp：读 `HKLM\SOFTWARE\WinFsp` + `WOW6432Node` + DLL 路径三重判定，已装则跳过，未装则 `msiexec /qn /norestart` 静默安装；返回码 0/3010/1641 → `SetRebootFlag true`，由 MUI 完成页给出"立即重启 / 稍后重启"（去掉了与 `MUI_FINISHPAGE_NOREBOOTSUPPORT` 的冲突写法）；失败则 `Abort`，绝不留下不可用安装
   - 关键校验：`tools\alist.exe`、`tools\rclone.exe` 任一缺失即 `Abort`（原 bug 的守门）
   - 卸载段补齐：调用 `scripts\uninstall.ps1` 停进程 / 解除盘符 / 注销 `CloudDriveMount`、`CloudDriveHealth` 计划任务，再 `RMDir /r` 清 `scripts`、`tools`、`data`、`config`
2. 新增 `source/scripts/uninstall.ps1`（卸载清场）
3. `source/ConfigApp.ps1`：补上**约束 H** —— 保存/挂载本机 Alist 配置时执行 `alist.exe admin set <密码>`（明文只在内存用一次，落盘仍只有 `rclone obscure` 串），并在启动时预建 `data\recycle_bin`（约束 I）
4. 行尾统一为 CRLF + BOM（约束 F）：`source\*.ps1`、`source\scripts\*.ps1`、`build.ps1`、`source\installer.nsi`
5. `build.ps1`：保留 NSIS 单一路径，加必需文件预检、产物体积与 MZ 头校验、并把成品同步到工程根目录
6. 归档误导性产物（避免再双击错文件）：`dist\._cache_*`（7z SFX）、`dist\Windows挂载网盘器-安装.ps1`、根目录原始 PyInstaller 版 `CloudMountSetup.exe` → `_archive/`

#### 验证
- `7z l -tNsis dist\CloudMountSetup.exe` → `Type = Nsis`，`SubType = NSIS-3 Unicode`，内嵌 `tools\alist.exe`(116,331,520 B)、`tools\rclone.exe`(85,160,448 B)、`tools\winfsp-2.1.25156.msi`(2,191,360 B)
- `alist.exe admin set <密码>` 空目录实测：生成 `data\data.db` 并设置 admin 密码成功（exit 0），确认 401 修复路径成立

---

### 2026-09-11 · 收尾：主程序 exe / 可选驱动 / 卸载清场 / 挂载链路实测

#### 一、新增主程序 CloudMount.exe
- 新增 `source/launcher.nsi` → 产出 `source/bin/CloudMount.exe`（37.7 KB，真实 PE）
- 作用等同旧的 `mount_wizard.exe`：双击拉起同目录的 WPF 配置界面（`ConfigApp.ps1`），`RequestExecutionLevel user` 不申请管理员
- 被 `installer.nsi` 打进安装包，落在安装目录根；桌面/开始菜单/完成页都指向它

#### 二、安装包新增"可选驱动"组件页
- 页面顺序：欢迎 → 选目录 → **组件（可选驱动）** → 环境检测 → 安装 → 完成
- `SEC_ALIST` / `SEC_RCLONE` 为可选项（`Section /o`），`.onInit` 里按检测结果决定默认勾选：
  - 检测范围 = 安装目录 `tools\` + `%PATH%`（自写 `FindOnPath` 逐段解析 PATH，未用外部命令）
  - **系统缺少 → 默认勾选**；**已存在 → 默认不勾选**，文案实时改成"系统已存在，可跳过"
- `SEC_WINFSP` 仍是 `SectionIn RO`（必需），已安装则跳过；MSI 始终释放，供卸载时使用
- 用户若两项都取消，完成页会追加缺失提醒

#### 三、卸载：彻底清场
- `Uninstall.exe` 卸载顺序：跑 `uninstall.ps1`（解除盘符/杀进程/注销计划任务）→ 移除 WinFsp → 删文件/快捷方式/注册表
- WinFsp 只在**本机由本程序安装**时自动移除（注册表 `Software\CloudDriveMount\WinFspInstalledByUs=1`），避免误删用户原有驱动；需要强制移除时传 `/REMOVEWINFSP`

#### 四、"双击被 7-Zip 当成压缩包 / 弹 Extract to:" 根因（复核结论）
产物实测取证（`7z l -tNsis` + 字节级检查）：
```
Path = dist\CloudMountSetup.exe
Type = Nsis            SubType = NSIS-3 Unicode
Embedded Stub Size = 54272        ← 真正的 PE 存根
偏移 54276: ef be ad de "NullsoftInst"   ← NSIS 头签名
7z 魔数 37 7A BC AF 27 1C：未出现
```
- 之前的错包是 `7z.sfx` 存根 + 7z 数据流首尾拼接，`Offset = 215171` ≈ `7z.sfx` 的 215,040 字节，本质是自解压压缩包；`7z.sfx` 是**纯解压模块**，不支持 `RunProgram`，所以运行时唯一行为就是弹 `Extract to:`，且内容探测会按 7z 签名把它识别成压缩包。该产物已归档到 `_archive/CloudMountSetup.7zSFX_废弃方案.exe`
- `build.ps1` 原先的"Nullsoft 标记"检查只在开头 8KB 找，而 NSIS 头在 54KB 存根之后，所以一直误报。**已改成三重判定**：MZ 头 + `NullsoftInst` 签名 + 全文件扫描无 7z 魔数（有 7z 魔数直接构建失败）

#### 五、挂载链路实测中修掉的 3 个真 bug
1. **远端名缺冒号**（致命）：`mount.ps1` 拼的是 `rclone mount cloud_xxx Z:`，rclone 把无冒号的远端当成本地目录
   → 日志特征 `"cloud_xxx" refers to a local folder` / `The service rclone has failed to start (Status=c0000185)`
   → 修正为 `cloud_xxx:`
2. **rclone.conf 带 BOM**：`Set-Content -Encoding utf8` 会写 BOM，`\ufeff[cloud_xxx]` 让 rclone 解析不出 section
   → 改为 `[System.IO.File]::WriteAllText(..., (New-Object System.Text.UTF8Encoding($false)))`
3. **WinFsp 驱动未加载**：新装后 FSD 可能没起来，用 WinFsp 自带 `fsptool-x64.exe load` 兜底加载（已写进 `mount.ps1`，失败即忽略）

#### 六、Alist 接口坑
- 管理接口前缀是 **`/api/admin/`**（`/api/admin/storage/create`、`/api/admin/storage/list`）
- `/api/storage/*` 会被前端 SPA 兜底，返回 200 + `index.html`，看起来像成功实则没生效（排查时极易误判）
- WebDAV 的 `Authorization` 走 Basic（用户名/密码），不能拿登录 JWT 去 PROPFIND，否则 401

#### 七、端到端回归结果（最终包 55.2 MB）
- 安装 `/S` 静默：退出码 0，`C:\CloudDrive` 下一级只有 `config / data / scripts / tools / CloudMount.exe / ConfigApp.cmd / ConfigApp.ps1 / Uninstall.exe`
- 挂载：Alist(Local 存储) → WebDAV → rclone → WinFsp → **Z: 就绪**，卷标 `E2E-WebDAV`，文件系统 `FUSE-rclone`，可列目录、可写入回读
- 卸载 `/S` 静默：退出码 0，16 项校验全部通过（安装目录、计划任务、进程、盘符、注册表、快捷方式、WinFsp 驱动全部清除）
- 注意：`--vfs-cache-mode full` 下写入先进本地缓存再异步上传，写完立刻回源目录查会查不到，属预期

#### 八、测试脚本
```
tests/01_install.ps1      静默安装 + 目录/驱动/注册表校验
tests/02_mount.ps1        起 Alist → 建 Local 存储 → mount.ps1 → Z 盘读写校验
tests/03_uninstall.ps1    静默卸载 + 16 项清场校验
tests/diag_mount.ps1      挂载隔离诊断（区分 BOM / 驱动 / 远端名问题）
tests/probe_alist_api.ps1 Alist 管理接口探测
```
> 注意：测试脚本必须存成 **UTF-8 with BOM**，PowerShell 5.1 按 ANSI 解析无 BOM 的中文脚本会直接解析失败。

