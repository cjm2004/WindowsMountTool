param([string]$InstDir = 'C:\CloudDrive')
# 01_install.ps1 - 静默安装测试：运行安装包 → 校验安装目录与驱动是否齐全
$root  = 'C:\Users\22303\Desktop\winmount'
$setup = Join-Path $root 'dist\CloudMountSetup.exe'
$r = @()
function L($m) { $script:r += $m }

L '=== 安装前状态 ==='
L ("安装目录已存在 : " + (Test-Path $InstDir))
L ("WinFsp 已安装  : " + [bool]((Get-ItemProperty 'HKLM:\SOFTWARE\WinFsp' -EA SilentlyContinue) -or (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\WinFsp' -EA SilentlyContinue)))
L ("alist 进程数   : " + @(Get-Process alist  -EA SilentlyContinue).Count)
L ("rclone 进程数  : " + @(Get-Process rclone -EA SilentlyContinue).Count)

L ''
L '=== 执行静默安装（自动提权）==='
L ("安装包: $setup")
$p = Start-Process -FilePath $setup -ArgumentList '/S', "/D=$InstDir" -Verb RunAs -PassThru -Wait
L ("退出码: " + $p.ExitCode)
Start-Sleep -Seconds 3

L ''
L '=== 安装目录内容 ==='
$expect = @(
    'CloudMount.exe',
    'Uninstall.exe',
    'ConfigApp.ps1',
    'ConfigApp.cmd',
    'tools\alist.exe',
    'tools\rclone.exe',
    'tools\winfsp-2.1.25156.msi',
    'scripts\mount.ps1',
    'scripts\watchdog.ps1',
    'scripts\tasks.ps1',
    'scripts\autostart.ps1',
    'scripts\uninstall.ps1',
    'config\profiles.json',
    'data\recycle_bin'
)
foreach ($f in $expect) {
    $full = Join-Path $InstDir $f
    if (Test-Path $full) { L ("  [OK]   {0,-42}" -f $f) } else { L ("  [缺失] {0,-42}" -f $f) }
}
$stray = @(Get-ChildItem $InstDir -Force -EA SilentlyContinue | ForEach-Object { $_.Name })
L ("安装目录一级内容: " + ($stray -join ', '))

L ''
L '=== 系统状态 ==='
L ("WinFsp 注册表(64): " + [bool](Get-ItemProperty 'HKLM:\SOFTWARE\WinFsp' -EA SilentlyContinue))
L ("WinFsp 注册表(32): " + [bool](Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\WinFsp' -EA SilentlyContinue))
L ("WinFsp.Launcher  : " + (Get-Service 'WinFsp.Launcher' -EA SilentlyContinue).Status)
L ("卸载注册表项     : " + [bool](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CloudDriveMount' -EA SilentlyContinue))
L ("桌面快捷方式     : " + (Test-Path 'C:\Users\Public\Desktop\Windows挂载网盘器.lnk'))
L ("开始菜单快捷方式 : " + (Test-Path 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Windows挂载网盘器'))

$r | Out-File (Join-Path $root 'logs\test-install.txt') -Encoding utf8
