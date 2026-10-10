"""CI pulls Docker Official Images from the AWS public mirror, not Docker Hub."""

from __future__ import annotations

from pathlib import Path
import re
import shlex

import yaml


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_DOCKERFILE = _ROOT / "Dockerfile"
_MIRROR = "public.ecr.aws/docker/library"
_EXPECTED_IMAGES = frozenset(
    {
        f"{_MIRROR}/postgres:16",
        f"{_MIRROR}/python:3.13-slim",
        f"{_MIRROR}/registry:2",
    }
)
_DOCKER_HUB_HOSTS = frozenset(
    {
        "docker.io",
        "index.docker.io",
        "registry-1.docker.io",
        "registry.hub.docker.com",
    }
)
# Flags that consume the next docker run/pull token. The image is the first
# positional; arguments after it (postgres -c ...) are not docker flags.
_VALUE_FLAGS = frozenset(
    {
        "--add-host",
        "--cap-add",
        "--cap-drop",
        "--cpus",
        "--device",
        "--entrypoint",
        "--env",
        "--env-file",
        "--group-add",
        "--health-cmd",
        "--health-interval",
        "--health-retries",
        "--health-start-period",
        "--health-timeout",
        "--hostname",
        "--label",
        "--label-file",
        "--log-driver",
        "--log-opt",
        "--memory",
        "--memory-reservation",
        "--memory-swap",
        "--mount",
        "--name",
        "--network",
        "--publish",
        "--pull",
        "--restart",
        "--security-opt",
        "--shm-size",
        "--sysctl",
        "--tmpfs",
        "--ulimit",
        "--user",
        "--volume",
        "--workdir",
        "-e",
        "-h",
        "-l",
        "-m",
        "-p",
        "-u",
        "-v",
        "-w",
    }
)
_FROM = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)
_ARG = re.compile(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.MULTILINE)
_DOCKER_INVOCATION = re.compile(r"\bdocker\s+(run|pull)\b")
_BARE_OFFICIAL = re.compile(r"(?<![\w./-])(?:postgres|python|registry):[^\s\\'\"]+")


def test_ci_pulls_official_images_from_the_aws_public_mirror() -> None:
    references = _ci_image_references()
    docker_hub = [
        f"{path.relative_to(_ROOT)}: {image}"
        for path, image in references
        if _is_docker_hub_image(image)
    ]
    assert docker_hub == [], (
        "CI workflows and the root Dockerfile pulled a Docker Hub image. "
        "Use the AWS public mirror of Docker Official Images "
        f"({_MIRROR}/<name>:<tag>). Bare names and docker.io hosts are "
        "anonymous rate-limited on GitHub-hosted runners: " + "; ".join(docker_hub)
    )
    assert {image for _path, image in references} == _EXPECTED_IMAGES


def test_each_ci_image_is_declared_once_per_file() -> None:
    by_file: dict[Path, set[str]] = {}
    for path, image in _ci_image_references():
        by_file.setdefault(path, set()).add(image)
    for path, images in sorted(by_file.items()):
        text = path.read_text(encoding="utf-8")
        for image in sorted(images):
            count = text.count(image)
            if count == 0 and image in _DOCKERFILE.read_text(encoding="utf-8"):
                continue
            assert count == 1, (
                f"{path.relative_to(_ROOT)} declares {image} {count} times; "
                "declare it once via workflow env, the service image key, "
                "or a Dockerfile ARG"
            )


def test_ci_steps_retry_mirror_pulls_before_using_the_image() -> None:
    """Public ECR throttles anonymous pulls per IP when shards start together."""
    for name in ("yoke-ci.yml", "yoke-tests-selection.yml"):
        step = _step_body(_WORKFLOWS / name, "Start Postgres")
        assert 'docker pull "$POSTGRES_IMAGE"' in step, name
        assert "for attempt in 1 2 3 4 5" in step, name
        assert "sleep $((5 + RANDOM % 26))" in step, name
        assert step.index('docker pull "$POSTGRES_IMAGE"') < step.index("docker run")
    build = _step_body(_WORKFLOWS / "yoke-ci.yml", "Build Yoke core image")
    assert "s/^ARG PYTHON_IMAGE=//p" in build
    assert 'docker pull "$python_image"' in build
    assert "for attempt in 1 2 3 4 5" in build
    assert build.index('docker pull "$python_image"') < build.index("docker build")


def test_ci_files_do_not_name_bare_docker_hub_official_images() -> None:
    offenders: list[str] = []
    for path in [*_workflow_paths(), _DOCKERFILE]:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            for match in _BARE_OFFICIAL.finditer(code):
                offenders.append(
                    f"{path.relative_to(_ROOT)}:{lineno}: {match.group(0)}"
                )
    assert offenders == [], (
        "bare Docker Hub official image reference (declare the AWS public "
        "mirror instead): " + "; ".join(offenders)
    )


def _ci_image_references() -> list[tuple[Path, str]]:
    references = [(_DOCKERFILE, image) for image in _dockerfile_images()]
    for path in _workflow_paths():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        workflow_env = _env_map(document)
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            job_env = _env_map(job)
            references.extend(
                (path, image)
                for image in _job_container_images(job, f"{path.name}:{job_name}")
            )
            for step_index, step in enumerate(job.get("steps") or [], 1):
                if not isinstance(step, dict):
                    continue
                origin = f"{path.name}:{job_name}:step {step_index}"
                env_chain = [_env_map(step), job_env, workflow_env]
                references.extend(
                    (path, image) for image in _step_images(step, env_chain, origin)
                )
    return references


