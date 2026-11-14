import unittest

from kingmaker import engine as E


def empty():
    return [0] * 64


def sq(n):
    """Standard 1-32 square number -> 64-square index."""
    return E.sq64(n - 1)


class PerftTests(unittest.TestCase):
    def perft(self, b, side, d):
        mv = E.legal_moves(b, side)
        if d == 1:
            return len(mv)
        return sum(self.perft(E.apply_move(b, m), -side, d - 1) for m in mv)

    def test_known_node_counts(self):
        expected = [7, 49, 302, 1469, 7361, 36768]
        for d, n in enumerate(expected, start=1):
            self.assertEqual(self.perft(E.start_board(), 1, d), n, f"depth {d}")


class NativeTests(unittest.TestCase):
    def setUp(self):
        from kingmaker import native
        if not native.available():
            self.skipTest("native library not built (run python build_native.py)")
        self.native = native

    def test_native_perft(self):
        expected = [7, 49, 302, 1469, 7361, 36768, 179740, 845931]
        for d, n in enumerate(expected, start=1):
            self.assertEqual(self.native.perft(E.start_board(), 1, d), n, f"depth {d}")

    def test_native_matches_python_on_tactics(self):
        b = empty()
        b[sq(14)], b[sq(18)], b[sq(30)] = 1, -1, -1
        self.assertEqual(E.notation(E.analyze(b, 1, 300).best), "14x23")
        a = E.analyze(E.start_board(), 1, 300)
        self.assertGreaterEqual(a.depth, 8)

    def test_native_handles_no_moves(self):
        b = empty()
        b[sq(1)] = 1
        self.assertIsNone(E.analyze(b, -1, 50).best)


class RuleTests(unittest.TestCase):
    def test_capture_is_mandatory(self):
        b = empty()
        b[sq(14)], b[sq(18)], b[sq(1)] = 1, -1, 1   # black 14 can jump red 18; black 1 could step
        moves = E.legal_moves(b, 1)
        self.assertTrue(moves and all(m.caps for m in moves))

    def test_multi_jump(self):
        b = empty()
        b[sq(9)], b[sq(14)], b[sq(22)] = 1, -1, -1
        moves = E.legal_moves(b, 1)
        self.assertEqual([E.notation(m) for m in moves], ["9x18x25"])
        self.assertEqual(len(moves[0].caps), 2)

    def test_man_stops_when_crowned(self):
        b = empty()
        b[sq(23)], b[sq(27)] = 1, -1                # black man jumps into row 7 and must stop there
        after = E.apply_move(b, E.legal_moves(b, 1)[0])
        self.assertEqual(after[sq(32)], 2)

    def test_men_do_not_move_backwards(self):
        b = empty()
        b[sq(18)] = 1
        dests = {E.sq32(m.path[-1]) + 1 for m in E.legal_moves(b, 1)}
        self.assertEqual(dests, {22, 23})

    def test_kings_move_both_ways(self):
        b = empty()
        b[sq(18)] = 2
        dests = {E.sq32(m.path[-1]) + 1 for m in E.legal_moves(b, 1)}
        self.assertEqual(dests, {14, 15, 22, 23})

    def test_no_moves_means_loss(self):
        b = empty()
        b[sq(1)] = 1
        self.assertEqual(E.legal_moves(b, -1), [])
        self.assertIsNone(E.analyze(b, -1, 50).best)


class SearchTests(unittest.TestCase):
    def test_takes_a_free_piece(self):
        b = empty()
        b[sq(14)], b[sq(18)], b[sq(30)] = 1, -1, -1
        a = E.analyze(b, 1, 500)
        self.assertEqual(E.notation(a.best), "14x23")

    def test_finds_forced_win(self):
        b = empty()
        b[sq(10)] = 2
        b[sq(30)] = -1
        a = E.analyze(b, 1, 1000)
        self.assertGreater(a.score, 0)

    def test_beats_random_player(self):
        import random
        rng = random.Random(7)
        b, side = E.start_board(), 1
        for _ in range(120):
            moves = E.legal_moves(b, side)
            if not moves:
                break
            m = E.analyze(b, side, 60).best if side == 1 else rng.choice(moves)
            b, side = E.apply_move(b, m), -side
        self.assertEqual(E.legal_moves(b, side), [])
        self.assertEqual(side, -1, "black (engine) should win")


if __name__ == "__main__":
    unittest.main()
