"""Copy to server_creds.py (gitignored) and fill in.

Used by scripts/ssh_lib.py for paramiko-based deploy/provision/E2E scripts.
"""
SSH_HOST = "your.server.ip.or.hostname"
SSH_USER = "your-ssh-username"
SSH_PASS = "your-ssh-password"

SUDO_PASS = SSH_PASS  # if the SSH user has sudo and same password; otherwise change
