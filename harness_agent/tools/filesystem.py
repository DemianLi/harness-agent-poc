"""Filesystem tools for the agent: ls, read_file, glob, grep, write_file, edit_file.

Trust boundary (read before reusing outside this project)
-----------------------------------------------------------
These tools accept absolute paths and operate with the OS-level permissions
of the running process. There is NO path allowlist, sandbox, or per-user
isolation — any path the process can reach, the model can read or write.
This is an accepted trade-off for a single-user local CLI where the human
operating the tool and the human running the agent are the same person.
It is NOT safe to expose these tools to multiple users or untrusted input
without adding a path-allowlist / sandboxing middleware first.

Error contract
--------------
Every tool returns a plain string. On success, a short human-readable
confirmation or the requested content. On failure, the string starts with
`"Error: {code}: "` where `code` is one of the constants in `ErrorCode`
below — callers (including the LLM) can rely on this prefix being stable,
even though the trailing message text is not.

Risk classification (drives the Permission/HITL layer)
--------------------------------------------------------
`write_file` performs a full, unconditional overwrite of arbitrary file
content — a single bad call can silently destroy an existing file, so it
is classified HIGH_RISK and requires human approval (see `middleware/hitl.py`).
`edit_file` is classified as NOT high-risk because it enforces two
structural safeguards that make it self-limiting: (1) it can only touch a
file that already exists, and (2) it fails closed if `old_string` is not
found exactly once — so it cannot silently clobber unintended content the
way a full overwrite can. `ls`/`read_file`/`glob`/`grep` are read-only and
therefore never require approval.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Error taxonomy                                                              #
# --------------------------------------------------------------------------- #

class ErrorCode:
    """Stable error-code strings used as the `Error: {code}: ...` prefix."""
    PATH_NOT_FOUND = "path_not_found"
    NOT_A_DIRECTORY = "not_a_directory"
    IS_DIRECTORY = "is_directory"
    FILE_NOT_FOUND = "file_not_found"
    INVALID_REGEX = "invalid_regex"
    NOT_UNIQUE = "not_unique"
    IO_ERROR = "io_error"


def _error(code: str, message: str = "") -> str:
    """Format an error string per the module's error contract."""
    return f"Error: {code}: {message}" if message else f"Error: {code}"


# --------------------------------------------------------------------------- #
# Configurable bounds (documented so limits aren't silent magic numbers)      #
# --------------------------------------------------------------------------- #

# read_file: default page size. Chosen to fit comfortably inside a single
# LLM context turn alongside other tool output without needing pagination
# for the common case (small-to-medium source files).
DEFAULT_READ_LIMIT = 150

# grep: caps to keep a single tool call's output bounded regardless of repo
# size — an LLM turn has a finite context budget, and an unbounded grep
# across a large repo could otherwise blow through it in one call.
GREP_MAX_FILES = 100
GREP_MAX_RESULTS = 200


# --------------------------------------------------------------------------- #
# Input schemas                                                                #
# --------------------------------------------------------------------------- #

class ReadFileInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file")
    offset: int = Field(default=0, description="Starting line (0-indexed)")
    limit: int = Field(default=DEFAULT_READ_LIMIT, description="Max lines to read")


class WriteFileInput(BaseModel):
    file_path: str = Field(description="Absolute path to write")
    content: str = Field(description="Full content to write")


class EditFileInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file")
    old_string: str = Field(description="Exact string to find and replace (must be unique in file)")
    new_string: str = Field(description="Replacement string")


class LsInput(BaseModel):
    path: str = Field(description="Directory path to list")


class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern (e.g. '**/*.py')")
    root: str = Field(description="Root directory to search from")


class GrepInput(BaseModel):
    pattern: str = Field(description="Regex pattern to search")
    path: str = Field(description="File or directory path to search in")
    glob: str = Field(default="*", description="File glob filter (e.g. '*.py')")


# --------------------------------------------------------------------------- #
# Tools                                                                        #
# --------------------------------------------------------------------------- #

