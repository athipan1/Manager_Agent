from pathlib import Path
import subprocess

import pytest


def test_repository_has_no_orphan_gitlinks():
    if not Path(".git").exists():
        pytest.skip("git metadata is unavailable")

    result = subprocess.run(
        ["git", "ls-files", "-s"],
        check=True,
        capture_output=True,
        text=True,
    )
    gitlinks = []
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=3)
        if fields and fields[0] == "160000":
            gitlinks.append(fields[-1] if len(fields) == 4 else line)

    assert not gitlinks, f"unexpected gitlinks without an intentional .gitmodules contract: {gitlinks}"
