from typing import Protocol
import numpy as np
from pathlib import Path
import csv

from structlog import get_logger

from .datacollector import DataCollector

logger = get_logger()


class HeartModel(Protocol):
    def compute_volume(self, activation: float, pressure: float) -> float:
        ...

    def dVdp(self, activation: float, pressure: float) -> float:
        ...

    def get_pressure(self) -> float:
        ...

    def get_volume(self) -> float:
        ...

    def save(self, t: float, outdir: Path) -> None:
        ...


class CirculationModel(Protocol):
    aortic_pressure: float
    aortic_pressure_derivation: float
    valve_open: bool

    def Q(self, pressure_current: float, pressure_old: float, dt: float) -> float:
        ...

    def dQdp(self, pressure_current: float, pressure_old: float, dt: float) -> float:
        ...

    def update_aortic_pressure(self) -> float:
        ...


def circulation_solver(
    heart_model: HeartModel,
    circulation_model: CirculationModel,
    activation: np.ndarray,
    time: np.ndarray,
    collector: DataCollector | None = None,
    start_time: int = 0,
):
    """
    Solves the coupled cardiac and circulation model dynamics over a specified time period.

    Parameters:
    heart_model (HeartModel): Instance of HeartModel for cardiac dynamics.
    circulation_model (CirculationModel): Instance of CirculationModel for circulation dynamics.
    activation (np.array): Array of activation levels corresponding to time points.
    time (np.array): Array of time points for the simulation.

    Raises:
    ValueError: If the lengths of time and activation arrays do not match.
    """

    if not len(time) == len(activation):
        raise ValueError(
            (
                "Please provide the time series for each activation value (the length of time and activation should be the same!)"
            ),
        )

    if collector is None:
        collector = DataCollector(outdir=Path("results"), problem=heart_model)

    for i, t in enumerate(time):
        # Getting state variable pressure and volume
        p_old = heart_model.get_pressure()
        v_old = heart_model.get_volume()
        # Current activation level
        a_current = activation[i]
        logger.info("Current time", t=t, a_current=a_current)
        # initial guess for the current pressure pressure
        if i == 0 or i == 1:
            p_current = p_old
            dt = time[i + 1] - time[i]
        else:
            dp = collector.pressures[-1] - collector.pressures[-2]
            dp_sign = np.sign(dp)
            dp_value = min(np.abs(dp), 2.0)

            p_current = collector.pressures[-1] + dp_sign * dp_value
            dt = time[i] - time[i - 1]

        tol = 1e-3
        R = []
        circ_iter = 0
        v_diff = 1.0
        while abs(v_diff) > tol and circ_iter < 20:
            v_current = heart_model.compute_volume(a_current, p_current)
            outflow = circulation_model.Q(p_current, p_old, dt)
            v_current_circ = v_old - outflow * dt
            v_diff = v_current - v_current_circ
            logger.info(
                "Iteration",
                v_diff=v_diff,
                p_current=p_current,
                v_current=v_current,
                v_current_circ=v_current_circ,
                dt=dt,
                circ_iter=circ_iter,
            )

            # Updataing p_current based on relative error using newton method
            if abs(v_diff) > tol:
                dVdp = heart_model.dVdp(a_current, p_current)
                dQdp = circulation_model.dQdp(p_current, p_old, dt)
                J = dVdp + dQdp * dt

                p_current = p_current - v_diff / J
                circ_iter += 1

        p_current = heart_model.get_pressure()
        v_current = heart_model.get_volume()
        if circulation_model.valve_open:
            circulation_model.update_aortic_pressure()

        collector.collect(
            t + start_time,
            a_current,
            v_current,
            p_current,
            outflow,
            circulation_model.aortic_pressure,
        )

        if p_current < 0.01:
            break
    # for time, activation, vol, pres_val, ao_pres_val, flow in zip(time, activation, volumes, presures, aortic_pressures, outflows):
    # writer.writerow([time, activation, vol, pres_val,ao_pres_val, flow])

    return collector
