#!/usr/bin/env python3
"""
Test runner script for the Flask application.

This script provides different test execution modes and options.
"""

import sys
import subprocess
import argparse
import os
from pathlib import Path


def run_command(cmd, description):
    """Run a command and return the exit code"""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure pytest is installed: pip install pytest")
        return 1


def run_unit_tests():
    """Run unit tests only"""
    cmd = ["python", "-m", "pytest", "tests/", "-m", "not integration", "-v"]
    return run_command(cmd, "Unit Tests")


def run_integration_tests():
    """Run integration tests only"""
    cmd = ["python", "-m", "pytest", "tests/test_integration.py", "-v"]
    return run_command(cmd, "Integration Tests")


def run_all_tests():
    """Run all tests"""
    cmd = ["python", "-m", "pytest", "tests/", "-v"]
    return run_command(cmd, "All Tests")


def run_fast_tests():
    """Run fast tests (exclude slow tests)"""
    cmd = ["python", "-m", "pytest", "tests/", "-m", "not slow", "-v"]
    return run_command(cmd, "Fast Tests")


def run_with_coverage():
    """Run tests with coverage report"""
    cmd = [
        "python", "-m", "pytest", 
        "tests/", 
        "--cov=flask_app", 
        "--cov=app",
        "--cov-report=html", 
        "--cov-report=term-missing",
        "--cov-report=xml",
        "-v"
    ]
    return run_command(cmd, "Tests with Coverage")


def run_specific_test(test_path):
    """Run a specific test file or test function"""
    cmd = ["python", "-m", "pytest", test_path, "-v"]
    return run_command(cmd, f"Specific Test: {test_path}")


def run_parallel_tests():
    """Run tests in parallel (requires pytest-xdist)"""
    cmd = ["python", "-m", "pytest", "tests/", "-n", "auto", "-v"]
    return run_command(cmd, "Parallel Tests")


def run_smoke_tests():
    """Run smoke tests"""
    cmd = ["python", "-m", "pytest", "tests/", "-m", "smoke", "-v"]
    return run_command(cmd, "Smoke Tests")


def lint_code():
    """Run code linting"""
    print(f"\n{'='*60}")
    print("Running: Code Linting")
    print(f"{'='*60}")
    
    # Run flake8 if available
    try:
        result = subprocess.run(["flake8", "flask_app/", "tests/", "--max-line-length=120"], check=False)
        if result.returncode == 0:
            print("✓ Code linting passed")
        else:
            print("✗ Code linting failed")
        return result.returncode
    except FileNotFoundError:
        print("flake8 not found. Install with: pip install flake8")
        return 0


def check_security():
    """Run security checks"""
    print(f"\n{'='*60}")
    print("Running: Security Checks")
    print(f"{'='*60}")
    
    # Run bandit if available
    try:
        result = subprocess.run(["bandit", "-r", "flask_app/"], check=False)
        if result.returncode == 0:
            print("✓ Security checks passed")
        else:
            print("✗ Security issues found")
        return result.returncode
    except FileNotFoundError:
        print("bandit not found. Install with: pip install bandit")
        return 0


def main():
    """Main function to handle command line arguments"""
    parser = argparse.ArgumentParser(description="Test runner for Flask application")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=[
            "unit", "integration", "all", "fast", "coverage", 
            "parallel", "smoke", "lint", "security", "ci"
        ],
        default="all",
        help="Test mode to run (default: all)"
    )
    parser.add_argument(
        "--test",
        help="Run a specific test file or test function"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--no-lint",
        action="store_true",
        help="Skip linting in CI mode"
    )
    
    args = parser.parse_args()
    
    # Change to project root directory
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    exit_code = 0
    
    if args.test:
        exit_code = run_specific_test(args.test)
    elif args.mode == "unit":
        exit_code = run_unit_tests()
    elif args.mode == "integration":
        exit_code = run_integration_tests()
    elif args.mode == "all":
        exit_code = run_all_tests()
    elif args.mode == "fast":
        exit_code = run_fast_tests()
    elif args.mode == "coverage":
        exit_code = run_with_coverage()
    elif args.mode == "parallel":
        exit_code = run_parallel_tests()
    elif args.mode == "smoke":
        exit_code = run_smoke_tests()
    elif args.mode == "lint":
        exit_code = lint_code()
    elif args.mode == "security":
        exit_code = check_security()
    elif args.mode == "ci":
        # CI mode: run all checks
        print("Running CI pipeline...")
        
        # Run linting
        if not args.no_lint:
            lint_exit = lint_code()
            if lint_exit != 0:
                exit_code = lint_exit
        
        # Run security checks
        security_exit = check_security()
        if security_exit != 0:
            exit_code = security_exit
        
        # Run tests with coverage
        test_exit = run_with_coverage()
        if test_exit != 0:
            exit_code = test_exit
    
    if exit_code == 0:
        print(f"\n{'='*60}")
        print("✓ All checks passed!")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print("✗ Some checks failed!")
        print(f"{'='*60}")
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
