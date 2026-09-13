#!/usr/bin/env pwsh
# ===== Windows 挂载网盘器 - 完整功能验证测试 =====
# 测试目标：按用户要求验证所有核心功能
# 测试时间：2026-09-11

param(
    [string]$TestDir = "C:\CloudMountTest"
)

$ErrorActionPreference = 'Continue'
$report = @()
$testResults = @{
    Pass = 0
    Fail = 0
    Warn = 0
}

function Write-TestResult {
    param(
        [string]$Category,
        [string]$TestName,
        [string]$Status,  # Pass, Fail, Warn
        [string]$Details = ""
    )
    
    $icon = switch ($Status) {
        "Pass" { "✓"; $script:testResults.Pass++ }
        "Fail" { "✗"; $script:testResults.Fail++ }
        "Warn" { "⚠️"; $script:testResults.Warn++ }
    }
    
    $color = switch ($Status) {
        "Pass" { "Green" }
        "Fail" { "Red" }
        "Warn" { "Yellow" }
    }
    
    $line = "$icon [$Category] $TestName"
    if ($Details) { $line += " - $Details" }
    
    $script:report += $line
    Write-Host $line -ForegroundColor $color
}

# ========== 测试开始 ==========
$script:report += "===== Windows 挂载网盘器 - 完整功能测试报告 ====="
$script:report += "测试时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$script:report += "测试环境: $env:COMPUTERNAME"
$script:report += "安装目录: $TestDir"
$script:report += ""

Write-Host "`n===== 开始完整功能测试 =====" -ForegroundColor Cyan
Write-Host "测试目录: $TestDir`n" -ForegroundColor Cyan

# ========== 1. 安装界面功能验证 ==========
$script:report += "【测试项 1：安装界面功能验证】"
Write-Host "`n【测试项 1：安装界面功能验证】" -ForegroundColor Yellow

# 1.1 检查安装程序
if (Test-Path $TestDir) {
    Write-TestResult "安装" "1.1 安装目录存在" "Pass" $TestDir
} else {
    Write-TestResult "安装" "1.1 安装目录存在" "Fail" "目录不存在"
    $script:report += "`n❌ 测试终止：安装目录不存在"
    $script:report -join "`r`n" | Out-File "C:\Users\22303\Desktop\winmount\logs\full_test_report.txt" -Encoding utf8
    exit 1
}

# 1.2 核心文件完整性
$coreFiles = @{
    "CloudMount.exe" = "主程序启动器"
    "ConfigApp.ps1" = "配置界面脚本"
    "Uninstall.exe" = "卸载程序"
    "tools\alist.exe" = "Alist 服务"
    "tools\rclone.exe" = "rclone 挂载引擎"
}

foreach ($file in $coreFiles.Keys) {
    $path = Join-Path $TestDir $file
    if (Test-Path $path) {
        $size = [math]::Round((Get-Item $path).Length / 1MB, 1)
        Write-TestResult "安装" "1.2 $($coreFiles[$file])" "Pass" "$size MB"
    } else {
        Write-TestResult "安装" "1.2 $($coreFiles[$file])" "Fail" "文件缺失: $file"
    }
}

# 1.3 WinFsp 驱动检测
$winfspPaths = @(
    "$env:ProgramFiles\WinFsp",
    "${env:ProgramFiles(x86)}\WinFsp"
)
$winfspFound = $false
foreach ($path in $winfspPaths) {
    if (Test-Path $path) {
        Write-TestResult "驱动" "1.3 WinFsp 驱动已安装" "Pass" $path
        $winfspFound = $true
        
        # 检查服务
        $svc = Get-Service WinFsp.Launcher -ErrorAction SilentlyContinue
        if ($svc) {
            Write-TestResult "驱动" "1.3 WinFsp 服务状态" "Pass" $svc.Status
        } else {
            Write-TestResult "驱动" "1.3 WinFsp 服务状态" "Warn" "服务未找到"
        }
        break
    }
}
if (-not $winfspFound) {
    Write-TestResult "驱动" "1.3 WinFsp 驱动已安装" "Warn" "测试环境未安装"
}

$script:report += ""

# ========== 2. 配置页面功能验证 ==========
$script:report += "【测试项 2：配置页面功能验证】"
Write-Host "`n【测试项 2：配置页面功能验证】" -ForegroundColor Yellow

