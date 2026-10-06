#!/usr/bin/env python3
"""local act-lane helper — copy text to the macOS clipboard via pbcopy.

Text is piped to pbcopy as stdin bytes (argv never carries it), so no
shell metacharacter can execute. Stdlib only.
"""
import argparse
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description="Copy text to clipboard (macOS)")
    p.add_argument("--text", required=True)
    a = p.parse_args()
    subprocess.run(["pbcopy"], input=a.text.encode("utf-8"), check=True)
    print(f"copied {len(a.text)} chars to clipboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())