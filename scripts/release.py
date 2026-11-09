import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION_ASSIGNMENT = re.compile(r'^(version\s*=\s*)"([^"]+)"(\r?\n?)$')
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
VERSION_FILES = (
    (Path("pyproject.toml"), "project"),
    (Path("xefm-extension.toml"), "extension"),
)
LOCK_FILE = Path("uv.lock")


class ReleaseError(Exception):
    pass


def version_in_section(content: str, section: str) -> str:
    current_section = ""
    versions = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
            continue
        if current_section != section:
            continue
        match = VERSION_ASSIGNMENT.fullmatch(line)
        if match:
            versions.append(match.group(2))

    if len(versions) != 1 or SEMVER.fullmatch(versions[0]) is None:
        raise ReleaseError(f"Expected one semantic version in [{section}].")
    return versions[0]


def increment_version(version: str, part: str) -> str:
    match = SEMVER.fullmatch(version)
    if match is None:
        raise ReleaseError(f"Invalid semantic version: {version}")

    major, minor, patch = (int(value) for value in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ReleaseError(f"Invalid version component: {part}")


def replace_version(content: str, section: str, version: str) -> str:
    current_section = ""
    replaced = 0
    lines = []

    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
        if current_section == section:
            match = VERSION_ASSIGNMENT.fullmatch(line)
            if match:
                line = f'{match.group(1)}"{version}"{match.group(3)}'
                replaced += 1
        lines.append(line)

    if replaced != 1:
        raise ReleaseError(f"Expected one version field in [{section}].")
    return "".join(lines)


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReleaseError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def update_uv_lock() -> None:
    try:
        result = subprocess.run(
            ["uv", "lock", "--offline"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ReleaseError(f"Could not run uv lock: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReleaseError(f"uv lock --offline failed: {detail}")


def release(part: str, dry_run: bool) -> None:
    status = run_git("status", "--porcelain", "--untracked-files=all")
    if status:
        raise ReleaseError(
            "The working tree must be clean. Commit or stash changes before releasing."
        )

    branch = run_git("branch", "--show-current")
    if not branch:
        raise ReleaseError("Cannot release from a detached HEAD.")
    run_git("remote", "get-url", "origin")

    original_files = {
        path: (ROOT / path).read_bytes()
        for path, _ in VERSION_FILES
    }
    original_lock = (ROOT / LOCK_FILE).read_bytes()
    contents = {
        path: original_files[path].decode("utf-8")
        for path, _ in VERSION_FILES
    }
    versions = [
        version_in_section(contents[path], section)
        for path, section in VERSION_FILES
    ]
    if versions[0] != versions[1]:
        raise ReleaseError("pyproject.toml and xefm-extension.toml versions differ.")

    next_version = increment_version(versions[0], part)
    tag = f"v{next_version}"
    if run_git("tag", "--list", tag):
        raise ReleaseError(f"Tag {tag} already exists locally.")

    if dry_run:
        sys.stdout.write(f"Would release {tag} from branch {branch}.\n")
        return

    try:
        for path, section in VERSION_FILES:
            updated = replace_version(contents[path], section, next_version)
            (ROOT / path).write_bytes(updated.encode("utf-8"))
        update_uv_lock()
    except ReleaseError:
        for path, content in original_files.items():
            (ROOT / path).write_bytes(content)
        (ROOT / LOCK_FILE).write_bytes(original_lock)
        raise

    run_git(
        "add",
        "--",
        *(path.as_posix() for path, _ in VERSION_FILES),
        LOCK_FILE.as_posix(),
    )
    run_git("commit", "-m", f"chore: release {tag}")
    run_git("tag", "-a", tag, "-m", f"Release {tag}")
    run_git(
        "push",
        "--atomic",
        "origin",
        f"HEAD:refs/heads/{branch}",
        f"refs/tags/{tag}:refs/tags/{tag}",
    )
    sys.stdout.write(f"Released {tag}.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Increment project versions, create a release tag, and push."
    )
    parser.add_argument(
        "--part",
        choices=("major", "minor", "patch"),
        default="patch",
        help="Version component to increment (default: patch).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the version and branch without changing files or pushing.",
    )
    args = parser.parse_args()

    try:
        release(args.part, args.dry_run)
    except ReleaseError as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
