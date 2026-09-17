"""Agent tool layer.

All agent filesystem/shell access goes through :class:`ToolContext`, which
enforces a workspace path jail, prohibited prefixes, per-task tool allowlists,
command allowlists, size limits, and writes a structured trajectory. Verifiers
inspect the same trajectory as evidence; an agent's self-report is never used
as proof that a boundary was respected.
"""
import hashlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

from .security import redact

DEFAULT_ALLOWED_TOOLS = ("list_files", "read_file", "write_file", "run_command")
DEFAULT_ALLOWED_COMMANDS = ("python3 --version",)


class ToolError(Exception):
    pass


class PermissionViolation(ToolError):
    pass


class ToolContext:
    def __init__(
        self,
        workspace: Path,
        task_id: str,
        prohibited: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        manifest: dict | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.task_id = task_id
        self.prohibited = [p.rstrip("/") for p in (prohibited or []) if p]
        self.allowed_tools = set(allowed_tools or DEFAULT_ALLOWED_TOOLS)
        self.allowed_commands = tuple(allowed_commands or DEFAULT_ALLOWED_COMMANDS)
        self.max_file_bytes = max_file_bytes
        self.manifest = manifest or {}
        self.trajectory: list[dict] = []
        self.permission_attempts: list[str] = []
        self._step = 0

    # ------------------------------------------------------------------ internals
    def _check_tool(self, tool: str) -> None:
        if tool not in self.allowed_tools:
            self.permission_attempts.append(f"tool:{tool}")
            raise PermissionViolation(f"Tool '{tool}' is not permitted for this task")

    def _log(self, tool, args, result, ok=True, error="", started=None):
        self._step += 1
        entry = {
            "step": self._step,
            "ts": time.time(),
            "type": "tool_call",
            "tool": tool,
            "args": redact(json.dumps(args, default=str))[:800],
            "ok": ok,
            "result_preview": redact(str(result))[:400],
            "error": redact(error)[:400],
            "duration_ms": round((time.time() - started) * 1000, 2) if started else None,
        }
        self.trajectory.append(entry)
        return entry

    def _resolve(self, rel: str) -> Path:
        rel = str(rel or ".")
        p = (self.workspace / rel).resolve()
        if p != self.workspace and self.workspace not in p.parents:
            self.permission_attempts.append(rel)
            raise PermissionViolation(f"Path escapes workspace: {rel}")
        rel_posix = p.relative_to(self.workspace).as_posix()
        for prefix in self.prohibited:
            if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
                self.permission_attempts.append(rel)
                raise PermissionViolation(f"Prohibited path: {rel}")
        return p

    # ------------------------------------------------------------------ tools
    def note(self, tool, args, result, ok=True):
        return self._log(tool, args if isinstance(args, dict) else {"info": str(args)}, result, ok=ok)

    def run_command(self, command: str) -> str:
        """Execute only exact commands listed in the task manifest. Shell-free."""
        started = time.time()
        try:
            self._check_tool("run_command")
            parts = shlex.split(command)
            if not parts:
                raise PermissionViolation("Empty command")
            normalized = " ".join(parts)
            if normalized not in self.allowed_commands:
                self.permission_attempts.append(f"run_command:{command}")
                raise PermissionViolation(f"Command not allowlisted: {command}")
            # Resolve path arguments for ls to keep them inside the jail.
            if parts[0] == "ls" and len(parts) == 2:
                argv = ["ls", str(self._resolve(parts[1]))]
            else:
                argv = parts
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.workspace), "LANG": "C.UTF-8"}
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=10, cwd=self.workspace,
                shell=False, env=env, check=False,
            )
            out = ((proc.stdout or "") + (proc.stderr or "")).strip()[:10_000]
            self._log("run_command", {"command": command, "returncode": proc.returncode}, out, started=started)
            if proc.returncode != 0:
                raise ToolError(f"Command exited {proc.returncode}: {out[:300]}")
            return out
        except PermissionViolation:
            self._log("run_command", {"command": command}, "", ok=False, error="not allowlisted", started=started)
            raise
        except Exception as e:
            self._log("run_command", {"command": command}, "", ok=False, error=str(e), started=started)
            raise

    def list_files(self, rel="."):
        started = time.time()
        try:
            self._check_tool("list_files")
            p = self._resolve(rel)
            files = sorted(
                str(x.relative_to(self.workspace)) for x in p.rglob("*") if x.is_file() and not x.is_symlink()
            ) if p.exists() else []
            self._log("list_files", {"path": rel}, files, started=started)
            return files
        except Exception as e:
            self._log("list_files", {"path": rel}, "", ok=False, error=str(e), started=started)
            raise

    def read_file(self, rel: str) -> str:
        started = time.time()
        try:
            self._check_tool("read_file")
            p = self._resolve(rel)
            if p.stat().st_size > self.max_file_bytes:
                raise ToolError(f"File too large to read ({p.stat().st_size} bytes > {self.max_file_bytes})")
            text = p.read_text(encoding="utf-8", errors="replace")
            self._log("read_file", {"path": rel}, text[:200], started=started)
            return text
        except Exception as e:
            self._log("read_file", {"path": rel}, "", ok=False, error=str(e), started=started)
            raise

    def write_file(self, rel: str, content: str) -> str:
        started = time.time()
        try:
            self._check_tool("write_file")
            data = str(content).encode("utf-8")
            if len(data) > self.max_file_bytes:
                raise ToolError(f"Write too large ({len(data)} bytes > {self.max_file_bytes})")
            p = self._resolve(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            self._log("write_file", {"path": rel, "bytes": len(data)}, "ok", started=started)
            return f"wrote {rel} ({len(data)} bytes)"
        except Exception as e:
            self._log("write_file", {"path": rel}, "", ok=False, error=str(e), started=started)
            raise

    def write_bytes(self, rel: str, data: bytes) -> str:
        started = time.time()
        try:
            self._check_tool("write_file")
            if len(data) > self.max_file_bytes:
                raise ToolError(f"Write too large ({len(data)} bytes > {self.max_file_bytes})")
            p = self._resolve(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            self._log("write_bytes", {"path": rel, "bytes": len(data)}, "ok", started=started)
            return f"wrote {rel}"
        except Exception as e:
            self._log("write_bytes", {"path": rel}, "", ok=False, error=str(e), started=started)
            raise

    def sha256(self, rel: str) -> str:
        self._check_tool("read_file")
        p = self._resolve(rel)
        return hashlib.sha256(p.read_bytes()).hexdigest()
