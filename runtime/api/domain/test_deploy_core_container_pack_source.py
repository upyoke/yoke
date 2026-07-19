"""Project-owned Pack source tests for core-container service files."""

from runtime.api.domain.deploy_core_container_test_support import (
    install_core_service_project_source,
)
from runtime.api.domain.test_deploy_core_container import _BINDING, _env
from yoke_core.domain.deploy_core_container import render_service_files


class TestRenderServiceFiles:
    def test_compose_pins_image_loopback_port_and_awslogs(self, tmp_path):
        compose, nginx, env_file = render_service_files(
            _env(),
            _env().image_ref("abc123def456"),
            _BINDING,
            repo_path=install_core_service_project_source(tmp_path),
        )
        assert (
            "image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/"
            "yoke-core:abc123def456" in compose
        )
        assert '"127.0.0.1:8765:8765"' in compose
        assert "driver: awslogs" in compose
        assert 'awslogs-group: "/yoke/prod/core"' in compose
        assert 'awslogs-region: "us-east-1"' in compose
        assert "container_name: yoke-core" in compose

    def test_compose_does_not_mount_static_dsn_file(self, tmp_path):
        compose, _, _ = render_service_files(
            _env(), "img:tag", _BINDING,
            repo_path=install_core_service_project_source(tmp_path),
        )
        assert "/run/yoke/dsn" not in compose
        assert "./dsn:" not in compose

    def test_nginx_proxies_origin_port_to_container(self, tmp_path):
        _, nginx, _ = render_service_files(
            _env(), "img:tag", _BINDING,
            repo_path=install_core_service_project_source(tmp_path),
        )
        assert "listen 80 default_server;" in nginx
        assert "server_name origin.example.com api.example.com;" in nginx
        assert "client_max_body_size" in nginx
        assert "proxy_pass http://127.0.0.1:8765;" in nginx

    def test_env_file_points_at_managed_secret_never_raw_password(self, tmp_path):
        _, _, env_file = render_service_files(
            _env(), "img:tag", _BINDING,
            repo_path=install_core_service_project_source(tmp_path),
        )
        assert "YOKE_DB_SECRET_ARN=arn:aws:secretsmanager" in env_file
        assert "YOKE_DB_SECRET_REGION=us-east-1" in env_file
        assert "YOKE_DB_HOST=db.internal" in env_file
        assert "YOKE_DB_NAME=yoke_prod" in env_file
        assert "YOKE_PG_DSN" not in env_file
        assert "password" not in env_file.lower()
        assert "YOKE_ENVIRONMENT=prod" in env_file
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env_file

    def test_env_file_adds_otel_endpoint_when_configured(self, tmp_path):
        _, _, env_file = render_service_files(
            _env(otel_exporter_endpoint="https://otel.example"),
            "img:tag",
            _BINDING,
            repo_path=install_core_service_project_source(tmp_path),
        )
        assert "OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.example" in env_file
