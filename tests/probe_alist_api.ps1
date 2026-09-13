param([string]$Pass = 'TestPass12345')
# probe_alist_api.ps1 - 探测 Alist 存储管理接口真实路径（在同一进程调用内完成，避免子进程被回收）
$root='C:\Users\22303\Desktop\winmount'
$r=@()
function L($m){ $script:r += $m; Write-Output $m }

# 1) 起 Alist
$up=$false
try { $up = (Invoke-WebRequest 'http://127.0.0.1:5244/' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $up=$false }
if(-not $up){
    Start-Process -FilePath 'C:\CloudDrive\tools\alist.exe' -ArgumentList 'server' -WorkingDirectory 'C:\CloudDrive' -WindowStyle Hidden
    for($i=0;$i -lt 60 -and -not $up;$i++){ Start-Sleep -Seconds 1; try{ $up=(Invoke-WebRequest 'http://127.0.0.1:5244/' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }catch{ $up=$false } }
}
L "Alist 就绪: $up"

# 2) 登录
$token=''
try{
  $l=Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5244/api/auth/login' -ContentType 'application/json' -Body (@{username='admin';password=$Pass}|ConvertTo-Json) -TimeoutSec 15
  $token=$l.data.token
  L ("login code=" + $l.code + " token=" + [bool]$token)
}catch{ L ("login 失败: " + $_.Exception.Message) }

# 3) 探测候选路由
$hdr=@{Authorization=$token}
$candidates = @(
  @{m='GET';  u='/api/storage/list'},
  @{m='GET';  u='/api/admin/storage/list'},
  @{m='GET';  u='/api/admin/storage/list?page=1&per_page=10'},
  @{m='GET';  u='/api/me'}
)
foreach($c in $candidates){
  try{
    $resp=Invoke-WebRequest -Method $c.m -Uri ("http://127.0.0.1:5244"+$c.u) -Headers $hdr -TimeoutSec 15 -UseBasicParsing
    $body=$resp.Content
    $isHtml = $body.TrimStart().StartsWith('<')
    L ("{0} {1,-45} => {2}  html={3}  {4}" -f $c.m,$c.u,$resp.StatusCode,$isHtml,($body.Substring(0,[Math]::Min(160,$body.Length)) -replace "`r?`n",' '))
  }catch{ L ("{0} {1,-45} => ERR {2}" -f $c.m,$c.u,$_.Exception.Message) }
}

# 4) 尝试用 fs 接口看根目录
try{
  $b=@{path='/'}|ConvertTo-Json
  $resp=Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:5244/api/fs/list' -Headers $hdr -ContentType 'application/json' -Body $b -TimeoutSec 15 -UseBasicParsing
  L ("POST /api/fs/list => " + $resp.StatusCode + " " + ($resp.Content.Substring(0,[Math]::Min(200,$resp.Content.Length))))
}catch{ L ("POST /api/fs/list => ERR " + $_.Exception.Message) }

# 5) 试探 create 的真实路径（只试 /api/admin/storage/create）
try{
  $addition=@{root_folder_path='C:\CloudMountTestData';thumbnail=$false;show_hidden=$true;mkdir_perm='777';recycle_bin=''}|ConvertTo-Json -Compress
  $body=@{mount_path='/test';order=0;remark='e2e';cache_expiration=30;web_proxy=$false;webdav_policy='native_proxy';down_proxy_url='';disable_index=$false;enable_sign=$false;driver='Local';addition=$addition;order_by='name';order_direction='asc';extract_folder='front';status='work'}|ConvertTo-Json -Depth 6
  $resp=Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:5244/api/admin/storage/create' -Headers $hdr -ContentType 'application/json' -Body $body -TimeoutSec 20 -UseBasicParsing
  L ("POST /api/admin/storage/create => " + $resp.StatusCode + " " + ($resp.Content.Substring(0,[Math]::Min(200,$resp.Content.Length))))
}catch{ L ("POST /api/admin/storage/create => ERR " + $_.Exception.Message) }

# 6) PROPFIND 看看 /dav/test 通不通
try{
  $req=[System.Net.HttpWebRequest]::Create('http://127.0.0.1:5244/dav/test/')
  $req.Method='PROPFIND'; $req.Headers['Authorization']=$token; $req.Timeout=15000
  $rs=$req.GetResponse(); L ("PROPFIND /dav/test/ => " + [int]$rs.StatusCode)
  $sr=New-Object System.IO.StreamReader($rs.GetResponseStream()); L ("  响应片段: " + ($sr.ReadToEnd().Substring(0,120)))
}catch{ L ("PROPFIND /dav/test/ => ERR " + $_.Exception.Message) }

$r | Out-File (Join-Path $root 'logs\test-alist-api.txt') -Encoding utf8
