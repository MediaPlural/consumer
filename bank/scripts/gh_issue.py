#!/usr/bin/env python3
"""repo (GitHub) act-lane helper — thin, stdlib-only wrapper over `gh`.

Auth is delegated entirely to the gh CLI (already authed on this box via
its keyring) — no token ever enters this script, argv, or a log. Args are
passed as literal argv elements to gh; the SAFE runner in bank.py has
already shlex-quoted everything upstream, and this script never touches
a shell.
"""
import argparse
import shutil
import subprocess
import sys


def gh(argv):
    if not shutil.which("gh"):
        print("FATAL: gh CLI not installed", file=sys.stderr)
        return 1
    return subprocess.run(["gh"] + argv, timeout=180).returncode


def main():
    p = argparse.ArgumentParser(description="GitHub act lane via gh CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-issue")
    c.add_argument("--repo", required=True, help="OWNER/REPO")
    c.add_argument("--title", required=True)
    c.add_argument("--body", default="")

    l = sub.add_parser("list-issues")
    l.add_argument("--repo", required=True, help="OWNER/REPO")
    l.add_argument("--state", default="open", choices=["open", "closed", "all"])
    l.add_argument("--limit", type=int, default=10)

    cl = sub.add_parser("close-issue")
    cl.add_argument("--repo", required=True, help="OWNER/REPO")
    cl.add_argument("--number", required=True)
    cl.add_argument("--comment", default=None)

    a = p.parse_args()
    if a.cmd == "create-issue":
        return gh(["issue", "create", "--repo", a.repo,
                   "--title", a.title, "--body", a.body])
    if a.cmd == "list-issues":
        return gh(["issue", "list", "--repo", a.repo, "--state", a.state,
                   "--limit", str(a.limit)])
    if a.cmd == "close-issue":
        argv = ["issue", "close", a.number, "--repo", a.repo]
        if a.comment:
            argv += ["--comment", a.comment]
        return gh(argv)
    return 2


if __name__ == "__main__":
    sys.exit(main())