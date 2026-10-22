#!/usr/bin/python3 -I
"""Forced SSH ingress: validate metadata, stream only to the fixed root broker."""
import os
import re
import subprocess
import sys
import tempfile

SHA = re.compile(r'^[0-9a-f]{40}$')
RUN = re.compile(r'^[1-9][0-9]{0,19}-[1-9][0-9]{0,5}$')
PRS = re.compile(r'^[1-9][0-9]{0,9}(,[1-9][0-9]{0,9}){0,19}$')
MAX_BUNDLE = 256 * 1024 * 1024


def receive(source, output, target):
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_BUNDLE:
            raise ValueError('bundle transfer exceeded')
        output.write(chunk)
    output.seek(0)
    if output.readline(32) != b'# v2 git bundle\n':
        raise ValueError('version 2 bundle required')
    heads = []
    header_size = 0
    while True:
        line = output.readline(65537)
        header_size += len(line)
        if not line or header_size > 65536:
            raise ValueError('invalid bundle header')
        if line == b'\n':
            break
        if line.endswith(b' HEAD\n'):
            heads.append(line.decode('ascii').split()[0])
    if heads != [target] or output.read(4) != b'PACK':
        raise ValueError('bundle declared SHA mismatch')
    output.seek(0)


def main():
    parts = os.environ.get('SSH_ORIGINAL_COMMAND', '').split()
    if (len(parts) != 4 or parts[0] != 'deploy' or not SHA.fullmatch(parts[1])
            or not RUN.fullmatch(parts[2]) or not PRS.fullmatch(parts[3])):
        return 2
    # No checkout writes, shell, service sudo, or configurable executable.
    with tempfile.TemporaryFile() as bundle:
        receive(sys.stdin.buffer, bundle, parts[1])
        return subprocess.call(['/usr/bin/sudo', '-n', '/usr/local/sbin/gaon-deployment-broker', *parts],
                               stdin=bundle,
                               env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('{"status":"unknown","error":"ssh_ingress_rejected"}')
        sys.exit(2)
