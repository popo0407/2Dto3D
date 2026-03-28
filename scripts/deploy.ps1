# 2Dto3D デプロイスクリプト (PowerShell)
# 使用方法: .\deploy.ps1 -Environment dev -Action deploy

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "prod")]
    [string]$Environment = "dev",
    
    [Parameter(Mandatory = $false)]
    [ValidateSet("setup", "test", "build", "synth", "deploy", "destroy", "all")]
    [string]$Action = "all"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "2Dto3D デプロイスクリプト" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "環境: $Environment" -ForegroundColor Yellow
Write-Host "アクション: $Action" -ForegroundColor Yellow
Write-Host ""

# ========== 環境確認 ==========
function Check-Prerequisites {
    Write-Host "⏳ 前提条件を確認しています..." -ForegroundColor Cyan
    
    $checks = @(
        @{ cmd = "python --version"; name = "Python 3.12+" },
        @{ cmd = "node --version"; name = "Node.js 18+" },
        @{ cmd = "aws --version"; name = "AWS CLI v2" }
    )
    
    foreach ($check in $checks) {
        try {
            $output = Invoke-Expression $check.cmd 2>&1
            Write-Host "✓ $($check.name): $output" -ForegroundColor Green
        }
        catch {
            Write-Host "✗ $($check.name) が見つかりません" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host ""
}

# ========== バックエンド環境構築 ==========
function Setup-Backend {
    Write-Host "⏳ バックエンド環境を構築しています..." -ForegroundColor Cyan
    
    $venvPath = Join-Path $projectRoot "backend" ".venv"
    
    # venv 作成
    if (-not (Test-Path $venvPath)) {
        Write-Host "venv を作成しています..."
        python -m venv $venvPath
    }
    
    # venv 有効化
    $activateScript = Join-Path $venvPath "Scripts" "Activate.ps1"
    & $activateScript
    
    # 依存関係インストール
    Write-Host "Python依存関係をインストールしています..."
    pip install --upgrade pip setuptools wheel
    pip install -r (Join-Path $projectRoot "backend" "requirements.txt")
    pip install -r (Join-Path $projectRoot "backend" "requirements-test.txt")
    
    Write-Host "✓ バックエンド環境構築完了" -ForegroundColor Green
    Write-Host ""
}

# ========== バックエンドテスト ==========
function Run-Backend-Tests {
    Write-Host "⏳ バックエンドテストを実行しています..." -ForegroundColor Cyan
    
    $backendPath = Join-Path $projectRoot "backend"
    Push-Location $backendPath
    
    try {
        $env:PYTHONPATH = $backendPath
        pytest tests/ -v --tb=short
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ バックエンドテスト成功" -ForegroundColor Green
        }
        else {
            Write-Host "✗ バックエンドテスト失敗" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== フロントエンド構築 ==========
function Setup-Frontend {
    Write-Host "⏳ フロントエンドを構築しています..." -ForegroundColor Cyan
    
    $frontendPath = Join-Path $projectRoot "frontend"
    Push-Location $frontendPath
    
    try {
        Write-Host "npm 依存関係をインストールしています..."
        npm install
        
        Write-Host "ビルドを実行しています..."
        npm run build
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ フロントエンドビルド成功" -ForegroundColor Green
        }
        else {
            Write-Host "✗ フロントエンドビルド失敗" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== CDK 初期化 ==========
function Setup-CDK {
    Write-Host "⏳ CDK 環境を初期化しています..." -ForegroundColor Cyan
    
    $cdkPath = Join-Path $projectRoot "cdk"
    Push-Location $cdkPath
    
    try {
        # CDK venv 作成
        $venvPath = Join-Path $cdkPath ".venv"
        if (-not (Test-Path $venvPath)) {
            Write-Host "CDK venv を作成しています..."
            python -m venv $venvPath
        }
        
        # venv 有効化
        $activateScript = Join-Path $venvPath "Scripts" "Activate.ps1"
        & $activateScript
        
        # CDK 依存関係インストール
        Write-Host "CDK 依存関係をインストールしています..."
        pip install --upgrade pip
        pip install -r requirements-cdk.txt
        
        Write-Host "✓ CDK 初期化完了" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== CDK Synth ==========
function Run-CDK-Synth {
    Write-Host "⏳ CDK Synth を実行しています... ($Environment)" -ForegroundColor Cyan
    
    $cdkPath = Join-Path $projectRoot "cdk"
    Push-Location $cdkPath
    
    try {
        $activateScript = Join-Path ".venv" "Scripts" "Activate.ps1"
        & $activateScript
        
        cdk synth --context environment=$Environment
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ CDK Synth 成功" -ForegroundColor Green
        }
        else {
            Write-Host "✗ CDK Synth 失敗" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== CDK Diff ==========
function Show-CDK-Diff {
    Write-Host "⏳ CDK コンフリクトを確認しています... ($Environment)" -ForegroundColor Cyan
    
    $cdkPath = Join-Path $projectRoot "cdk"
    Push-Location $cdkPath
    
    try {
        $activateScript = Join-Path ".venv" "Scripts" "Activate.ps1"
        & $activateScript
        
        Write-Host "差分内容:" -ForegroundColor Yellow
        cdk diff --context environment=$Environment
        
        if ($Environment -eq "prod") {
            Write-Host ""
            Write-Host "⚠️  本番環境へのデプロイが必要です。手動で確認してください。" -ForegroundColor Red
            Write-Host "実行コマンド: cd cdk && cdk deploy --context environment=prod" -ForegroundColor Yellow
        }
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== CDK Deploy ==========
function Run-CDK-Deploy {
    Write-Host "⏳ CDK デプロイを実行しています... ($Environment)" -ForegroundColor Cyan
    
    if ($Environment -eq "prod") {
        Write-Host ""
        Write-Host "⚠️  本番環境へのデプロイが要求されました。" -ForegroundColor Red
        Write-Host "⚠️  本スクリプトは dev 環境のみ自動デプロイ可能です。" -ForegroundColor Red
        Write-Host "⚠️  本番環境へのデプロイは以下のコマンドで手動実行してください:" -ForegroundColor Yellow
        Write-Host "cd cdk && cdk deploy --context environment=prod" -ForegroundColor Yellow
        Write-Host ""
        
        Write-Host "続行しますか? (yes/no): " -ForegroundColor Yellow -NoNewline
        $response = Read-Host
        
        if ($response -ne "yes") {
            Write-Host "✗ デプロイがキャンセルされました" -ForegroundColor Red
            exit 0
        }
    }
    
    $cdkPath = Join-Path $projectRoot "cdk"
    Push-Location $cdkPath
    
    try {
        $activateScript = Join-Path ".venv" "Scripts" "Activate.ps1"
        & $activateScript
        
        Write-Host "デプロイを実行しています..."
        cdk deploy --context environment=$Environment --require-approval never
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ CDK デプロイ成功" -ForegroundColor Green
        }
        else {
            Write-Host "✗ CDK デプロイ失敗" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== CDK Destroy ==========
function Run-CDK-Destroy {
    Write-Host "⏳ CDK スタックを削除しています... ($Environment)" -ForegroundColor Cyan
    
    Write-Host ""
    Write-Host "⚠️  スタックの削除は取り消せません!" -ForegroundColor Red
    Write-Host "続行しますか? (yes/no): " -ForegroundColor Yellow -NoNewline
    $response = Read-Host
    
    if ($response -ne "yes") {
        Write-Host "✗ 削除がキャンセルされました" -ForegroundColor Red
        exit 0
    }
    
    $cdkPath = Join-Path $projectRoot "cdk"
    Push-Location $cdkPath
    
    try {
        $activateScript = Join-Path ".venv" "Scripts" "Activate.ps1"
        & $activateScript
        
        cdk destroy --context environment=$Environment
    }
    finally {
        Pop-Location
    }
    Write-Host ""
}

# ========== メイン実行ロジック ==========
try {
    Check-Prerequisites
    
    switch ($Action) {
        "setup" {
            Setup-Backend
            Setup-Frontend
            Setup-CDK
        }
        "test" {
            Setup-Backend
            Run-Backend-Tests
        }
        "build" {
            Setup-Frontend
        }
        "synth" {
            Setup-CDK
            Run-CDK-Synth
        }
        "deploy" {
            Setup-Backend
            Run-Backend-Tests
            Setup-Frontend
            Setup-CDK
            Show-CDK-Diff
            Run-CDK-Deploy
        }
        "destroy" {
            Setup-CDK
            Run-CDK-Destroy
        }
        "all" {
            Setup-Backend
            Run-Backend-Tests
            Setup-Frontend
            Setup-CDK
            Show-CDK-Diff
            Run-CDK-Deploy
        }
    }
    
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "✓ デプロイスクリプト完了" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    
}
catch {
    Write-Host ""
    Write-Host "✗ エラーが発生しました:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
