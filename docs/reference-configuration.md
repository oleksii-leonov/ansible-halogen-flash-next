# Reference configuration

This baseline was derived from inspection of a working Framework Desktop running
Halogen 0.18.5 on **2026-10-16**. Hostnames, accounts and network addresses are
configured separately for each machine. See the validation boundary below for
what has been tested.

## Hardware and operating system

| Component | Tested configuration |
| --- | --- |
| System | Framework Desktop (AMD Ryzen AI Max 300 Series) |
| CPU / iGPU | AMD Ryzen AI Max+ 395 / Radeon 8060S, 32 logical CPUs |
| GPU PCI identity | `1002:1586`, bound to `amdgpu` |
| BIOS | INSYDE 03.06 |
| OS | Ubuntu 26.04.1 LTS, Resolute |
| Kernel | `7.0.0-38-generic`, `CONFIG_HSA_AMD_SVM=y` |
| Memory | 128 GB installed, approximately 125 GiB visible to Linux |
| GPU dedicated VRAM / GTT | 512 MiB / 124 GiB |

The VRAM size was measured from sysfs; the BIOS menu itself was not inspected.
The playbooks require at least 120 GiB visible RAM and 190 GiB free on the model
filesystem before downloading. Disk layout and swap configuration are left to
the OS installation.

## Host settings required by this deployment

The playbook adds these options through `/etc/default/grub.d/99-halogen.cfg`,
preserving existing boot arguments:

```text
amd_iommu=off amdgpu.gttsize=126976 ttm.pages_limit=32505856
```

These settings expose 124 GiB of GTT. `amd_iommu=off` disables DMA isolation;
use this baseline for a dedicated inference host that does not need IOMMU
isolation or GPU passthrough. GPU clocks and NPU configuration are not managed.

Memory-lock configuration, with `<service-user>` and `<uid>` derived from the
SSH account rather than fixed values:

```text
# /etc/security/limits.d/halogen.conf
<service-user> hard memlock unlimited
<service-user> soft memlock unlimited

# /etc/systemd/system/user@<uid>.service.d/memlock.conf
[Service]
LimitMEMLOCK=infinity
```

Both the login and systemd user-manager limits must be unlimited. The working
model accounted for approximately 63 GiB of locked memory. The SSH user is added
to `video` and `render` for access to `/dev/kfd` and `/dev/dri`. Podman preserves
these supplementary groups through `crun` and `GroupAdd=keep-groups`.

The account needs subordinate UID/GID ranges in `/etc/subuid` and `/etc/subgid`
for rootless containers. A normal Ubuntu installer-created account already has
them; deployment checks the runtime mappings with `podman info`. Preparation
enables lingering so the user service starts at boot without an interactive login.

The following are Ubuntu defaults, not extra tuning applied by this project:
`vm.max_map_count=1048576`, `vm.swappiness=60`, `vm.compaction_proactiveness=20`.
Neither AppArmor nor user-namespace restrictions are disabled by the playbooks.

## Software

| Package | Tested version |
| --- | --- |
| Podman | 5.7.0 (`5.7.0+ds2-3build1`) |
| crun | 1.21 (`1.21-1ubuntu3`) |
| uidmap | `1:4.17.4-2ubuntu3` |
| passt / pasta | `0.0~git20260120.386b5f5-1` |
| dbus-user-session | `1.16.2-2ubuntu4` |
| linux-firmware | `20260319.git217ca6e4.1ubuntu` |
| Tailscale | 1.104.1, official stable Ubuntu repository |
| Python | 3.14.3 |
| OpenSSH server | `1:10.2p1-2ubuntu3.8` |
| Avahi | `0.8-18ubuntu1.1` |

Podman is rootless with cgroup v2, the systemd cgroup manager, crun, netavark,
pasta networking and native overlay storage under `~/.local/share/containers/storage`.
GPU userspace libraries and Hugging Face tooling are inside the Halogen image;
a separate host ROCm installation is not needed by this deployment. Ubuntu and
Tailscale package versions are recorded here as a tested baseline, not pinned.

