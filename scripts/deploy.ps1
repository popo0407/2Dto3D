# 2Dto3D Deployment Script (PowerShell)
# Usage: .\deploy.ps1 -Environment dev -Action deploy

param(
    [ValidateSet("dev", "prod")]
    [string]$Environment = "dev",
    
    [ValidateSet("setup", "test", "build", "synth", "deploy", "destroy", "all")]
    [string]$Action = "all"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "2Dto3D Deploy Script" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Action: $Action" -ForegroundColor Yellow
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Cyan
python --version | Out-Null
node --version | Out-Null
aws --version | Out-Null
Write-Host "✓ All prerequisites OK" -ForegroundColor Green
Write-Host ""

# Run Backend Tests
function Run-Backend-Tests {
    Write-Host "Running backend tests..." -ForegroundColor Cyan
    Set-Location "$projectRoot\backend"
    
    Write-Host "Installing test dependencies..."
    python -m pip install --user -r requirements-test.txt
    
    $env:PYTHONPATH = "$projectRoot\backend"
    pytest tests/ -v --tb=short
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Backend tests failed" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "✓ Backend tests passed" -ForegroundColor Green
    Set-Location $projectRoot
}

# Setup Frontend
function Setup-Frontend {
    Write-Host "Setting up frontend..." -ForegroundColor Cyan
    Set-Location "$projectRoot\frontend"
    
    npm install
    npm run build
    
    Write-Host "✓ Frontend setup complete" -ForegroundColor Green
    Set-Location $projectRoot
}

# Setup CDK
function Setup-CDK {
    Write-Host "Setting up CDK..." -ForegroundColor Cyan
    Set-Location "$projectRoot\cdk"
    
    Write-Host "Installing CDK dependencies..."
    python -m pip install --user -r requirements-cdk.txt
    
    Write-Host "✓ CDK setup complete" -ForegroundColor Green
    Set-Location $projectRoot
}

# Run CDK Synth
function Run-CDK-Synth {
    Write-Host "Running CDK synth ($Environment)..." -ForegroundColor Cyan
    Set-Location "$projectRoot\cdk"
    
    cdk synth --context environment=$Environment
    
    Write-Host "✓ CDK synth complete" -ForegroundColor Green
    Set-Location $projectRoot
}

# Show CDK Diff
function Show-CDK-Diff {
    Write-Host "Showing CDK diff ($Environment)..." -ForegroundColor Cyan
    Set-Location "$projectRoot\cdk"
    
    cdk diff --context environment=$Environment
    
    Set-Location $projectRoot
}

# Run CDK Deploy
function Run-CDK-Deploy {
    Write-Host "Running CDK deploy ($Environment)..." -ForegroundColor Cyan
    Set-Location "$projectRoot\cdk"
    
    cdk deploy --context environment=$Environment --require-approval never
    
    Write-Host "✓ CDK deploy complete" -ForegroundColor Green
    Set-Location $projectRoot
}

# Run CDK Destroy
function Run-CDK-Destroy {
    Write-Host "Warning: This will destroy all AWS resources!" -ForegroundColor Red
    $response = Read-Host "Continue? (yes/no)"
    
    if ($response -ne "yes") {
        Write-Host "Cancelled" -ForegroundColor Yellow
        return
    }
    
    Set-Location "$projectRoot\cdk"
    cdk destroy --context environment=$Environment
    Set-Location $projectRoot
}

# Main execution
try {
    switch ($Action) {
        "setup" {
            Setup-Frontend
            Setup-CDK
        }
        "test" {
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
            Run-Backend-Tests
            Setup-Frontend
            Setup-CDK
            Show-CDK-Diff
            Run-CDK-Deploy
        }
        "destroy" {
            Run-CDK-Destroy
        }
        "all" {
            Run-Backend-Tests
            Setup-Frontend
            Setup-CDK
            Show-CDK-Diff
            Run-CDK-Deploy
        }
    }
    
    Write-Host ""
    Write-Host "=======================================" -ForegroundColor Cyan
    Write-Host "✓ Deployment complete" -ForegroundColor Green
    Write-Host "=======================================" -ForegroundColor Cyan
}
catch {
    Write-Host ""
    Write-Host "✗ Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
