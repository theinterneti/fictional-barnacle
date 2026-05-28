#!/usr/bin/env python3
"""
Wait for test services (PostgreSQL, Redis, Neo4j) to be ready.

Polls each service with a 60s timeout, 2s interval.
On timeout, prints diagnostics (docker compose ps + logs).
Exits 0 if all services ready, 1 if any fail.
"""

import subprocess
import sys
import time


def run_command(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=capture, text=True)


def check_postgres() -> bool:
    """Check if PostgreSQL is ready using pg_isready."""
    try:
        result = run_command(["pg_isready", "-h", "localhost", "-p", "5432"])
        return result.returncode == 0
    except FileNotFoundError:
        # pg_isready not installed, try alternative check with netcat
        try:
            result = subprocess.run(["nc", "-z", "localhost", "5432"], capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


def check_redis() -> bool:
    """Check if Redis is ready using redis-cli ping."""
    try:
        result = run_command(["redis-cli", "-h", "localhost", "-p", "6379", "ping"])
        return result.returncode == 0 and result.stdout.strip() == "PONG"
    except FileNotFoundError:
        # redis-cli not installed, try alternative check with netcat
        try:
            result = subprocess.run(["nc", "-z", "localhost", "6379"], capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


def check_neo4j() -> bool:
    """Check if Neo4j is ready by hitting the HTTP endpoint."""
    result = run_command(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:7474"])
    return result.stdout.strip() == "200"


def print_diagnostics(service_name: str) -> None:
    """Print docker compose diagnostics for a failed service."""
    print(f"\n=== Diagnostics for {service_name} ===")
    
    print("\n--- docker compose ps ---")
    run_command(["docker", "compose", "ps"], capture=False)
    
    print("\n--- docker compose logs --tail=20 ---")
    run_command(["docker", "compose", "logs", "--tail=20", service_name], capture=False)


def wait_for_service(name: str, check_fn, timeout: int = 60, interval: int = 2) -> bool:
    """Wait for a service to become ready."""
    print(f"Waiting for {name}...", end=" ", flush=True)
    
    start = time.time()
    while time.time() - start < timeout:
        if check_fn():
            print("ready!")
            return True
        time.sleep(interval)
        print(".", end=" ", flush=True)
    
    print("timeout!")
    return False


def main() -> int:
    """Main entry point."""
    services = [
        ("postgres", check_postgres),
        ("redis", check_redis),
        ("neo4j", check_neo4j),
    ]
    
    failed_services = []
    
    for name, check_fn in services:
        if not wait_for_service(name, check_fn):
            failed_services.append(name)
    
    if failed_services:
        print(f"\n❌ Failed to connect to: {', '.join(failed_services)}")
        for service in failed_services:
            print_diagnostics(service)
        return 1
    
    print("\n✅ All services are ready!")
    return 0


if __name__ == "__main__":
    sys.exit(main())