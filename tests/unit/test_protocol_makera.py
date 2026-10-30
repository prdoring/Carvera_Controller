import pytest

from carveracontroller.protocols.framing import (
    PTYPE_FILE_MD5,
    PTYPE_LOAD_ERROR,
    PTYPE_LOAD_FINISH,
    PTYPE_LOAD_INFO,
    PTYPE_NORMAL_INFO,
    PTYPE_STATUS_RES,
    build_frame,
)
from carveracontroller.protocols.makera import MakeraProtocol
from carveracontroller.protocols.messages import MessageKind
from carveracontroller.protocols.session import ProtocolSession


def test_encode_realtime_and_command():
    proto = MakeraProtocol()
    frame = proto.encode_realtime(ord("?"))
    assert frame[:2] == b"\x86\x68"
    assert frame[-2:] == b"\x55\xaa"

    cmd = proto.encode_command(b"version\n")
    assert cmd[:2] == b"\x86\x68"
    # Trailing newlines must be stripped from CTRL_MULTI payloads (OEM behavior).
    assert b"version\n" not in cmd
    assert b"version" in cmd

    baud = proto.encode_command(b"baud 230400\n")
    assert b"230400\n" not in baud
    assert b"baud 230400" in baud

    file_cmd = proto.encode_file_command(b"upload /sd/a.nc")
    assert file_cmd[:2] == b"\x86\x68"
    # File-start frames keep the trailing newline.
    assert b"upload /sd/a.nc\n" in file_cmd


def test_feed_status_frame():
    proto = MakeraProtocol()
    payload = b"<Idle|MPos:1,2,3>"
    frame = build_frame(PTYPE_STATUS_RES, payload)
    msgs = proto.feed(frame)
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == payload.decode()


def test_feed_normal_info_and_load():
    proto = MakeraProtocol()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"ok\r\n"))
    assert msgs[0].kind == MessageKind.LINE
    assert "ok" in msgs[0].text

    msgs = proto.feed(build_frame(PTYPE_LOAD_INFO, b"file.nc\n"))
    assert msgs[0].kind == MessageKind.LOAD_CHUNK
    assert "file.nc" in msgs[0].text


def test_feed_normal_info_buffers_until_newline():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"hel")) == []
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"lo")) == []

    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b" world\r\n"))
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == "hello world\r"


def test_feed_normal_info_splits_on_embedded_newlines():
    proto = MakeraProtocol()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"one\ntwo\npartial"))
    assert [m.text for m in msgs] == ["one", "two"]

    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b" line\n"))
    assert len(msgs) == 1
    assert msgs[0].text == "partial line"


def test_feed_normal_info_reset_discards_partial_line():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"leftover")) == []
    proto.reset()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"fresh\n"))
    assert len(msgs) == 1
    assert msgs[0].text == "fresh"


def test_session_emits_one_mdi_line_for_buffered_normal_info():
    session = ProtocolSession()
    session.select("makera")
    assert session.feed(build_frame(PTYPE_NORMAL_INFO, b"Build version: ")) == []
    assert session.feed(build_frame(PTYPE_NORMAL_INFO, b"edge-")) == []
    msgs = session.feed(build_frame(PTYPE_NORMAL_INFO, b"123\r\n"))
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == "Build version: edge-123"


def test_feed_status_is_not_held_by_normal_info_buffer():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"partial")) == []
    msgs = proto.feed(build_frame(PTYPE_STATUS_RES, b"<Idle>"))
    assert len(msgs) == 1
    assert msgs[0].text == "<Idle>"
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b" line\n"))
    assert len(msgs) == 1
    assert msgs[0].text == "partial line"


def test_feed_load_finish_and_error():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_LOAD_FINISH, b"done"))[0].kind == MessageKind.LOAD_EOF
    assert proto.feed(build_frame(PTYPE_LOAD_ERROR, b"err"))[0].kind == MessageKind.LOAD_ERROR


def test_feed_rejects_bad_footer():
    proto = MakeraProtocol()
    frame = bytearray(build_frame(PTYPE_STATUS_RES, b"<Idle>"))
    frame[-1] = 0x00
    assert proto.feed(bytes(frame)) == []


def test_feed_byte_at_a_time():
    proto = MakeraProtocol()
    frame = build_frame(PTYPE_STATUS_RES, b"<Run>")
    msgs = []
    for b in frame:
        msgs.extend(proto.feed(bytes([b])))
    assert len(msgs) == 1
    assert msgs[0].text == "<Run>"


def test_file_transfer_frames_ignored_on_control_channel():
    proto = MakeraProtocol()
    frame = build_frame(PTYPE_FILE_MD5, b"3bc28b19cfca32e413fd9029000117a3")
    assert proto.feed(frame) == []


def test_incomplete_directory_reply_does_not_keep_swallowing_status(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("carveracontroller.protocols.makera.time.monotonic", lambda: now[0])
    session = ProtocolSession()
    session.select("makera")
    listing = build_frame(PTYPE_LOAD_INFO, b"example.nc 7000000 20261030120000\r\n" * 120)
    assert session.feed(listing[:100]) == []
    status = build_frame(PTYPE_STATUS_RES, b"<Idle|MPos:0,0,0>")
    for _ in range(8):
        now[0] += 0.2
        assert session.feed(status) == []
    now[0] = 2.1
    messages = session.feed(status)
    assert [message.text for message in messages] == ["<Idle|MPos:0,0,0>"]
    assert session.ready and session.protocol.ready


def test_large_fragmented_directory_reply_within_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("carveracontroller.protocols.makera.time.monotonic", lambda: now[0])
    proto = MakeraProtocol()
    payload = b"x" * 8000
    frame = build_frame(PTYPE_LOAD_INFO, payload)
    assert proto.feed(frame[:100]) == []
    now[0] = 0.9
    assert proto.feed(frame[100:4000]) == []
    now[0] = 1.8
    assert [message.text for message in proto.feed(frame[4000:])] == [payload.decode()]
    now[0] = 4.0
    assert proto.feed(build_frame(PTYPE_LOAD_FINISH))[0].kind == MessageKind.LOAD_EOF


@pytest.mark.parametrize("length", [0, 1, 2, 8201])
def test_invalid_length_does_not_consume_following_status(length):
    proto = MakeraProtocol()
    assert proto.feed(b"\x86\x68" + length.to_bytes(2, "big")) == []
    messages = proto.feed(build_frame(PTYPE_STATUS_RES, b"<Idle>"))
    assert [message.text for message in messages] == ["<Idle>"]
