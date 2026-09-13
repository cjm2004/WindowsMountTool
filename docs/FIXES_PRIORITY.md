# 问题修复清单与代码补丁

根据 QA_REPORT.md，按优先级排序的修复方案与具体代码。

---

## 🔴 P0 - 立即修复（阻塞发布）

### P0-1. 密码明文存储 → 必须加密

**文件**：`source/ConfigApp.ps1:44`  
**当前代码**：
```powershell
$p=[pscustomobject]@{
    # ...
    pass=(C Pass).Password  # ← 明文！
    # ...
}
```

**修复后**：
```powershell
# 在 L44 保存按钮 Click 事件内，改为：
try {
    $items=@(ReadProfiles)
    $n=(C Name).Text.Trim()
    if(!$n){throw '请填写名称'}
    
    $plainPass=(C Pass).Password
    $obscuredPass = ''
    if($plainPass) {
        $obscuredPass = Obscure $plainPass  # 调用已有 Obscure 函数
    }
    
    $p=[pscustomobject]@{
        id=[guid]::NewGuid().ToString()
        name=$n
        type=$type.Text
        url=(C Url).Text.Trim()
        user=(C User).Text.Trim()
        pass=$obscuredPass  # ← 改为加密后的值
        drive=$drive.Text.TrimEnd(':')
        path=(C Path).Text.Trim()
        enabled=([bool](C Enabled).IsChecked)
    }
    
    if(IsLocalAlist $p.url){EnsureAlistAdmin $plainPass}
    $items=@($items|? id -ne $p.id)+$p
    SaveProfiles $items
    Refresh
    [Windows.MessageBox]::Show('已保存。密码已加密存储，不会以明文保存。','保存成功')
} catch {
    [Windows.MessageBox]::Show($_.Exception.Message,'保存失败')
}
```

---

### P0-2. rclone.conf BOM 检查防回归

**文件**：`source/scripts/mount.ps1:7`  
**在 WriteAllText 之后立即加校验**：

```powershell
# L7 原代码：
[System.IO.File]::WriteAllText($conf,(($lines -join "`r`n")+"`r`n"),(New-Object System.Text.UTF8Encoding($false)))

# 紧接着加（L8 新增）：
$bytes=[System.IO.File]::ReadAllBytes($conf)
if($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF){
    Log "CRITICAL: rclone.conf has BOM, rclone will fail to parse sections"
    exit 1
}
```

---

## 🟡 P1 - 高优（影响体验）

### P1-1. WinFsp 驱动加载失败无提示

**文件**：`source/scripts/mount.ps1:8`  
**当前代码**：
```powershell
foreach($wd in @("$env:ProgramFiles(x86)\WinFsp","$env:ProgramFiles\WinFsp")){
    if(Test-Path $wd){
        $ft=Get-ChildItem $wd -Recurse -Filter fsptool-x64.exe -ErrorAction SilentlyContinue|Select-Object -First 1
        if($ft){& $ft.FullName load 2>$null|Out-Null}
    }
}
```

**修复后**：
```powershell
$loaded=$false
foreach($wd in @("$env:ProgramFiles(x86)\WinFsp","$env:ProgramFiles\WinFsp")){
    if(Test-Path $wd){
        $ft=Get-ChildItem $wd -Recurse -Filter fsptool-x64.exe -EA SilentlyContinue|Select -First 1
        if($ft){
            & $ft.FullName load 2>&1|Out-Null
            # 检查驱动是否真的加载成功（通过设备节点）
            if($LASTEXITCODE -eq 0 -or (Test-Path '\\.\WinFsp')){$loaded=$true;break}
        }
    }
}
if(-not $loaded){
    Log "WARNING: WinFsp driver not loaded. If WinFsp was just installed, REBOOT required before mount works."
    # 不退出，继续尝试挂载（可能已重启过）
}
```

---

### P1-2. 异常处理加强

**文件**：所有脚本  
**策略**：关键操作包 try-catch，至少记日志

**示例 - mount.ps1 挂载失败时捕获**：
```powershell
# 当前 L9 直接启动 rclone，无异常捕获
# 改为：
try {
    Start-Process (Join-Path $root 'tools\rclone.exe') $args -WorkingDirectory $root -WindowStyle Hidden -ErrorAction Stop
    for($i=0;$i-lt 45 -and !(Alive);$i++){Start-Sleep 1}
    if(Alive){Log "$drive mount success"}else{Log "$drive mount timeout after 45s"}
} catch {
    Log "mount failed: $($_.Exception.Message)"
    exit 1
}
```

**watchdog.ps1 全局加 try-catch**：
```powershell
# 当前整个脚本无异常保护，改为：
try {
    # ... 原有逻辑 ...
} catch {
    W "watchdog error: $($_.Exception.Message)"
}
```

