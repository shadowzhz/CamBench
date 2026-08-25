from dataclasses import dataclass

from camera.utils import normalize_format


@dataclass(frozen=True)
class CameraMode:

    pixel_format: str
    width: int
    height: int
    fps: float


    @property
    def display_name(self):
        return (
            f"{self.width}x{self.height} | "
            f"{normalize_format(self.pixel_format)} | "
            f"{self.fps:.2f} FPS"
        )


@dataclass(frozen=True)
class CameraInfo:

    device: str
    name: str
    bus_info: str
    modes: tuple
    alt_devices: tuple = ()


    @property
    def display_name(self):

        if self.bus_info:
            return (
                f"{self.name}    "
                f"{self.device}"
            )

        return self.device


    @property
    def device_candidates(self):

        return (
            self.device,
        ) + tuple(
            x for x in self.alt_devices
            if x != self.device
        )
    