# unifiguard Improvements Design
**Date:** 2026-04-02  
**Status:** Approved  
**Scope:** Additions and improvements to the base spec defined in CLAUDE.md

---

## Overview

This document captures design decisions made on top of the base CLAUDE.md spec. It covers five areas: session architecture, CLI command additions, config file additions, error handling improvements, and post-deployment verification. All decisions here extend the existing spec — nothing in CLAUDE.md is removed or contradicted.

---

## Section 1: Session Context Architecture

### Motivation

Several features (dry-run, partial-failure cleanup, key vs password auth) all require shared context flowing through every service module. Threading this via function arguments or global state leads to scattered `if dry_run:` checks and makes testing difficult. A `Session` dataclass solves this cleanly.

### Session Dataclass

Lives in `src/unifiguard/session.py`. Created once in `main.py` before any command runs and passed into every service function that touches SSH, the Controller API, or the filesystem.

```python
@dataclass
class Session:
    # Runtime flags
    dry_run: bool
    network: str | None         # selected network profile name
    log_level: str

    # Connections (populated lazily during pre-flight)
    usg_client: paramiko.SSHClient | None = None
    ck_client:  paramiko.SSHClient | None = None
    api_session: requests.Session | None = None

    # Operation log — completed step descriptions appended here
    # Used for cleanup on partial failure and dry-run reporting
    ops: list[str] = field(default_factory=list)

    # Resolved config for the selected network profile
    config: NetworkConfig | None = None
```

### Dry-Run Helpers

Two SSH helpers in `session.py` enforce the read/write distinction:

```python
def read_ssh(session: Session, cmd: str) -> str:
    """Always executes — reads are safe in dry-run mode."""
    stdout, _ = exec_command(session.usg_client, cmd)
    return stdout

def write_ssh(session: Session, cmd: str, description: str) -> str:
    """Suppressed in dry-run mode. Appends to ops log on execution."""
    if session.dry_run:
        console.print(f"[DRY RUN] would run: {description}")
        return ""
    stdout, _ = exec_command(session.usg_client, cmd)
    session.ops.append(description)
    return stdout
```

Read operations (`sudo wg show`, reading `peers.json`, fetching site list, pre-flight checks) always use `read_ssh()`. Write operations (configure mode changes, file writes, API calls that modify state) always use `write_ssh()` or equivalent CloudKey/API variants. This is what makes dry-run useful: it shows actual current state alongside what would change.

### Within-Run Failure Tracking

`session.ops` tracks what the *current run* has completed. If a command fails mid-execution, the ops log tells the cleanup path exactly what to undo. This is distinct from detecting a *prior* partial run — that is done by checking artifact presence on the USG/CloudKey via SSH (see Section 4).

---

## Section 2: CLI Commands

### Global Flags (all commands)

```
--network <name>   Select network profile from config.
                   Interactive prompt if omitted and multiple profiles exist.
                   Auto-selected silently if only one profile is defined.
--dry-run          Read-only mode. SSH connects and reads state; no writes executed.
--config <path>    Config file path (default: ./unifiguard.conf)
--log-level        DEBUG | INFO | WARNING | ERROR (default: INFO)
--output-dir       Client file output directory (default: ./clients/)
```

### `unifiguard setup` (updated)

All existing steps from CLAUDE.md apply. Additions:

- **Pre-flight check** runs before any work (see Section 4)
- **Partial setup detection** on start: checks for prior incomplete run, offers cleanup (see Section 4)
- **Subnet conflict detection**: parses `show interfaces`, warns and aborts if `wg_subnet` overlaps any existing USG interface subnet
- **Dry-run output**: architecture detection result, full wg0 config that would be applied, firewall/NAT rules that would be added, `config.gateway.json` diff

### `unifiguard status` (new)

Read-only health check across all layers. Connects to all devices (runs pre-flight) but makes no changes. Safe to run at any time. Exits non-zero if any check fails.

**USG checks:**
- SSH reachable
- WireGuard kernel module loaded (`lsmod | grep wireguard`)
- wg0 interface up
- Listen port active
- WAN_LOCAL firewall rule present
- NAT masquerade rule present
- Persistence script present (`/config/scripts/install-edgeos-packages`)

**CloudKey checks:**
- SSH reachable
- `config.gateway.json` exists and is valid JSON
- Peer count in JSON matches live `sudo wg show` peer count

**Controller API checks:**
- Reachable (tries `/proxy/network` then `:8443`)
- Authenticated
- USG device found in site
- USG provisioning state (provisioned / provisioning / adopting)

