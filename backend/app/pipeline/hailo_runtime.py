"""Thin HailoRT wrapper for the Hailo-8 PCIe accelerator.

Hailo does not plug into ONNX Runtime as an execution provider: it runs
its own compiled `.hef` binaries through HailoRT. This module isolates
every HailoRT import and API-version quirk so the rest of the pipeline
only sees `infer(image) -> {name: tensor}`.

Importing this module never fails on machines without HailoRT — call
`hailo_available()` first, and construct `HailoNetwork` only when true.
"""

import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np

from app.logging_setup import get_logger

logger = get_logger("pipeline.hailo")

HAILO_DEVICE_NODE = Path("/dev/hailo0")


def hailo_runtime_installed() -> bool:
    """True when the HailoRT Python package is importable in this container."""
    try:
        import hailo_platform  # noqa: F401
    except Exception:
        return False
    return True


def hailo_device_present() -> bool:
    """True when the Hailo PCIe driver has published its device node."""
    return HAILO_DEVICE_NODE.exists()


def hailo_available() -> bool:
    """Both the runtime and the device are usable."""
    return hailo_runtime_installed() and hailo_device_present()


def device_temperature_c() -> float | None:
    """Chip temperature in Celsius, or None when unavailable."""
    if not hailo_available():
        return None
    try:
        from hailo_platform import Device

        devices = Device.scan()
        if not devices:
            return None
        with Device(devices[0]) as device:
            temps = device.control.get_chip_temperature()
            # Two on-die sensors; report the hotter one.
            return round(max(float(temps.ts0_temperature), float(temps.ts1_temperature)), 1)
    except Exception:
        return None


class HailoNetwork:
    """One compiled `.hef` network held open on the accelerator.

    The vstream pipeline is created once and reused for every inference:
    re-entering it per frame costs tens of milliseconds and would defeat
    the point of the accelerator.
    """

    def __init__(self, hef_path: Path, vdevice: Any | None = None) -> None:
        from hailo_platform import (
            HEF,
            ConfigureParams,
            FormatType,
            HailoStreamInterface,
            InferVStreams,
            InputVStreamParams,
            OutputVStreamParams,
            VDevice,
        )

        self._lock = threading.Lock()
        self._stack = ExitStack()
        self._owns_device = vdevice is None

        try:
            self._vdevice = vdevice or VDevice()
            hef = HEF(str(hef_path))

            params = ConfigureParams.create_from_hef(
                hef, interface=HailoStreamInterface.PCIe
            )
            self._network_group = self._vdevice.configure(hef, params)[0]

            input_info = hef.get_input_vstream_infos()[0]
            self._input_name = input_info.name
            self.input_shape = tuple(input_info.shape)  # (H, W, C)

            input_params = InputVStreamParams.make(
                self._network_group, format_type=FormatType.UINT8
            )
            output_params = OutputVStreamParams.make(
                self._network_group, format_type=FormatType.FLOAT32
            )

            # Older HailoRT needs an explicit activation; newer builds with the
            # scheduler enabled activate implicitly and raise here instead.
            try:
                self._stack.enter_context(
                    self._network_group.activate(self._network_group.create_params())
                )
            except Exception as error:  # noqa: BLE001 - version-dependent, non-fatal
                logger.debug("Network activation skipped (scheduler mode): %s", error)

            self._pipeline = self._stack.enter_context(
                InferVStreams(self._network_group, input_params, output_params)
            )
        except Exception:
            self._stack.close()
            raise

        logger.info("Hailo network loaded: %s (input %s)", hef_path.name, self.input_shape)

    @property
    def input_size(self) -> int:
        """Square input side length in pixels."""
        return int(self.input_shape[0])

    def infer(self, image_hwc: np.ndarray) -> dict[str, np.ndarray]:
        """Run one image (uint8, HWC, RGB) through the network."""
        batch = np.expand_dims(np.ascontiguousarray(image_hwc, dtype=np.uint8), axis=0)
        with self._lock:  # the device is shared by the pipeline and the search API
            return self._pipeline.infer({self._input_name: batch})

    def close(self) -> None:
        """Release the vstream pipeline and, if owned, the virtual device."""
        self._stack.close()
        if self._owns_device:
            try:
                self._vdevice.release()
            except Exception:  # noqa: BLE001 - best effort on shutdown
                pass
