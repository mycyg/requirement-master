"""Thin paramiko wrapper for our deploy/provision scripts."""
from __future__ import annotations

import io
import posixpath
import stat
import sys
from pathlib import Path
from typing import Iterable

import paramiko

from server_creds import SSH_HOST, SSH_PASS, SSH_USER, SUDO_PASS


def connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)
    return client


def run(client: paramiko.SSHClient, cmd: str, *, check: bool = True, timeout: int = 120, quiet: bool = False) -> tuple[int, str, str]:
    if not quiet:
        print(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if not quiet:
        if out.strip():
            print(out.rstrip())
        if err.strip():
            print(f"[stderr] {err.rstrip()}", file=sys.stderr)
    if check and rc != 0:
        raise RuntimeError(f"command failed (rc={rc}): {cmd}\nstderr: {err}")
    return rc, out, err


def sudo(client: paramiko.SSHClient, cmd: str, *, check: bool = True, timeout: int = 120) -> tuple[int, str, str]:
    """Run a sudo command, piping the password to stdin via sudo -S."""
    print(f"# sudo: {cmd}")
    full = f"sudo -S -p '' bash -c {_shquote(cmd)}"
    stdin, stdout, stderr = client.exec_command(full, timeout=timeout, get_pty=False)
    stdin.write(SUDO_PASS + "\n")
    stdin.flush()
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(f"[stderr] {err.rstrip()}", file=sys.stderr)
    if check and rc != 0:
        raise RuntimeError(f"sudo command failed (rc={rc}): {cmd}\nstderr: {err}")
    return rc, out, err


def _shquote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def put_text(client: paramiko.SSHClient, remote_path: str, content: str, *, mode: int = 0o644) -> None:
    sftp = client.open_sftp()
    try:
        _ensure_remote_dir(sftp, posixpath.dirname(remote_path))
        with sftp.file(remote_path, "w") as f:
            f.write(content)
        sftp.chmod(remote_path, mode)
    finally:
        sftp.close()


def put_file(client: paramiko.SSHClient, local_path: Path, remote_path: str, *, mode: int | None = None) -> None:
    sftp = client.open_sftp()
    try:
        _ensure_remote_dir(sftp, posixpath.dirname(remote_path))
        sftp.put(str(local_path), remote_path)
        if mode is not None:
            sftp.chmod(remote_path, mode)
    finally:
        sftp.close()


def put_tree(
    client: paramiko.SSHClient,
    local_root: Path,
    remote_root: str,
    *,
    exclude: Iterable[str] = (),
) -> int:
    """Upload all files under local_root to remote_root. Returns count uploaded."""
    exclude_set = set(exclude)
    count = 0
    sftp = client.open_sftp()
    try:
        _ensure_remote_dir(sftp, remote_root)
        for local in sorted(local_root.rglob("*")):
            if local.is_dir():
                continue
            rel = local.relative_to(local_root).as_posix()
            top = rel.split("/", 1)[0]
            if top in exclude_set or any(p in exclude_set for p in rel.split("/")):
                continue
            remote = posixpath.join(remote_root, rel)
            _ensure_remote_dir(sftp, posixpath.dirname(remote))
            sftp.put(str(local), remote)
            count += 1
            print(f"  → {rel}")
    finally:
        sftp.close()
    return count


def _ensure_remote_dir(sftp: paramiko.SFTPClient, path: str) -> None:
    if not path or path == "/":
        return
    try:
        st = sftp.stat(path)
        if stat.S_ISDIR(st.st_mode):
            return
        raise RuntimeError(f"remote path exists and is not a directory: {path}")
    except FileNotFoundError:
        _ensure_remote_dir(sftp, posixpath.dirname(path))
        sftp.mkdir(path)