# 2.1 驱动检测 UI 代码验证
$configPath = Join-Path $TestDir "ConfigApp.ps1"
if (Test-Path $configPath) {
    $configContent = Get-Content $configPath -Raw -Encoding UTF8
    
    # 检查驱动状态栏
    if ($configContent -match '驱动状态') {
        Write-TestResult "配置UI" "2.1 驱动状态栏代码" "Pass"
    } else {
        Write-TestResult "配置UI" "2.1 驱动状态栏代码" "Fail" "缺少驱动状态栏"
    }
    
    # 检查三个安装按钮
    $buttons = @("InstallWinFsp", "InstallAlist", "InstallRclone")
    foreach ($btn in $buttons) {
        if ($configContent -match $btn) {
            Write-TestResult "配置UI" "2.1 ${btn} 按钮" "Pass"
        } else {
            Write-TestResult "配置UI" "2.1 ${btn} 按钮" "Fail"
        }
    }
    
    # 检查驱动检测函数
    if ($configContent -match 'CheckWinFsp.*CheckAlist.*CheckRclone') {
        Write-TestResult "配置UI" "2.1 驱动检测函数" "Pass"
    } else {
        Write-TestResult "配置UI" "2.1 驱动检测函数" "Fail"
    }
    
    # 检查 UpdateDriverStatus
    if ($configContent -match 'UpdateDriverStatus') {
        Write-TestResult "配置UI" "2.1 驱动状态更新函数" "Pass"
    } else {
        Write-TestResult "配置UI" "2.1 驱动状态更新函数" "Fail"
    }
    
    # 检查窗口尺寸
    if ($configContent -match 'Height="670"') {
        Write-TestResult "配置UI" "2.1 窗口高度调整" "Pass" "670px"
    } else {
        Write-TestResult "配置UI" "2.1 窗口高度调整" "Warn" "未调整或已修改"
    }
} else {
    Write-TestResult "配置UI" "2.1 ConfigApp.ps1" "Fail" "文件不存在"
}

# 2.2 配置文件读写
$profilesPath = Join-Path $TestDir "config\profiles.json"
if (Test-Path $profilesPath) {
    Write-TestResult "配置UI" "2.2 profiles.json 存在" "Pass"
    
    try {
        $profiles = Get-Content $profilesPath -Raw | ConvertFrom-Json
        Write-TestResult "配置UI" "2.2 配置文件格式" "Pass" "JSON 解析成功"
    } catch {
        Write-TestResult "配置UI" "2.2 配置文件格式" "Fail" $_.Exception.Message
    }
} else {
    Write-TestResult "配置UI" "2.2 profiles.json 存在" "Warn" "未初始化"
}

$script:report += ""

# ========== 3. 多配置挂载能力验证 ==========
$script:report += "【测试项 3：多配置挂载能力（功能模拟）】"
Write-Host "`n【测试项 3：多配置挂载能力（功能模拟）】" -ForegroundColor Yellow

# 3.1 创建测试配置（模拟 WebDAV + Alist）
$testConfigs = @(
    @{
        id = [guid]::NewGuid().ToString()
        name = "测试WebDAV配置"
        type = "WebDAV"
        url = "http://127.0.0.1:5244/dav"
        user = "admin"
        pass = "encrypted_pass_webdav"
        drive = "Y"
        path = "/webdav"
        enabled = $true
    },
    @{
        id = [guid]::NewGuid().ToString()
        name = "测试Alist配置"
        type = "Alist / OpenList"
        url = "http://192.168.1.100:5244/dav"
        user = "admin"
        pass = "encrypted_pass_alist"
        drive = "X"
        path = "/alist"
        enabled = $true
    }
)

try {
    $testJson = $testConfigs | ConvertTo-Json -Depth 5
    $testJson | Set-Content $profilesPath -Encoding UTF8
    Write-TestResult "多配置" "3.1 写入多个测试配置" "Pass" "2个配置（WebDAV + Alist）"
} catch {
    Write-TestResult "多配置" "3.1 写入多个测试配置" "Fail" $_.Exception.Message
}

# 3.2 验证配置读取
try {
    $loaded = Get-Content $profilesPath -Raw | ConvertFrom-Json
    if ($loaded.Count -eq 2) {
        Write-TestResult "多配置" "3.2 配置数量正确" "Pass" "$($loaded.Count) 个"
    } else {
        Write-TestResult "多配置" "3.2 配置数量正确" "Fail" "期望2个，实际$($loaded.Count)个"
    }
    
    # 验证字段完整性
    $first = $loaded[0]
    $requiredFields = @('id', 'name', 'type', 'url', 'user', 'pass', 'drive', 'path', 'enabled')
    $missingFields = $requiredFields | Where-Object { $null -eq $first.$_ }
    
    if ($missingFields.Count -eq 0) {
        Write-TestResult "多配置" "3.2 配置字段完整" "Pass"
    } else {
        Write-TestResult "多配置" "3.2 配置字段完整" "Fail" "缺失: $($missingFields -join ', ')"
    }
} catch {
    Write-TestResult "多配置" "3.2 配置读取验证" "Fail" $_.Exception.Message
}

