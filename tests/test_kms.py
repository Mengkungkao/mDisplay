"""Direct HDMI output (DRM/KMS): the kernel interface as mDisplay declares it, and
the choice of screen and mode. No /dev/dri device is opened here."""

import ctypes
import unittest

import helpers  # noqa: F401  (puts the project on sys.path)
from app.display import kms

# From the Linux UAPI headers <drm/drm.h> and <drm/drm_mode.h>, compiled with gcc
# on aarch64 (2026-10-23); the same on every 64-bit and 32-bit Linux ABI.
IOCTLS = {"SET_MASTER": 0x641E, "DROP_MASTER": 0x641F, "GETRESOURCES": 0xC04064A0,
          "GETCRTC": 0xC06864A1, "SETCRTC": 0xC06864A2, "GETENCODER": 0xC01464A6,
          "GETCONNECTOR": 0xC05064A7, "ADDFB": 0xC01C64AE, "RMFB": 0xC00464AF,
          "PAGE_FLIP": 0xC01864B0, "CREATE_DUMB": 0xC02064B2, "MAP_DUMB": 0xC01064B3,
          "DESTROY_DUMB": 0xC00464B4}
SIZES = {"ModeInfo": 68, "CardRes": 64, "Crtc": 104, "GetEncoder": 20, "GetConnector": 80,
         "FbCmd": 28, "PageFlip": 24, "CreateDumb": 32, "MapDumb": 16, "DestroyDumb": 4}

HDMI, DSI, DP, VGA = 11, 16, 10, 1


def mode(w, h, hz=60, preferred=False):
    return kms.Mode(w, h, hz, preferred)


def connector(kind, connected=True, modes=None, type_id=1, card="/dev/dri/card0"):
    return kms.Connector(card, 40 + kind, kind, type_id, connected,
                         modes if modes is not None else [mode(1920, 1080, preferred=True)], 0, [])


class KernelInterfaceTests(unittest.TestCase):
    def test_ioctl_numbers_match_the_kernel(self):
        for name, value in IOCTLS.items():
            self.assertEqual(getattr(kms, name), value, name)

    def test_structures_match_the_kernel(self):
        for name, size in SIZES.items():
            self.assertEqual(ctypes.sizeof(getattr(kms, name)), size, name)


class ChooseModeTests(unittest.TestCase):
    MODES = [mode(1920, 1080, 60, True), mode(1920, 1080, 50), mode(1280, 720, 60),
             mode(1280, 720, 50), mode(1024, 768, 60), mode(720, 576, 50)]

    def test_software_drawing_takes_the_smallest_same_shape_mode_from_1280(self):
        chosen = kms.choose_mode(self.MODES, prefer_small=True)
        self.assertEqual((chosen.width, chosen.height, chosen.refresh), (1280, 720, 60))

    def test_otherwise_the_preferred_mode(self):
        chosen = kms.choose_mode(self.MODES, prefer_small=False)
        self.assertEqual((chosen.width, chosen.height, chosen.refresh), (1920, 1080, 60))

    def test_a_4k_preference_is_capped(self):
        modes = [mode(3840, 2160, 30, True), mode(1920, 1080, 60), mode(1920, 1080, 30)]
        chosen = kms.choose_mode(modes, prefer_small=False)
        self.assertEqual((chosen.width, chosen.height, chosen.refresh), (1920, 1080, 60))

    def test_no_smaller_mode_of_the_same_shape_keeps_the_preferred_one(self):
        modes = [mode(1680, 1050, 60, True), mode(1024, 768, 60)]
        chosen = kms.choose_mode(modes, prefer_small=True)
        self.assertEqual((chosen.width, chosen.height), (1680, 1050))

    def test_no_modes(self):
        self.assertIsNone(kms.choose_mode([], prefer_small=True))


class ChooseConnectorTests(unittest.TestCase):
    def test_a_connected_hdmi_screen_is_chosen_over_a_built_in_panel(self):
        chosen = kms.choose_connector([connector(DSI), connector(HDMI)])
        self.assertEqual(chosen.name, "HDMI-A-1")

    def test_built_in_panels_are_never_chosen_automatically(self):
        self.assertIsNone(kms.choose_connector([connector(DSI)]))

    def test_unplugged_screens_are_not_chosen(self):
        self.assertIsNone(kms.choose_connector([connector(HDMI, connected=False)]))
        self.assertIsNone(kms.choose_connector([connector(HDMI, modes=[])]))

    def test_hdmi_before_displayport_before_vga(self):
        chosen = kms.choose_connector([connector(VGA), connector(DP), connector(HDMI, type_id=2)])
        self.assertEqual(chosen.name, "HDMI-A-2")

    def test_a_named_screen(self):
        found = [connector(HDMI), connector(HDMI, type_id=2)]
        self.assertEqual(kms.choose_connector(found, "HDMI-A-2").name, "HDMI-A-2")
        self.assertIsNone(kms.choose_connector(found, "DP-1"))


if __name__ == "__main__":
    unittest.main()
