"""Regression tests for the logo theme and its background gradient."""
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

class TestGradient(unittest.TestCase):
    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_background_gradient_is_diagonal_and_subtle(self):
        image = theme.background_gradient_image(100, 100, False)
        upper_left = image.getpixel((0, 0))
        lower_right = image.getpixel((99, 99))
        self.assertNotEqual(upper_left, lower_right)
        window = tuple(int(theme.pick(theme.WINDOW, False)[i:i + 2], 16) for i in (1, 3, 5))
        for pixel in (upper_left, lower_right):
            self.assertLess(max(abs(a - b) for a, b in zip(pixel, window)), 70)

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_header_gradient_endpoints(self):
        image = theme.gradient_image(400, 8)
        self.assertEqual(image.size, (400, 8))
        self.assertEqual(image.getpixel((0, 4)), (33, 150, 243))
        self.assertEqual(image.getpixel((399, 4)), (233, 30, 99))

if __name__ == "__main__":
    unittest.main(verbosity=2)
