<#
.SYNOPSIS
  停止 Windows 本机测试环境（后端 8081 / Vite 5173，可选 Neo4j）。

.DESCRIPTION
  先按 backend\data\logs 下的 PID 文件停止；随后**无条件**再做一次命令行扫描，
  清掉旧会话 / 手工用 start.bat 或 npm run dev 启动的残留进程。
  扫描只匹配 python.exe / node.exe 且命令行含本项目特征（uvicorn app.main:app、
  本仓库 node_modules 下的 vite），不会误伤本脚本自身或其它程序。

.PARAMETER IncludeNeo4j
  同时停止 Neo4j Windows 服务（默认保留，避免下次启动等它冷启动）。
#>
param([switch]$IncludeNeo4j)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$LogDir = Join-Path $Root 'backend\data\logs'

function Stop-ByPidFile([string]$PidFile, [string]$Label) {
  if (-not (Test-Path $PidFile)) { return $false }
  $raw = (Get-Content $PidFile -Raw).Trim()
  if ($raw -match '^\d+$') {
    $procId = [int]$raw
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
      & taskkill /PID $procId /T /F | Out-Null
      Write-Host "已停止 $Label（PID $procId）"
    } else {
      Write-Host "$Label 的 PID 文件存在，但进程 $procId 已不存在"
    }
  }
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
  return $true
}

function Stop-ByCommandLine([string]$Pattern, [string]$Label) {
  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -in @('python.exe', 'node.exe') -and $_.CommandLine -and $_.CommandLine -match $Pattern
  }
  foreach ($p in $procs) {
    & taskkill /PID $p.ProcessId /T /F | Out-Null
    Write-Host "已停止 $Label（PID $($p.ProcessId)，按命令行匹配）"
  }
  return @($procs).Count
}

Write-Host '== 停止 Windows 本机测试环境 ==' -ForegroundColor Cyan

$backendPid = Stop-ByPidFile (Join-Path $LogDir 'backend-8081.pid') '后端 8081'
$backendSweep = Stop-ByCommandLine 'uvicorn\s+app\.main:app' '后端（uvicorn app.main:app）'
if (-not $backendPid -and $backendSweep -eq 0) { Write-Host '后端未在运行' }

$vitePid = Stop-ByPidFile (Join-Path $LogDir 'vite-5173.pid') 'Vite 5173'
$viteSweep = Stop-ByCommandLine 'vite[\\/]bin[\\/]vite\.js' 'Vite（本项目 vite）'
if (-not $vitePid -and $viteSweep -eq 0) { Write-Host 'Vite 未在运行' }

if ($IncludeNeo4j) {
  $svc = Get-Service -Name neo4j -ErrorAction SilentlyContinue
  if ($svc -and $svc.Status -eq 'Running') {
    Stop-Service neo4j
    Write-Host '已停止 Neo4j 服务'
  } else {
    Write-Host 'Neo4j 服务未运行或不存在'
  }
} else {
  Write-Host 'Neo4j 服务保持运行（需要一起停时加 -IncludeNeo4j）'
}

Start-Sleep -Milliseconds 500
Write-Host '--- 端口状态 ---'
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in 8080, 8081, 5173 } |
  Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