**Per-peer checks:**
- Latest handshake timestamp (flags peers that have never connected)
- rx/tx bytes non-zero (flags peers connected but with no traffic)

### `unifiguard peer add` (updated)

All existing steps from CLAUDE.md apply. Additions:

- Pre-flight check before any work
- Dry-run support: shows tunnel IP that would be assigned, client config that would be generated, `config.gateway.json` diff
- Post-add verification flow (see Section 5)

### `unifiguard peer list`

Unchanged from CLAUDE.md.

### `unifiguard peer remove <friendly-name>` (updated)

All existing steps from CLAUDE.md apply. Additions:

- Pre-flight check before any work
- Dry-run support: shows peer details, JSON diff, confirms no writes will occur

### `unifiguard peer update <friendly-name>` (new)

Prompts at start:
```
Rename this peer? [y/N]
Rotate this peer's keys? [y/N]
```
At least one must be selected.

**Rename flow:**
1. Prompt for new friendly name
2. Update `peers.json` on USG
3. Rename `clients/<old>.conf` and `clients/<old>_qr.png` if they exist locally
   (warns if not found locally — does not abort, remote state is authoritative)

**Key rotation flow:**
1. Generate new client keypair locally
2. Update peer on USG via configure mode (replace public key)
3. Update `peers.json` on USG
4. Backup `config.gateway.json`, merge updated public key, write
5. Trigger re-provisioning and poll
6. Regenerate `clients/<name>.conf` and QR code
   (old `.conf` backed up as `<name>.conf.bak` before overwrite)
7. Post-rotation verification flow (same as peer add, see Section 5)

Both operations together in one invocation: rename runs first, key rotation runs second using the new name.

---

## Section 3: Config File Additions

New fields in `unifiguard.conf.example`:

```ini
# SSH private key path for USG authentication (optional)
# If set, key auth is attempted before password auth
# Key must be passphrase-free, or passphrase loaded into ssh-agent
usg_key_path =

# SSH private key path for Controller (used when controller_access = direct)
controller_key_path =

# Default network profile to use when --network flag is omitted
# If unset and multiple [network.*] sections exist, interactive prompt is shown
default_network =
```

### Auth Resolution Order

Applied per connection (USG and Controller independently):

1. `usg_key_path` set in config → key auth via `paramiko.RSAKey.from_private_key_file()`
2. `usg_pass` set in config → password auth
3. Neither set → prompt interactively

### Multi-Network Selection Logic

Applied at session start, before pre-flight:

1. `--network <name>` flag provided → use that profile; error clearly if not found in config
2. `default_network` set in config → use that profile silently
3. Exactly one `[network.*]` section defined → use it, log the name
4. Multiple profiles, no default, no flag → display rich table of profiles, interactive prompt
5. No config file → full interactive credential prompting (existing CLAUDE.md behavior)

---

## Section 4: Error Handling & Safety Improvements

### Pre-Flight Connectivity Check

Every command that touches more than one device runs a pre-flight before any configuration work. Fails fast with a per-device status table before touching anything:

```
Pre-flight check failed — aborting before making any changes.

  USG (192.168.1.1)        ✓ connected
  CloudKey (192.168.1.2)   ✗ connection refused — SSH may be disabled
  Controller API            ✗ skipped (CloudKey unreachable)

CloudKey SSH is disabled. Enable it at:
  https://192.168.1.2/manage → Settings → Advanced → SSH
```

Pre-flight also:
- Validates credentials (surfaces wrong passwords before any work begins)
- Resolves and caches the Controller site ID
- Detects CloudKey SSH disabled specifically (errno 111) with actionable instructions
- Runs in `--dry-run` mode too (read access to all devices is required for useful output)

### Partial Setup Detection

On `setup` start, checks for these artifacts in order:

1. `/config/auth/wireguard/` directory exists on USG
2. `wg0` interface present in `show interfaces`
3. `peers.json` present at `/config/auth/wireguard/peers.json`
4. `config.gateway.json` present on CloudKey at expected path

Any combination short of all-four-present is a partial setup. The tool displays:
- Which artifacts were found
- Which are missing
- Then asks: **"Clean up partial setup and start fresh? [y/N]"**

Cleanup removes (with per-step logging):
- wg0 configure mode entries (`delete interfaces wireguard wg0`)
- Key files from `/config/auth/wireguard/`
- The WireGuard package (`dpkg --remove wireguard`)
- The persistence script
- WireGuard sections from `config.gateway.json` (if present)

After cleanup, exits cleanly so the user reruns `setup` from scratch.

### Subnet Conflict Detection

