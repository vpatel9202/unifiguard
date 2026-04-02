# unifiguard

A cross-platform CLI tool for managing WireGuard VPN peers on Ubiquiti USG networks.
Handles both initial WireGuard setup and ongoing peer management, with full persistence
via config.gateway.json on the CloudKey and USG re-provisioning via the UniFi Controller API.

Licensed under MIT. Public repository.

---

## Project Structure

```
unifiguard/
├── CLAUDE.md
├── README.md
├── LICENSE
├── .gitignore                      # includes /clients/, *.log, unifiguard.conf
├── unifiguard.conf.example         # example config file with comments
├── .github/
│   └── workflows/
│       └── build.yml               # PyInstaller builds for win/mac/linux
├── pyproject.toml                  # uv project config, Python 3.11+
├── src/
│   └── unifiguard/
│       ├── __init__.py
│       ├── main.py                 # CLI entrypoint, typer app
│       ├── ssh.py                  # SSH connections, jump host logic
│       ├── wireguard.py            # Key generation, peer management
│       ├── unifi_api.py            # UniFi Controller API client
│       ├── cloudkey.py             # config.gateway.json read/write/backup
│       ├── config.py               # Config file, credential prompting, defaults
│       ├── provisioning.py         # Re-provisioning, polling, rollback
│       ├── output.py               # Client .conf + QR code generation
│       └── logger.py               # Logging setup
└── clients/                        # Default output dir, gitignored
    └── logs/                       # Log files, gitignored
```

---

## Dependencies

Use uv for all dependency management. Python 3.11+ required.

Key dependencies:
- `paramiko` — SSH connections (direct + jump host)
- `cryptography` — WireGuard key generation (Curve25519)
- `requests` — UniFi Controller API (SSL verification disabled, self-signed certs)
- `qrcode[pil]` — QR code generation
- `rich` — terminal output, tables, prompts, progress
- `typer` — CLI interface
- `pyinstaller` — binary builds (dev dependency)

---

## CLI Commands

### `unifiguard setup`
Full initial WireGuard setup on a USG from scratch.

Steps:
1. Collect credentials (see Credentials section)
2. SSH into USG
3. Detect architecture (mips64/x86_64) — fail gracefully if unexpected
4. Fetch latest wireguard-vyatta-ubnt release from GitHub API for detected arch
5. Verify checksum before installing
6. Install WireGuard package via dpkg
7. Verify kernel module loads (`sudo modprobe wireguard`)
8. Generate USG server keypair at /config/auth/wireguard/
9. Configure wg0 interface (address, listen-port, private-key, route-allowed-ips)
10. Add WAN_LOCAL firewall rule for UDP 51820
11. Add NAT masquerade rule 5000 for WireGuard subnet
12. Set up install-edgeos-packages persistence script
13. Download wireguard.deb to /config/data/install-packages/
14. Initialize peers metadata file at /config/auth/wireguard/peers.json
15. Authenticate to UniFi Controller API
16. Discover site ID (see Site ID Discovery)
17. Connect to Controller (jump host or direct, per user choice)
18. Create config.gateway.json
19. Prompt user to confirm re-provisioning
20. If confirmed, trigger re-provisioning and poll for USG recovery (see Provisioning)
21. Verify WireGuard running post-provision via `sudo wg show`
22. Add first peer (inline peer add flow)
23. Prompt to save defaults to config file (opt-in, per-network)

If WireGuard is already configured on USG:
- Detect this condition
- Warn user: "WireGuard appears to already be configured on this USG."
- Ask: "Skip setup and proceed to peer management, or abort?"
- If skip: jump to peer add flow
- If abort: exit cleanly

### `unifiguard peer add`
Add a new WireGuard peer.

Steps:
1. Collect credentials
2. SSH into USG
3. Read /config/auth/wireguard/peers.json
   - If missing: reconstruct state from `sudo wg show` + key files in
     /config/auth/wireguard/ — warn user that metadata file was missing
4. Determine next available tunnel IP (see IP Assignment)
5. Prompt for friendly name (used for filename, description, key filenames)
   - Example: "vash-iphone" → client files: clients/vash-iphone.conf,
     clients/vash-iphone_qr.png