def _workflow_paths() -> list[Path]:
    return sorted([*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")])


def _dockerfile_images() -> list[str]:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    first = _FROM.search(text)
    preamble = text[: first.start()] if first else text
    defaults = {name: value.strip() for name, value in _ARG.findall(preamble)}
    images: list[str] = []
    for token in _FROM.findall(text):
        name = _shell_name(token)
        if name is not None:
            if name not in defaults:
                raise AssertionError(
                    "Dockerfile: FROM uses "
                    f"${{{name}}} with no ARG default before the first FROM"
                )
            token = defaults[name]
        if "$" in token:
            raise AssertionError(f"Dockerfile: FROM {token!r} is not a concrete image")
        images.append(token)
    return images


def _job_container_images(job: dict, origin: str) -> list[str]:
    images: list[str] = []
    container = job.get("container")
    if isinstance(container, str):
        images.append(_concrete_static_image(container, f"{origin} container"))
    elif isinstance(container, dict) and "image" in container:
        images.append(
            _concrete_static_image(container["image"], f"{origin} container.image")
        )
    for service_name, service in (job.get("services") or {}).items():
        service_origin = f"{origin} services.{service_name}"
        if isinstance(service, str):
            images.append(_concrete_static_image(service, service_origin))
        elif isinstance(service, dict) and "image" in service:
            images.append(
                _concrete_static_image(service["image"], f"{service_origin}.image")
            )
    return images


def _step_images(step: dict, env_chain: list[dict[str, str]], origin: str) -> list[str]:
    images: list[str] = []
    uses = step.get("uses")
    if isinstance(uses, str) and uses.startswith("docker://"):
        images.append(uses.removeprefix("docker://"))
    run = step.get("run")
    if isinstance(run, str):
        images.extend(_docker_command_images(run, env_chain, origin))
    return images


def _docker_command_images(
    script: str, env_chain: list[dict[str, str]], origin: str
) -> list[str]:
    joined = re.sub(r"\\\n[ \t]*", " ", script)
    images: list[str] = []
    for match in _DOCKER_INVOCATION.finditer(joined):
        tail = re.split(r"\n|&&|\|\||;", joined[match.end() :], maxsplit=1)[0]
        token = _first_positional(shlex.split(tail), origin)
        images.append(_resolve_shell_image(token, env_chain, origin, script))
    return images


def _first_positional(tokens: list[str], origin: str) -> str:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            if index + 1 >= len(tokens):
                raise AssertionError(f"{origin}: docker command has no image")
            return tokens[index + 1]
        if token.startswith("-"):
            if "=" in token or token not in _VALUE_FLAGS:
                index += 1
                continue
            index += 2
            continue
        return token
    raise AssertionError(f"{origin}: docker command has no image")


def _step_body(path: Path, step_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker, _, body = text.partition(step_name)
    assert marker != text, f"{path.name}: missing step {step_name}"
    return body.split("\n      - name:", 1)[0]


def _resolve_shell_image(
    token: str,
    env_chain: list[dict[str, str]],
    origin: str,
    script: str,
) -> str:
    name = _shell_name(token)
    if name is not None:
        for env in env_chain:
            if name in env:
                token = env[name]
                break
        else:
            token = _image_assigned_from_dockerfile_arg(script, name, origin)
    if "$" in token or "${{" in token:
        raise AssertionError(f"{origin}: {token!r} is not a concrete image reference")
    return token


_DOCKERFILE_ARG_ASSIGNMENT = re.compile(
    r"""([A-Za-z_][A-Za-z0-9_]*)="\$\(sed -n 's/\^ARG """
    r"""([A-Za-z_][A-Za-z0-9_]*)=//p' Dockerfile\)\""""
)


def _image_assigned_from_dockerfile_arg(script: str, name: str, origin: str) -> str:
    for match in _DOCKERFILE_ARG_ASSIGNMENT.finditer(script):
        if match.group(1) != name:
            continue
        text = _DOCKERFILE.read_text(encoding="utf-8")
        first = _FROM.search(text)
        preamble = text[: first.start()] if first else text
        defaults = {
            arg_name: value.strip() for arg_name, value in _ARG.findall(preamble)
        }
        arg_name = match.group(2)
        if arg_name not in defaults:
            raise AssertionError(
                f"{origin}: ${name} reads ARG {arg_name}, which has no default "
                "before the first FROM"
            )
        return defaults[arg_name]
    raise AssertionError(
        f"{origin}: ${name} is not declared in workflow, job, or step env"
    )


def _concrete_static_image(value: object, origin: str) -> str:
    image = str(value).strip()
    if "$" in image or "${{" in image:
        raise AssertionError(
            f"{origin}: this key cannot expand env or inputs; declare the "
            "mirror image once as a literal"
        )
    return image


def _shell_name(token: str) -> str | None:
    if token.startswith("${") and token.endswith("}") and token[2:-1].isidentifier():
        return token[2:-1]
    if token.startswith("$") and token[1:].isidentifier():
        return token[1:]
    return None


def _env_map(node: object) -> dict[str, str]:
    if not isinstance(node, dict):
        return {}
    env = node.get("env")
    if not isinstance(env, dict):
        return {}
    return {str(key): str(value) for key, value in env.items()}


def _is_docker_hub_image(reference: str) -> bool:
    name = reference.split("@", 1)[0]
    host, separator, _rest = name.partition("/")
    if separator == "":
        return True
    if "." not in host and ":" not in host and host != "localhost":
        return True
    return host.split(":", 1)[0].lower() in _DOCKER_HUB_HOSTS
