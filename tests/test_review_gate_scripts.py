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
import plistlib
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
        'echo "DEV_ONLY_KEY=[${DEV_ONLY_KEY-<absent>}]"\n'
        'echo "TABBED_KEY=[${TABBED_KEY-<absent>}]"\n'
        'echo "CWD=$(pwd)"\n'
    )
    stub.chmod(0o755)

    if env_file is not None:
        (repo / ".env").write_text(env_file)
    return repo


# 980labsOS scripts/with-8d-env.sh, in the two places it is checked out.
REAL_WRAPPERS = (
    Path.home() / "Documents/GitHub/980labsOS-deploy/scripts/with-8d-env.sh",
    Path.home() / "Documents/GitHub/980labsOS/scripts/with-8d-env.sh",
)


def find_real_wrapper() -> Path | None:
    return next((w for w in REAL_WRAPPERS if w.is_file() and os.access(w, os.X_OK)), None)


def make_wrapper(tmp_path: Path, *, executable: bool = True) -> Path:
    """Stand-in for 980labsOS scripts/with-8d-env.sh.

    It enforces the real wrapper's calling contract — `-- <cmd> <args...>`, with
    the literal `--` as the first argument — so a caller that stops passing it
    fails here rather than passing against a laxer stub than production.
    """
    wrapper = tmp_path / "with-8d-env.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "--" ] || { echo "stub-wrapper: expected -- first, got: $1" >&2; exit 64; }\n'
        "shift\n"
        'exec "$@"\n'
    )
    wrapper.chmod(0o755 if executable else 0o644)
    return wrapper


def make_8d_env_file(tmp_path: Path, **values: str) -> Path:
    """A file shaped the way the real wrapper insists on: regular file, owned by
    us, mode 600, carrying the Agent Native OS marker line."""
    path = tmp_path / "agent-native-os.env"
    body = "export AGENT_NATIVE_OS_INFISICAL_ENV_LOADED=1\n"
    body += "".join(f"export {k}={v}\n" for k, v in values.items())
    path.write_text(body)
    path.chmod(0o600)
    return path


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
    assert "DEV_ONLY_KEY=[dev-value]" in result.stdout


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


# --- third pass: the loader's own failure modes -----------------------------


def test_empty_injected_value_is_not_refilled_from_the_file(tmp_path: Path) -> None:
    """An exported-but-empty variable is SET, and must win.

    `-n` treats it as absent, so the local file refills the credential and
    review-gate.sh's empty-key check — which runs afterwards — never fires. That
    defeats the whole mock-CRM guard.
    """
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=from-dotfile\n")
    result = run_gate(
        repo,
        env={
            "SM_CRM_ENV_WRAPPED": "1",
            "SM_CRM_LOG_DIR": str(tmp_path / "logs"),
            "TWENTY_API_KEY": "",
        },
    )
    assert result.returncode == 78, result.stdout
    assert "TWENTY_API_KEY is empty" in result.stderr
    assert "from-dotfile" not in result.stdout


