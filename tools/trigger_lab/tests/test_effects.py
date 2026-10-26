import random
import unittest

from ds5 import effects


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


class EncoderTests(unittest.TestCase):
    def test_feedback_full_strength_from_rest(self):
        self.assertEqual(hexs(effects.feedback(0, 8)), "21 FF 03 FF FF FF 3F 00 00 00 00")

    def test_feedback_partial(self):
        self.assertEqual(hexs(effects.feedback(3, 2)), "21 F8 03 00 92 24 09 00 00 00 00")

    def test_weapon(self):
        self.assertEqual(hexs(effects.weapon(2, 5, 8)), "25 24 00 07 00 00 00 00 00 00 00")

    def test_vibration_frequency_byte(self):
        self.assertEqual(hexs(effects.vibration(0, 8, 40)), "26 FF 03 FF FF FF 3F 00 00 28 00")

    def test_bow(self):
        self.assertEqual(hexs(effects.bow(1, 6, 2, 2)), "22 42 00 09 00 00 00 00 00 00 00")

    def test_zero_strength_is_off(self):
        self.assertEqual(effects.feedback(4, 0), effects.off())
        self.assertEqual(effects.multi_feedback([0] * 10), effects.off())

    def test_ranges_rejected(self):
        with self.assertRaises(ValueError):
            effects.weapon(1, 5, 5)          # start must be >= 2
        with self.assertRaises(ValueError):
            effects.weapon(5, 5, 5)          # end must be > start
        with self.assertRaises(ValueError):
            effects.multi_feedback([9] + [0] * 9)

    def test_slope_monotonic(self):
        _, zones = effects.zone_view(effects.slope_feedback(0, 9, 1, 8))
        self.assertEqual(zones, sorted(zones))
        self.assertEqual((zones[0], zones[9]), (1, 8))

    def test_zone_view_roundtrip(self):
        rng = random.Random(1)
        for _ in range(200):
            zones = [rng.randint(0, 8) for _ in range(10)]
            block = effects.multi_feedback(zones)
            if any(zones):
                self.assertEqual(effects.zone_view(block), ("resist", zones))
            self.assertEqual(len(block), effects.BLOCK_SIZE)


if __name__ == "__main__":
    unittest.main()
