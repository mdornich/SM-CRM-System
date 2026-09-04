"""Behavioural tests for the shell entrypoints in scripts/.

These are zsh scripts, not Python, but they carry real operational authority:
`review-gate.sh` is the process launchd keeps alive as the human-approval gate,
and `_repo-env.sh` decides which credentials that gate ends up using. Getting
either wrong fails silently and looks healthy, so they get the same coverage the
Python does.

Each test drives the real scripts inside a throwaway repo tree with a stub venv
and a stub `python`, and asserts on what the stub was actually invoked with.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("_repo-env.sh", "review-gate.sh", "serve-review-ui.sh")

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")


def build_sandbox(tmp_path: Path, *, env_file: str | None = None) -> Path:
    """A minimal repo tree: the real scripts, a stub venv, a stub `python`."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in SCRIPTS:
        target = repo / "scripts" / name
        shutil.copy(REPO_ROOT / "scripts" / name, target)
        target.chmod(0o755)

    bin_dir = repo / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    # `source .venv/bin/activate` must put the stub python on PATH.
    (bin_dir / "activate").write_text(f'export PATH="{bin_dir}:$PATH"\n')
    stub = bin_dir / "python"
    stub.write_text(
        "#!/bin/sh\n"
        'echo "PYTHON_ARGS: $@"\n'
        'echo "TWENTY_API_URL=${TWENTY_API_URL-}"\n'
        'echo "TWENTY_API_KEY=${TWENTY_API_KEY-}"\n'
        'echo "DEV_ONLY_KEY=${DEV_ONLY_KEY-}"\n'
        'echo "CWD=$(pwd)"\n'
    )
    stub.chmod(0o755)

    if env_file is not None:
        (repo / ".env").write_text(env_file)
    return repo


def make_wrapper(tmp_path: Path, *, executable: bool = True) -> Path:
    """Stand-in for 980labsOS scripts/with-8d-env.sh: exec the child verbatim."""
    wrapper = tmp_path / "with-8d-env.sh"
    wrapper.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    wrapper.chmod(0o755 if executable else 0o644)
    return wrapper


