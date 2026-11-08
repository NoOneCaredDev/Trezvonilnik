import os
import random
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TREZVONILNIK_HOME", tempfile.mkdtemp(prefix="trz-test-"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from ui.widgets.wheel import WheelPage, WheelWidget, final_angle, pick_winner, sector_at_pointer


class WheelMathTests(unittest.TestCase):
    def test_pointer_lands_on_chosen_sector_for_random_inputs(self):
        rng = random.Random(7)
        for _ in range(500):
            n = rng.randint(2, 12)
            weights = [rng.choice([0.1, 0.5, 1, 2, 7]) for _ in range(n)]
            winner, offset = pick_winner(weights, rng)
            turns = rng.uniform(5, 8)
            self.assertEqual(sector_at_pointer(weights, final_angle(weights, winner, offset, turns)), winner)

    def test_weights_are_respected(self):
        rng = random.Random(1)
        counts = [0, 0, 0]
        for _ in range(20000):
            counts[pick_winner([1, 1, 2], rng)[0]] += 1
        self.assertAlmostEqual(counts[2] / 20000, 0.5, delta=0.02)
        self.assertAlmostEqual(counts[0] / 20000, 0.25, delta=0.02)

    def test_offset_never_hugs_sector_border(self):
        rng = random.Random(3)
        offs = [pick_winner([1, 1], rng)[1] for _ in range(1000)]
        self.assertGreaterEqual(min(offs), 0.12)
        self.assertLessEqual(max(offs), 0.88)


class _Cleanup(unittest.TestCase):
    """Виджеты PySide нужно убирать до завершения QApplication — иначе возможен segfault при выходе."""
    def tearDown(self):
        for w in QApplication.topLevelWidgets():
            w.deleteLater()
        app.processEvents()


class WheelWidgetTests(_Cleanup):
    def test_animation_ends_exactly_on_winner(self):
        w = WheelWidget()
        w.resize(360, 360)
        w.set_data(["a", "b", "c", "d"], [1, 3, 1, 1])
        done = []
        w.finished.connect(done.append)
        w.spin_to(1, 0.5, 6, ms=250)
        QTest.qWait(500)
        self.assertEqual(done, [1])
        self.assertEqual(sector_at_pointer(w.weights, w.angle), 1)
        self.assertFalse(w.spinning)

    def test_second_spin_ignored_while_spinning(self):
        w = WheelWidget()
        w.set_data(["a", "b"], [1, 1])
        w.spin_to(0, 0.5, 6, ms=300)
        w.spin_to(1, 0.5, 6, ms=300)
        QTest.qWait(450)
        self.assertEqual(w.winner, 0)


class WheelPageTests(_Cleanup):
    def test_editor_updates_wheel_and_percentages(self):
        page = WheelPage()
        page.set_options([{"name": "A", "weight": 1}, {"name": "B", "weight": 3}, {"name": "", "weight": 5}])
        self.assertEqual(page.wheel.options, ["A", "B"])                     # пустые варианты не попадают на колесо
        self.assertEqual(page._rows[1].percent.text(), "75%")
        page._rows[0].weight.setValue(3)
        self.assertEqual(page._rows[0].percent.text(), "50%")

    def test_spin_emits_share_payload_only_when_enabled(self):
        page = WheelPage()
        page.set_options([{"name": "A", "weight": 1}, {"name": "B", "weight": 1}])
        got = []
        page.spun.connect(got.append)
        page.share.setChecked(False)
        page.spin()
        self.assertEqual(got, [])
        QTest.qWait(5600)
        page.share.setChecked(True)
        page.spin()
        self.assertEqual(len(got), 1)
        self.assertEqual(set(got[0]), {"options", "weights", "winner", "offset", "turns"})
        QTest.qWait(5600)
        self.assertIn(page.wheel.options[got[0]["winner"]], page.result.text())

    def test_remote_spin_shows_who_and_result(self):
        page = WheelPage()
        page.play_remote({"options": ["x", "y", "z"], "weights": [1, 1, 1], "winner": 2, "offset": 0.4, "turns": 5}, "Вася")
        self.assertIn("Вася", page.result.text())
        self.assertFalse(page.spin_btn.isEnabled())
        QTest.qWait(5600)
        self.assertIn("z", page.result.text())
        self.assertTrue(page.spin_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
