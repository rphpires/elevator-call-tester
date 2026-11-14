import pytest

from elevator_call_tester.links import LinkError


class FakeLink:
    """In-memory link. ``responder(request) -> bytes`` scripts the other side."""

    description = "fake"

    def __init__(self, responder=None):
        self.responder = responder or (lambda request: b"")
        self.sent: list[bytes] = []
        self.rx = bytearray()
        self.opened = 0
        self._open = False
        self.fail_next_write = False

    @property
    def is_open(self):
        return self._open

    def open(self):
        self.opened += 1
        self._open = True

    def ensure_open(self):
        if not self._open:
            self.open()

    def close(self):
        self._open = False

    def write(self, data):
        if self.fail_next_write:
            self.fail_next_write = False
            self._open = False
            raise LinkError("cable unplugged")
        self.sent.append(bytes(data))
        self.rx += self.responder(bytes(data))

    def read(self, size, timeout):
        chunk = bytes(self.rx[:size])
        del self.rx[:size]
        return chunk

    def discard_input(self, wait=0.0):
        self.rx.clear()


@pytest.fixture
def fake_link():
    return FakeLink


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr("elevator_call_tester.modbus.time.sleep", lambda s: None)
