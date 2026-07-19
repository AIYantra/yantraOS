from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class DeploymentSecurityTests(unittest.TestCase):
    def test_iso_has_no_remote_or_password_login(self) -> None:
        forge = read("archlive/forge_sovereign_iso.sh")
        ssh = read("archlive/airootfs/etc/ssh/sshd_config.d/10-archiso.conf")
        packages = {
            line.strip()
            for line in read("archlive/packages.x86_64").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertNotRegex(forge, r"(?:root|yantra_user)::")
        self.assertIn("root:!:", forge)
        self.assertNotIn("yantra_user", forge)
        self.assertIn("-name 'autologin.conf' -delete", forge)
        self.assertNotIn('"sshd.service"', forge)
        self.assertNotIn("openssh", packages)
        self.assertFalse(
            (ROOT / "archlive/airootfs/etc/systemd/system/multi-user.target.wants/sshd.service").exists()
        )
        self.assertNotRegex(ssh, r"(?m)^\s*(?:PermitRootLogin|PasswordAuthentication|PermitEmptyPasswords)\s+yes\s*$")
        for directive in ("PermitRootLogin no", "PasswordAuthentication no", "PermitEmptyPasswords no"):
            self.assertIn(directive, ssh)

    def test_credentials_are_never_staged(self) -> None:
        self.assertFalse((ROOT / ".env").exists())
        for runtime_path in (ROOT / ".compliance_key.pem", ROOT / "consent_ledger.db"):
            if runtime_path.exists():
                self.assertEqual(0o600, runtime_path.stat().st_mode & 0o777, str(runtime_path))

        forge_files = (
            "archlive/forge_sovereign_iso.sh",
            "cloud/forge_azure_vhd.sh",
            ".github/workflows/yantra_cloud_forge.yml",
        )
        for path in forge_files:
            content = read(path)
            self.assertNotIn("stage_secrets", content, path)
            self.assertNotIn("host_secrets.env", content, path)

        workflow = read(".github/workflows/yantra_cloud_forge.yml")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", workflow)
        self.assertNotIn("AZURE_OPENAI_API_KEY", workflow)
        self.assertIn(
            "EnvironmentFile=-/etc/yantra/daemon.env",
            read("deploy/systemd/yantra.service"),
        )
        self.assertIn(
            "EnvironmentFile=-/etc/yantra/telegram.env",
            read("deploy/systemd/yantra-telegram.service"),
        )
        self.assertIn("User=yantra_telegram", read("deploy/systemd/yantra-telegram.service"))
        self.assertNotIn(
            "EnvironmentFile=",
            read("deploy/systemd/yantra-host-executor.service"),
        )

        example = read(".env.example")
        example_values = [
            line.split("=", 1)[1]
            for line in example.splitlines()
            if line and not line.startswith("#")
        ]
        self.assertTrue(example_values)
        self.assertTrue(
            all(value.startswith("<") and value.endswith(">") for value in example_values)
        )
        self.assertIn("YANTRA_CONTROL_TOKEN=<required-random-control-token>", example)
        self.assertIn("!.env.example", read(".gitignore"))
        self.assertIn("len(token)>=32", read("deploy/systemd/yantra.service"))
        self.assertIn("YANTRA_CONTROL_TOKEN is required", read("Dockerfile.daemon"))

    def test_daemon_has_no_raw_docker_access(self) -> None:
        compose = read("docker-compose.yml")
        sysusers = read("deploy/sysusers.d/yantra.conf")

        self.assertNotIn("docker.sock", compose)
        self.assertNotIn("docker.sock", sysusers)
        self.assertNotRegex(sysusers, r"(?m)^m\s+yantra_daemon\s+docker\s*$")
        self.assertRegex(sysusers, r"(?m)^g\s+yantra\s+-$")
        self.assertRegex(sysusers, r"(?m)^u\s+yantra_daemon\s+-\s+")
        self.assertRegex(sysusers, r"(?m)^u\s+yantra_telegram\s+-\s+")
        self.assertNotIn("yantra_user", sysusers)
        self.assertIn("source: /run/yantra-sandbox/broker.sock", compose)
        self.assertNotRegex(compose, r"(?m)^\s*source:\s*/run/yantra-sandbox/?\s*$")
        self.assertIn('user: "${YANTRA_UID:?', compose)
        self.assertIn('${YANTRA_GID:?', compose)
        self.assertIn("read_only: true", compose)
        self.assertRegex(compose, r"cap_drop:\s*\n\s*- ALL")
        self.assertIn("no-new-privileges:true", compose)
        self.assertNotRegex(compose, r"(?m)^\s*ports:\s*$")
        self.assertNotIn("executor.sock", compose)
        prepare = read("scripts/prepare_compose_runtime.sh")
        self.assertIn("install -d -m0700", prepare)
        self.assertIn("Missing broker socket", prepare)

    def test_runtime_directories_and_broker_ordering_are_hardened(self) -> None:
        daemon = read("deploy/systemd/yantra.service")
        tmpfiles = read("deploy/tmpfiles.d/yantra.conf")

        self.assertIn("Requires=yantra-sandbox-broker.service", daemon)
        self.assertRegex(daemon, r"(?m)^After=.*\byantra-sandbox-broker\.service\b")
        self.assertIn("YANTRA_AUDIT_LOG_PATH=/var/log/yantra/audit.jsonl", daemon)
        self.assertIn(
            "YANTRA_CONFIRMATION_COUNTER_PATH=/var/lib/yantra/confirmation_counter.json",
            daemon,
        )
        self.assertRegex(tmpfiles, r"(?m)^d\s+/run/yantra\s+0750\s+root\s+yantra\b")
        self.assertRegex(tmpfiles, r"(?m)^d\s+/run/yantra-sandbox\s+0750\s+root\s+yantra\b")
        self.assertNotIn("RuntimeDirectory=yantra\n", daemon)

        for image_builder in ("archlive/forge_sovereign_iso.sh", "cloud/forge_azure_vhd.sh"):
            self.assertIn('"yantra-sandbox-broker.service"', read(image_builder))
            self.assertIn('"yantra-provision-secrets.service"', read(image_builder))
            self.assertNotIn('"yantra-host-executor.service"', read(image_builder))
            self.assertIn("docker save", read(image_builder))

        broker = read("deploy/systemd/yantra-sandbox-broker.service")
        self.assertIn("docker load -i /opt/yantra/images/yantra-sandbox-3.20.3.tar", broker)
        self.assertIn("docker image inspect yantra-sandbox:3.20.3", broker)
        provisioner = read("deploy/systemd/yantra-provision-secrets.service")
        self.assertIn("Before=yantra.service yantra-telegram.service", provisioner)
        self.assertIn("ReadWritePaths=/etc/yantra", provisioner)
        executor = read("deploy/systemd/yantra-host-executor.service")
        self.assertIn("ProtectSystem=strict", executor)
        self.assertIn("ReadWritePaths=/run/yantra /.snapshots", executor)
        snapshot = read("core/cli_snapshot.py")
        self.assertIn('SNAPSHOT_SUBVOL: str = "/.snapshots"', snapshot)
        self.assertIn('ROOT_SUBVOL: str = "/"', snapshot)

        for path in (ROOT / "deploy/systemd").glob("*.service"):
            section = ""
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("["):
                    section = line
                if line.startswith("StartLimit"):
                    self.assertEqual("[Unit]", section, f"{path}: {line}")
            self.assertIn("UMask=0077", path.read_text(encoding="utf-8"), str(path))

    def test_supply_chain_and_cloud_network_policy(self) -> None:
        workflow = read(".github/workflows/yantra_cloud_forge.yml")
        dockerfile = read("Dockerfile.daemon")
        azure = read("cloud/azure_vm_deploy.azcli")

        self.assertIn("SigLevel = Required DatabaseOptional", workflow)
        self.assertNotIn("SigLevel = Never", workflow)
        action_refs = re.findall(r"(?m)^\s*uses:\s*\S+@([^\s#]+)", workflow)
        self.assertTrue(action_refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs))
        self.assertLess(workflow.index("Forge Azure VHD"), workflow.index("Authenticate to Azure"))
        self.assertRegex(
            dockerfile,
            r"FROM python:3\.12\.10-slim-bookworm@sha256:[0-9a-f]{64}",
        )
        self.assertNotIn(":latest", dockerfile)
        sandbox_dockerfile = read("core/sandbox/Dockerfile")
        self.assertRegex(
            sandbox_dockerfile,
            r"FROM alpine:3\.20\.3@sha256:[0-9a-f]{64}",
        )
        self.assertIn("bash=5.2.26-r0", sandbox_dockerfile)
        self.assertIn("coreutils=9.5-r2", sandbox_dockerfile)
        self.assertNotIn(":latest", sandbox_dockerfile)
        self.assertIn('SANDBOX_IMAGE: Final[str] = "yantra-sandbox:3.20.3"', read("core/sandbox.py"))
        self.assertNotIn("--access Allow", azure)
        self.assertNotIn("az network public-ip create", azure)
        self.assertNotIn("50000", azure)
        self.assertIn("Legacy public API ingress rule absent", azure)
        self.assertNotIn("storage account keys list", azure)
        self.assertNotIn("--account-key", azure)
        self.assertIn("--auth-mode login", azure)
        self.assertIn("Storage Blob Data Contributor", azure)
        self.assertNotIn("az vm delete", azure)
        self.assertNotIn("az disk delete", azure)
        self.assertIn("DEPLOYMENT_ID", azure)
        self.assertIn("az vm wait --created", azure)
        self.assertIn("--assign-identity", azure)
        self.assertIn("Key Vault Secrets User", azure)
        self.assertIn("YANTRA_HEALTHY", azure)
        self.assertNotIn("az vm run-command", azure)
        self.assertIn("environment: production", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        for workflow_path in (ROOT / ".github/workflows").glob("*.yml"):
            refs = re.findall(
                r"(?m)^\s*uses:\s*\S+@([^\s#]+)",
                workflow_path.read_text(encoding="utf-8"),
            )
            self.assertTrue(
                all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs),
                str(workflow_path),
            )

    def test_image_source_copies_fail_closed_and_preserve_root_ownership(self) -> None:
        for path in ("archlive/forge_sovereign_iso.sh", "cloud/forge_azure_vhd.sh"):
            content = read(path)
            self.assertIn("rsync -a --chown=root:root --delete", content, path)
            self.assertIn("Required source directory missing", content, path)

    def test_docker_context_is_allowlisted(self) -> None:
        dockerignore = read(".dockerignore")
        self.assertTrue(dockerignore.startswith("**\n"))
        for required in ("!core/**", "!scripts/**", "**/.env", "**/*.pem", "**/*.db", "**/.git/**", "**/venv/**", "**/*.iso"):
            self.assertIn(required, dockerignore)

    def test_runtime_dependencies_are_directly_pinned(self) -> None:
        requirements = [
            line.strip()
            for line in read("requirements.txt").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        for requirement in requirements:
            if " @ git+" in requirement:
                self.assertRegex(requirement, r"@[0-9a-f]{40}$")
            else:
                self.assertIn("==", requirement)
        lock = read("requirements.lock")
        self.assertIn("--hash=sha256:", lock)
        self.assertNotIn("git+", lock)
        self.assertIn("!requirements.lock", read(".dockerignore"))
        self.assertIn("--require-hashes -r requirements.lock", read("Dockerfile.daemon"))
        for image_builder in ("archlive/forge_sovereign_iso.sh", "cloud/forge_azure_vhd.sh"):
            self.assertIn("--require-hashes -r /opt/yantra/requirements.lock", read(image_builder))
        cloud_forge = read("cloud/forge_azure_vhd.sh")
        self.assertNotIn("NetworkManager.service", cloud_forge)
        self.assertNotIn("systemd-sysusers >/dev/null 2>&1 || true", cloud_forge)
        self.assertNotIn("passwd -l root >/dev/null 2>&1 || true", cloud_forge)
        self.assertIn("95-yantra-sync-esp.hook", cloud_forge)


if __name__ == "__main__":
    unittest.main()