Before writing any config during `setup`, parses `show interfaces` and checks if `wg_subnet` overlaps any existing interface subnet using Python's `ipaddress` module:

```
Warning: WireGuard subnet 10.10.10.0/24 overlaps with eth1 (10.10.10.1/24).
Change wg_subnet in your config file and re-run setup.
```

Aborts before touching anything.

### config.gateway.json Conflict Resolution

When adding WireGuard config, inspects existing rules for conflicts:

- **Firewall rule conflict** (WAN_LOCAL rule `20` already taken): finds next available rule number ≥ 20, informs user: `"WAN_LOCAL rule 20 is taken — using rule 21 for WireGuard UDP."`
- **NAT rule conflict** (rule `5000` already taken): finds next available ≥ 5000, same notification pattern

Both chosen rule numbers are shown in dry-run output and the confirmation prompt before writing.

### Additional Edge Cases

- **USG already in configure mode**: `configure` returns "already configured" — detect this string and skip the command rather than aborting
- **CloudKey sites directory missing**: created automatically with `mkdir -p`, logged at INFO
- **Controller API version fallback**: tries `/proxy/network` first, falls back to `:8443`, logs which URL succeeded
- **WAN IP is RFC1918**: flagged prominently with explanation during endpoint detection; user prompted to override with public IP or DDNS hostname

---

## Section 5: Post-Deployment Verification

### AllowedIPs Default

Generated client configs always use:

```ini
AllowedIPs = 0.0.0.0/0, ::/0
```

The `::/0` entry is not macOS-specific — omitting it causes silent routing failures on macOS because the OS routes some traffic via IPv6 even for IPv4 destinations. Including it is harmless on all other platforms. This is the universal default; it is not configurable (no valid reason to omit it for full-tunnel mode).

### Post-Peer-Add Verification Flow

After `peer add` and `peer update` (key rotation), once client config/QR code is delivered:

```
Peer "vash-iphone" added. Client config written to clients/vash-iphone.conf

Next step: import the config into your WireGuard app and connect.
Waiting for handshake... (press Ctrl+C to skip)  [elapsed: 0:00:12]
```

Polls `sudo wg show` every 5 seconds, up to 5 minutes. Ctrl+C skips gracefully with a reminder to run `unifiguard status` later.

**On handshake detected**, verifies traffic routing server-side:

| Check | Method | Pass condition |
|---|---|---|
| Handshake occurred | `sudo wg show` | Latest handshake ≤ 30s ago |
| Traffic flowing | `sudo wg show` rx/tx bytes | Both non-zero |
| NAT masquerade active | `show nat rules` | Rule present for WireGuard subnet |
| Route allowed IPs | `show interfaces wireguard wg0` | `route-allowed-ips: true` |

**All checks pass:**
```
✓ Handshake confirmed
✓ Traffic flowing (↑ 1.2 KiB  ↓ 840 B)
✓ NAT masquerade rule active
✓ Route allowed IPs enabled

Connection verified. vash-iphone is live.
```

**Handshake confirmed but no traffic** (silent failure detection):
```
✓ Handshake confirmed
✗ No traffic detected — tunnel connected but traffic may not be routing correctly.

  Common causes:
  • AllowedIPs missing ::/0 in client config (this tool uses the correct default;
    check if you are using an old manually-created config)
  • NAT masquerade rule missing or targeting wrong subnet
  • route-allowed-ips not enabled on wg0

  Run `unifiguard status` to check all layers.
```

**If Ctrl+C skipped:** prints client config path and reminder to run `unifiguard status`.

---

## Summary of Changes vs CLAUDE.md

| Area | Change |
|---|---|
| New file | `src/unifiguard/session.py` — `Session` dataclass |
| New command | `unifiguard status` |
| New command | `unifiguard peer update <name>` |
| New global flags | `--dry-run`, `--network <name>` |
| New config fields | `usg_key_path`, `controller_key_path`, `default_network` |
| Auth | SSH key auth via key path, password fallback, interactive fallback |
| Safety | Pre-flight connectivity check before every multi-device command |
| Safety | Partial setup detection and cleanup on `setup` |
| Safety | Subnet conflict detection on `setup` |
| Safety | `config.gateway.json` rule conflict auto-merge |
| Error UX | CloudKey SSH disabled → actionable instructions |
| Error UX | USG in configure mode → detect and skip, not abort |
| Correctness | `AllowedIPs = 0.0.0.0/0, ::/0` universal default |
| Verification | Server-side handshake + traffic polling after `peer add` / `peer update` |
| Verification | Silent-failure detection and diagnostic output |
