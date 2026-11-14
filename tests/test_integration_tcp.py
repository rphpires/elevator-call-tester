"""Real sockets against the bundled simulator: both converter types, detection, reconnect."""

import pytest

from elevator_call_tester.drivers import CallRequest, ConnectionConfig, TkeDriver
from elevator_call_tester.modbus import Framing
from elevator_call_tester.simulator import Simulator

PARAMS = {"unit_id": "1", "device": "2", "floor_offset": "0", "mco_map": "1", "message": "auto"}


def config(sim, framing=Framing.AUTO):
    host, port = sim.address
    return ConnectionConfig(kind="tcp", host=host, port=port, framing=framing)


@pytest.mark.parametrize("mode,expected", [("gateway", "MBAP"), ("transparent", "RTU")])
def test_call_through_simulator(mode, expected):
    with Simulator(mode) as sim:
        driver = TkeDriver()
        driver.connect(config(sim))
        try:
            result = driver.call(CallRequest(3, 9, PARAMS))
        finally:
            driver.close()
    assert result.accepted, result.summary
    assert expected in result.summary
    assert sim.calls == [(0, [3, 2, 9, 1, 0, 0, 1, 0])]


def test_gateway_exception_for_unknown_unit():
    with Simulator("gateway", unit=1) as sim:
        driver = TkeDriver()
        driver.connect(config(sim, Framing.MBAP))
        result = driver.call(CallRequest(1, 2, {**PARAMS, "unit_id": "9"}))
        driver.close()
    assert not result.accepted
    assert "0x0B" in result.summary


def test_reconnects_after_peer_restart():
    sim = Simulator("gateway").start()
    host, port = sim.address
    driver = TkeDriver()
    driver.connect(config(sim, Framing.MBAP))
    assert driver.call(CallRequest(1, 2, PARAMS)).accepted
    sim.stop()
    with Simulator("gateway", host=host, port=port) as sim2:
        result = driver.call(CallRequest(1, 3, PARAMS))
    driver.close()
    assert result.accepted, result.summary
    assert sim2.calls


def test_connection_refused_is_a_link_error():
    from elevator_call_tester.links import LinkError

    with Simulator("gateway") as sim:
        host, port = sim.address
    with pytest.raises(LinkError):
        TkeDriver().connect(ConnectionConfig(kind="tcp", host=host, port=port))