6. Generate client keypair locally using cryptography library
7. Add peer to USG via configure mode
8. Update peers.json on USG
9. Connect to Controller (jump host or direct)
10. Read existing config.gateway.json from CloudKey
    - Create timestamped backup on CloudKey and locally before any changes
11. Merge new peer into JSON
12. Validate JSON
13. Write updated config.gateway.json
14. Prompt user to confirm re-provisioning
15. If confirmed, trigger re-provisioning and poll for USG recovery
16. Verify peer appears in `sudo wg show`
17. Generate client .conf file to clients/<friendly-name>.conf
18. Generate QR code to clients/<friendly-name>_qr.png
19. Print summary table (tunnel IP, public key, endpoint, output paths)

### `unifiguard peer list`
List all WireGuard peers with live stats.

Output (rich table):
- Friendly name (from peers.json, or "unknown" if missing)
- Tunnel IP
- Public key (truncated)
- Latest handshake
- Transfer (received/sent)
- Assigned since (from peers.json)

Data source: `sudo wg show` for live stats, peers.json for metadata.

### `unifiguard peer remove <friendly-name>`
Remove a peer by friendly name.

Steps:
1. Collect credentials
2. SSH into USG
3. Read peers.json, find peer by friendly name — fail gracefully if not found
4. Show peer details, ask for confirmation
5. Remove peer from USG via configure mode
6. Delete key files from /config/auth/wireguard/
7. Update peers.json
8. Connect to Controller
9. Backup config.gateway.json (timestamped, CloudKey + local)
10. Remove peer from JSON, validate, write
11. Prompt user to confirm re-provisioning
12. If confirmed, trigger re-provisioning and poll
13. Verify peer no longer appears in `sudo wg show`
14. Inform user local .conf and QR files were NOT deleted (user manages those)

---

## Credentials & Prompting

All inputs are prompted interactively with a short explanation of what is being asked
and why. Example format:

```
USG hostname or IP address
  (The address used to SSH into your UniFi Security Gateway.
   This is also your WireGuard endpoint if IP Passthrough is configured.)
> _
```

All inputs can alternatively be provided via config file (see Config File section).
Never store credentials in memory longer than needed. Never log credentials.

Inputs collected:
- USG hostname/IP
- USG SSH username
- USG SSH password
- Controller access method:
    "How is your UniFi Controller accessed?"
    [1] Via SSH jump through USG (e.g. CloudKey on same LAN as USG)
    [2] Direct SSH (e.g. self-hosted controller, UDM, off-site controller)
    Explanation shown for each option.
- If jump: CloudKey/Controller LAN IP
  - Attempt auto-discovery via USG ARP table first
  - If ambiguous or fails: prompt user
- If direct: Controller hostname/IP
- Controller SSH username (if direct)
- Controller SSH password (if direct)
- UniFi Controller web UI URL
  - Default: https://<controller-ip>/proxy/network
  - Fall back to https://<controller-ip>:8443 if newer URL fails
- Controller web UI username
- Controller web UI password

On first successful run, after completing the operation, prompt:
  "Would you like to save these settings for this network? (passwords included,
   file will be gitignored) [y/N]"
If yes: write to unifiguard.conf (or path specified by --config flag).

---

## Config File

Format: key=value pairs with inline comments. Not TOML or YAML.
Default location: ./unifiguard.conf (same dir as script/executable)
Override: --config /path/to/file

Committed to repo: unifiguard.conf.example (with all keys, explanatory comments, no real values)
Gitignored: unifiguard.conf

Example unifiguard.conf.example:
```
# unifiguard configuration file
# Copy to unifiguard.conf and fill in your values.
# This file supports per-network configuration.
# Passwords may be stored here — ensure this file is gitignored.

# ---------------------------------------------------------------
# Network: home (you can have multiple [network] sections)
# ---------------------------------------------------------------
[network.home]

# Hostname or IP address of your UniFi Security Gateway
# Used for SSH access and as the default WireGuard endpoint
usg_host = 

# SSH username for the USG (default is usually ubnt or your custom username)
usg_user = 

# SSH password for the USG
usg_pass = 

# How to access the UniFi Controller:
#   jump  = SSH through the USG as a jump host (use for on-site CloudKey)
#   direct = SSH directly to the controller (use for UDM, off-site, or VPS controller)
controller_access = jump

# LAN IP of the CloudKey or Controller (used when controller_access = jump)
controller_ip = 

# SSH username for the Controller (used when controller_access = direct)
controller_ssh_user = 

# SSH password for the Controller (used when controller_access = direct)
controller_ssh_pass = 

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
# Default: ./clients/ (relative to working directory or executable location)
output_dir = ./clients/

# Log verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)
log_level = INFO
```

