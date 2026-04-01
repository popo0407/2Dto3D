#!/bin/bash

# 2Dto3D Deployment Script (Bash/Linux)
# Usage: bash scripts/deploy.sh [dev|prod] [setup|test|build|synth|deploy|destroy|all]

set -e

ENVIRONMENT="${1:-dev}"
ACTION="${2:-all}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Validate inputs
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod)$ ]]; then
    echo "❌ Invalid environment: $ENVIRONMENT (must be dev or prod)"
    exit 1
fi

if [[ ! "$ACTION" =~ ^(setup|test|build|synth|deploy|destroy|all)$ ]]; then
    echo "❌ Invalid action: $ACTION"
    exit 1
fi

echo "======================================="
echo "2Dto3D Deploy Script"
echo "======================================="
echo "Environment: $ENVIRONMENT"
echo "Action: $ACTION"
echo ""

# Check prerequisites
echo "Checking prerequisites..."
python3 --version
node --version
aws --version
echo "✓ All prerequisites OK"
echo ""

# Backend Tests
run_backend_tests() {
    echo "📦 Running backend tests..."
    cd "$PROJECT_ROOT/backend"
    
    python3 -m venv venv_test 2>/dev/null || true
    source venv_test/bin/activate
    
    pip install --quiet -r requirements-test.txt
    PYTHONPATH="$PROJECT_ROOT/backend" pytest tests/ -v --tb=short
    
    if [ $? -ne 0 ]; then
        echo "❌ Backend tests failed"
        exit 1
    fi
    
    deactivate
    echo "✓ Backend tests passed"
    cd "$PROJECT_ROOT"
}

# Setup Frontend
setup_frontend() {
    echo "📦 Setting up frontend..."
    cd "$PROJECT_ROOT/frontend"
    npm install --prefer-offline --no-audit
    echo "✓ Frontend setup complete"
    cd "$PROJECT_ROOT"
}

# Build Frontend
build_frontend() {
    echo "🏗️  Building frontend..."
    cd "$PROJECT_ROOT/frontend"
    npm run build
    echo "✓ Frontend build complete"
    cd "$PROJECT_ROOT"
}

# Setup CDK
setup_cdk() {
    echo "📦 Setting up CDK..."
    cd "$PROJECT_ROOT/cdk"
    
    python3 -m venv venv_cdk 2>/dev/null || true
    source venv_cdk/bin/activate
    
    pip install --quiet -r requirements-cdk.txt
    echo "✓ CDK setup complete"
    cd "$PROJECT_ROOT"
}

# Run CDK synth
cdk_synth() {
    echo "🔨 Synthesizing CDK..."
    cd "$PROJECT_ROOT/cdk"
    source venv_cdk/bin/activate
    
    cdk synth --context environment="$ENVIRONMENT"
    echo "✓ CDK synth complete"
    cd "$PROJECT_ROOT"
}

# Show CDK diff
cdk_diff() {
    echo "📊 CDK diff for environment: $ENVIRONMENT"
    cd "$PROJECT_ROOT/cdk"
    source venv_cdk/bin/activate
    
    cdk diff --context environment="$ENVIRONMENT" || true
    cd "$PROJECT_ROOT"
}

# Deploy with CDK
cdk_deploy() {
    echo "🚀 Deploying to AWS ($ENVIRONMENT)..."
    
    if [ "$ENVIRONMENT" = "prod" ]; then
        echo "❌ Cannot auto-deploy to prod. Please review changes and deploy manually."
        exit 1
    fi
    
    cd "$PROJECT_ROOT/cdk"
    source venv_cdk/bin/activate
    
    cdk deploy --context environment="$ENVIRONMENT" \
        --require-approval=never \
        --outputs-file="$PROJECT_ROOT/cdk.outputs.json"
    
    echo "✓ CDK deploy complete"
    
    # Show outputs
    if [ -f "$PROJECT_ROOT/cdk.outputs.json" ]; then
        echo ""
        echo "📋 Deployed Outputs:"
        cat "$PROJECT_ROOT/cdk.outputs.json" | jq '.' || cat "$PROJECT_ROOT/cdk.outputs.json"
    fi
    
    cd "$PROJECT_ROOT"
}

# Destroy CDK stack
cdk_destroy() {
    echo "🗑️  Destroying CDK stack ($ENVIRONMENT)..."
    
    if [ "$ENVIRONMENT" = "prod" ]; then
        echo "❌ Cannot destroy prod environment"
        exit 1
    fi
    
    cd "$PROJECT_ROOT/cdk"
    source venv_cdk/bin/activate
    
    cdk destroy --context environment="$ENVIRONMENT" --force
    echo "✓ CDK destroy complete"
    cd "$PROJECT_ROOT"
}

# Execute actions
case "$ACTION" in
    setup)
        run_backend_tests
        setup_frontend
        setup_cdk
        ;;
    test)
        run_backend_tests
        ;;
    build)
        setup_frontend
        build_frontend
        ;;
    synth)
        setup_cdk
        cdk_synth
        ;;
    deploy)
        echo "Skipping tests for faster deployment..."
        setup_frontend
        build_frontend
        setup_cdk
        cdk_diff
        cdk_deploy
        ;;
    destroy)
        setup_cdk
        cdk_destroy
        ;;
    all)
        run_backend_tests
        setup_frontend
        build_frontend
        setup_cdk
        cdk_synth
        cdk_diff
        cdk_deploy
        ;;
    *)
        echo "❌ Unknown action: $ACTION"
        exit 1
        ;;
esac

echo ""
echo "======================================="
echo "✓ Deployment complete!"
echo "======================================="
