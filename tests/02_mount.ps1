param(
    [string]$InstDir = 'C:\CloudDrive',
    [string]$Drive   = 'Z',
    [string]$Pass    = 'TestPass12345'
)
# 02_mount.ps1 - 挂载测试：内嵌 Alist 起 WebDAV 服务 → rclone 挂载为盘符 → 验证可读写
# 这条链路就是产品真实链路：Alist(Local存储) --WebDAV--> rclone --WinFsp--> 盘符
$root  = 'C:\Users\22303\Desktop\winmount'
$r = @()
function L($m) { $script:r += $m; Write-Output $m }

$tools  = Join-Path $InstDir 'tools'
$alist  = Join-Path $tools 'alist.exe'
$rclone = Join-Path $tools 'rclone.exe'
$srcDir = 'C:\CloudMountTestData'          # 模拟"云端"的本地源目录

L '=== 0. 准备测试数据源 ==='
New-Item -ItemType Directory -Force -Path $srcDir | Out-Null
'hello from fake cloud' | Set-Content (Join-Path $srcDir 'hello.txt') -Encoding UTF8
'第二份文件'            | Set-Content (Join-Path $srcDir '文件二.txt') -Encoding UTF8
L ("源目录: $srcDir  文件: " + ((Get-ChildItem $srcDir).Name -join ', '))

L ''
L '=== 1. 启动内嵌 Alist（本地 WebDAV 服务）==='
$up = $false
try { $up = (Invoke-WebRequest 'http://127.0.0.1:5244/' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $up = $false }
if (-not $up) {
    Start-Process -FilePath $alist -ArgumentList 'server' -WorkingDirectory $InstDir -WindowStyle Hidden
    for ($i = 0; $i -lt 90 -and -not $up; $i++) {
        Start-Sleep -Seconds 1
        try { $up = (Invoke-WebRequest 'http://127.0.0.1:5244/' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $up = $false }
    }
}
L ("Alist 就绪: $up")

L ''
L '=== 2. 设置 Alist 管理员密码（约束 H）==='
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $alist
$psi.Arguments = "admin set $Pass"
$psi.WorkingDirectory = $InstDir
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$pr = [System.Diagnostics.Process]::Start($psi)
$so = $pr.StandardOutput.ReadToEnd(); $se = $pr.StandardError.ReadToEnd(); $pr.WaitForExit()
L ("alist admin set 返回码: " + $pr.ExitCode)
if ($so) { L ("stdout: " + ($so -replace "`r?`n", ' | ')) }
if ($se) { L ("stderr: " + ($se -replace "`r?`n", ' | ')) }

L ''
L '=== 3. 登录 Alist 并挂载 Local 存储 ==='
$token = ''
try {
    $login = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5244/api/auth/login' -ContentType 'application/json' -TimeoutSec 20 -Body (@{ username = 'admin'; password = $Pass } | ConvertTo-Json)
    L ("login code: " + $login.code)
    $token = $login.data.token
} catch { L ("login 失败: " + $_.Exception.Message) }
L ("token 获取: " + [bool]$token)

if ($token) {
    $hdr = @{ Authorization = $token }
    # 注意：Alist 管理接口前缀是 /api/admin/ ；/api/storage/* 会被前端 SPA 兜底返回 HTML
    $exists = $false
    try {
        $lst = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:5244/api/admin/storage/list' -TimeoutSec 20 -Headers $hdr
        $paths = @($lst.data.content | ForEach-Object { $_.mount_path })
        L ("已有存储: " + ($paths -join ', '))
        $exists = $paths -contains '/test'
    } catch { L ("storage/list 失败: " + $_.Exception.Message) }

    if ($exists) {
        L '存储 /test 已存在，跳过创建'
    } else {
        try {
            $addition = @{ root_folder_path = $srcDir; thumbnail = $false; show_hidden = $true; mkdir_perm = '777'; recycle_bin = '' } | ConvertTo-Json -Compress
            $body = @{
                mount_path = '/test'; order = 0; remark = 'e2e'; cache_expiration = 30
                web_proxy = $false; webdav_policy = 'native_proxy'; down_proxy_url = ''
                disable_index = $false; enable_sign = $false; driver = 'Local'
                addition = $addition; order_by = 'name'; order_direction = 'asc'
                extract_folder = 'front'; status = 'work'
            } | ConvertTo-Json -Depth 6
            $res = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5244/api/admin/storage/create' -ContentType 'application/json' -TimeoutSec 30 -Headers $hdr -Body $body
            L ("storage/create 返回: " + ($res | ConvertTo-Json -Compress -Depth 4))
        } catch { L ("storage/create 失败: " + $_.Exception.Message) }
    }
}

L ''
L '=== 4. 写入挂载配置并调用 mount.ps1 ==='
$obscure = (& $rclone obscure $Pass 2>$null | Select-Object -Last 1)
L ("rclone obscure 结果长度: " + ($obscure | ForEach-Object { $_.ToString().Length }))
$id = [guid]::NewGuid().ToString()
$profile = [pscustomobject]@{
    id = $id; name = 'E2E-WebDAV'; type = 'WebDAV'
    url = 'http://127.0.0.1:5244/dav'; user = 'admin'; pass = $obscure
    drive = $Drive; path = 'test'; enabled = $true
}
$profilesFile = Join-Path $InstDir 'config\profiles.json'
$profile | ConvertTo-Json -Depth 6 | Set-Content $profilesFile -Encoding UTF8
L ("profiles.json 已写入，盘符: ${Drive}:")

& (Join-Path $InstDir 'scripts\mount.ps1') -ProfileId $id
L 'mount.ps1 已返回'

L ''
L '=== 5. 盘符验证 ==='
$target = "${Drive}:\"
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $d = [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.Name -eq $target }
    if ($d -and $d.IsReady) { $ok = $true; break }
}
if ($ok) {
    $d = [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.Name -eq $target }
    L ("[成功] 盘符 ${target} 已就绪")
    L ("  卷标        : " + $d.VolumeLabel)
    L ("  文件系统    : " + $d.DriveFormat)
    L ("  可用/总容量 : {0:N1} GB / {1:N1} GB" -f ($d.AvailableFreeSpace/1GB), ($d.TotalSize/1GB))
    L ("  目录内容    : " + ((Get-ChildItem $target -Force -EA SilentlyContinue).Name -join ', '))
    # 读写验证
    $tmp = Join-Path $target 'e2e_write_test.txt'
    try {
        'written through Z:' | Set-Content $tmp -Encoding UTF8
        $back = Get-Content $tmp -Raw
        L ("  写入回读    : " + ($back.Trim()))
        L ("  源文件同步  : " + (Test-Path (Join-Path $srcDir 'e2e_write_test.txt')))
    } catch { L ("  写入失败: " + $_.Exception.Message) }
} else {
    L ("[失败] 60 秒内 ${target} 未就绪")
}

L ''
L '=== 6. rclone / alist 进程 ==='
L ("rclone: " + (@(Get-Process rclone -EA SilentlyContinue).Count) + "  alist: " + (@(Get-Process alist -EA SilentlyContinue).Count))

$r | Out-File (Join-Path $root 'logs\test-mount.txt') -Encoding utf8
