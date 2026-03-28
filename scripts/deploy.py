#!/usr/bin/env python3
"""
2Dto3D デプロイスクリプト
フルデプロイメント自動化ツール

使用方法:
    python deploy.py --environment dev --action deploy
    python deploy.py --environment prod --action synth
"""

import argparse
import subprocess
import sys
import os
import venv as venv_module
from pathlib import Path
from typing import Optional

# ========== 設定 ==========
PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
CDK_DIR = PROJECT_ROOT / "cdk"

def print_section(title: str):
    """セクションヘッダーを表示"""
    print("\n" + "=" * 50)
    print(f"⏳ {title}")
    print("=" * 50)

def print_success(message: str):
    """成功メッセージを表示"""
    print(f"✓ {message}")

def print_error(message: str):
    """エラーメッセージを表示"""
    print(f"✗ {message}", file=sys.stderr)

def run_command(cmd: list, cwd: Optional[Path] = None, check: bool = True) -> int:
    """コマンド実行"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=False
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"コマンド失敗: {' '.join(cmd)}")
        return result.returncode
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

def check_prerequisites():
    """前提条件を確認"""
    print_section("前提条件を確認しています")
    
    checks = [
        (["python", "--version"], "Python 3.12+"),
        (["node", "--version"], "Node.js 18+"),
        (["aws", "--version"], "AWS CLI v2"),
    ]
    
    for cmd, name in checks:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print_success(f"{name}: {result.stdout.strip()}")
        else:
            print_error(f"{name} が見つかりません")
            sys.exit(1)

def setup_backend():
    """バックエンド環境構築"""
    print_section("バックエンド環境を構築しています")
    
    venv_path = BACKEND_DIR / ".venv"
    
    # venv 作成
    if not venv_path.exists():
        print("venv を作成しています...")
        venv_module.create(str(venv_path), with_pip=True)
    
    # 依存関係インストール
    pip_cmd = str(venv_path / "Scripts" / "pip.exe" if sys.platform == "win32" 
                  else venv_path / "bin" / "pip")
    
    print("Python依存関係をインストールしています...")
    run_command([pip_cmd, "install", "--upgrade", "pip", "setuptools", "wheel"])
    run_command([pip_cmd, "install", "-r", str(BACKEND_DIR / "requirements.txt")])
    run_command([pip_cmd, "install", "-r", str(BACKEND_DIR / "requirements-test.txt")])
    
    print_success("バックエンド環境構築完了")

def run_backend_tests():
    """バックエンドテスト実行"""
    print_section("バックエンドテストを実行しています")
    
    venv_path = BACKEND_DIR / ".venv"
    pytest_cmd = str(venv_path / "Scripts" / "pytest.exe" if sys.platform == "win32"
                    else venv_path / "bin" / "pytest")
    
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    
    result = subprocess.run(
        [pytest_cmd, "tests/", "-v", "--tb=short"],
        cwd=BACKEND_DIR,
        env=env,
        check=False
    )
    
    if result.returncode == 0:
        print_success("バックエンドテスト成功")
    else:
        print_error("バックエンドテスト失敗")
        sys.exit(1)

def setup_frontend():
    """フロントエンド構築"""
    print_section("フロントエンドを構築しています")
    
    print("npm 依存関係をインストールしています...")
    run_command(["npm", "install"], cwd=FRONTEND_DIR)
    
    print("ビルドを実行しています...")
    run_command(["npm", "run", "build"], cwd=FRONTEND_DIR)
    
    print_success("フロントエンドビルド成功")

def setup_cdk():
    """CDK 初期化"""
    print_section("CDK 環境を初期化しています")
    
    venv_path = CDK_DIR / ".venv"
    
    # venv 作成
    if not venv_path.exists():
        print("CDK venv を作成しています...")
        venv_module.create(str(venv_path), with_pip=True)
    
    # CDK 依存関係インストール
    pip_cmd = str(venv_path / "Scripts" / "pip.exe" if sys.platform == "win32"
                  else venv_path / "bin" / "pip")
    
    print("CDK 依存関係をインストールしています...")
    run_command([pip_cmd, "install", "--upgrade", "pip"])
    run_command([pip_cmd, "install", "-r", str(CDK_DIR / "requirements-cdk.txt")],
               cwd=CDK_DIR)
    
    print_success("CDK 初期化完了")

def run_cdk_synth(environment: str):
    """CDK Synth 実行"""
    print_section(f"CDK Synth を実行しています ({environment})")
    
    venv_path = CDK_DIR / ".venv"
    cdk_cmd = str(venv_path / "Scripts" / "cdk.exe" if sys.platform == "win32"
                 else venv_path / "bin" / "cdk")
    
    run_command([cdk_cmd, "synth", f"--context", f"environment={environment}"],
               cwd=CDK_DIR)
    
    print_success("CDK Synth 成功")

def show_cdk_diff(environment: str):
    """CDK Diff 表示"""
    print_section(f"CDK 差分を確認しています ({environment})")
    
    venv_path = CDK_DIR / ".venv"
    cdk_cmd = str(venv_path / "Scripts" / "cdk.exe" if sys.platform == "win32"
                 else venv_path / "bin" / "cdk")
    
    print("差分内容:")
    run_command([cdk_cmd, "diff", f"--context", f"environment={environment}"],
               cwd=CDK_DIR, check=False)
    
    if environment == "prod":
        print("\n⚠️  本番環境へのデプロイが必要です。手動で確認してください。")
        print("実行コマンド: cd cdk && cdk deploy --context environment=prod")

def run_cdk_deploy(environment: str):
    """CDK Deploy 実行"""
    print_section(f"CDK デプロイを実行しています ({environment})")
    
    if environment == "prod":
        print("\n⚠️  本番環境へのデプロイが要求されました。")
        print("⚠️  本スクリプトは dev 環境のみ自動デプロイ可能です。")
        print("⚠️  本番環境へのデプロイは手動で実行してください:")
        print("cd cdk && cdk deploy --context environment=prod")
        print()
        
        response = input("続行しますか? (yes/no): ").strip().lower()
        if response != "yes":
            print_success("デプロイがキャンセルされました")
            return
    
    venv_path = CDK_DIR / ".venv"
    cdk_cmd = str(venv_path / "Scripts" / "cdk.exe" if sys.platform == "win32"
                 else venv_path / "bin" / "cdk")
    
    run_command([
        cdk_cmd, "deploy",
        "--context", f"environment={environment}",
        "--require-approval", "never"
    ], cwd=CDK_DIR)
    
    print_success("CDK デプロイ成功")

def run_cdk_destroy(environment: str):
    """CDK Destroy 実行"""
    print_section(f"CDK スタックを削除しています ({environment})")
    
    print("\n⚠️  スタックの削除は取り消せません!")
    response = input("続行しますか? (yes/no): ").strip().lower()
    
    if response != "yes":
        print_success("削除がキャンセルされました")
        return
    
    venv_path = CDK_DIR / ".venv"
    cdk_cmd = str(venv_path / "Scripts" / "cdk.exe" if sys.platform == "win32"
                 else venv_path / "bin" / "cdk")
    
    run_command([cdk_cmd, "destroy", "--context", f"environment={environment}"],
               cwd=CDK_DIR, check=False)

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="2Dto3D デプロイスクリプト"
    )
    parser.add_argument(
        "--environment",
        choices=["dev", "prod"],
        default="dev",
        help="デプロイ環境 (デフォルト: dev)"
    )
    parser.add_argument(
        "--action",
        choices=["setup", "test", "build", "synth", "deploy", "destroy", "all"],
        default="all",
        help="実行アクション (デフォルト: all)"
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 50)
    print("2Dto3D デプロイスクリプト")
    print("=" * 50)
    print(f"環境: {args.environment}")
    print(f"アクション: {args.action}")
    
    try:
        check_prerequisites()
        
        if args.action in ["setup", "all"]:
            setup_backend()
            setup_frontend()
            setup_cdk()
        
        if args.action in ["test", "all"]:
            setup_backend()
            run_backend_tests()
        
        if args.action in ["build", "all"]:
            setup_frontend()
        
        if args.action in ["synth", "all"]:
            setup_cdk()
            run_cdk_synth(args.environment)
        
        if args.action in ["deploy", "all"]:
            setup_backend()
            run_backend_tests()
            setup_frontend()
            setup_cdk()
            show_cdk_diff(args.environment)
            run_cdk_deploy(args.environment)
        
        if args.action == "destroy":
            setup_cdk()
            run_cdk_destroy(args.environment)
        
        print("\n" + "=" * 50)
        print_success("デプロイスクリプト完了")
        print("=" * 50)
        
    except KeyboardInterrupt:
        print("\n✗ スクリプトが中断されました")
        sys.exit(1)
    except Exception as e:
        print_error(f"エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
