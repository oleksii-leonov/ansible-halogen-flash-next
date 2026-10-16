"""Offline checks for bindings, image pinning and non-destructive boot settings."""

from pathlib import Path
import subprocess
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_quadlet_uses_only_the_target_hosts_addresses(self):
        variables = yaml.safe_load((ROOT / "group_vars/all.yml").read_text())
        variables["halogen_bind_addresses"] = ["100.64.0.42", "192.0.2.42"]
        unit = Environment(undefined=StrictUndefined, trim_blocks=True).from_string(
            (ROOT / "templates/halogen.container.j2").read_text()
        ).render(variables)
        ports = [line for line in unit.splitlines() if line.startswith("PublishPort=")]
        self.assertEqual(ports, ["PublishPort=100.64.0.42:8731:8731", "PublishPort=192.0.2.42:8731:8731"])
        self.assertRegex(unit, r"Image=ghcr.io/peonist-ai/halogen-flash-server@sha256:[0-9a-f]{64}")
        self.assertIn("Volume=%h/halogen-models:/models:ro", unit)
        self.assertNotIn("HALOGEN_DOWNLOAD", unit)
        self.assertNotIn("8730:", unit)
        self.assertIn("StopTimeout=60\n", unit)
        self.assertIn("TimeoutStopSec=90\n", unit)
        self.assertIn("WantedBy=default.target", unit)

    def test_boot_settings_preserve_existing_options_and_do_not_duplicate(self):
        script = (ROOT / "files/99-halogen.cfg").read_text()
        for initial in ["", "quiet splash mitigations=auto", "quiet amd_iommu=off"]:
            with self.subTest(initial=initial):
                result = subprocess.run(
                    ["/bin/sh", "-c", 'GRUB_CMDLINE_LINUX_DEFAULT="$1"\n' + script + script
                     + '\nprintf "%s" "$GRUB_CMDLINE_LINUX_DEFAULT"', "test", initial],
                    capture_output=True, text=True, check=True,
                )
                args = result.stdout.split()
                self.assertTrue(set(initial.split()).issubset(args))
                for arg in ["amd_iommu=off", "amdgpu.gttsize=126976", "ttm.pages_limit=32505856"]:
                    self.assertEqual(args.count(arg), 1)

    def test_model_download_is_revision_pinned_and_stays_inside_model_directory(self):
        variables = yaml.safe_load((ROOT / "group_vars/all.yml").read_text())
        self.assertRegex(variables["halogen_model_revision"], r"^[0-9a-f]{40}$")
        for model in variables["halogen_model_files"]:
            self.assertFalse(Path(model["name"]).is_absolute())
            self.assertNotIn("..", Path(model["name"]).parts)
            self.assertGreater(model["size"], 0)


if __name__ == "__main__":
    unittest.main()
