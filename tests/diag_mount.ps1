param([string]$Drive = 'Z', [string]$Pass = 'TestPass12345')
# diag_mount.ps1 - 隔离诊断：用"无 BOM"的 rclone.conf 手工挂载，区分是 BOM 问题还是 WinFsp 未重启问题
$root = 'C:\Users\22303\Desktop\winmount'
$r = @()
function L($m) { $script:r += $m; Write-Output $m }

$testDir = 'C:\CloudMountDiag'
New-Item -ItemType Directory -Force -Path $testDir | Out-Null
$conf = Join-Path $testDir 'rclone.conf'
$obsc = (& 'C:\CloudDrive\tools\rclone.exe' obscure $Pass 2>$null | Select-Object -Last 1)
$enc  = New-Object System.Text.UTF8Encoding($false)      # 关键：无 BOM
$text = "[diag]`r`ntype = webdav`r`nurl = http://127.0.0.1:5244/dav/test`r`nvendor = other`r`nuser = admin`r`npass = $obsc`r`n"
[System.IO.File]::WriteAllText($conf, $text, $enc)
L ("conf 首字节: " + [int]([System.IO.File]::ReadAllBytes($conf))[0] + "  (91='[' 表示无 BOM)")

# 先用 ls 验证远端能不能读（不依赖 WinFsp）
$rclone = 'C:\CloudDrive\tools\rclone.exe'
$out = & $rclone ls "diag:" --config $conf 2>&1
L '--- rclone ls diag: ---'
$out | ForEach-Object { L ("  " + $_) }

L ''
L '--- 手工挂载 ---'
$log = Join-Path $testDir 'rclone_diag.log'
Start-Process -FilePath $rclone -ArgumentList "mount diag: ${Drive}: --config `"$conf`" --log-file `"$log`" --log-level INFO --vfs-cache-mode full --volname DiagTest" -WindowStyle Hidden
$ok = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    $d = [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.Name -eq "${Drive}:\" }
    if ($d -and $d.IsReady) { $ok = $true; break }
}
L ("盘符 ${Drive}: 就绪 = " + $ok)
if ($ok) { L ("内容: " + ((Get-ChildItem "${Drive}:\" -Force -EA SilentlyContinue).Name -join ', ')) }
L '--- rclone 日志 ---'
if (Test-Path $log) { Get-Content $log -Tail 25 | ForEach-Object { L ("  " + $_) } }

L ''
L '--- WinFsp 状态 ---'
L ("WinFsp.Launcher : " + (Get-Service 'WinFsp.Launcher' -EA SilentlyContinue).Status)
$drv = Get-CimInstance Win32_SystemDriver -Filter "Name='WinFsp'" -EA SilentlyContinue
L ("WinFsp 驱动     : " + $(if ($drv) { "$($drv.State) / $($drv.StartMode)" } else { '未找到' }))
L ("WinFsp 设备     : " + [System.IO.File]::Exists('\\.\WinFsp'))

$r | Out-File (Join-Path $root 'logs\test-diag.txt') -Encoding utf8
