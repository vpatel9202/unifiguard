# unifiguard Foundation & Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the project and build the four foundational modules (config, logger, session, ssh) that every command in Plans 2–4 depends on.

**Architecture:** Four independent modules with no circular dependencies. `config.py` parses INI files into `NetworkConfig` dataclasses. `logger.py` sets up file + console logging. `session.py` holds the `Session` dataclass and `read_ssh`/`write_ssh` helpers that enforce dry-run semantics. `ssh.py` provides paramiko-based SSH connections with key-before-password auth and jump-host support. `main.py` wires global flags (`--dry-run`, `--network`, etc.) into a `Session` and is a skeleton for now — commands are added in Plans 2–4.

**Tech Stack:** Python 3.11+, uv, typer, paramiko, rich, pytest, pytest-mock

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv project config, dependencies, entry point |
| `unifiguard.conf.example` | Documented example config with all keys |
| `src/unifiguard/__init__.py` | Package marker, exposes `__version__` |
| `src/unifiguard/config.py` | `NetworkConfig` dataclass, `parse_config()`, `resolve_network()` |
| `src/unifiguard/logger.py` | `setup_logger()` — file + console handler, log-level config |
| `src/unifiguard/session.py` | `Session` dataclass, `read_ssh()`, `write_ssh()` (CloudKey/API write variants added in Plans 3–4) |
| `src/unifiguard/ssh.py` | `connect_usg()`, `connect_ck_via_jump()`, `connect_direct()`, `exec_command()` |
| `src/unifiguard/main.py` | Typer app, global flags, `--version`, session creation |
| `tests/conftest.py` | Shared pytest fixtures (mock SSH clients, sample configs) |
| `tests/test_config.py` | Config parsing and network resolution tests |
| `tests/test_logger.py` | Logger setup tests |
| `tests/test_session.py` | Session dry-run and ops-log tests |
| `tests/test_ssh.py` | SSH connection and error handling tests (paramiko mocked) |
| `tests/test_main.py` | CLI flag and `--version` tests |

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/unifiguard/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "unifiguard"
version = "0.1.0"
description = "WireGuard peer management for Ubiquiti USG networks"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
dependencies = [
    "paramiko>=3.0",
    "cryptography>=41.0",
    "requests>=2.31",
    "qrcode[pil]>=7.4",
    "rich>=13.0",
    "typer>=0.9",
]

[project.scripts]
unifiguard = "unifiguard.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pyinstaller>=6.0",
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `src/unifiguard/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create empty `tests/__init__.py` and `tests/conftest.py`**

`tests/__init__.py` — empty file.

`tests/conftest.py`:
```python
# Shared fixtures added here as the test suite grows.
```

- [ ] **Step 4: Install dependencies and verify**

```bash
uv sync
```

Expected: resolves and installs all dependencies with no errors.

- [ ] **Step 5: Verify entry point resolves**

```bash
uv run unifiguard --help
```

Expected: error like `No such command` or similar — confirms the entry point wires up (even though `main.py` doesn't exist yet, this will fail with an import error, which is expected at this stage).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/unifiguard/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold project structure and dependencies"
```

---

## Task 2: Logger Module

**Files:**
- Create: `src/unifiguard/logger.py`
- Create: `tests/test_logger.py`

`★ Insight: The logger is the first module because every subsequent module needs it. By writing it as a pure function that returns a configured logger (rather than a module-level singleton), it's easy to test in isolation and safe to call multiple times without handler duplication.`

- [ ] **Step 1: Write the failing tests**

`tests/test_logger.py`:
```python
import logging
import os
from pathlib import Path
from unifiguard.logger import setup_logger


def test_logger_returns_logger_instance(tmp_path):
    logger = setup_logger("INFO", tmp_path / "test.log")
    assert isinstance(logger, logging.Logger)


def test_logger_respects_level(tmp_path):
    logger = setup_logger("DEBUG", tmp_path / "test.log")
    assert logger.level == logging.DEBUG


def test_logger_creates_log_file(tmp_path):
    log_path = tmp_path / "logs" / "unifiguard_test.log"
    setup_logger("INFO", log_path)
    assert log_path.exists()


def test_logger_does_not_duplicate_handlers(tmp_path):
    log_path = tmp_path / "test.log"
    setup_logger("INFO", log_path)
    logger = setup_logger("INFO", log_path)
    # Each call should produce a fresh named logger, not stack handlers
    assert len(logger.handlers) == 2  # file + console


def test_logger_warning_level(tmp_path):
    logger = setup_logger("WARNING", tmp_path / "test.log")
    assert logger.level == logging.WARNING
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_logger.py -v
```