---

### P1-3. 盘符冲突检测

**文件**：`source/scripts/mount.ps1:5`（挂载前检测）

```powershell
# 在 L5 Alive 检测之前加：
$existingDrive=[System.IO.DriveInfo]::GetDrives()|? Name -eq "$drive\"
if($existingDrive -and $existingDrive.IsReady){
    # 检查是否是我们自己挂的（通过 VolumeLabel 或 DriveFormat）
    if($existingDrive.DriveFormat -ne 'FUSE-rclone'){
        Log "$drive is occupied by another drive (format: $($existingDrive.DriveFormat))"
        exit 1
    }
}
```

---

### P1-4. 计划任务路径转义

**文件**：`source/scripts/tasks.ps1:1`

**当前代码**：
```powershell
$a=New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\autostart.ps1`""
```

**问题**：若 `$root` 含特殊字符（如单引号），会解析错误

**修复**：
```powershell
# 用双重转义或改用 -ArgumentList 数组
$scriptPath = Join-Path $root 'scripts\autostart.ps1'
$a = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$scriptPath"""
# 注意：NSIS 写入计划任务时已经双引号包裹，PS 内部再加一层双引号转义
```

---

## 🔵 P2 - 中优（质量提升）

### P2-1. 输入验证

**文件**：`source/ConfigApp.ps1:44`（保存按钮）

```powershell
# 在 L44 Save Click 内，$n 校验后加：
if(!$n){throw '请填写名称'}

# 新增：盘符校验
$driveLetter = (C Drive).Text.Trim().TrimEnd(':')
if($driveLetter -notmatch '^[D-Z]$'){
    throw '盘符必须为 D-Z 中的单个字母（C 盘为系统保留）'
}

# URL 格式校验
$urlText = (C Url).Text.Trim()
if($urlText -and $urlText -notmatch '^https?://'){
    throw 'URL 必须以 http:// 或 https:// 开头'
}

# 用户名非空校验（可选，按需）
$userText = (C User).Text.Trim()
if(!$userText){
    throw '账号不能为空'
}
```

---

### P2-2. 看门狗并发保护

**文件**：`source/scripts/watchdog.ps1:1`

**当前问题**：多实例可能同时触发修复

**修复**：加互斥锁或进程检测

```powershell
# 在脚本开头加（L1 后）：
$mutex = New-Object System.Threading.Mutex($false, 'Global\CloudDriveWatchdog')
if(-not $mutex.WaitOne(0)){
    # 已有实例在跑，直接退出
    exit 0
}
try {
    # ... 原有逻辑 ...
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
```

---

### P2-3. Alist 启动超时优化

**文件**：`source/scripts/mount.ps1:6`

**当前**：60 秒轮询，效率低

**优化**：
```powershell
# L6 改为 30 秒超时 + 提前读 stderr 判断启动失败
if(!$ok -and (Test-Path $alist)){
    Get-Process alist -EA SilentlyContinue|Stop-Process -Force
    
    $job = Start-Job -ScriptBlock {
        param($alistPath, $workDir)
        & $alistPath server 2>&1
    } -ArgumentList $alist, $root
    
    for($i=0; $i -lt 30 -and !$ok; $i++){
        Start-Sleep 1
        try{
            $ok = (Invoke-WebRequest http://127.0.0.1:5244/ -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200
        } catch {}
        
        # 检查 Job 是否提前失败
        if($job.State -eq 'Failed'){
            $err = Receive-Job $job 2>&1
            Log "Alist failed to start: $err"
            break
        }
    }
    
    if($ok){
        # 后台运行，不等待
        $job | Remove-Job -Force
    } else {
        Log 'Alist not ready after 30s'
        Stop-Job $job; Remove-Job $job -Force
        exit 1
    }
}
```

---

### P2-4. installer.nsi 组件检测增强

**文件**：`source/installer.nsi:268+`（FindOnPath 函数后）

**新增函数 - 注册表查询**：
```nsis
; 检查 App Paths 注册表
Function FindInRegistry
  Exch $0  ; 可执行文件名（如 "alist.exe"）
  Push $1
  Push $2
  
  StrCpy $2 ""
  
  ; 查 HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\alist.exe
  ReadRegStr $1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$0" ""
  ${If} $1 != ""
  ${AndIf} ${FileExists} $1
    StrCpy $2 $1
    Goto done
  ${EndIf}
  
  ; 查 HKCU 路径
  ReadRegStr $1 HKCU "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$0" ""
  ${If} $1 != ""
  ${AndIf} ${FileExists} $1
    StrCpy $2 $1
  ${EndIf}
  
  done:
  StrCpy $0 $2
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
```

**在 .onInit 内调用**：
```nsis
; L334 附近，FindOnPath 后加
Pop $AlistPath
${If} $AlistPath == ""
  Push "alist.exe"
  Call FindInRegistry
  Pop $AlistPath
${EndIf}
```

---

## 🟢 P3 - 低优（长期优化）

### P3-1. 代码可读性 - 拆分单行

**示例 - watchdog.ps1 格式化**：

**当前**：
```powershell
$root=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition);$log=Join-Path $root 'data\watchdog.log';if(Test-Path (Join-Path $root 'data\MAINTENANCE')){exit};...
```

**重构后**：
```powershell
# 变量定义
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
$log = Join-Path $root 'data\watchdog.log'

# 维护模式检测
if (Test-Path (Join-Path $root 'data\MAINTENANCE')) {
    exit 0
}

# 冷却文件
$cooldown = "$log.cooldown"

# 日志函数
function WriteLog($message) {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$timestamp $message" | Out-File $log -Append -Encoding utf8
    
    # 日志裁剪
    $lines = Get-Content $log
    if ($lines.Count -gt 800) {
        $lines | Select-Object -Last 400 | Set-Content $log -Encoding utf8
    }
}

# 主循环
foreach ($profile in (ReadProfiles | Where-Object enabled)) {
    # ... 逻辑 ...
}
```

---

### P3-2. 魔法数字提取配置

**新建**：`source/config/settings.json`

```json
{
  "mount": {
    "timeout_seconds": 45,
    "alist_startup_timeout": 30,
    "virtual_disk_size": "24.05T"
  },
  "watchdog": {
    "check_interval_minutes": 3,
    "repair_cooldown_seconds": 180
  },
  "logging": {
    "max_lines": 800,
    "keep_lines": 400
  }
}
```

**mount.ps1 读取配置**：
```powershell
# L2 后加
$settings = Get-Content (Join-Path $root 'config\settings.json') -Raw | ConvertFrom-Json
$mountTimeout = $settings.mount.timeout_seconds
$virtualSize = $settings.mount.virtual_disk_size

# L9 使用：
for($i=0; $i -lt $mountTimeout -and !(Alive); $i++){Start-Sleep 1}
# ...
--vfs-disk-space-total-size $virtualSize
```

---

### P3-3. 用户手册（新建）

**文件**：`docs/USER_MANUAL.md`

```markdown
# Windows 挂载网盘器 · 用户手册

## 1. 安装

1. 双击 `CloudMountSetup.exe`
2. 选择安装目录（默认 C:\CloudDrive）
3. 等待安装完成（自动安装 WinFsp / Alist / rclone）
4. **重要**：安装 WinFsp 后必须重启一次电脑

## 2. 配置挂载

1. 双击桌面"Windows挂载网盘器"图标
2. 右侧"新建配置"：
   - 名称：自定义（如"我的网盘"）
   - 类型：选 WebDAV / Alist / 中国移动网盘
   - 服务地址：如 `http://127.0.0.1:5244/dav`
   - 账号/密码：Alist 管理员密码（首次设置后自动保存）
   - 盘符：选择 D-Z（默认 Z:）
3. 点"保存配置"

## 3. 挂载盘符

1. 选中列表中的配置
2. 点"挂载选中"
3. 打开"此电脑"，看到新盘符即成功

## 4. 开机自启

勾选"登录时自动挂载并开启看门狗"，重启后自动挂载

## 5. 故障排查

**挂载失败**：
- 检查 WinFsp 是否已重启
- 查看 `C:\CloudDrive\data\mount.log`

**盘符不显示**：
- 任务管理器检查 rclone.exe 是否在运行
- `data\rclone_run.log` 查看错误

**卸载**：
开始菜单 → Windows挂载网盘器 → 卸载
```

---

## 修复执行计划

### 第一阶段（今日完成）
- [x] P0-1 密码加密
- [x] P0-2 BOM 检查
- [ ] P1-1 WinFsp 加载提示
- [ ] P1-2 异常处理

### 第二阶段（明日）
- [ ] P1-3 盘符冲突
- [ ] P1-4 路径转义
- [ ] P2-1 输入验证

### 第三阶段（本周内）
- [ ] P2-2~P2-4 优化项
- [ ] P3-1~P3-3 重构 + 文档

---

**修复后回归测试清单**：
1. 重新构建安装包
2. 全量测试：安装 → 配置 → 挂载 → 开机自启 → 卸载
3. 安全测试：检查 profiles.json 密码是否加密
4. 边界测试：盘符冲突、并发挂载、网络断线
5. 更新 QA_REPORT.md 测试结果
