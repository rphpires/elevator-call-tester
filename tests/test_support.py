import logging
import threading
import time

from elevator_call_tester import logsetup, settings
from elevator_call_tester.drivers import DRIVERS
from elevator_call_tester.i18n import STRINGS, Translator
from elevator_call_tester.ui.worker import IoWorker


def test_every_language_has_every_key():
    keys = {lang: set(table) for lang, table in STRINGS.items()}
    assert keys["en"] == keys["pt_BR"]


def test_driver_parameters_are_translated():
    for driver in DRIVERS.values():
        for param in driver.parameters:
            keys = [param.label] + ([param.help] if param.help else []) + [lbl for _, lbl in param.choices]
            for key in keys:
                assert key in STRINGS["en"], key


def test_translator_falls_back_to_english_and_key():
    t = Translator("xx")
    assert t("conn.connect") == "Connect"
    assert t("missing.key") == "missing.key"
    assert "1.0" in Translator("pt_BR")("about.text", version="1.0")


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "s.json"
    settings.save({"host": "10.0.0.1"}, path)
    assert settings.load(path) == {"host": "10.0.0.1"}
    path.write_text("{broken", encoding="utf-8")
    assert settings.load(path) == {}
    assert settings.load(tmp_path / "missing.json") == {}


def test_session_log_file(tmp_path):
    records, log_file = logsetup.setup(tmp_path)
    logging.getLogger("elevator_call_tester.test").info("hello")
    for handler in logging.getLogger(logsetup.LOGGER_NAME).handlers:
        handler.flush()
    assert log_file is not None and "hello" in log_file.read_text(encoding="utf-8")
    assert not records.empty()


def drain(worker, until, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        worker.poll()
        time.sleep(0.01)


def test_worker_runs_tasks_in_order_on_one_thread():
    worker = IoWorker()
    seen, results = [], []
    for i in range(5):
        worker.submit(
            lambda i=i: seen.append((i, threading.current_thread().name)) or i,
            lambda result, error: results.append(result),
        )
    drain(worker, lambda: len(results) == 5)
    assert results == [0, 1, 2, 3, 4]
    assert {name for _, name in seen} == {"io-worker"}
    assert not worker.busy
    worker.shutdown()


def test_worker_reports_errors_to_callback():
    worker = IoWorker()
    got = []

    def boom():
        raise RuntimeError("x")

    worker.submit(boom, lambda result, error: got.append(error))
    drain(worker, lambda: got)
    assert isinstance(got[0], RuntimeError)
    worker.shutdown()


def test_failing_callback_does_not_block_later_callbacks():
    worker = IoWorker()
    got = []

    def bad(result, error):
        raise RuntimeError("callback bug")

    worker.submit(lambda: 1, bad)
    worker.submit(lambda: 2, lambda result, error: got.append(result))
    drain(worker, lambda: got)
    assert got == [2]
    assert not worker.busy
    worker.shutdown()
