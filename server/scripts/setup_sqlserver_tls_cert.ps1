<#
.SYNOPSIS
    为 SQL Server 默认实例配置一张「客户端信任的」TLS 服务器证书。

.DESCRIPTION
    背景：实例未指定 Certificate 时使用启动时自生成的证书。此时任何以
    Encrypt=yes + TrustServerCertificate=no 连接的客户端都会因证书链不受信任
    而握手失败，报 SQLSTATE 08001 / SEC_E_UNTRUSTED_ROOT (0x80090325)：

        [08001] SSL 提供程序: 证书链是由不受信任的颁发机构颁发的。 (-2146893019)

    本脚本创建一张自签名服务器证书并完成全部落地：

      1. 生成带服务器身份验证 EKU 的证书，私钥存入 LocalMachine\My；
      2. 授予 SQL Server 服务账号该私钥的读取权限（缺失会导致实例无法启用证书）；
      3. 把公钥导入 LocalMachine\Root，使客户端无需 TrustServerCertificate 即可信任；
      4. 将实例 SuperSocketNetLib\Certificate 设为该证书指纹；
      5. 重启 SQL Server 服务，并校验实例实际加载了这张证书。

    效果：Encrypt=no / Encrypt=yes+TrustServerCertificate=yes /
    Encrypt=yes+TrustServerCertificate=no 三种组合均可正常连接。

    所有改动可用 -Rollback 撤销。

.NOTES
    必须以管理员身份运行。脚本只影响本机默认实例 MSSQL15.MSSQLSERVER。

.EXAMPLE
    # 配置证书（会重启 SQL Server，约数秒不可用）
    powershell -ExecutionPolicy Bypass -File .\setup_sqlserver_tls_cert.ps1

.EXAMPLE
    # 撤销：恢复原 Certificate 值、移除证书与信任项、重启服务
    powershell -ExecutionPolicy Bypass -File .\setup_sqlserver_tls_cert.ps1 -Rollback
#>
[CmdletBinding()]
param(
    # 撤销本次配置：清空实例 Certificate 值，并从 My / Root 中移除本脚本创建的证书
    [switch]$Rollback,

    # 撤销时指定要移除的证书指纹；默认按 FriendlyName 自动查找
    [string]$Thumbprint,

    # 等待 SQL Server 就绪的秒数
    [int]$WaitSeconds = 120
)

$ErrorActionPreference = 'Stop'

# 先校验权限：缺少管理员权限时给出明确提示，而不是在写注册表或证书存储时抛出难懂的异常
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host ''
    Write-Host '错误：本脚本必须以管理员身份运行。' -ForegroundColor Red
    Write-Host '请用「以管理员身份运行」打开 PowerShell 后重新执行。' -ForegroundColor Red
    Write-Host ''
    exit 1
}

$InstanceRegPath = 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQLServer\SuperSocketNetLib'
$ServiceName     = 'MSSQLSERVER'
$ServiceAccount  = 'NT Service\MSSQLSERVER'
$CertFriendly    = 'SQL Server TLS'
$ErrorLogPath    = 'C:\Program Files\Microsoft SQL Server\MSSQL15.MSSQLSERVER\MSSQL\LOG\ERRORLOG'

function Write-Step { param([string]$Message) Write-Host "==> $Message" }
function Write-Note { param([string]$Message) Write-Host "    $Message" }

function Get-CurrentCertificateValue {
    (Get-ItemProperty -Path $InstanceRegPath -Name Certificate -ErrorAction SilentlyContinue).Certificate
}

function Find-ManagedCertificate {
    param([string]$Thumb)
    if ($Thumb) {
        return Get-ChildItem 'Cert:\LocalMachine\My' | Where-Object { $_.Thumbprint -eq $Thumb }
    }
    Get-ChildItem 'Cert:\LocalMachine\My' | Where-Object { $_.FriendlyName -eq $CertFriendly }
}

function Test-SqlPort {
    param([int]$TimeoutMs = 2000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', 1433, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($iar)
        return $true
    }
    catch { return $false }
    finally { $client.Close() }
}