## Network and identity

- LAN IPv4: set `halogen_lan_ip` in the private inventory and reserve it in DHCP.
- Tailscale IPv4: discovered from each host, which must be tagged `tag:server`.
- API published only on those two IPv4 addresses, TCP 8731.
- Engine listens inside the container at `127.0.0.1:8730`.
- API authentication is not enabled by default; existing firewall policy is unchanged.

Each host needs its own LAN address and Tailscale enrollment. The example inventory
uses documentation-only addresses. Tailnet policy and upstream router/firewall
rules are managed separately. Tailscale rules do not restrict access through the LAN.

## Model and service

Source: `~/.config/containers/systemd/halogen.container`, owned by the SSH user.
Runtime: user `halogen.service`, container `systemd-halogen`, one image serving
both engine and API. Version 0.18.5 was healthy with matching API and engine builds.

Image digest: `sha256:94c9d76b6b938459e00805c61978808957703745fe573ca2d7f01e9157446b3d`.
The playbook pins this verified digest rather than a mutable image tag.

Weights: `peonist-ai/halogen-qwen3.8-flash-next`, revision
`6e1aa1acda75bd8a3bb9043b1545f83187cb6ded`, confirmed against the public manifest.
The nine exact filenames and sizes are in `group_vars/all.yml`. The three `.hgn`
files are v2 weights (66,687,678,432 bytes), lookup table (51,200,246,144 bytes),
and vision tower (897,916,416 bytes). Six tokenizer files accompany them.
Deployment verifies file sizes and records the revision; it does not recompute
full weight checksums.

The generated unit uses `/dev/kfd`, `/dev/dri`, host IPC, unlimited
memlock, read-only `~/halogen-models:/models`, and writable `~/halogen-cache:/cache`.
The explicit runtime environment is:

```ini
HALOGEN_KV_POOL_POSITIONS=786432
HALOGEN_VISION_TOWER=1
HALOGEN_WEIGHTS_LOCK=1
HALOGEN_MAX_TOKENS_DEFAULT=32768
HALOGEN_MAX_THINKING_TOKENS=16384
HALOGEN_TEMPERATURE=1.0
HALOGEN_TOP_P=0.95
HALOGEN_TOP_K=20
HALOGEN_CACHE_DIR=/cache
HALOGEN_CACHE_PRUNE_OLD=1
```

Image defaults supply 262,144 context per request, four generating slots,
`xhigh` reasoning effort, prompt-cache mode 2 and a 64 GiB disk-cache budget.
The pool accommodates three full contexts or more shorter conversations.
No NPU models, request records or runtime model downloads are enabled.

The unit restarts on failure after 30 seconds, allows 900 seconds for startup,
and gives Podman 60 seconds to stop within a 90-second systemd stop timeout.
`WantedBy=default.target` and lingering start it at boot. Memory locking is scoped
to the service user's manager. Podman generates a network wait dependency, and
the 30-second failure retry handles addresses appearing late.

## Validation boundary

Validation completed on 2026-10-16:

- Three offline tests passed: per-host bindings and image pinning, preservation of
  existing boot arguments without duplicates, and model manifest path constraints.
- All three playbooks passed Ansible syntax checks.
- `prepare.yml --check --diff` and `deploy.yml --check --diff` passed against the
  working host. Reported changes were previews; no configuration was applied.
- Podman 5.7's Quadlet generator compiled the rendered template in a temporary
  directory, including the GPU groups, published addresses and 60-second stop grace.
- A disposable helper container resolved all nine files at the pinned revision
  with `hf download --dry-run`, reporting 118.8 GB, without downloading weights.
- `verify.yml` passed against the live 0.18.5 server: health, matching builds,
  capacity, streaming, strict tool arguments, concurrent requests and vision.

A full installation on a blank machine, a second real provisioning run
to measure idempotence, and performance/load benchmarks remain untested.