@tool(args_schema=LsInput)
def ls(path: str) -> str:
    """List files and directories at the given path."""
    target = Path(path)
    if not target.exists():
        return _error(ErrorCode.PATH_NOT_FOUND, path)
    if not target.is_dir():
        return _error(ErrorCode.NOT_A_DIRECTORY, path)

    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = []
    for entry in entries:
        prefix = "" if entry.is_dir() else "  "
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{prefix}{entry.name}{suffix}")
    return "\n".join(lines) if lines else "(empty directory)"


@tool(args_schema=ReadFileInput)
def read_file(file_path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> str:
    """Read file content with line numbers (cat -n format).

    Returns content with 1-based line numbers. Includes truncation hint if needed.
    """
    path = Path(file_path)
    if not path.exists():
        return _error(ErrorCode.FILE_NOT_FOUND, file_path)
    if path.is_dir():
        return _error(ErrorCode.IS_DIRECTORY, file_path)

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return _error(ErrorCode.IO_ERROR, str(e))

    selected = lines[offset: offset + limit]
    formatted = "\n".join(
        f"{offset + i + 1:>6}\t{line}" for i, line in enumerate(selected)
    )

    if offset + limit < len(lines):
        formatted += (
            f"\n\n[Output truncated at line {offset + limit}. "
            f"Use offset={offset + limit} to read more.]"
        )

    return formatted


@tool(args_schema=GlobInput)
def glob(pattern: str, root: str) -> str:
    """Find files matching a glob pattern under the given root directory."""
    root_path = Path(root)
    if not root_path.exists():
        return _error(ErrorCode.PATH_NOT_FOUND, root)

    matches = sorted(root_path.glob(pattern))
    if not matches:
        return f"No files found matching '{pattern}' under {root}"

    # Return relative paths for readability
    lines = [str(p.relative_to(root_path)) for p in matches]
    return "\n".join(lines)


@tool(args_schema=GrepInput)
def grep(pattern: str, path: str, glob: str = "*") -> str:
    """Search for a regex pattern in files under the given path.

    Returns matching lines with file path and line number.
    """
    target = Path(path)
    if not target.exists():
        return _error(ErrorCode.PATH_NOT_FOUND, path)

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return _error(ErrorCode.INVALID_REGEX, str(e))

    results = []

    files = [target] if target.is_file() else [
        f for f in target.rglob("*")
        if f.is_file() and fnmatch.fnmatch(f.name, glob)
    ]

    for file_path in sorted(files)[:GREP_MAX_FILES]:
        try:
            for i, line in enumerate(
                file_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if regex.search(line):
                    rel = file_path.relative_to(target) if target.is_dir() else file_path
                    results.append(f"{rel}:{i}: {line.strip()}")
        except OSError:
            continue

    if not results:
        return f"No matches found for '{pattern}'"

    output = "\n".join(results[:GREP_MAX_RESULTS])
    if len(results) > GREP_MAX_RESULTS:
        output += f"\n\n[Output truncated. {len(results) - GREP_MAX_RESULTS} more matches not shown.]"
    return output


@tool(args_schema=WriteFileInput)
def write_file(file_path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed.

    This is a high-risk operation — always requires human approval before execution.
    """
    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {path} ({len(content)} chars)"
    except OSError as e:
        return _error(ErrorCode.IO_ERROR, str(e))


@tool(args_schema=EditFileInput)
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Perform an exact string replacement in a file.

    Use this for targeted updates — memory files, appending sections, small edits.
    old_string must appear exactly once in the file.
    """
    path = Path(file_path)
    if not path.exists():
        return _error(ErrorCode.FILE_NOT_FOUND, file_path)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return _error(ErrorCode.IO_ERROR, str(e))

    count = content.count(old_string)
    if count == 0:
        return _error(ErrorCode.NOT_UNIQUE, "old_string not found in file")
    if count > 1:
        return _error(
            ErrorCode.NOT_UNIQUE,
            f"old_string found {count} times — must be unique. Add more surrounding context.",
        )

    try:
        path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
    except OSError as e:
        return _error(ErrorCode.IO_ERROR, str(e))
    return f"Successfully edited {file_path}"


# Exported list for use in the agent
FILESYSTEM_TOOLS = [ls, read_file, glob, grep, write_file, edit_file]

# write_file (full overwrite) requires HITL; edit_file (targeted) does not
HIGH_RISK_TOOLS = {"write_file"}