Expected: `ModuleNotFoundError: No module named 'unifiguard.logger'`

- [ ] **Step 3: Implement `src/unifiguard/logger.py`**

```python
import logging
import uuid
from pathlib import Path


def setup_logger(log_level: str, log_file: Path) -> logging.Logger:
    """Configure and return a logger with file and console handlers.

    Uses a unique logger name per call to avoid handler accumulation
    across multiple invocations in the same process.
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"unifiguard.{uuid.uuid4().hex[:8]}")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_logger.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/unifiguard/logger.py tests/test_logger.py
git commit -m "feat: add logger module with file and console handlers"
```

---

## Task 3: NetworkConfig Dataclass and Config Parsing

**Files:**
- Create: `src/unifiguard/config.py`
- Create: `tests/test_config.py`
- Create: `unifiguard.conf.example`

`★ Insight: Representing config as a typed dataclass (rather than a raw dict) gives you IDE autocompletion and a single source of truth for all valid keys. parse_config() returns a dict keyed by network name so multi-network support is a first-class concept from day one — the calling code never needs to know whether there's one network or ten.`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from pathlib import Path
from unifiguard.config import NetworkConfig, parse_config, resolve_network, ConfigError


# --- parse_config ---

def test_parse_single_network(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text(
        "[network.home]\n"
        "usg_host = 192.168.1.1\n"
        "usg_user = ubnt\n"
        "usg_pass = secret\n"
        "wg_subnet = 10.10.10.0/24\n"
        "wg_port = 51820\n"
    )
    result = parse_config(conf)
    assert "home" in result
    assert result["home"].usg_host == "192.168.1.1"
    assert result["home"].usg_user == "ubnt"
    assert result["home"].wg_port == 51820


def test_parse_multiple_networks(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text(
        "[network.home]\nusg_host = 10.0.0.1\n\n"
        "[network.office]\nusg_host = 10.0.1.1\n"
    )
    result = parse_config(conf)
    assert set(result.keys()) == {"home", "office"}


def test_parse_missing_file_returns_empty(tmp_path):
    result = parse_config(tmp_path / "nonexistent.conf")
    assert result == {}


def test_parse_defaults_applied(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text("[network.home]\nusg_host = 10.0.0.1\n")
    result = parse_config(conf)
    assert result["home"].wg_subnet == "10.10.10.0/24"
    assert result["home"].wg_port == 51820
    assert result["home"].controller_access == "jump"
    assert result["home"].log_level == "INFO"


def test_parse_key_path_fields(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text(
        "[network.home]\n"
        "usg_host = 10.0.0.1\n"
        "usg_key_path = /home/user/.ssh/id_rsa\n"
    )
    result = parse_config(conf)
    assert result["home"].usg_key_path == "/home/user/.ssh/id_rsa"


def test_parse_ignores_non_network_sections(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text("[global]\nfoo = bar\n\n[network.home]\nusg_host = 10.0.0.1\n")
    result = parse_config(conf)
    assert list(result.keys()) == ["home"]


# --- resolve_network ---

def test_resolve_by_flag(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text("[network.home]\nusg_host = 10.0.0.1\n\n[network.office]\nusg_host = 10.0.1.1\n")
    configs = parse_config(conf)
    resolved = resolve_network(configs, flag="home", default=None)
    assert resolved.usg_host == "10.0.0.1"


def test_resolve_flag_not_found_raises(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text("[network.home]\nusg_host = 10.0.0.1\n")
    configs = parse_config(conf)
    with pytest.raises(ConfigError, match="Network 'missing' not found"):
        resolve_network(configs, flag="missing", default=None)


def test_resolve_single_network_auto_selected(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text("[network.home]\nusg_host = 10.0.0.1\n")
    configs = parse_config(conf)
    resolved = resolve_network(configs, flag=None, default=None)
    assert resolved.usg_host == "10.0.0.1"


def test_resolve_default_network(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text(
        "[network.home]\nusg_host = 10.0.0.1\n\n"
        "[network.office]\nusg_host = 10.0.1.1\ndefault_network = office\n"
    )
    configs = parse_config(conf)
    # default_network is a top-level config key; read from first section that has it
    resolved = resolve_network(configs, flag=None, default="office")
    assert resolved.usg_host == "10.0.1.1"


def test_resolve_multiple_no_default_returns_none(tmp_path):
    conf = tmp_path / "unifiguard.conf"
    conf.write_text(
        "[network.home]\nusg_host = 10.0.0.1\n\n"
        "[network.office]\nusg_host = 10.0.1.1\n"
    )
    configs = parse_config(conf)
    # When multiple networks and no default/flag, returns None to signal interactive prompt
    result = resolve_network(configs, flag=None, default=None)
    assert result is None


def test_resolve_empty_configs_returns_none():
    result = resolve_network({}, flag=None, default=None)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'unifiguard.config'`

- [ ] **Step 3: Implement `src/unifiguard/config.py`**

```python
import configparser
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class NetworkConfig:
    # USG
    usg_host: str = ""
    usg_user: str = ""
    usg_pass: str = ""
    usg_key_path: str = ""
    # Controller access
    controller_access: str = "jump"   # "jump" or "direct"
    controller_ip: str = ""
    controller_ssh_user: str = ""
    controller_ssh_pass: str = ""
    controller_key_path: str = ""
    controller_user: str = ""
    controller_pass: str = ""
    # WireGuard
    wg_subnet: str = "10.10.10.0/24"
    wg_port: int = 51820
    # Tool behaviour
    output_dir: str = "./clients/"
    log_level: str = "INFO"
    default_network: str = ""


def parse_config(path: Path) -> dict[str, NetworkConfig]:
    """Parse a unifiguard.conf file and return a dict of {name: NetworkConfig}.

    Returns an empty dict if the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        return {}

    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    parser.read(path)

    configs: dict[str, NetworkConfig] = {}
    for section in parser.sections():
        if not section.startswith("network."):
            continue
        name = section[len("network."):]
        cfg = NetworkConfig()
        s = parser[section]

        cfg.usg_host = s.get("usg_host", cfg.usg_host)
        cfg.usg_user = s.get("usg_user", cfg.usg_user)
        cfg.usg_pass = s.get("usg_pass", cfg.usg_pass)
        cfg.usg_key_path = s.get("usg_key_path", cfg.usg_key_path)
        cfg.controller_access = s.get("controller_access", cfg.controller_access)
        cfg.controller_ip = s.get("controller_ip", cfg.controller_ip)
        cfg.controller_ssh_user = s.get("controller_ssh_user", cfg.controller_ssh_user)
        cfg.controller_ssh_pass = s.get("controller_ssh_pass", cfg.controller_ssh_pass)
        cfg.controller_key_path = s.get("controller_key_path", cfg.controller_key_path)
        cfg.controller_user = s.get("controller_user", cfg.controller_user)
        cfg.controller_pass = s.get("controller_pass", cfg.controller_pass)
        cfg.wg_subnet = s.get("wg_subnet", cfg.wg_subnet)
        cfg.wg_port = int(s.get("wg_port", str(cfg.wg_port)))
        cfg.output_dir = s.get("output_dir", cfg.output_dir)
        cfg.log_level = s.get("log_level", cfg.log_level)
        cfg.default_network = s.get("default_network", cfg.default_network)

        configs[name] = cfg

    return configs


def resolve_network(
    configs: dict[str, NetworkConfig],
    flag: str | None,
    default: str | None,
) -> NetworkConfig | None:
    """Select a NetworkConfig based on priority order.

    Priority:
      1. --network flag
      2. default_network value
      3. Single network auto-select
      4. Returns None → caller must prompt interactively

    Raises ConfigError if the requested network name is not found.
    """
    if not configs:
        return None

    if flag:
        if flag not in configs:
            raise ConfigError(f"Network '{flag}' not found in config. "
                              f"Available: {', '.join(configs)}")
        return configs[flag]

    if default and default in configs:
        return configs[default]

    if len(configs) == 1:
        return next(iter(configs.values()))

    return None  # Caller must present interactive selection
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Write `unifiguard.conf.example`**

```ini
# unifiguard configuration file
# Copy to unifiguard.conf and fill in your values.
# This file supports per-network configuration.
# Passwords may be stored here — ensure this file is gitignored.

# ---------------------------------------------------------------
# Network: home (you can have multiple [network.*] sections)
# ---------------------------------------------------------------
[network.home]

# Hostname or IP address of your UniFi Security Gateway
usg_host =

# SSH username for the USG (usually ubnt or a custom username)
usg_user =

# SSH password for the USG
usg_pass =

# SSH private key path for USG authentication (optional).
# If set, key auth is used instead of password auth.
# Key must be passphrase-free, or passphrase loaded into ssh-agent.
usg_key_path =

# How to access the UniFi Controller:
#   jump   = SSH through the USG as a jump host (use for on-site CloudKey)
#   direct = SSH directly to the controller (UDM, off-site, or VPS controller)
controller_access = jump

# LAN IP of the CloudKey or Controller (used when controller_access = jump)
controller_ip =

# SSH username for the Controller (used when controller_access = direct)
controller_ssh_user =

# SSH password for the Controller (used when controller_access = direct)
controller_ssh_pass =

# SSH private key path for Controller (used when controller_access = direct)
controller_key_path =

# UniFi Controller web UI username
controller_user =

# UniFi Controller web UI password
controller_pass =

# WireGuard subnet (default: 10.10.10.0/24)
# Change if this conflicts with an existing subnet on your network
wg_subnet = 10.10.10.0/24

# WireGuard listen port (default: 51820)
wg_port = 51820

# Directory to write client .conf and QR code files
output_dir = ./clients/

# Log verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)
log_level = INFO

# Default network profile to use when --network flag is omitted.
# If unset and multiple [network.*] sections exist, you will be prompted.
default_network =
```

- [ ] **Step 6: Commit**

```bash
git add src/unifiguard/config.py tests/test_config.py unifiguard.conf.example
git commit -m "feat: add NetworkConfig dataclass and config file parsing"
```

---

## Task 4: Session Module

**Files:**
- Create: `src/unifiguard/session.py`
- Create: `tests/test_session.py`

`★ Insight: The Session dataclass is the spine of the dry-run design. The key insight is that read_ssh() and write_ssh() are NOT methods on Session — they're module-level functions that take a Session. This keeps Session a pure data holder (easy to construct in tests) and puts behavior where it belongs: in functions, not in the dataclass.`

- [ ] **Step 1: Write the failing tests**

`tests/test_session.py`:
```python
import pytest
from unittest.mock import MagicMock, call
from unifiguard.session import Session, read_ssh, write_ssh


def make_mock_client():
    client = MagicMock()
    stdin = MagicMock()
    stdout = MagicMock()
    stdout.read.return_value = b"output\n"
    stderr = MagicMock()
    stderr.read.return_value = b""
    client.exec_command.return_value = (stdin, stdout, stderr)
    return client


def test_session_defaults():
    s = Session(dry_run=False, network=None, log_level="INFO")
    assert s.usg_client is None
    assert s.ck_client is None
    assert s.api_session is None
    assert s.ops == []
    assert s.config is None


def test_write_ssh_dry_run_suppresses_execution(capsys):
    client = make_mock_client()
    s = Session(dry_run=True, network=None, log_level="INFO")
    result = write_ssh(s, client, "sudo rm -rf /", "delete everything")
    client.exec_command.assert_not_called()
    assert result == ""
    assert s.ops == []


def test_write_ssh_dry_run_prints_description(capsys):
    client = make_mock_client()
    s = Session(dry_run=True, network=None, log_level="INFO")
    write_ssh(s, client, "echo hi", "print greeting")
    captured = capsys.readouterr()
    assert "print greeting" in captured.out


def test_write_ssh_executes_when_not_dry_run():
    client = make_mock_client()
    s = Session(dry_run=False, network=None, log_level="INFO")
    result = write_ssh(s, client, "echo hi", "print greeting")
    client.exec_command.assert_called_once_with("echo hi")
    assert result == "output\n"


def test_write_ssh_appends_to_ops():
    client = make_mock_client()
    s = Session(dry_run=False, network=None, log_level="INFO")
    write_ssh(s, client, "echo one", "step one")
    write_ssh(s, client, "echo two", "step two")
    assert s.ops == ["step one", "step two"]


def test_read_ssh_always_executes_in_dry_run():
    client = make_mock_client()
    s = Session(dry_run=True, network=None, log_level="INFO")
    result = read_ssh(s, client, "sudo wg show")
    client.exec_command.assert_called_once_with("sudo wg show")
    assert result == "output\n"


def test_read_ssh_does_not_append_to_ops():
    client = make_mock_client()
    s = Session(dry_run=False, network=None, log_level="INFO")
    read_ssh(s, client, "sudo wg show")
    assert s.ops == []


def test_write_ssh_does_not_append_in_dry_run():
    client = make_mock_client()
    s = Session(dry_run=True, network=None, log_level="INFO")
    write_ssh(s, client, "configure", "enter configure mode")
    assert s.ops == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_session.py -v
```

Expected: `ModuleNotFoundError: No module named 'unifiguard.session'`

- [ ] **Step 3: Implement `src/unifiguard/session.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    import paramiko
    import requests
    from unifiguard.config import NetworkConfig

console = Console()


@dataclass
class Session:
    dry_run: bool
    network: str | None
    log_level: str

    # SSH connections — populated during pre-flight
    usg_client: "paramiko.SSHClient | None" = None
    ck_client: "paramiko.SSHClient | None" = None
    api_session: "requests.Session | None" = None

    # Completed step log — used to track within-run progress for cleanup
    # on partial failure. Not used for detecting prior partial runs
    # (that is done by checking artifact presence on the USG/CloudKey via SSH).
    ops: list[str] = field(default_factory=list)

    # Resolved config for the selected network profile
    config: "NetworkConfig | None" = None


def read_ssh(session: Session, client: "paramiko.SSHClient", cmd: str) -> str:
    """Execute a read-only SSH command. Always runs, even in dry-run mode.

    Read operations are safe to execute during dry-run — they show actual
    current state alongside what would change, making dry-run output useful.
    """
    stdin, stdout, stderr = client.exec_command(cmd)
    return stdout.read().decode()


def write_ssh(
    session: Session,
    client: "paramiko.SSHClient",
    cmd: str,
    description: str,
) -> str:
    """Execute a write SSH command, suppressing it in dry-run mode.

    In dry-run mode: prints the description and returns an empty string.
    In normal mode: executes the command, appends description to ops log,
    and returns stdout.
    """
    if session.dry_run:
        console.print(f"[yellow][DRY RUN][/yellow] would run: {description}")
        return ""
    stdin, stdout, stderr = client.exec_command(cmd)
    result = stdout.read().decode()
    session.ops.append(description)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_session.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/unifiguard/session.py tests/test_session.py
git commit -m "feat: add Session dataclass with dry-run aware read_ssh/write_ssh helpers"
```

---

## Task 5: SSH Module — USG Connection and Auth Resolution

**Files:**
- Create: `src/unifiguard/ssh.py`
- Create: `tests/test_ssh.py`

`★ Insight: The auth resolution order (key path → password → prompt) is implemented as a single connect_usg() function rather than three separate functions. This keeps the calling code simple — it never needs to know which auth method was used — and makes it easy to test each branch independently by controlling what the NetworkConfig contains.`

- [ ] **Step 1: Write the failing tests for auth resolution**

`tests/test_ssh.py`:
```python
import socket
import pytest
import paramiko
from unittest.mock import MagicMock, patch, call
from unifiguard.ssh import connect_usg, exec_command, SSHError
from unifiguard.config import NetworkConfig
from unifiguard.session import Session


def make_session(config: NetworkConfig) -> Session:
    s = Session(dry_run=False, network="home", log_level="INFO")
    s.config = config
    return s


# --- exec_command ---

def test_exec_command_returns_stdout_stderr():
    client = MagicMock()
    stdout = MagicMock()
    stdout.read.return_value = b"hello\n"
    stderr = MagicMock()
    stderr.read.return_value = b""
    client.exec_command.return_value = (MagicMock(), stdout, stderr)

    out, err = exec_command(client, "echo hello")
    assert out == "hello\n"
    assert err == ""


def test_exec_command_returns_stderr():
    client = MagicMock()
    stdout = MagicMock()
    stdout.read.return_value = b""
    stderr = MagicMock()
    stderr.read.return_value = b"error message\n"
    client.exec_command.return_value = (MagicMock(), stdout, stderr)

    out, err = exec_command(client, "bad-command")
    assert err == "error message\n"


# --- connect_usg: auth resolution ---

@patch("unifiguard.ssh.paramiko.SSHClient")
@patch("unifiguard.ssh.paramiko.RSAKey.from_private_key_file")
def test_connect_usg_uses_key_when_key_path_set(mock_rsa, mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_key = MagicMock()
    mock_rsa.return_value = mock_key

    cfg = NetworkConfig(usg_host="10.0.0.1", usg_user="ubnt", usg_key_path="/home/user/.ssh/id_rsa")
    session = make_session(cfg)

    result = connect_usg(session)

    mock_rsa.assert_called_once_with("/home/user/.ssh/id_rsa")
    mock_client.connect.assert_called_once_with(
        "10.0.0.1", username="ubnt", pkey=mock_key
    )
    assert result is mock_client


@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_usg_uses_password_when_no_key(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    cfg = NetworkConfig(usg_host="10.0.0.1", usg_user="ubnt", usg_pass="secret")
    session = make_session(cfg)

    result = connect_usg(session)

    mock_client.connect.assert_called_once_with(
        "10.0.0.1", username="ubnt", password="secret"
    )
    assert result is mock_client


@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_usg_key_takes_precedence_over_password(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    with patch("unifiguard.ssh.paramiko.RSAKey.from_private_key_file") as mock_rsa:
        mock_key = MagicMock()
        mock_rsa.return_value = mock_key

        cfg = NetworkConfig(
            usg_host="10.0.0.1",
            usg_user="ubnt",
            usg_pass="secret",
            usg_key_path="/home/user/.ssh/id_rsa",
        )
        session = make_session(cfg)
        connect_usg(session)

    # Key auth called, NOT password auth
    call_kwargs = mock_client.connect.call_args.kwargs
    assert "pkey" in call_kwargs
    assert "password" not in call_kwargs


# --- connect_usg: error handling ---

@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_usg_connection_refused_raises_ssh_error(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.connect.side_effect = socket.error(111, "Connection refused")

    cfg = NetworkConfig(usg_host="10.0.0.1", usg_user="ubnt", usg_pass="secret")
    session = make_session(cfg)

    with pytest.raises(SSHError, match="Connection refused"):
        connect_usg(session)


@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_usg_auth_failure_raises_ssh_error(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.connect.side_effect = paramiko.AuthenticationException()

    cfg = NetworkConfig(usg_host="10.0.0.1", usg_user="ubnt", usg_pass="wrong")
    session = make_session(cfg)

    with pytest.raises(SSHError, match="Authentication failed"):
        connect_usg(session)


@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_usg_sets_missing_host_key_policy(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    cfg = NetworkConfig(usg_host="10.0.0.1", usg_user="ubnt", usg_pass="secret")
    session = make_session(cfg)
    connect_usg(session)

    mock_client.set_missing_host_key_policy.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_ssh.py -v
```

Expected: `ModuleNotFoundError: No module named 'unifiguard.ssh'`

- [ ] **Step 3: Implement `src/unifiguard/ssh.py` (USG connection only)**

```python
from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import paramiko

if TYPE_CHECKING:
    from unifiguard.session import Session


class SSHError(Exception):
    pass


def exec_command(client: paramiko.SSHClient, cmd: str) -> tuple[str, str]:
    """Execute a command and return (stdout, stderr) as decoded strings."""
    _, stdout, stderr = client.exec_command(cmd)
    return stdout.read().decode(), stderr.read().decode()


def connect_usg(session: Session) -> paramiko.SSHClient:
    """Open an SSH connection to the USG.

    Auth resolution order:
      1. usg_key_path set → RSA key auth
      2. usg_pass set → password auth
      3. Neither → raises SSHError (caller must prompt and retry)
    """
    cfg = session.config
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {"username": cfg.usg_user}

    if cfg.usg_key_path:
        try:
            pkey = paramiko.RSAKey.from_private_key_file(cfg.usg_key_path)
        except (paramiko.SSHException, OSError) as e:
            raise SSHError(f"Failed to load key '{cfg.usg_key_path}': {e}") from e
        connect_kwargs["pkey"] = pkey
    elif cfg.usg_pass:
        connect_kwargs["password"] = cfg.usg_pass
    else:
        raise SSHError(
            "No USG credentials configured. Set usg_key_path or usg_pass in config."
        )

    try:
        client.connect(cfg.usg_host, **connect_kwargs)
    except paramiko.AuthenticationException as e:
        raise SSHError(
            f"Authentication failed for {cfg.usg_user}@{cfg.usg_host}. "
            "Check your credentials."
        ) from e
    except socket.error as e:
        raise SSHError(
            f"Connection refused to {cfg.usg_host}. "
            "Verify the host is reachable and SSH is enabled."
        ) from e
    except Exception as e:
        raise SSHError(f"Failed to connect to USG at {cfg.usg_host}: {e}") from e

    return client
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_ssh.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/unifiguard/ssh.py tests/test_ssh.py
git commit -m "feat: add SSH module with USG connection and auth resolution"
```

---

## Task 6: SSH Module — CloudKey Jump Host and Direct Controller

**Files:**
- Modify: `src/unifiguard/ssh.py`
- Modify: `tests/test_ssh.py`

`★ Insight: The jump-host pattern in paramiko works by opening a direct-tcpip channel through the existing USG transport, then constructing a new SSHClient that uses that channel as its socket. The key is that paramiko.SSHClient.connect() accepts a sock= parameter — this is the escape hatch that makes jump hosts possible without shelling out to OpenSSH.`

- [ ] **Step 1: Add jump host and direct connection tests**

Add these two imports to the existing import block at the top of `tests/test_ssh.py`:
```python
from unifiguard.ssh import connect_ck_via_jump, connect_direct
```

Then append the following test functions to the bottom of `tests/test_ssh.py`:
```python
from unifiguard.ssh import connect_ck_via_jump, connect_direct


# --- connect_ck_via_jump ---

@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_ck_via_jump_opens_channel(mock_client_cls):
    # USG transport mock
    usg_client = MagicMock()
    transport = MagicMock()
    channel = MagicMock()
    usg_client.get_transport.return_value = transport
    transport.open_channel.return_value = channel

    # CloudKey client mock
    ck_client = MagicMock()
    mock_client_cls.return_value = ck_client

    cfg = NetworkConfig(
        usg_host="10.0.0.1",
        controller_ip="192.168.1.2",
        controller_ssh_user="ui",
        controller_ssh_pass="cloudkeypass",
    )
    session = make_session(cfg)

    result = connect_ck_via_jump(session, usg_client)

    transport.open_channel.assert_called_once_with(
        "direct-tcpip", ("192.168.1.2", 22), ("127.0.0.1", 0)
    )
    ck_client.connect.assert_called_once_with(
        "192.168.1.2", username="ui", password="cloudkeypass", sock=channel
    )
    assert result is ck_client


@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_ck_via_jump_uses_key_when_set(mock_client_cls):
    usg_client = MagicMock()
    transport = MagicMock()
    channel = MagicMock()
    usg_client.get_transport.return_value = transport
    transport.open_channel.return_value = channel

    ck_client = MagicMock()
    mock_client_cls.return_value = ck_client

    with patch("unifiguard.ssh.paramiko.RSAKey.from_private_key_file") as mock_rsa:
        mock_key = MagicMock()
        mock_rsa.return_value = mock_key

        cfg = NetworkConfig(
            usg_host="10.0.0.1",
            controller_ip="192.168.1.2",
            controller_ssh_user="ui",
            controller_key_path="/home/user/.ssh/ck_key",
        )
        session = make_session(cfg)
        connect_ck_via_jump(session, usg_client)

    call_kwargs = ck_client.connect.call_args.kwargs
    assert "pkey" in call_kwargs
    assert "password" not in call_kwargs


# --- connect_direct ---

@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_direct_uses_controller_host(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    cfg = NetworkConfig(
        controller_ip="10.0.0.5",
        controller_ssh_user="admin",
        controller_ssh_pass="adminpass",
    )
    session = make_session(cfg)

    result = connect_direct(session)

    mock_client.connect.assert_called_once_with(
        "10.0.0.5", username="admin", password="adminpass"
    )
    assert result is mock_client


@patch("unifiguard.ssh.paramiko.SSHClient")
def test_connect_direct_cloudkey_ssh_disabled_gives_helpful_error(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.connect.side_effect = socket.error(111, "Connection refused")

    cfg = NetworkConfig(
        controller_ip="192.168.1.2",
        controller_ssh_user="ui",
        controller_ssh_pass="pass",
    )
    session = make_session(cfg)

    with pytest.raises(SSHError) as exc_info:
        connect_direct(session)

    assert "SSH may be disabled" in str(exc_info.value)
    assert "192.168.1.2/manage" in str(exc_info.value)
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
uv run pytest tests/test_ssh.py -v -k "jump or direct"
```

Expected: `ImportError: cannot import name 'connect_ck_via_jump'`

- [ ] **Step 3: Add `connect_ck_via_jump` and `connect_direct` to `src/unifiguard/ssh.py`**

Append to `ssh.py`:
```python
def connect_ck_via_jump(
    session: Session, usg_client: paramiko.SSHClient
) -> paramiko.SSHClient:
    """Connect to the CloudKey by tunnelling through the USG as a jump host."""
    cfg = session.config
    transport = usg_client.get_transport()
    channel = transport.open_channel(
        "direct-tcpip",
        (cfg.controller_ip, 22),
        ("127.0.0.1", 0),
    )

    ck_client = paramiko.SSHClient()
    ck_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {"username": cfg.controller_ssh_user, "sock": channel}

    if cfg.controller_key_path:
        try:
            pkey = paramiko.RSAKey.from_private_key_file(cfg.controller_key_path)
        except (paramiko.SSHException, OSError) as e:
            raise SSHError(f"Failed to load CloudKey key '{cfg.controller_key_path}': {e}") from e
        connect_kwargs["pkey"] = pkey
    elif cfg.controller_ssh_pass:
        connect_kwargs["password"] = cfg.controller_ssh_pass
    else:
        raise SSHError("No CloudKey credentials configured.")

    try:
        ck_client.connect(cfg.controller_ip, **connect_kwargs)
    except paramiko.AuthenticationException as e:
        raise SSHError(
            f"Authentication failed for {cfg.controller_ssh_user}@{cfg.controller_ip}."
        ) from e
    except Exception as e:
        raise SSHError(f"Failed to connect to CloudKey at {cfg.controller_ip}: {e}") from e

    return ck_client


def connect_direct(session: Session) -> paramiko.SSHClient:
    """Connect directly to the Controller (non-jump-host mode)."""
    cfg = session.config
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {"username": cfg.controller_ssh_user}

    if cfg.controller_key_path:
        try:
            pkey = paramiko.RSAKey.from_private_key_file(cfg.controller_key_path)
        except (paramiko.SSHException, OSError) as e:
            raise SSHError(f"Failed to load key '{cfg.controller_key_path}': {e}") from e
        connect_kwargs["pkey"] = pkey
    elif cfg.controller_ssh_pass:
        connect_kwargs["password"] = cfg.controller_ssh_pass
    else:
        raise SSHError("No Controller credentials configured.")

    try:
        client.connect(cfg.controller_ip, **connect_kwargs)
    except paramiko.AuthenticationException as e:
        raise SSHError(
            f"Authentication failed for {cfg.controller_ssh_user}@{cfg.controller_ip}."
        ) from e
    except socket.error as e:
        raise SSHError(
            f"Connection refused to Controller at {cfg.controller_ip}. "
            "SSH may be disabled. Enable it at: "
            f"https://{cfg.controller_ip}/manage → Settings → Advanced → SSH"
        ) from e
    except Exception as e:
        raise SSHError(f"Failed to connect to Controller at {cfg.controller_ip}: {e}") from e

    return client
```

- [ ] **Step 4: Run all SSH tests**

```bash
uv run pytest tests/test_ssh.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/unifiguard/ssh.py tests/test_ssh.py
git commit -m "feat: add CloudKey jump-host and direct controller SSH connections"
```

---

## Task 7: main.py Skeleton

**Files:**
- Create: `src/unifiguard/main.py`
- Create: `tests/test_main.py`

`★ Insight: Typer's callback() with invoke_without_command=True is the right place for global flags. The callback runs before any subcommand, constructing the Session. Using a typer.Context to pass Session to subcommands (rather than global state) keeps the app testable — you can invoke the CLI in tests with CliRunner without sharing state between test runs.`

- [ ] **Step 1: Write failing tests**

`tests/test_main.py`:
```python
from typer.testing import CliRunner
from unifiguard.main import app
from unifiguard import __version__

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_flag():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "unifiguard" in result.output.lower()


def test_dry_run_flag_accepted():
    # --dry-run is a global flag; with no subcommand the app should exit cleanly
    result = runner.invoke(app, ["--dry-run", "--help"])
    assert result.exit_code == 0


def test_network_flag_accepted():
    result = runner.invoke(app, ["--network", "home", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'unifiguard.main'`

- [ ] **Step 3: Implement `src/unifiguard/main.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from unifiguard import __version__

app = typer.Typer(
    name="unifiguard",
    help="WireGuard peer management for Ubiquiti USG networks.",
    no_args_is_help=True,
)

# Global state passed via typer context
_session_params: dict = {}


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Read-only mode — no writes."),
    network: Optional[str] = typer.Option(None, "--network", "-n", help="Network profile name."),
    config: Path = typer.Option(Path("./unifiguard.conf"), "--config", help="Config file path."),
    log_level: str = typer.Option("INFO", "--log-level", help="Log verbosity."),
    output_dir: Path = typer.Option(Path("./clients/"), "--output-dir", help="Client file output dir."),
) -> None:
    if version:
        typer.echo(f"unifiguard {__version__}")
        raise typer.Exit()

    # Store global params for subcommands to consume
    ctx.ensure_object(dict)
    ctx.obj["dry_run"] = dry_run
    ctx.obj["network"] = network
    ctx.obj["config"] = config
    ctx.obj["log_level"] = log_level
    ctx.obj["output_dir"] = output_dir
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_main.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests in all modules PASS. Zero failures.

- [ ] **Step 6: Verify CLI entry point works**

```bash
uv run unifiguard --version
uv run unifiguard --help
```

Expected: version string printed, help text shows global flags.

- [ ] **Step 7: Commit**

```bash
git add src/unifiguard/main.py tests/test_main.py
git commit -m "feat: add main.py CLI skeleton with global flags and --version"
```

---

## Final Check

- [ ] **Run full test suite one last time**

```bash
uv run pytest -v --tb=short
```

Expected: all tests PASS, zero warnings about missing modules.

- [ ] **Verify package installs cleanly**

```bash
uv run unifiguard --version
uv run unifiguard --help
```

---

## What's Next

This plan is complete when all tests pass and `unifiguard --version` works.

The next three plans build on this foundation in order:

- **Plan 2 — USG & WireGuard:** `wireguard.py`, `setup` command, `status` command (USG layer), pre-flight checks, partial setup detection
- **Plan 3 — CloudKey & Controller:** `cloudkey.py`, `unifi_api.py`, `provisioning.py`, `status` command (CloudKey/Controller layers)
- **Plan 4 — Commands & Output:** `peer add/remove/list/update`, `output.py`, post-peer verification flow, GitHub Actions build
