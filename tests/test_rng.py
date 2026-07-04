from musicgen.rng import Seeder


def test_same_keys_same_stream():
    a = Seeder(42).stream("melody", 17)
    b = Seeder(42).stream("melody", 17)
    assert [a.random() for _ in range(8)] == [b.random() for _ in range(8)]


def test_streams_independent_of_draw_history():
    # Draining one stream must not affect another (PLANS.md §9).
    s = Seeder(42)
    drained = s.stream("melody", 1)
    for _ in range(100):
        drained.random()
    a = s.stream("harmony", 1).random()
    b = Seeder(42).stream("harmony", 1).random()
    assert a == b


def test_different_keys_differ():
    s = Seeder(42)
    assert s.stream("melody", 1).random() != s.stream("melody", 2).random()
    assert s.stream("melody", 1).random() != s.stream("bass", 1).random()
    assert Seeder(1).stream("x").random() != Seeder(2).stream("x").random()
