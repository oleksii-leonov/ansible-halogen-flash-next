# Ansible Halogen

Deploy Halogen on a **Framework Desktop with Ryzen AI Max+ 395, 128 GB RAM
and native Ubuntu 26.04**. The [reference configuration](docs/reference-configuration.md)
documents the tested hardware, kernel, GPU memory settings, packages and service.

This project has two provisioning playbooks, a verification playbook, one Quadlet,
and no external Ansible collections. It pins Halogen **0.18.5 by image digest**,
and pins the Flash v2 model and tokenizer by Hugging Face commit. Ubuntu and Tailscale packages
come from their supported repositories; their versions are recorded, not frozen.

## Before running

1. Install Ubuntu 26.04 on the target machine. Create a normal non-root user with
   sudo access, install OpenSSH, and add your SSH public key. Use a unique hostname.
   The SSH user owns the rootless container; choose its name in your inventory.
2. In BIOS set the UMA frame buffer to the smallest explicit value. The tested
   configuration exposes **512 MiB VRAM** and about **125 GiB system RAM**. The playbook
   refuses machines exposing less than 120 GiB RAM. Firmware flashing and OS/disk
   installation remain manual.
3. Reserve the new machine's LAN address in DHCP. Allow **190 GiB free** on its
   home filesystem before the download: approximately 111 GiB of model files,
   a 64 GiB prompt cache and runtime headroom. Prefer a dedicated NVMe-backed host.
4. Confirm SSH access and sudo work. Accept its SSH host key normally; host-key
   verification is kept enabled. Define `tag:server` in your Tailscale policy.

Preparation configures `amd_iommu=off`, `amdgpu.gttsize=126976` and
`ttm.pages_limit=32505856`. **It can reboot the target.**
The IOMMU setting disables DMA isolation; this baseline is for a dedicated
inference server, not a machine needing IOMMU isolation or GPU passthrough.

## Set up the controller

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) on the
controller. The project uses Python 3.12–3.14; uv can download a compatible
interpreter if needed.

```bash
cd ~/code/ansible-halogen
uv sync --locked
cp inventory.example.yml inventory.yml
```

uv manages `.venv` and installs the exact dependencies recorded in `uv.lock`.
Commit both `pyproject.toml` and `uv.lock` when changing dependencies. The target
servers use Ubuntu's system Python and do not need uv.

Edit `inventory.yml`: replace `192.0.2.10` with the target's LAN IP and `inference`
with its existing SSH user. Add more hosts to the `halogen` group as needed, each
with a unique alias and address. `inventory.yml` is ignored by Git. SSH keys stay
in your SSH agent/config, and sudo passwords are supplied with `--ask-become-pass`
when needed.

## Provision a server

Use the target's inventory alias after `--limit`; the example uses `halogen-1`.

```bash
uv run --locked ansible-playbook prepare.yml --limit halogen-1 --ask-become-pass
```

This installs Podman and Tailscale, grants GPU access, configures memory locking
for both SSH sessions and the systemd user manager, enables lingering, and applies
the boot settings. It reboots when needed to make the new limits and groups active.
No firewall is disabled or opened by the playbook.

Enroll each machine once, using its own identity. Replace the example SSH user
and address with the values from your inventory:

```bash
ssh inference@192.0.2.10
sudo tailscale login --advertise-tags=tag:server
exit
```

Complete the displayed sign-in link as a permitted tag owner. Each host must have
its own Tailscale identity, SSH host keys and machine ID. Then deploy and test:

```bash
uv run --locked ansible-playbook deploy.yml --limit halogen-1
uv run --locked ansible-playbook verify.yml --limit halogen-1
```

Deployment pulls the pinned image as the SSH user, downloads only the nine
required model/tokenizer files using the image's `hf` CLI, then mounts them
read-only in the server. Only the download helper sets `HF_HUB_OFFLINE=0`;
the server retains the image's offline defaults. The first download can take
hours; interrupted downloads
resume on the next run. A revision marker is written only after every expected
file size matches. Subsequent runs skip a complete pinned download and avoid
restarting an unchanged running service.

The API binds to the host's discovered Tailscale IPv4 and the inventory's LAN IPv4
on port **8731**. The internal engine port **8730** is not published. Keep the LAN
address stable; after changing either address, rerun `deploy.yml`.

**API authentication is not enabled by default.** The playbooks leave firewall
policy alone: any client that can reach port 8731 can use it. Tailscale access
rules do not cover LAN traffic.
On a host with a firewall, allow intended clients explicitly. Restrict the LAN or
add Halogen API authentication before putting this on an untrusted network.

## Operation

Run on the target as its Halogen user:

```bash
systemctl --user status halogen.service
journalctl --user -u halogen.service -f
curl http://YOUR_LAN_IP:8731/health
```

Models live in `~/halogen-models`, prompt cache in `~/halogen-cache`, and the
managed source in `~/.config/containers/systemd/halogen.container`. The generated
service is under `/run/user/UID/systemd/generator/`; do not edit or enable that
generated file. Quadlet's `WantedBy=default.target` plus lingering starts it at boot.

For upgrades, change `halogen_version` and `halogen_image` together in
`group_vars/all.yml`, stop client traffic, then rerun deployment and verification.
Deployment refuses a health report showing active/queued requests. Model revision
changes stop the service before writing weights. Keep clients stopped during an
upgrade; the initial idle check does not prevent new requests from arriving.
Old build caches are pruned (`HALOGEN_CACHE_PRUNE_OLD=1`); first requests after an
upgrade may have to process their full prompts again. No rollback automation.

## Check changes

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ansible-playbook -i inventory.example.yml prepare.yml --syntax-check
uv run --locked ansible-playbook -i inventory.example.yml deploy.yml --syntax-check
uv run --locked ansible-playbook -i inventory.example.yml verify.yml --syntax-check
uv run --locked ansible-playbook deploy.yml --limit halogen-1 --check --diff
```

The deployment check/diff is for a **prepared, enrolled host**. It queries runtime
state and previews the Quadlet but skips pulls, downloads, restarts and inference.
It cannot prove a first installation works. `verify.yml` checks health, version,
capacity, streaming, strict tool arguments, two concurrent requests and vision
with synthetic data. It executes no returned tools and is not a load benchmark.

## References

- [Halogen deployment and checkpoint upgrade instructions](https://github.com/peonist-ai/halogen-flash-server/blob/main/docs/getting-started.md)
- [Halogen memory locking and host requirements](https://github.com/peonist-ai/halogen-flash-server/blob/main/docs/host-setup.md)
- [Podman Quadlet lifecycle and rootless units](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
- [Official Tailscale Ubuntu packages](https://pkgs.tailscale.com/stable/#ubuntu-resolute)