def test_values_are_not_word_split_globbed_or_executed(tmp_path: Path) -> None:
    """`eval "export $line"` runs command substitutions and splits on spaces."""
    marker = tmp_path / "pwned"
    repo = build_sandbox(
        tmp_path,
        env_file=(f"TWENTY_API_KEY=k\nDEV_ONLY_KEY=hello world $(touch {marker}) *\n"),
    )
    result = run_gate(
        repo,
        env={"SM_CRM_ENV_WRAPPED": "1", "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "a command substitution in a value was executed"
    assert f"DEV_ONLY_KEY=[hello world $(touch {marker}) *]" in result.stdout


def test_indented_and_tab_prefixed_lines_are_loaded(tmp_path: Path) -> None:
    """Stripping one space leaves a key like '\tFOO', which is silently dropped."""
    repo = build_sandbox(
        tmp_path,
        env_file="TWENTY_API_KEY=k\n\tTABBED_KEY=tabbed\n    DEV_ONLY_KEY=indented\n",
    )
    result = run_gate(
        repo,
        env={"SM_CRM_ENV_WRAPPED": "1", "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    assert result.returncode == 0, result.stderr
    assert "TABBED_KEY=[tabbed]" in result.stdout
    assert "DEV_ONLY_KEY=[indented]" in result.stdout


def test_stray_repo_dir_is_ignored_by_the_gate_too(tmp_path: Path) -> None:
    """review-gate.sh must not paper over this by assigning REPO_DIR itself.

    The protection has to live in _repo-env.sh, where every entrypoint gets it.
    """
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    decoy = build_sandbox(tmp_path / "elsewhere", env_file="TWENTY_API_KEY=decoy\n")
    result = run_gate(
        repo,
        env={
            "SM_CRM_ENV_WRAPPED": "1",
            "SM_CRM_LOG_DIR": str(tmp_path / "logs"),
            "REPO_DIR": str(decoy),
        },
    )
    assert result.returncode == 0, result.stderr
    assert f"CWD={repo.resolve()}" in result.stdout


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


# --- fourth pass ------------------------------------------------------------


def test_plist_does_not_infinitely_restart_a_configuration_refusal() -> None:
    """`KeepAlive: <true/>` would respawn the exit-78 refusal every
    ThrottleInterval forever, and the log it spams is the only evidence of why.

    launchd ORs the KeepAlive dictionary keys and, finding no match, "falls back
    on demand based invocation" — it stops. A non-zero exit matches neither
    SuccessfulExit (exit 0 only) nor Crashed (signal deaths only), so the
    refusal stops the job while genuine failures still come back.
    """
    plist_path = REPO_ROOT / "scripts/launchd/com.stablemischief.smcrm-reviewgate.plist"
    plist = plistlib.loads(plist_path.read_bytes())

    keep_alive = plist["KeepAlive"]
    assert isinstance(keep_alive, dict), (
        "KeepAlive must be a dictionary: <true/> restarts unconditionally, "
        "including on the exit-78 configuration refusal."
    )
    assert keep_alive.get("SuccessfulExit") is True
    assert keep_alive.get("Crashed") is True
    # Any key that would match a plain non-zero exit reopens the loop.
    assert "SuccessfulExit" in keep_alive and keep_alive["SuccessfulExit"] is not False


def test_refusal_exit_code_is_not_restarted_by_the_plist(tmp_path: Path) -> None:
    """Ties the script's actual refusal code to the plist policy, so changing
    one without the other fails rather than silently reopening the loop."""
    repo = build_sandbox(tmp_path, env_file="TWENTY_API_KEY=k\n")
    wrapper = make_wrapper(tmp_path, executable=False)
    result = run_gate(
        repo,
        env={"SM_CRM_ENV_WRAPPER": str(wrapper), "SM_CRM_LOG_DIR": str(tmp_path / "logs")},
    )
    plist = plistlib.loads(
        (REPO_ROOT / "scripts/launchd/com.stablemischief.smcrm-reviewgate.plist").read_bytes()
    )
    keep_alive = plist["KeepAlive"]

    assert result.returncode != 0, "a refusal must not exit 0, or SuccessfulExit restarts it"
    assert isinstance(keep_alive, dict)
    # Neither OR'd condition matches a plain non-zero exit, so launchd stops.
    assert set(keep_alive) <= {"SuccessfulExit", "Crashed"}, (
        f"unreviewed KeepAlive conditions may restart exit {result.returncode}: {set(keep_alive)}"
    )


@pytest.mark.skipif(find_real_wrapper() is None, reason="980labsOS with-8d-env.sh not checked out")
def test_arguments_survive_the_real_8d_wrapper(tmp_path: Path) -> None:
    """The documented `review-gate.sh --port 9000` goes through with-8d-env.sh,
    so verify it against the real wrapper's `-- <cmd> <args>` contract rather
    than only against a stub.
    """
    wrapper = find_real_wrapper()
    assert wrapper is not None
    repo = build_sandbox(tmp_path)
    env_file = make_8d_env_file(tmp_path, TWENTY_API_KEY="from-wrapper")

    result = run_gate(
        repo,
        "--port",
        "9000",
        env={
            "SM_CRM_ENV_WRAPPER": str(wrapper),
            "SM_CRM_LOG_DIR": str(tmp_path / "logs"),
            "AGENT_NATIVE_OS_INFISICAL_ENV_FILE": str(env_file),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "TWENTY_API_KEY=from-wrapper" in result.stdout
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