---

## SSH Architecture

USG is the primary SSH endpoint (always direct connection).
CloudKey is accessed via USG as a jump host (when controller_access = jump).
Controller is accessed directly (when controller_access = direct).

```python
# Jump host pattern for CloudKey access
import paramiko

usg = paramiko.SSHClient()
usg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
usg.connect(usg_host, username=usg_user, password=usg_pass)

transport = usg.get_transport()
dest_addr = (cloudkey_ip, 22)
local_addr = ('127.0.0.1', 0)
channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)

ck = paramiko.SSHClient()
ck.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ck.connect(cloudkey_ip, username='ui', password=ck_pass, sock=channel)
```

All SSH operations must be wrapped in try/except with graceful failure and
descriptive error messages. Never leave the live network in a partially
modified state — if a step fails mid-operation, log the failure clearly and
instruct the user what was and was not completed.

---

## UniFi Controller API

Base URL (try in order):
1. `https://<controller-ip>/proxy/network`
2. `https://<controller-ip>:8443`

Authentication: POST to `/api/auth/login` with username/password.
Maintain session cookie across requests.
Disable SSL certificate verification (self-signed certs on CloudKey).
Re-authenticate automatically on 401 responses.

### Site ID Discovery
GET `/api/self/sites` — returns list of sites.
- If one site: use automatically, log site name and ID.
- If multiple sites: display rich table of site names and IDs, prompt user to select.

### Re-provisioning
1. Get USG MAC address from `show interfaces` output (eth0 MAC)
2. POST to `/api/s/<site_id>/cmd/devmgr`:
```json
{
  "cmd": "force-provision",
  "mac": "<usg-mac-address>"
}
```

---

## Provisioning & Polling

After triggering re-provisioning:
- Poll Controller API every 10 seconds for USG status
- Timeout: 10 minutes
- Show rich progress indicator with elapsed time
- On recovery: log success, verify WireGuard via `sudo wg show`
- On timeout: 
  - Warn user clearly
  - If controller is behind the USG (jump access mode):
    - Inform user that rollback cannot be attempted automatically since
      the controller is unreachable if the USG is down
    - Instruct user to manually check the USG and provision from UI
  - If controller is direct access:
    - Ask user: "Would you like to attempt rollback to the previous
      config.gateway.json backup? [y/N]"
    - If yes: restore backup on CloudKey, attempt re-provisioning again
    - Log all rollback actions clearly

---

## WireGuard Key Generation

Server keypair: generated on USG at /config/auth/wireguard/
Client keypairs: generated locally using cryptography library

```python
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
import base64

private_key = X25519PrivateKey.generate()
private_bytes = private_key.private_bytes(
    Encoding.Raw, PrivateFormat.Raw, NoEncryption()
)
public_bytes = private_key.public_key().public_bytes(
    Encoding.Raw, PublicFormat.Raw
)

private_b64 = base64.b64encode(private_bytes).decode()
public_b64 = base64.b64encode(public_bytes).decode()
```

---

## IP Assignment

WireGuard subnet: configurable, default 10.10.10.0/24
USG server address: first host in subnet (e.g. 10.10.10.1)
Client IPs: start at second host (e.g. 10.10.10.2), incrementing by 1

To determine next available IP:
1. Read /config/auth/wireguard/peers.json for all assigned IPs (including removed peers)
2. Find all IPs ever assigned (to support reuse of removed peer IPs)
3. Find lowest available IP not currently assigned to an active peer
4. Reuse IPs from removed peers before incrementing to new ones
5. Fail gracefully if subnet is exhausted

---

## Peers Metadata File

Location on USG: /config/auth/wireguard/peers.json

