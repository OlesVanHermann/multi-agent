from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
VERSION = "26.8.2"
DIGEST = "sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0"
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


def test_keycloak_26_health_uses_management_port():
    # Keycloak 26 serves /health/* on the management port 9000, not on 8080.
    for relative in (
        "scripts/status.sh",
        "setup/install_keycloak.sh",
        "setup/keycloak_user_create.sh",
        "setup/keycloak_user_list.sh",
        "setup/keycloak_user_delete.sh",
        "setup/keycloak_passwd_modify.sh",
    ):
        content = (BASE / relative).read_text()
        assert "8080/health" not in content, relative
        assert "$KEYCLOAK_URL/health" not in content, relative
