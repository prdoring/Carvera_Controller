"""Diagnose ({...}) status parsing, including RSSI."""

from unittest.mock import Mock

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.protocols.framing import PTYPE_CTRL_SINGLE, PTYPE_DIAG_RES, build_frame
from carveracontroller.protocols.session import ProtocolSession


def test_comms_strips_trailing_newline_from_diagnose_payload():
    session = ProtocolSession()
    session.select("makera")
    # Firmware get_diagnose_string() ends with "}\\n"; framing includes that payload.
    frame = build_frame(PTYPE_DIAG_RES, b"{S:0,5000|RSSI:-57}\n")
    msgs = session.feed(frame)
    assert len(msgs) == 1
    assert msgs[0].text == "{S:0,5000|RSSI:-57}"


def test_diagnose_rssi_field():
    ctrl = Controller(CNC(), lambda _line: None, False)
    ctrl.parseBigParentheses("{S:0,5000|L:0,0|F:1,0|V:0,1|G:0|T:0|R:0|I:0|RSSI:-57}")
    assert CNC.vars["sw_spindle"] == 0
    assert CNC.vars["RSSI"] == -57


def test_diagnose_with_junk_after_brace():
    ctrl = Controller(CNC(), lambda _line: None, False)
    ctrl.parseBigParentheses("{S:1,1000|RSSI:-40}\x00")
    assert CNC.vars["sw_spindle"] == 1
    assert CNC.vars["RSSI"] == -40


def test_diagnose_external_output_power():
    ctrl = Controller(CNC(), lambda _line: None, False)
    ctrl.parseBigParentheses("{G:1,0,0,1,75}")
    assert CNC.vars["sw_light"] == 1
    assert CNC.vars["extout_state"] == 1
    assert CNC.vars["extout_power"] == 75
    assert CNC.vars["extout_report_time"] > 0
    ctrl.parseBigParentheses("{G:1}")
    assert CNC.vars["extout_state"] is None
    assert CNC.vars["extout_power"] is None


@pytest.mark.parametrize("protocol", ["makera", "smoothie"])
def test_diagnose_poll_waits_for_reply_and_retries_after_timeout(monkeypatch, protocol):
    ctrl = Controller(CNC(), None, False)
    ctrl.stream = Mock()
    ctrl.comms.select(protocol)
    now = [10.0]
    monkeypatch.setattr("carveracontroller.Controller.time.monotonic", lambda: now[0])
    expected = build_frame(PTYPE_CTRL_SINGLE, b"*") if protocol == "makera" else b"diagnose\n"

    ctrl.viewDiagnoseReport(True)
    ctrl.stream.send.assert_called_once_with(expected)
    for _ in range(8):
        now[0] += .2
        ctrl.viewDiagnoseReport(True)
    assert ctrl.stream.send.call_count == 1

    now[0] += 1
    ctrl.viewDiagnoseReport(True)
    assert ctrl.stream.send.call_count == 2
    ctrl.parseLine("{G:1,0,0,1,55}")
    assert CNC.vars["extout_power"] == 55
    ctrl.viewDiagnoseReport(True)
    assert ctrl.stream.send.call_count == 3


def test_late_diagnose_reply_updates_power_without_pending_poll():
    ctrl = Controller(CNC(), None, False)
    ctrl.sio_diagnose = True
    ctrl.parseLine("{G:1,0,0,1,50}")
    assert not ctrl.sio_diagnose
    ctrl.parseLine("{G:1,0,0,1,90}")
    assert CNC.vars["extout_power"] == 90


@pytest.mark.parametrize("busy", ["loadNUM", "sendNUM"])
def test_diagnose_does_not_poll_during_transfer(busy):
    ctrl = Controller(CNC(), None, False)
    ctrl.stream = Mock()
    ctrl.comms.select("makera")
    setattr(ctrl, busy, 1)
    ctrl.viewDiagnoseReport(True)
    ctrl.stream.send.assert_not_called()
