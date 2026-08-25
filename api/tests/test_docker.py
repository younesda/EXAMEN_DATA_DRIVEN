from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
import uuid

import pytest

pytestmark = pytest.mark.docker


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="RUN_DOCKER_TESTS=1 requis")
def test_image_build_health_routes_and_secret_absence():
    image = "ecommerce-model-api:test"
    name = f"ecommerce-model-api-test-{uuid.uuid4().hex[:8]}"
    docker("build", "--tag", image, ".")
    started = docker("run", "--detach", "--name", name, "--publish", "127.0.0.1::8000", image)
    assert started.stdout.strip()
    try:
        port_output = docker("port", name, "8000/tcp").stdout.strip()
        port = int(port_output.rsplit(":", 1)[1])
        deadline = time.monotonic() + 60
        status = "starting"
        while time.monotonic() < deadline:
            inspect = docker("inspect", "--format", "{{json .State.Health.Status}}", name)
            status = json.loads(inspect.stdout)
            if status == "healthy":
                break
            if status == "unhealthy":
                break
            time.sleep(1)
        assert status == "healthy", docker("logs", name, check=False).stderr

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            assert response.status == 200
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ready", timeout=5) as response:
            assert response.status == 200
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/models/status", timeout=5) as response:
            assert response.status == 200

        assert docker("exec", name, "test", "!", "-e", "/app/.env").returncode == 0
        assert docker("exec", name, "test", "!", "-d", "/app/api/tests").returncode == 0
        environment = docker("inspect", "--format", "{{json .Config.Env}}", name).stdout
        assert "API_KEY=" not in environment
        assert "DATABASE_URL=" not in environment
        assert "SUPABASE" not in environment
    finally:
        docker("stop", "--time", "10", name, check=False)