def run_gate(repo: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    full = {"HOME": str(repo.parent), "PATH": os.environ.get("PATH", "")}
    full.update(env)
    return subprocess.run(
        ["zsh", str(repo / "scripts" / "review-gate.sh"), *args],
        capture_output=True,
        text=True,
        env=full,
        timeout=60,
    )


# --- finding 1: .env must never override injected values -------------------


def test_dotenv_does_not_override_injected_values(tmp_path: Path) -> None:
    """The regression this exists for.

    A plain `set -a; source .env; set +a` reverts everything with-8d-env.sh just
    injected, in the shell, before Python runs — so load_settings() reads dev
    values and never sees the Infisical ones.
    """
    repo = build_sandbox(
        tmp_path,
        env_file="TWENTY_API_KEY=from-dotfile\nTWENTY_API_URL=http://dev.invalid\n",
    )
    result = run_gate(
        repo,
        env={
            "SM_CRM_ENV_WRAPPED": "1",
            "SM_CRM_LOG_DIR": str(tmp_path / "logs"),
            "TWENTY_API_KEY": "from-wrapper",
            "TWENTY_API_URL": "http://127.0.0.1:3002",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "TWENTY_API_KEY=from-wrapper" in result.stdout
    assert "from-dotfile" not in result.stdout
    assert "TWENTY_API_URL=http://127.0.0.1:3002" in result.stdout


def test_dotenv_still_fills_gaps(tmp_path: Path) -> None:
    """Lowest-precedence, not ignored: a key only in .env is still loaded."""
    repo = build_sandbox(
        tmp_path,
        env_file="TWENTY_API_KEY=from-dotfile\nDEV_ONLY_KEY=dev-value\n",
    )
    result = run_gate(
        repo,
        env={"SM_CRM_ENV_WRAPPED": "1", "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    assert result.returncode == 0, result.stderr
    assert "DEV_ONLY_KEY=dev-value" in result.stdout


# --- finding 2: launchd creates the log file, not its parent ---------------


def test_gate_creates_its_log_directory(tmp_path: Path) -> None:
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    log_dir = tmp_path / "nested" / "smcrm"
    assert not log_dir.exists()
    result = run_gate(repo, env={"SM_CRM_ENV_WRAPPED": "1", "SM_CRM_LOG_DIR": str(log_dir)})
    assert result.returncode == 0, result.stderr
    assert log_dir.is_dir()


# --- finding 3: no silent degradation to a mock-backed gate ----------------


def test_gate_refuses_to_start_when_wrapper_is_not_executable(tmp_path: Path) -> None:
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    wrapper = make_wrapper(tmp_path, executable=False)
    result = run_gate(
        repo,
        env={"SM_CRM_ENV_WRAPPER": str(wrapper), "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    assert result.returncode == 78
    assert "refusing to start" in result.stderr
    assert "PYTHON_ARGS" not in result.stdout


def test_gate_refuses_to_start_with_an_empty_api_key(tmp_path: Path) -> None:
    """An approval gate backed by the mock CRM gates nothing. Fail loudly."""
    repo = build_sandbox(tmp_path)
    result = run_gate(
        repo,
        env={
            "SM_CRM_ENV_WRAPPED": "1",
            "SM_CRM_LOG_DIR": str(tmp_path / "logs"),
            "TWENTY_API_KEY": "",
        },
    )
    assert result.returncode == 78
    assert "TWENTY_API_KEY is empty" in result.stderr
    assert "PYTHON_ARGS" not in result.stdout


def test_gate_execs_through_the_wrapper_when_it_is_available(tmp_path: Path) -> None:
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    wrapper = make_wrapper(tmp_path)
    result = run_gate(
        repo,
        env={"SM_CRM_ENV_WRAPPER": str(wrapper), "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    assert result.returncode == 0, result.stderr
    assert "PYTHON_ARGS" in result.stdout


# --- finding 4: a stray REPO_DIR in the environment must not redirect ------


def test_environment_repo_dir_cannot_redirect_the_checkout(tmp_path: Path) -> None:
    """with-8d-env.sh exports the whole secret file with `set -a`; a generic
    REPO_DIR from another job's secret set must not send an entrypoint into a
    different checkout.

    Driven through serve-review-ui.sh rather than review-gate.sh: the gate
    assigns REPO_DIR itself before sourcing, which would mask the bug. The other
    entrypoints source _repo-env.sh with whatever the environment happens to
    hold, so they are where this actually bites.
    """
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    decoy = build_sandbox(tmp_path / "elsewhere", env_file="TWENTY_API_KEY=decoy\n")

    result = subprocess.run(
        ["zsh", str(repo / "scripts" / "serve-review-ui.sh")],
        capture_output=True,
        text=True,
        env={
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
            "REPO_DIR": str(decoy),
        },
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert f"CWD={repo.resolve()}" in result.stdout
    assert str(decoy.resolve()) not in result.stdout


# --- finding 5: arguments are forwarded, not silently dropped --------------


def test_arguments_reach_the_review_ui(tmp_path: Path) -> None:
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    result = run_gate(
        repo,
        "--port",
        "9000",
        env={"SM_CRM_ENV_WRAPPED": "1", "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    assert result.returncode == 0, result.stderr
    args_line = next(ln for ln in result.stdout.splitlines() if ln.startswith("PYTHON_ARGS:"))
    assert args_line.endswith("--port 9000"), args_line


# --- finding 6: exactly one agent may bind 127.0.0.1:8765 ------------------


def test_only_one_launchd_agent_binds_the_review_port() -> None:
    plists = sorted((REPO_ROOT / "scripts" / "launchd").glob("*.plist"))
    binders = [p.name for p in plists if "review" in p.name]
    assert binders == ["com.stablemischief.smcrm-reviewgate.plist"], (
        "Two KeepAlive agents on 127.0.0.1:8765 leave one crash-looping on its "
        f"ThrottleInterval forever. Found: {binders}"
    )
