<#
.SYNOPSIS
  启动 Windows 本机测试环境：Neo4j + FastAPI 后端（后端同时伺服已构建的前端）。

.DESCRIPTION
  本机没有 RK3588 NPU / RKLLM 推理服务，脚本**不启动任何大模型**：
  后端调用模型失败会自动降级为规则摘要，报告照常生成（provenance.llm_used=false 且带 llm_error）。
  知识图谱（Neo4j）保留：/api/health/ready、检测项、评估依据等接口依赖它。

  运行时文件都在 backend\data\ 下（.gitignore 已忽略）：
    业务库     backend\data\elevator.db
    备份       backend\data\backups\
    导出       backend\data\exports\
    日志/PID   backend\data\logs\

.PARAMETER Build
  强制重新构建前端（npm run build：vue-tsc + vite build + prune）。
.PARAMETER Dev
  额外启动 Vite 开发服务器（http://127.0.0.1:5173，热更新，/api 代理到 8081）。
.PARAMETER SkipNeo4j
  不检查/启动 Neo4j 服务（只调试业务库相关接口时可用）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\dev\start-test-env.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\dev\start-test-env.ps1 -Dev
#>
param(
  [switch]$Build,
  [switch]$Dev,
  [switch]$SkipNeo4j
)

$ErrorActionPreference = 'Stop'
# 让 uvicorn 的 stdout 立即写进日志文件（否则被块缓冲，排障时看不到启动/请求日志）
$env:PYTHONUNBUFFERED = '1'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend = Join-Path $Root 'backend'
$Web = Join-Path $Root 'web'
$Python = 'D:\miniconda3\envs\elevator_kg\python.exe'
$LogDir = Join-Path $Backend 'data\logs'
$null = New-Item -ItemType Directory -Force -Path $LogDir

function Wait-Port([int]$Port, [int]$Seconds = 60) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Start-Detached([string]$Exe, [string[]]$Arguments, [string]$WorkDir, [string]$OutLog, [string]$ErrLog) {
  return Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $WorkDir -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -WindowStyle Hidden -PassThru
}

Write-Host '== 电梯安全评估系统 · Windows 本机测试环境 ==' -ForegroundColor Cyan

if (-not (Test-Path $Python)) { throw "找不到 Python：$Python（见 docs\本地测试环境部署-Windows.md）" }
if (-not (Test-Path (Join-Path $Backend '.env'))) { throw '缺少 backend\.env：请按 docs\本地测试环境部署-Windows.md 生成（.env 已被 .gitignore 忽略）' }

# ── 1/4 Neo4j 知识图谱 ──────────────────────────────────
if (-not $SkipNeo4j) {
  $svc = Get-Service -Name neo4j -ErrorAction SilentlyContinue
  if ($null -eq $svc) {
    Write-Warning '[1/4] 未找到名为 neo4j 的 Windows 服务，跳过（图谱相关接口会不可用）'
  } elseif ($svc.Status -ne 'Running') {
    Write-Host '[1/4] 启动 Neo4j 服务...'
    Start-Service neo4j
  } else {
    Write-Host '[1/4] Neo4j 服务已在运行'
  }
  if (-not (Wait-Port 7687 60)) {
    Write-Warning '[1/4] Neo4j 7687 端口 60s 内未就绪；后端可启动，但 /api/health/ready 会 503'
  }
} else {
  Write-Host '[1/4] 按参数跳过 Neo4j'
}

# ── 2/4 前端产物 ────────────────────────────────────────
$distIndex = Join-Path $Web 'dist\index.html'
if ($Build -or -not (Test-Path $distIndex)) {
  Write-Host '[2/4] 构建前端产物（npm run build）...'
  Push-Location $Web
  try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build 失败' }
  } finally { Pop-Location }
} else {
  Write-Host "[2/4] 前端产物已存在：$distIndex（加 -Build 可强制重建）"
}

# ── 3/4 后端（8081，同时伺服前端）───────────────────────
$backendPidFile = Join-Path $LogDir 'backend-8081.pid'
$backendAlive = $false
if (Test-Path $backendPidFile) {
  $raw = (Get-Content $backendPidFile -Raw).Trim()
  if ($raw -match '^\d+$' -and (Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue)) { $backendAlive = $true }
}
if (-not $backendAlive) {
  if (Get-NetTCPConnection -State Listen -LocalPort 8081 -ErrorAction SilentlyContinue) {
    throw '8081 已被其它进程占用：先执行 tools\dev\stop-test-env.ps1'
  }
  Write-Host '[3/4] 启动后端 127.0.0.1:8081 ...'
  $backendArgs = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8081')
  $proc = Start-Detached -Exe $Python -Arguments $backendArgs -WorkDir $Backend -OutLog (Join-Path $LogDir 'backend-8081.log') -ErrLog (Join-Path $LogDir 'backend-8081.err.log')
  Set-Content -Path $backendPidFile -Value $proc.Id -Encoding ascii
} else {
  Write-Host '[3/4] 后端已在运行'
}

$ready = $false
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
  try {
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:8081/api/health/ready' -TimeoutSec 5
    if ($resp.ready) { $ready = $true; break }
  } catch { Start-Sleep -Milliseconds 800 }
}
if ($ready) {
  Write-Host '      后端就绪（业务库 + Neo4j 均可用）'
} else {
  Write-Warning "后端未在 60s 内就绪，请查看 $LogDir\backend-8081.err.log"
}

# ── 4/4 可选 Vite 开发服务器 ────────────────────────────
if ($Dev) {
  $vitePidFile = Join-Path $LogDir 'vite-5173.pid'
  $viteAlive = $false
  if (Test-Path $vitePidFile) {
    $raw = (Get-Content $vitePidFile -Raw).Trim()
    if ($raw -match '^\d+$' -and (Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue)) { $viteAlive = $true }
  }
  if (-not $viteAlive) {
    if (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue) {
      Write-Warning '5173 已被其它进程占用，跳过 Vite'
    } else {
      Write-Host '[4/4] 启动 Vite 开发服务器 127.0.0.1:5173 ...'
      $node = (Get-Command node -ErrorAction Stop).Source
      $viteJs = Join-Path $Web 'node_modules\vite\bin\vite.js'
      $viteArgs = @($viteJs,'--host','127.0.0.1','--port','5173')
      $proc = Start-Detached -Exe $node -Arguments $viteArgs -WorkDir $Web -OutLog (Join-Path $LogDir 'vite-5173.log') -ErrLog (Join-Path $LogDir 'vite-5173.err.log')
      Set-Content -Path $vitePidFile -Value $proc.Id -Encoding ascii
      $null = Wait-Port 5173 30
    }
  } else {
    Write-Host '[4/4] Vite 已在运行'
  }
} else {
  Write-Host '[4/4] 未启用 Vite 开发服务器（需要热更新时加 -Dev）'
}

Write-Host ''
Write-Host '──────────────────────────────────────────────' -ForegroundColor DarkGray
Write-Host '  系统入口（后端同源伺服前端）: http://127.0.0.1:8081' -ForegroundColor Green
if ($Dev) { Write-Host '  开发入口（Vite 热更新）      : http://127.0.0.1:5173' -ForegroundColor Green }
Write-Host '  登录账号                     : admin / admin123'
Write-Host "  业务库                       : $Backend\data\elevator.db"
Write-Host "  日志                         : $LogDir"
Write-Host '  停止环境                     : powershell -ExecutionPolicy Bypass -File tools\dev\stop-test-env.ps1'
Write-Host '──────────────────────────────────────────────' -ForegroundColor DarkGray