$script:report += ""

# ========== 4. 挂载/卸载/删除操作验证 ==========
$script:report += "【测试项 4：挂载/卸载/删除操作（脚本完整性）】"
Write-Host "`n【测试项 4：挂载/卸载/删除操作（脚本完整性）】" -ForegroundColor Yellow

# 4.1 mount.ps1 关键逻辑检查
$mountScript = Join-Path $TestDir "scripts\mount.ps1"
if (Test-Path $mountScript) {
    $mountContent = Get-Content $mountScript -Raw -Encoding UTF8
    
    # 检查关键修复
    $checks = @{
        "无BOM写入" = 'UTF8Encoding\(\$false\)'
        "WinFsp加载" = 'fsptool-x64\.exe.*load'
        "远端名冒号" = '\$remoteRef.*:'
        "杀残留进程" = 'Stop-Process.*rclone'
    }
    
    foreach ($check in $checks.Keys) {
        if ($mountContent -match $checks[$check]) {
            Write-TestResult "挂载脚本" "4.1 mount.ps1 - $check" "Pass"
        } else {
            Write-TestResult "挂载脚本" "4.1 mount.ps1 - $check" "Fail"
        }
    }
} else {
    Write-TestResult "挂载脚本" "4.1 mount.ps1" "Fail" "文件不存在"
}

# 4.2 uninstall.ps1 卸载逻辑检查
$uninstallScript = Join-Path $TestDir "scripts\uninstall.ps1"
if (Test-Path $uninstallScript) {
    $uninstallContent = Get-Content $uninstallScript -Raw -Encoding UTF8
    
    $checks = @{
        "删除盘符" = 'net use.*delete'
        "杀rclone进程" = 'Stop-Process.*rclone'
        "杀alist进程" = 'Stop-Process.*alist'
        "删除计划任务" = 'Unregister-ScheduledTask'
    }
    
    foreach ($check in $checks.Keys) {
        if ($uninstallContent -match $checks[$check]) {
            Write-TestResult "卸载脚本" "4.2 uninstall.ps1 - $check" "Pass"
        } else {
            Write-TestResult "卸载脚本" "4.2 uninstall.ps1 - $check" "Warn" "未找到"
        }
    }
} else {
    Write-TestResult "卸载脚本" "4.2 uninstall.ps1" "Fail" "文件不存在"
}

$script:report += ""

# ========== 5. 开机自启功能验证 ==========
$script:report += "【测试项 5：开机自启功能（计划任务）】"
Write-Host "`n【测试项 5：开机自启功能（计划任务）】" -ForegroundColor Yellow

# 5.1 tasks.ps1 计划任务脚本检查
$tasksScript = Join-Path $TestDir "scripts\tasks.ps1"
if (Test-Path $tasksScript) {
    $tasksContent = Get-Content $tasksScript -Raw -Encoding UTF8
    
    if ($tasksContent -match 'Register-ScheduledTask') {
        Write-TestResult "自启" "5.1 计划任务注册逻辑" "Pass"
    } else {
        Write-TestResult "自启" "5.1 计划任务注册逻辑" "Fail"
    }
    
    if ($tasksContent -match 'CloudDriveMount|CloudDriveHealth') {
        Write-TestResult "自启" "5.1 计划任务名称定义" "Pass"
    } else {
        Write-TestResult "自启" "5.1 计划任务名称定义" "Fail"
    }
} else {
    Write-TestResult "自启" "5.1 tasks.ps1" "Fail" "文件不存在"
}

# 5.2 autostart.ps1 自启脚本检查
$autostartScript = Join-Path $TestDir "scripts\autostart.ps1"
if (Test-Path $autostartScript) {
    Write-TestResult "自启" "5.2 autostart.ps1 存在" "Pass"
} else {
    Write-TestResult "自启" "5.2 autostart.ps1 存在" "Warn" "文件不存在"
}

# 5.3 watchdog.ps1 看门狗检查
$watchdogScript = Join-Path $TestDir "scripts\watchdog.ps1"
if (Test-Path $watchdogScript) {
    Write-TestResult "自启" "5.3 watchdog.ps1 存在" "Pass"
} else {
    Write-TestResult "自启" "5.3 watchdog.ps1 存在" "Warn" "文件不存在"
}

$script:report += ""

# ========== 6. 工具可执行性验证 ==========
$script:report += "【测试项 6：核心工具可执行性】"
Write-Host "`n【测试项 6：核心工具可执行性】" -ForegroundColor Yellow

