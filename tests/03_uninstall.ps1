param([string]$InstDir = 'C:\CloudDrive', [string]$Drive = 'Z')
# 03_uninstall.ps1 - 卸载测试：运行 Uninstall.exe /S → 校验系统恢复干净
$root = 'C:\Users\22303\Desktop\winmount'
$r = @()
function L($m) { $script:r += $m; Write-Output $m }

L '=== 卸载前状态 ==='
L ("安装目录存在 : " + (Test-Path $InstDir))
L ("Z 盘存在     : " + [bool]([System.IO.DriveInfo]::GetDrives() | Where-Object { $_.Name -eq "${Drive}:\" }))
L ("rclone 进程  : " + @(Get-Process rclone -EA SilentlyContinue).Count)
L ("alist 进程   : " + @(Get-Process alist  -EA SilentlyContinue).Count)

L ''
L '=== 执行静默卸载（自动提权）==='
$uninst = Join-Path $InstDir 'Uninstall.exe'
L ("卸载程序: $uninst")
if (Test-Path $uninst) {
    $p = Start-Process -FilePath $uninst -ArgumentList '/S' -Verb RunAs -PassThru -Wait
    L ("退出码: " + $p.ExitCode)
} else {
    L '[错误] 未找到 Uninstall.exe'
}
Start-Sleep -Seconds 8

L ''
L '=== 卸载后校验 ==='
$checks = [ordered]@{
    '安装目录已删除'      = -not (Test-Path $InstDir)
    '主程序已删除'        = -not (Test-Path (Join-Path $InstDir 'CloudMount.exe'))
    '驱动目录已删除'      = -not (Test-Path (Join-Path $InstDir 'tools'))
    '计划任务 CloudDriveMount 已注销' = -not (Get-ScheduledTask -TaskName 'CloudDriveMount' -EA SilentlyContinue)
    '计划任务 CloudDriveHealth 已注销' = -not (Get-ScheduledTask -TaskName 'CloudDriveHealth' -EA SilentlyContinue)
    'rclone 进程已结束'   = (@(Get-Process rclone -EA SilentlyContinue).Count -eq 0)
    'alist 进程已结束'    = (@(Get-Process alist  -EA SilentlyContinue).Count -eq 0)
    "盘符 ${Drive}: 已解除" = -not ([System.IO.DriveInfo]::GetDrives() | Where-Object { $_.Name -eq "${Drive}:\" })
    '卸载注册表项已删除'  = -not (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CloudDriveMount' -EA SilentlyContinue)
    'HKLM\Software\CloudDriveMount 已删除' = -not (Test-Path 'HKLM:\SOFTWARE\CloudDriveMount')
    '桌面快捷方式已删除'  = -not (Test-Path 'C:\Users\Public\Desktop\Windows挂载网盘器.lnk')
    '开始菜单已删除'      = -not (Test-Path 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Windows挂载网盘器')
    'WinFsp 注册表(64)已清除' = -not (Get-ItemProperty 'HKLM:\SOFTWARE\WinFsp' -EA SilentlyContinue)
    'WinFsp 注册表(32)已清除' = -not (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\WinFsp' -EA SilentlyContinue)
    'WinFsp.Launcher 服务已移除' = -not (Get-Service 'WinFsp.Launcher' -EA SilentlyContinue)
    'WinFsp 安装目录已移除' = -not (Test-Path 'C:\Program Files (x86)\WinFsp')
}
foreach ($k in $checks.Keys) {
    $v = $checks[$k]
    if ($v) { L ("  [通过] {0}" -f $k) } else { L ("  [未通过] {0}" -f $k) }
}

L ''
L '=== 残留进程/服务 ==='
L ("进程: " + (((Get-Process rclone, alist -EA SilentlyContinue) | ForEach-Object { $_.ProcessName }) -join ', '))
L ("WinFsp 相关服务: " + (((Get-Service -EA SilentlyContinue | Where-Object { $_.Name -match 'WinFsp' }) | ForEach-Object { $_.Name }) -join ', '))

L ''
L '=== 卸载脚本日志（%TEMP%\CloudMount_uninstall.log）==='
$ul = Join-Path $env:TEMP 'CloudMount_uninstall.log'
if (Test-Path $ul) { Get-Content $ul -Tail 15 | ForEach-Object { L ("  " + $_) } }
else { L '  （无）' }

$r | Out-File (Join-Path $root 'logs\test-uninstall.txt') -Encoding utf8
