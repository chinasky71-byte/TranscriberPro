# -*- coding: utf-8 -*-
"""Guard for the container artifacts (ADR-004, WebUI Step 8).

No docker daemon is needed: the checks read the Dockerfile, the compose file
and the ignore file. They protect the rules that matter: no drivers or weights
in the image, no Qt, non-root, one image per backend, explicit volumes.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker" / "Dockerfile"
COMPOSE = ROOT / "docker" / "compose.yaml"
IGNORE = ROOT / ".dockerignore"

DRIVER_PACKAGES = ("nvidia-driver", "rocm-dev", "rocm-libs", "amdgpu-dkms",
                   "nvidia-container-toolkit", "mesa-vulkan-drivers")


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _instructions(text: str):
    """Dockerfile instructions with line continuations folded and comments dropped."""
    joined = re.sub(r"\\\s*\n", " ", text)
    for line in joined.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def test_one_image_per_backend():
    text = _dockerfile()
    assert "ARG BACKEND" in text
    for backend in ("rocm", "cuda"):
        assert f"{backend})" in text, f"backend {backend} missing from the build switch"
    assert "BACKEND must be rocm or cuda" in text, "unknown backend must fail the build"


def test_no_drivers_and_no_weights_in_the_image():
    text = _dockerfile().lower()
    for package in DRIVER_PACKAGES:
        assert package not in text, f"{package} must not be installed in the image"
    copies = [line for line in _instructions(_dockerfile()) if line.upper().startswith("COPY")]
    assert not any("models" in line for line in copies), "models are a volume, not image content"
    assert not any("samples" in line for line in copies), "media is a volume, not image content"


def test_no_qt_in_the_image():
    text = _dockerfile()
    assert "requirements-gui.txt" not in text
    assert "PyQt" not in text


def test_container_runs_as_non_root_and_healthchecks():
    text = _dockerfile()
    assert re.search(r"^USER\s+tp\s*$", text, re.MULTILINE), "runtime stage must drop root"
    assert "HEALTHCHECK" in text
    assert "/api/health" in text
    assert "web.main" in text, "the container serves the WebUI"


def test_env_dirs_point_at_volumes():
    text = _dockerfile()
    assert "TP_DATA_DIR=/data" in text
    assert "TP_MODELS_DIR=/models" in text
    declares = [line for line in _instructions(text) if line.upper().startswith("VOLUME")]
    assert declares and "/data" in declares[0] and "/models" in declares[0]


def test_compose_declares_the_three_backends():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = data["services"]
    assert set(services) == {"rocm", "cuda"}
    for name, service in services.items():
        assert service["profiles"] == [name]
        assert service["build"]["args"]["BACKEND"] == name
        assert "TP_WEB_TOKEN" in service["environment"]
        assert service["security_opt"] if name == "rocm" else True
        assert service.get("privileged") is not True


def test_compose_gpu_wiring():
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    rocm = services["rocm"]
    assert "/dev/kfd" in rocm["devices"]
    assert "/dev/dri" in rocm["devices"]
    assert "video" in rocm["group_add"] and "render" in rocm["group_add"]
    assert rocm["ipc"] == "host"

    cuda = services["cuda"]
    reservation = cuda["deploy"]["resources"]["reservations"]["devices"][0]
    assert reservation["driver"] == "nvidia"
    assert "gpu" in reservation["capabilities"]


def test_compose_mounts_data_models_and_media():
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    volumes = " ".join(services["rocm"]["volumes"])
    assert ":/data" in volumes
    assert ":/models" in volumes
    assert ":/media" in volumes
    assert "tp-data" in services["rocm"]["volumes"][0]


def test_dockerignore_keeps_local_state_out_of_the_build():
    ignored = {line.strip() for line in IGNORE.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.strip().startswith("#")}
    for entry in ("venv/", "models/", "samples/", ".git"):
        assert entry in ignored, f"{entry} must not enter the build context"