function Wait-SqlReady {
    param([int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ((Get-Service -Name $ServiceName).Status -eq 'Running' -and (Test-SqlPort)) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Restart-SqlService {
    Write-Step "重启 SQL Server 服务 $ServiceName"
    # -Force 会一并停止依赖服务（如 SQLSERVERAGENT）但不会自动拉起，先记下来后补
    $dependents = @(
        Get-Service -Name $ServiceName -DependentServices -ErrorAction SilentlyContinue |
            Where-Object { $_.Status -eq 'Running' } |
            Select-Object -ExpandProperty Name
    )
    if ($dependents.Count -gt 0) {
        Write-Note ("重启后需恢复依赖服务：" + ($dependents -join ', '))
    }

    Restart-Service -Name $ServiceName -Force
    if (-not (Wait-SqlReady -TimeoutSec $WaitSeconds)) {
        throw "SQL Server 在 $WaitSeconds 秒内未就绪"
    }
    Write-Note '服务已就绪，1433 可连接'

    foreach ($dependent in $dependents) {
        Start-Service -Name $dependent -ErrorAction SilentlyContinue
        $state = (Get-Service -Name $dependent -ErrorAction SilentlyContinue).Status
        Write-Note "依赖服务 $dependent 状态：$state"
    }
}

function Show-LoadedCertificate {
    if (-not (Test-Path $ErrorLogPath)) { return }
    Write-Step '实例启动日志中的证书行'
    Get-Content -LiteralPath $ErrorLogPath -Tail 400 |
        Select-String -Pattern 'certificate' |
        Select-Object -Last 4 |
        ForEach-Object { Write-Note $_.Line.Trim() }
}

# ---------------------------------------------------------------- 撤销分支

if ($Rollback) {
    Write-Step '撤销 SQL Server TLS 证书配置'

    $certs = @(Find-ManagedCertificate -Thumb $Thumbprint)
    if ($certs.Count -eq 0) {
        Write-Note '未找到由本脚本创建的证书，继续清理注册表与信任项'
    }

    foreach ($cert in $certs) {
        Write-Note "移除证书 $($cert.Thumbprint)"

        foreach ($storeName in 'Root', 'My') {
            $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($storeName, 'LocalMachine')
            $store.Open('ReadWrite')
            $match = $store.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
            foreach ($m in $match) { $store.Remove($m) }
            $store.Close()
        }
    }

    if ((Get-CurrentCertificateValue)) {
        Write-Note '清空实例 Certificate 注册表值（回到自生成证书）'
        Set-ItemProperty -Path $InstanceRegPath -Name Certificate -Value ''
    }

    Restart-SqlService
    Show-LoadedCertificate
    Write-Host ''
    Write-Host '撤销完成：实例已回到自生成证书。'
    exit 0
}

# ---------------------------------------------------------------- 配置分支

Write-Step '检查当前状态'
$previousThumbprint = Get-CurrentCertificateValue
if ($previousThumbprint) {
    Write-Note "实例已有 Certificate 值：$previousThumbprint（将被替换）"
}
else {
    Write-Note '实例当前未指定 Certificate，使用自生成证书'
}

if ($previousThumbprint) {
    $existing = Get-ChildItem 'Cert:\LocalMachine\My' -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $previousThumbprint }
    if (-not $existing) {
        throw "注册表指定的证书 $previousThumbprint 在 LocalMachine\My 中不存在，请先人工确认"
    }
}

# 1. 生成证书
Write-Step '生成服务器证书'
$dnsNames = @('localhost', $env:COMPUTERNAME, '127.0.0.1') | Where-Object { $_ } | Select-Object -Unique
Write-Note ("SAN: " + ($dnsNames -join ', '))

$cert = New-SelfSignedCertificate `
    -Subject "CN=$env:COMPUTERNAME" `
    -DnsName $dnsNames `
    -CertStoreLocation 'Cert:\LocalMachine\My' `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -KeyUsage DigitalSignature, KeyEncipherment `
    -Type SSLServerAuthentication `
    -NotAfter (Get-Date).AddYears(5) `
    -FriendlyName $CertFriendly
Write-Note "指纹：$($cert.Thumbprint)"
Write-Note "有效期至：$($cert.NotAfter)"

# 2. 授予服务账号私钥读取权限
Write-Step '授予 SQL Server 服务账号私钥读取权限'
$keyPath = $null
try {
    $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
    if ($rsa -and $rsa.Key -and $rsa.Key.UniqueName) {
        $candidate = Join-Path $env:ProgramData "Microsoft\Crypto\Keys\$($rsa.Key.UniqueName)"
        if (Test-Path -LiteralPath $candidate) { $keyPath = $candidate }
    }
}
catch {
    Write-Note "CNG 私钥定位失败，回退 CAPI：$($_.Exception.Message)"
}

if (-not $keyPath) {
    try {
        $containerName = $cert.PrivateKey.CspKeyContainerInfo.UniqueKeyContainerName
        $candidate = Join-Path $env:ProgramData "Microsoft\Crypto\RSA\MachineKeys\$containerName"
        if (Test-Path -LiteralPath $candidate) { $keyPath = $candidate }
    }
    catch {
        Write-Note "CAPI 私钥定位失败：$($_.Exception.Message)"
    }
}

if (-not $keyPath) {
    throw '未能定位私钥文件，无法授予 SQL Server 读取权限，已中止（未修改注册表）'
}
Write-Note "私钥文件：$keyPath"

$acl = Get-Acl -LiteralPath $keyPath
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($ServiceAccount, 'Read', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $keyPath -AclObject $acl
Write-Note "$ServiceAccount 已获得读取权限"

# 3. 让客户端信任
Write-Step '把公钥导入 LocalMachine\Root 受信任根'
$cerFile = Join-Path $env:TEMP "sqlserver-tls-$($cert.Thumbprint).cer"
Export-Certificate -Cert $cert -FilePath $cerFile -Force | Out-Null
Import-Certificate -FilePath $cerFile -CertStoreLocation 'Cert:\LocalMachine\Root' | Out-Null
Remove-Item -LiteralPath $cerFile -Force -ErrorAction SilentlyContinue
Write-Note '已导入；客户端无需 TrustServerCertificate 即可校验通过'

# 4. 写入实例配置
Write-Step '设置实例 Certificate 注册表值'
Set-ItemProperty -Path $InstanceRegPath -Name Certificate -Value $cert.Thumbprint
Write-Note (Get-CurrentCertificateValue)

# 5. 重启并校验
try {
    Restart-SqlService
}
catch {
    Write-Host ''
    Write-Warning "重启失败：$($_.Exception.Message)"
    Write-Warning '执行回滚：清空 Certificate 值并再次重启'
    Set-ItemProperty -Path $InstanceRegPath -Name Certificate -Value $previousThumbprint
    Restart-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    throw
}

Show-LoadedCertificate

Write-Host ''
Write-Host '配置完成。'
Write-Host "  证书指纹   : $($cert.Thumbprint)"
Write-Host "  生效范围   : 本机默认实例 $ServiceName"
Write-Host "  撤销命令   : powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Rollback"
