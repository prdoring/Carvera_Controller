from unittest.mock import Mock

import pytest

from carveracontroller.addons.cmm_workbench.ui.probe_runner import ProbeRunner


def test_cancel_before_run_report_waits_for_fresh_status_and_ignores_late_result():
    state, revision = ["Idle"], [3]
    probing, status, abort = Mock(), Mock(), Mock()
    runner = ProbeRunner(set_is_probing=probing, set_status_text=status,
                         on_is_probing_changed=Mock(), controller_abort=abort,
                         get_machine_state=lambda: state[0], get_status_revision=lambda: revision[0],
                         on_timeout=Mock(), on_invalid_state=Mock())
    token = runner.start()
    try:
        runner.cancel(abort_machine=True)
        abort.assert_called_once()
        assert not runner.is_token_valid(token)
        runner.cancel(abort_machine=True)
        abort.assert_called_once()
        runner.complete()
        runner._check_cancelled(0)
        assert runner.cancellation_pending
        with pytest.raises(RuntimeError):
            runner.start()
        state[0] = "N/A"
        revision[0] += 1
        runner._check_cancelled(0)
        assert runner.cancellation_pending
        assert "unconfirmed" in status.call_args.args[0]
        state[0] = "Run"
        revision[0] += 1
        runner._check_cancelled(0)
        assert runner.cancellation_pending
        state[0] = "Idle"
        revision[0] += 1
        event = runner._cancel_event
        assert runner._check_cancelled(0) is False
        event.cancel()
        assert not runner.cancellation_pending
        probing.assert_called_with(False)
    finally:
        runner.shutdown()
        if runner._cancel_event is not None:
            runner._cancel_event.cancel()
