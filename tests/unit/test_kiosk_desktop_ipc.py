"""Exercise the native authenticated pipe without requesting disk privileges."""

import os
import subprocess
import sys

import pytest

from kioskdesktop.ipc import Endpoint


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() != 0), reason="Isolated Linux root worker test"
)
def test_unix_socket_authenticates_owner_and_root_worker_without_tcp():
    endpoint = Endpoint()
    program = (
        "import os,sys; from kioskdesktop.ipc import worker_connection; "
        "c=worker_connection(sys.argv[1],sys.argv[2],int(sys.argv[3])); "
        "v=c.receive(); c.send({'received':v['value']}); c.close()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, endpoint.address, endpoint.nonce, str(os.getpid())],
        env=dict(os.environ, PKEXEC_UID=str(os.getuid())),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    directory = endpoint.directory.name
    try:
        channel = endpoint.accept(process.pid, process)
        channel.send({"value": "bounded local transfer"})
        assert channel.receive() == {"received": "bounded local transfer"}
        assert process.wait(timeout=10) == 0
    finally:
        endpoint.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    assert not os.path.exists(directory)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows named-pipe contract")
def test_native_pipe_binds_child_pid_and_transfers_bounded_messages():
    endpoint = Endpoint()
    program = (
        "import os,sys; from kioskdesktop.ipc import worker_connection; print(os.getpid(),flush=True); "
        "c=worker_connection(sys.argv[1],sys.argv[2],int(sys.argv[3])); "
        "v=c.receive(); c.send({'received':v['value']}); c.close()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, endpoint.address, endpoint.nonce, str(os.getpid())],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        # Windows venv redirectors may launch a second Python process. The frozen worker has no redirector.
        worker_pid = int(process.stdout.readline())
        channel = endpoint.accept(worker_pid, process)
        channel.send({"value": "private IPC 工作室"})
        assert channel.receive() == {"received": "private IPC 工作室"}
        process.wait(timeout=10)
        assert process.returncode == 0
        assert not channel.alive()
    finally:
        endpoint.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
