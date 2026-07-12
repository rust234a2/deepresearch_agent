<#
.SYNOPSIS
  一键构建本地高级检索能力：scope 经营范围语义检索（FAISS）+ GraphRAG 股权/行业图（Neo4j）。

.DESCRIPTION
  幂等脚本。按顺序：前置检查 → 装可选依赖 → 建 FAISS 索引 → 起 Neo4j → SQLite 灌图。
  重复运行安全：已建的索引默认跳过（-Force 强制重建），灌图本身幂等。

  前提：必须先有 SQLite 事实库 data/procurement/derived/companies.sqlite3
  （不在 git 里，须先跑数据管道 clean_qcc_company_data.py + build_company_database.py 生成）。

  注意（能力可迁移性）：FAISS 索引与该 SQLite 库是「成对」的——索引只存向量+chunk 编号，
  取原文要回同一份 SQLite 查；且查询时仍需 bge 模型现场编码问题。故「建完索引给别人零配置直用」
  不成立：别人要么同时拿到 DB+索引+装 .[rag]+下模型（等于分发企查查衍生数据，属数据治理决定），
  要么自己有数据跑本脚本重建。

.PARAMETER WithMemory
  额外安装 mem0 跨会话记忆（.[memory]）。注意：mem0 抽取走云端 DeepSeek、企业名会出本地，
  属核心本地化红线的豁免线，需已设 DEEPSEEK_API_KEY。默认不装。

.PARAMETER Force
  即使 FAISS 索引已存在也重建。

.EXAMPLE
  .\setup.ps1                 # 本地两项：scope + graph
  .\setup.ps1 -WithMemory     # 额外 mem0（云端，需 DEEPSEEK_API_KEY）
  .\setup.ps1 -Force          # 强制重建索引
#>
[CmdletBinding()]
param(
    [switch]$WithMemory,
    [switch]$Force,
    [string]$Database = "data/procurement/derived/companies.sqlite3",
    [string]$Index = "data/procurement/derived/scope_index.faiss",
    [string]$Neo4jPassword = "devpassword"
)

$ErrorActionPreference = "Stop"
$py = ".\.conda-env\python.exe"

function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  [X]  $m" -ForegroundColor Red; exit 1 }

# ---- 0. 前置检查 ----
Step "0/4 前置检查"
if (-not (Test-Path $py)) { Die "找不到 conda 解释器 $py，请在项目根目录运行本脚本。" }
Ok "解释器 $py"
if (-not (Test-Path $Database)) {
    Die @"
缺少 SQLite 事实库：$Database
    它是构建索引/图的前提，且不在 git 里。请先跑数据管道生成：
      $py scripts/clean_qcc_company_data.py --input <企查查导出.xlsx> --output-dir data/procurement/processed
      $py scripts/build_company_database.py
"@
}
Ok "事实库 $Database"
& docker version *> $null
if ($LASTEXITCODE -ne 0) { Die "docker 不可用（未装或未启动 Docker Desktop）。GraphRAG 那步需要它。" }
Ok "docker 可用"

# ---- 1. 安装可选依赖 ----
Step "1/4 安装可选依赖"
$extras = if ($WithMemory) { "rag,neo4j,memory" } else { "rag,neo4j" }
if ($WithMemory -and -not $env:DEEPSEEK_API_KEY) {
    Warn "已选 -WithMemory 但未设 DEEPSEEK_API_KEY；mem0 运行时会静默 no-op（不影响其余能力）。"
}
& $py -m pip install -e ".[$extras]"
if ($LASTEXITCODE -ne 0) { Die "pip 安装失败（extras=$extras）" }
Ok "已装 .[$extras]"

# ---- 2. 构建 FAISS 经营范围索引（幂等）----
Step "2/4 构建 FAISS 经营范围索引"
if ((Test-Path $Index) -and (-not $Force)) {
    Ok "索引已存在，跳过（加 -Force 可强制重建）：$Index"
} else {
    Warn "首次会下载嵌入模型 bge-small-zh-v1.5（~100MB，需联网；国内可能要配 HF 镜像 HF_ENDPOINT）"
    & $py scripts/build_scope_index.py --database $Database --index $Index
    if ($LASTEXITCODE -ne 0) { Die "FAISS 索引构建失败" }
    Ok "索引已建：$Index"
}

# ---- 3. 启动 Neo4j 并等待就绪 ----
Step "3/4 启动 Neo4j 容器"
# 先设连接环境变量，让 docker compose（NEO4J_AUTH 用 ${NEO4J_PASSWORD:-devpassword}）与后续探测/灌图一致
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = $Neo4jPassword
& docker compose up -d
if ($LASTEXITCODE -ne 0) { Die "docker compose up 失败（Docker Desktop 是否已启动？）" }

$probe = "from neo4j import GraphDatabase; import os; d=GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD'])); d.verify_connectivity(); d.close()"
$ready = $false
foreach ($i in 1..30) {
    & $py -c $probe *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Die @"
Neo4j 60 秒内未就绪。若曾用别的密码起过，卷里存的是旧密码，先重置：
    docker compose down -v
再重跑本脚本。
"@
}
Ok "Neo4j 就绪 bolt://localhost:7687（neo4j / $Neo4jPassword）"

# ---- 4. SQLite → Neo4j 灌图（股权 + 行业层；build_ownership_neo4j.py 无 CLI，经 stdin 调其函数）----
Step "4/4 SQLite -> Neo4j 灌图（幂等）"
$loader = @'
import os, sys
sys.path.insert(0, "scripts")
from neo4j import GraphDatabase
from deepresearch_agent.company_repository import CompanyRepository
import build_ownership_neo4j as b

repo = CompanyRepository(sys.argv[1])
driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
)
try:
    b.build_ownership_neo4j(repo, driver)
    b.build_industry_neo4j(repo, driver)
finally:
    driver.close()
print("graph loaded")
'@
$loader | & $py - $Database
if ($LASTEXITCODE -ne 0) { Die "灌图失败" }
Ok "股权 + 行业图已灌入 Neo4j"

# ---- 完成 ----
Step "完成 — 现在可验"
Write-Host @"
  scope 混合检索（能力找公司）:
    $py -m deepresearch_agent.cli "哪些企业能做木材加工机械" --database $Database --index $Index

  GraphRAG 多步（股权/围标线索）:
    $py -m deepresearch_agent.cli "找做数控机械且股东有关联的供应商" --database $Database --graph
"@ -ForegroundColor Green
if ($WithMemory) {
    Write-Host @"
  mem0 跨会话记忆:
    $py -m deepresearch_agent.cli chat --user me --database $Database
    （第一会话提偏好 -> 退出重开 -> 相关问题的报告 open_questions 顶部出现"历史记忆"召回）
"@ -ForegroundColor Green
}
