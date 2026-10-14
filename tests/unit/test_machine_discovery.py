from collections import deque

import pytest

from carveracontroller.WIFIStream import MachineDetector


class DatagramSocket:
    def __init__(self):
        self.packets = deque()
        self.blocking = None
        self.closed = False
        self.read_count = 0

    def setblocking(self, blocking):
        self.blocking = blocking

    def bind(self, address):
        self.address = address

    def recvfrom(self, size):
        self.read_count += 1
        if not self.packets:
            raise BlockingIOError
        return self.packets.popleft(), ("192.0.2.1", 3333)

    def close(self):
        self.closed = True


@pytest.fixture
def discovery(monkeypatch):
    now = [100.0]
    sockets = []

    def create_socket(*args):
        sock = DatagramSocket()
        sockets.append(sock)
        return sock

    monkeypatch.setattr("carveracontroller.WIFIStream.socket.socket", create_socket)
    monkeypatch.setattr("carveracontroller.WIFIStream.time.monotonic", lambda: now[0])
    detector = MachineDetector()
    detector.query_for_machines()
    return detector, sockets, now


def test_scan_is_nonblocking_and_finishes_without_packets(discovery):
    detector, sockets, now = discovery
    sock = sockets[0]
    assert sock.blocking is False
    assert detector.check_for_responses() is None
    assert sock.read_count == 1
    now[0] += 3
    assert detector.check_for_responses() == []
    assert sock.closed
    assert detector.sock is None


def test_scan_ignores_invalid_packets_and_deduplicates(discovery):
    detector, sockets, now = discovery
    sockets[0].packets.extend([
        b"\xff", b"partial", b"bad,192.0.2.1,no,0", b"bad,192.0.2.1,0,0",
        b"Air,192.0.2.2,2222,0", b"Air,192.0.2.2,2222,0", b"Carvera,192.0.2.3,2222,1",
    ])
    assert detector.check_for_responses() is None
    now[0] += 3
    assert detector.check_for_responses() == [
        {"machine": "Air", "ip": "192.0.2.2", "port": 2222, "busy": False},
        {"machine": "Carvera", "ip": "192.0.2.3", "port": 2222, "busy": True},
    ]


def test_reopening_and_canceling_scan_release_socket(discovery):
    detector, sockets, now = discovery
    detector.query_for_machines()
    assert sockets[0].closed
    assert sockets[1].blocking is False
    detector.close()
    detector.close()
    assert sockets[1].closed
    assert detector.check_for_responses() == []


def test_packet_flood_cannot_keep_one_frame_busy(discovery):
    detector, sockets, now = discovery
    sockets[0].packets.extend([b"partial"] * 1000)
    assert detector.check_for_responses() is None
    assert sockets[0].read_count == 64
    now[0] += 3
    assert detector.check_for_responses() == []
    assert sockets[0].closed


def test_bind_failure_returns_completed_scan(discovery, monkeypatch):
    detector, sockets, now = discovery

    def fail_bind(self, address):
        raise OSError("address in use")

    monkeypatch.setattr(DatagramSocket, "bind", fail_bind)
    detector.query_for_machines()
    assert sockets[-1].closed
    assert detector.check_for_responses() == []
