"""CRC and buffer ownership are independent of the stream's mutable storage."""

import pytest

from carveracontroller.protocols.framing import (
    PTYPE_CTRL_SINGLE,
    build_frame,
    crc16_ccitt,
    validate_packet_data,
)

# CRC-16/CCITT with initial value zero over 00 04 A1 3F is 35 33.
REALTIME_FRAME = bytes.fromhex("86 68 00 04 A1 3F 35 33 55 AA")


@pytest.mark.parametrize("buffer_type", [bytes, bytearray])
def test_crc_known_vector_and_prefix(buffer_type):
    assert crc16_ccitt(buffer_type(b"123456789")) == 0x31C3
    assert crc16_ccitt(buffer_type(b"123456789suffix"), 9) == 0x31C3


@pytest.mark.parametrize("buffer_type", [bytes, bytearray])
def test_realtime_frame_matches_wire_bytes(buffer_type):
    frame = build_frame(PTYPE_CTRL_SINGLE, buffer_type(b"?"))
    assert type(frame) is bytes
    assert frame == REALTIME_FRAME


@pytest.mark.parametrize("buffer_type", [bytes, bytearray])
def test_validation_accepts_receive_buffer_and_returns_immutable_snapshot(buffer_type):
    packet = buffer_type(REALTIME_FRAME[2:-2])
    parsed = validate_packet_data(packet)
    assert parsed is not None
    assert parsed.ptype == PTYPE_CTRL_SINGLE
    assert parsed.payload == b"?" and type(parsed.payload) is bytes
    assert parsed.raw == REALTIME_FRAME[2:-2] and type(parsed.raw) is bytes
    if isinstance(packet, bytearray):
        packet.clear()
        assert parsed.payload == b"?" and parsed.raw == REALTIME_FRAME[2:-2]


@pytest.mark.parametrize("buffer_type", [bytes, bytearray])
@pytest.mark.parametrize("offset", [0, 1, 2, 3, 4, 5])
def test_corrupted_length_type_payload_or_crc_is_rejected(buffer_type, offset):
    packet = bytearray(REALTIME_FRAME[2:-2])
    packet[offset] ^= 1
    assert validate_packet_data(buffer_type(packet)) is None


@pytest.mark.parametrize("buffer_type", [bytes, bytearray])
@pytest.mark.parametrize("length", range(5))
def test_short_packet_is_rejected(buffer_type, length):
    assert validate_packet_data(buffer_type(REALTIME_FRAME[2:-2][:length])) is None
