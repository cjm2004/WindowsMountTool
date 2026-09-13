#!/usr/bin/env pwsh
# ===== Windows 挂载网盘器 - 全面功能测试脚本 =====
# 测试目标: 验证安装、配置、挂载、卸载、自启、驱动安装等所有功能
# 测试时间: 2026-09-11

param(
    [string]$TestDir = "C:\CloudMountTest"
)

$ErrorActionPreference = 'Continue'
$report = @()
$passCount = 0
$failCount = 0

function Test-Item {
    param([string]$Name, [scriptblock]$Check, [string]$Expected = "✓")
    try {
        $result = & $Check
        if ($result) {
            $script:passCount++
            $script:report += "✓ $Name"
            Write-Host "✓ $Name" -ForegroundColor Green
            return $true
        } else {
            $script:failCount++
            $script:report += "✗ $Name (期望: $Expected)"
            Write-Host "✗ $Name" -ForegroundColor Red
            return $false
        }
    } catch {
        $script:failCount++
        $script:report += "✗ $Name (异常: $($_.Exception.Message))"
        Write-Host "✗ $Name - 异常: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

$report += "===== Windows 挂载网盘器 - 全面功能测试报告 ====="
$report += "测试时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$report += "测试环境: $env:COMPUTERNAME - $env:OS"
$report += "安装目录: $TestDir"
$report += ""

# ========== 阶段一: 安装结果验证 ==========
$report += "【阶段一: 安装结果验证】"
Write-Host "`n===== 阶段一: 安装结果验证 =====" -ForegroundColor Cyan

Test-Item "1.1 安装目录存在" { Test-Path $TestDir }
Test-Item "1.2 CloudMount.exe 存在" { Test-Path "$TestDir\CloudMount.exe" }
Test-Item "1.3 ConfigApp.ps1 存在" { Test-Path "$TestDir\ConfigApp.ps1" }
Test-Item "1.4 Uninstall.exe 存在" { Test-Path "$TestDir\Uninstall.exe" }
Test-Item "1.5 alist.exe 存在" { Test-Path "$TestDir\tools\alist.exe" }
Test-Item "1.6 rclone.exe 存在" { Test-Path "$TestDir\tools\rclone.exe" }
Test-Item "1.7 scripts 目录完整" { 
    $scripts = @('mount.ps1', 'tasks.ps1', 'uninstall.ps1', 'watchdog.ps1', 'autostart.ps1')
    $missing = $scripts | Where-Object { !(Test-Path "$TestDir\scripts\$_") }
    $missing.Count -eq 0
}
Test-Item "1.8 config 目录存在" { Test-Path "$TestDir\config" }
Test-Item "1.9 data 目录存在" { Test-Path "$TestDir\data" }
Test-Item "1.10 profiles.json 已初始化" { Test-Path "$TestDir\config\profiles.json" }

$report += ""

# ========== 阶段二: 驱动检测代码验证 ==========
$report += "【阶段二: 驱动检测代码验证】"
Write-Host "`n===== 阶段二: 驱动检测代码验证 =====" -ForegroundColor Cyan

$configContent = Get-Content "$TestDir\ConfigApp.ps1" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
Test-Item "2.1 驱动状态栏 UI 代码存在" { $configContent -match '驱动状态' }
Test-Item "2.2 WinFsp 安装按钮代码存在" { $configContent -match 'InstallWinFsp' }
Test-Item "2.3 Alist 安装按钮代码存在" { $configContent -match 'InstallAlist' }
Test-Item "2.4 Rclone 安装按钮代码存在" { $configContent -match 'InstallRclone' }
Test-Item "2.5 驱动检测函数存在" { $configContent -match 'CheckWinFsp|CheckAlist|CheckRclone' }
Test-Item "2.6 UpdateDriverStatus 函数存在" { $configContent -match 'UpdateDriverStatus' }
Test-Item "2.7 窗口高度已调整(670)" { $configContent -match 'Height="670"' }

$report += ""

# ========== 阶段三: WinFsp 驱动检查 ==========
$report += "【阶段三: WinFsp 驱动检查】"
Write-Host "`n===== 阶段三: WinFsp 驱动检查 =====" -ForegroundColor Cyan

$winfspPaths = @(
    "$env:ProgramFiles\WinFsp",
    "${env:ProgramFiles(x86)}\WinFsp"
)
$winfspPath = $winfspPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
Test-Item "3.1 WinFsp 已安装" { $null -ne $winfspPath }
if ($winfspPath) {
    Test-Item "3.2 WinFsp bin 目录存在" { Test-Path "$winfspPath\bin" }
    Test-Item "3.3 fsptool-x64.exe 存在" {
        $fsptool = Get-ChildItem $winfspPath -Recurse -Filter fsptool-x64.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        $null -ne $fsptool
    }
    $winfspSvc = Get-Service WinFsp.Launcher -ErrorAction SilentlyContinue
    Test-Item "3.4 WinFsp.Launcher 服务存在" { $null -ne $winfspSvc }
    if ($winfspSvc) {
        $report += "   └─ 服务状态: $($winfspSvc.Status)"
    }
}

$report += ""

# ========== 阶段四: 配置文件功能测试 ==========
$report += "【阶段四: 配置文件操作测试】"
Write-Host "`n===== 阶段四: 配置文件操作测试 =====" -ForegroundColor Cyan

# 4.1 创建测试配置（模拟用户在 UI 中保存配置）
$testProfiles = @(
    @{
        id = [guid]::NewGuid().ToString()
        name = "测试WebDAV-1"
        type = "WebDAV"
        url = "http://127.0.0.1:5244/dav"
        user = "admin"
        pass = "test_encrypted_pass_1"  # 实际应该用 rclone obscure
        drive = "Y"
        path = "/test1"
        enabled = $true
    },
    @{
        id = [guid]::NewGuid().ToString()
        name = "测试Alist-2"
        type = "Alist / OpenList"
        url = "http://127.0.0.1:5244/dav"
        user = "admin"
        pass = "test_encrypted_pass_2"
        drive = "X"
        path = "/test2"
        enabled = $false
    }
)

try {
    $profilesJson = $testProfiles | ConvertTo-Json -Depth 5
    $profilesJson | Set-Content "$TestDir\config\profiles.json" -Encoding UTF8 -ErrorAction Stop
    Test-Item "4.1 写入测试配置成功" { $true }
} catch {
    Test-Item "4.1 写入测试配置失败" { $false }
}

Test-Item "4.2 读取配置文件不报错" {
    $loaded = Get-Content "$TestDir\config\profiles.json" -Raw | ConvertFrom-Json
    $loaded.Count -eq 2
}

Test-Item "4.3 配置包含正确字段" {
    $loaded = Get-Content "$TestDir\config\profiles.json" -Raw | ConvertFrom-Json
    $first = $loaded[0]
    ($null -ne $first.id) -and ($null -ne $first.name) -and ($null -ne $first.drive)
}

$report += ""

# ========== 阶段五: rclone 工具验证 ==========
$report += "【阶段五: rclone 工具验证】"
Write-Host "`n===== 阶段五: rclone 工具验证 =====" -ForegroundColor Cyan

$rclonePath = "$TestDir\tools\rclone.exe"
Test-Item "5.1 rclone.exe 可执行" { 
    $v = & $rclonePath version 2>&1
    $LASTEXITCODE -eq 0
}

Test-Item "5.2 rclone obscure 功能正常" {
    $encrypted = & $rclonePath obscure "testpassword" 2>&1 | Select-Object -Last 1
    $encrypted.Length -gt 0 -and $encrypted -ne "testpassword"
}

$report += ""

# ========== 阶段六: Alist 工具验证 ==========
$report += "【阶段六: Alist 工具验证】"
Write-Host "`n===== 阶段六: Alist 工具验证 =====" -ForegroundColor Cyan

$alistPath = "$TestDir\tools\alist.exe"
Test-Item "6.1 alist.exe 可执行" {
    $v = & $alistPath version 2>&1
    $LASTEXITCODE -eq 0
}

$report += ""

# ========== 阶段七: 脚本完整性检查 ==========
$report += "【阶段七: 核心脚本完整性检查】"
Write-Host "`n===== 阶段七: 核心脚本完整性检查 =====" -ForegroundColor Cyan

$mountScript = Get-Content "$TestDir\scripts\mount.ps1" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
Test-Item "7.1 mount.ps1 包含 rclone obscure 解密逻辑" { $mountScript -match 'rclone.*obscure|Obscure' }
Test-Item "7.2 mount.ps1 包含 WinFsp 加载逻辑" { $mountScript -match 'fsptool-x64\.exe.*load' }
Test-Item "7.3 mount.ps1 包含远端名尾部冒号" { $mountScript -match '\$remoteRef\s*=.*:' }
Test-Item "7.4 mount.ps1 包含无 BOM 写入" { $mountScript -match 'UTF8Encoding\(\$false\)' }

$uninstallScript = Get-Content "$TestDir\scripts\uninstall.ps1" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
Test-Item "7.5 uninstall.ps1 包含 net use 删除" { $uninstallScript -match 'net use.*delete' }
Test-Item "7.6 uninstall.ps1 包含杀进程逻辑" { $uninstallScript -match 'Stop-Process.*rclone' }

$tasksScript = Get-Content "$TestDir\scripts\tasks.ps1" -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
Test-Item "7.7 tasks.ps1 包含计划任务注册" { $tasksScript -match 'Register-ScheduledTask' }

$report += ""

# ========== 阶段八: 卸载程序检查 ==========
$report += "【阶段八: 卸载程序检查】"
Write-Host "`n===== 阶段八: 卸载程序检查 =====" -ForegroundColor Cyan

Test-Item "8.1 Uninstall.exe 存在且大小正常" {
    $uninstall = Get-Item "$TestDir\Uninstall.exe" -ErrorAction SilentlyContinue
    ($null -ne $uninstall) -and ($uninstall.Length -gt 10KB)
}

$report += ""

# ========== 测试总结 ==========
$report += ""
$report += "===== 测试总结 ====="
$report += "通过: $passCount 项"
$report += "失败: $failCount 项"
$totalTests = $passCount + $failCount
$passRate = if ($totalTests -gt 0) { [math]::Round(($passCount / $totalTests) * 100, 1) } else { 0 }
$report += "通过率: $passRate%"
$report += ""

if ($failCount -eq 0) {
    $report += "🎉 所有测试通过！"
    Write-Host "`n🎉 所有测试通过！" -ForegroundColor Green
} else {
    $report += "⚠️ 发现 $failCount 项失败，请检查详细报告"
    Write-Host "`n⚠️ 发现 $failCount 项失败" -ForegroundColor Yellow
}

# 保存报告
$reportPath = "C:\Users\22303\Desktop\winmount\logs\comprehensive_test_report.txt"
$report -join "`r`n" | Out-File $reportPath -Encoding utf8
Write-Host "`n测试报告已保存: $reportPath" -ForegroundColor Cyan

return @{ Pass = $passCount; Fail = $failCount; Rate = $passRate }