Schema:
```json
{
  "server": {
    "public_key": "<usg-public-key>",
    "address": "10.10.10.1/24",
    "port": 51820
  },
  "peers": [
    {
      "friendly_name": "vash-iphone",
      "tunnel_ip": "10.10.10.2",
      "public_key": "<client-public-key>",
      "assigned_at": "2026-01-15T21:00:00Z",
      "active": true
    }
  ]
}
```

If file is missing:
1. Warn user prominently
2. Reconstruct from `sudo wg show` output and key files in /config/auth/wireguard/
3. Assign friendly name "unknown-<tunnel-ip>" for any peers without metadata
4. Write reconstructed peers.json to USG
5. Inform user to review and update friendly names if desired

---

## config.gateway.json Management

Location on CloudKey: /data/unifi/data/sites/<site_id>/config.gateway.json

Operations:
- Read → parse → modify → validate → backup → write
- Never overwrite without backup
- Backup naming: config.gateway.json.<timestamp> (e.g. config.gateway.json.20260115_210000)
- Backups stored on CloudKey alongside the live file
- Backups also pulled to clients/logs/ locally
- If file doesn't exist: create directory structure and file from scratch
- Validate JSON after every modification before writing

Default config.gateway.json structure (matches manual setup reference):
```json
{
  "firewall": {
    "name": {
      "WAN_LOCAL": {
        "rule": {
          "20": {
            "action": "accept",
            "description": "WireGuard",
            "destination": { "port": "51820" },
            "protocol": "udp"
          }
        }
      }
    },
    "group": {
      "network-group": {
        "remote_user_vpn_network": {
          "description": "Remote User VPN subnets",
          "network": ["10.10.10.0/24"]
        }
      }
    }
  },
  "interfaces": {
    "wireguard": {
      "wg0": {
        "address": ["10.10.10.1/24"],
        "firewall": {
          "in": { "name": "LAN_IN" },
          "local": { "name": "LAN_LOCAL" },
          "out": { "name": "LAN_OUT" }
        },
        "listen-port": "51820",
        "mtu": "1500",
        "peer": [],
        "private-key": "/config/auth/wireguard/wg_private.key",
        "route-allowed-ips": "true"
      }
    }
  }
}
```

---

## Client Output Files

Default output directory: ./clients/ (relative to CWD or executable location)
Override: output_dir in config file or --output-dir flag

Per client:
- clients/<friendly-name>.conf — WireGuard config, importable into WireGuard app
- clients/<friendly-name>_qr.png — QR code for mobile import