# 6.1 rclone 版本检查
$rclonePath = Join-Path $TestDir "tools\rclone.exe"
if (Test-Path $rclonePath) {
    try {
        $rcloneVer = & $rclonePath version 2>&1 | Select-Object -First 1
        if ($LASTEXITCODE -eq 0) {
            Write-TestResult "工具" "6.1 rclone 可执行" "Pass" $rcloneVer
        } else {
            Write-TestResult "工具" "6.1 rclone 可执行" "Fail" "退出码: $LASTEXITCODE"
        }
    } catch {
        Write-TestResult "工具" "6.1 rclone 可执行" "Fail" $_.Exception.Message
    }
    
    # 测试 obscure 功能
    try {
        $encrypted = & $rclonePath obscure "testpass" 2>&1 | Select-Object -Last 1
        if ($encrypted -and $encrypted -ne "testpass") {
            Write-TestResult "工具" "6.1 rclone obscure 功能" "Pass"
        } else {
            Write-TestResult "工具" "6.1 rclone obscure 功能" "Fail"
        }
    } catch {
        Write-TestResult "工具" "6.1 rclone obscure 功能" "Fail" $_.Exception.Message
    }
} else {
    Write-TestResult "工具" "6.1 rclone" "Fail" "文件不存在"
}

# 6.2 alist 版本检查
$alistPath = Join-Path $TestDir "tools\alist.exe"
if (Test-Path $alistPath) {
    try {
        $alistVer = & $alistPath version 2>&1 | Select-Object -First 3 | Select-Object -Last 1
        if ($LASTEXITCODE -eq 0) {
            Write-TestResult "工具" "6.2 alist 可执行" "Pass" $alistVer
        } else {
            Write-TestResult "工具" "6.2 alist 可执行" "Fail" "退出码: $LASTEXITCODE"
        }
    } catch {
        Write-TestResult "工具" "6.2 alist 可执行" "Fail" $_.Exception.Message
    }
} else {
    Write-TestResult "工具" "6.2 alist" "Fail" "文件不存在"
}

$script:report += ""

# ========== 7. 卸载程序验证 ==========
$script:report += "【测试项 7：卸载程序完整性】"
Write-Host "`n【测试项 7：卸载程序完整性】" -ForegroundColor Yellow

$uninstallExe = Join-Path $TestDir "Uninstall.exe"
if (Test-Path $uninstallExe) {
    $size = (Get-Item $uninstallExe).Length
    if ($size -gt 10KB) {
        Write-TestResult "卸载" "7.1 Uninstall.exe 大小正常" "Pass" "$([math]::Round($size/1KB, 1)) KB"
    } else {
        Write-TestResult "卸载" "7.1 Uninstall.exe 大小正常" "Warn" "文件过小"
    }
} else {
    Write-TestResult "卸载" "7.1 Uninstall.exe" "Fail" "文件不存在"
}

# ========== 测试总结 ==========
$script:report += ""
$script:report += "===== 测试总结 ====="
$total = $testResults.Pass + $testResults.Fail + $testResults.Warn
$passRate = if ($total -gt 0) { [math]::Round(($testResults.Pass / $total) * 100, 1) } else { 0 }

$script:report += "✓ 通过: $($testResults.Pass) 项"
$script:report += "✗ 失败: $($testResults.Fail) 项"
$script:report += "⚠️ 警告: $($testResults.Warn) 项"
$script:report += "通过率: $passRate%"
$script:report += ""

Write-Host "`n===== 测试总结 =====" -ForegroundColor Cyan
Write-Host "✓ 通过: $($testResults.Pass) 项" -ForegroundColor Green
Write-Host "✗ 失败: $($testResults.Fail) 项" -ForegroundColor Red
Write-Host "⚠️ 警告: $($testResults.Warn) 项" -ForegroundColor Yellow
Write-Host "通过率: $passRate%`n" -ForegroundColor Cyan

if ($testResults.Fail -eq 0) {
    $script:report += "🎉 核心功能验证全部通过！"
    Write-Host "🎉 核心功能验证全部通过！" -ForegroundColor Green
} else {
    $script:report += "⚠️ 发现 $($testResults.Fail) 项失败，需要修复"
    Write-Host "⚠️ 发现 $($testResults.Fail) 项失败，需要修复" -ForegroundColor Yellow
}

# 保存报告
$reportPath = "C:\Users\22303\Desktop\winmount\logs\full_test_report.txt"
$script:report -join "`r`n" | Out-File $reportPath -Encoding utf8
Write-Host "`n完整测试报告已保存: $reportPath" -ForegroundColor Cyan

return @{
    Pass = $testResults.Pass
    Fail = $testResults.Fail
    Warn = $testResults.Warn
    Rate = $passRate
}
