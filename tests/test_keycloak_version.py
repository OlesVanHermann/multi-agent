from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
VERSION = "26.8.0"
DIGEST = "sha256:b0f60d489d51c5d113390bdf5461d4c06e6051be026c05549f2e1e10ec352bcc"
IMAGE = f"quay.io/keycloak/keycloak:{VERSION}@{DIGEST}"


def test_keycloak_image_is_pinned_consistently():
    for relative in (
        "scripts/infra.sh",
        "setup/install_keycloak.sh",
        "web/docker-compose.yml",
    ):
        content = (BASE / relative).read_text()
        assert IMAGE in content, f"{relative} does not pin {IMAGE}"


def test_keycloak_26_runtime_configuration():
    for relative in (
        "scripts/infra.sh",
        "setup/install_keycloak.sh",
        "web/docker-compose.yml",
    ):
        content = (BASE / relative).read_text()
        assert "KC_BOOTSTRAP_ADMIN_USERNAME" in content
        assert "KC_BOOTSTRAP_ADMIN_PASSWORD" in content
        assert "KC_HOSTNAME" in content
        assert "KC_PROXY_HEADERS=xforwarded" in content
        assert "KC_DB_USERNAME" in content
        assert "KC_DB_PASSWORD" in content
        assert "KC_HOSTNAME_URL" not in content
        assert "KC_PROXY=edge" not in content