Client config template:
```ini
[Interface]
PrivateKey = <client_private_key>
Address = <tunnel_ip>/32
DNS = <usg_lan_ip>          # auto-detected from USG eth1 interface

[Peer]
PublicKey = <usg_public_key>
Endpoint = <endpoint>:51820  # auto-detected from USG WAN IP, presented to user
                              # flagged if IP appears to be a private/LAN address
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

Endpoint detection logic:
1. Read USG WAN IP from `show interfaces` (eth0)
2. Present to user: "Detected WAN IP: 70.251.214.27 — use this as endpoint? [Y/n]"
3. If IP is in RFC1918 range (10.x, 172.16-31.x, 192.168.x): flag prominently:
   "Warning: detected IP appears to be a private address. This may mean the USG
    is behind NAT. The endpoint should be your public IP or a DDNS hostname."
4. Allow user to override with custom hostname/IP (e.g. vashp2029.mooo.com)

---

## Endpoint Auto-Detection

Auto-detect USG LAN IP (for DNS field in client config):
- Parse `show interfaces` output, read eth1 IP address

Auto-detect USG WAN IP (for Endpoint field in client config):
- Parse `show interfaces` output, read eth0 IP address
- Check if RFC1918 and warn if so
- Present to user for confirmation/override

---

## Logging

Log file location: clients/logs/unifiguard_<timestamp>.log
One log file per invocation.
Never log passwords or private keys.

Log levels (configurable via config file or --log-level flag):
- DEBUG: full SSH command/response traces, API request/response bodies
- INFO: step-by-step progress, all user-facing actions (default)
- WARNING: non-fatal issues (missing metadata file, ambiguous auto-detection)
- ERROR: failures, with full context for debugging

Log format:
```
2026-01-15 21:00:00 [INFO]  Connecting to USG at 70.251.214.27...
2026-01-15 21:00:01 [INFO]  Connected. Detected architecture: mips64
2026-01-15 21:00:01 [DEBUG] SSH response: Linux UniFi-Security-Gateway...
```

All log files retained locally. No automatic rotation (tool is run infrequently).

---

## GitHub Actions Build

File: .github/workflows/build.yml
Trigger: push to main, pull request to main
Also trigger on: tagged releases (vX.Y.Z)

Matrix:
- ubuntu-latest → unifiguard (Linux binary)
- macos-latest → unifiguard (macOS binary)
- windows-latest → unifiguard.exe (Windows binary)

Steps per platform:
1. Checkout repo
2. Install uv
3. uv sync
4. PyInstaller: `pyinstaller --onefile src/unifiguard/main.py -n unifiguard`
5. Upload artifact

On tagged release:
- Attach all three binaries to GitHub Release as downloadable assets
- Include SHA256 checksums for each binary in release notes

Fallback install instructions (in README):
```
pip install unifiguard
```

---

## Error Handling Philosophy

This tool operates on live network infrastructure. The guiding principle is:
**never leave the network in an unknown state.**

Rules:
- Every operation that modifies USG or CloudKey config must be logged before
  and after the modification
- If any step fails, log exactly what was completed and what was not
- Never silently swallow exceptions — always surface them to the user with
  context and suggested next steps
- On SSH disconnection mid-operation: attempt reconnect once, then fail
  gracefully with clear state summary
- On API failure: distinguish auth failures (401) from connectivity failures
  from unexpected errors — each gets a specific message
- On JSON parse/validation failure: show the problematic content, never write
  invalid JSON to CloudKey
- On any unexpected condition: log at ERROR level, print clear message,
  exit with non-zero status code

---

## Known Quirks (Reference from Manual Setup)

Document these in code comments where relevant:

- USG runs BusyBox — avoid GNU utility assumptions (nc -z doesn't work, etc.)
- CloudKey SSH is disabled by default — tool should detect connection refused
  and instruct user to enable SSH via UniFi OS dashboard at
  https://<cloudkey-ip>/manage
- UniFi Controller on CloudKey uses self-signed SSL — always disable verification
- USG configure mode may already be active on login — handle gracefully
  (configure command returns "command not found" if already in configure mode)
- WireGuard config survives reboot via config.gateway.json + install-edgeos-packages,
  but not firmware upgrades without the persistence script
- macOS WireGuard client requires AllowedIPs = 0.0.0.0/0, ::/0 (explicit IPv6)
  for full tunnel mode — note this in generated client config comments
- Multiple VPN clients on macOS (e.g. Citrix + WireGuard) can cause default
  route conflicts — out of scope but worth noting in README troubleshooting
- config.gateway.json sites directory may not exist on CloudKey until created —
  tool must create it if missing
- UniFi Controller site ID is a hex string found in the Controller UI URL,
  not necessarily "default"
- NAT masquerade rule needed for WireGuard traffic to reach WAN — rule 5000
  by default, verify no conflict with existing rules before adding
- WAN_LOCAL firewall rule required (not WAN_IN) for traffic destined for
  USG itself (SSH, WireGuard handshake)

---

## Reference Implementation

The canonical reference for this tool is the manual setup performed on:
- USG model: UniFi-Gateway-3 (mips64), firmware v4.4.57
- CloudKey: UCK-G2-PLUS, UniFi OS
- AT&T fiber with static IP, IP Passthrough mode enabled on AT&T gateway
- WireGuard subnet: 10.10.10.0/24
- WireGuard port: 51820
- NAT rule: 5000
- Firewall rule: WAN_LOCAL rule 20
- Key path: /config/auth/wireguard/
- config.gateway.json path: /data/unifi/data/sites/<site_id>/config.gateway.json
- Persistence: install-edgeos-packages script + /config/data/install-packages/wireguard.deb

All defaults in the tool should match this reference implementation exactly.
Deviations from defaults should require explicit user configuration.
```