"""Tests de helpers puros del sistema XP/niveles."""
import tools


# _calculate_xp(item_type, outcome, streak_after=0) -> (xp_amount, streak_bonus)

def test_calculate_xp_task_on_time():
    xp, bonus = tools._calculate_xp("task", "on_time")
    assert xp == 10
    assert bonus == 0


def test_calculate_xp_task_grace():
    xp, bonus = tools._calculate_xp("task", "grace")
    assert xp == 5
    assert bonus == 0


def test_calculate_xp_event_on_time():
    xp, bonus = tools._calculate_xp("event", "on_time")
    assert xp == 10
    assert bonus == 0


def test_calculate_xp_event_grace():
    xp, bonus = tools._calculate_xp("event", "grace")
    assert xp == 5
    assert bonus == 0


def test_calculate_xp_routine_on_time_no_streak():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=0)
    assert xp == 5
    assert bonus == 0


def test_calculate_xp_routine_on_time_streak_one():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=1)
    assert xp == 6
    assert bonus == 1


def test_calculate_xp_routine_on_time_streak_seven():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=7)
    assert xp == 12
    assert bonus == 7


def test_calculate_xp_routine_on_time_streak_capped():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=14)
    assert xp == 12
    assert bonus == 7


def test_calculate_xp_routine_grace_with_streak():
    xp, bonus = tools._calculate_xp("routine", "grace", streak_after=3)
    assert xp == 5
    assert bonus == 3


def test_calculate_xp_objective_on_time():
    xp, bonus = tools._calculate_xp("objective", "on_time")
    assert xp == 50
    assert bonus == 0


def test_calculate_xp_objective_grace():
    xp, bonus = tools._calculate_xp("objective", "grace")
    assert xp == 25
    assert bonus == 0


# compute_level(xp_total) -> int

def test_compute_level_zero():
    assert tools.compute_level(0) == 0


def test_compute_level_below_first():
    assert tools.compute_level(29) == 0


def test_compute_level_exactly_first():
    assert tools.compute_level(30) == 1


def test_compute_level_just_below_second():
    assert tools.compute_level(79) == 1


def test_compute_level_exactly_second():
    assert tools.compute_level(80) == 2


def test_compute_level_ten():
    assert tools.compute_level(1200) == 10


def test_compute_level_below_ten():
    # nivel 10 = 1200; nivel 9 = 990
    assert tools.compute_level(1199) == 9


# medal_for_level(level) -> str

def test_medal_level_zero_no_medal():
    assert tools.medal_for_level(0) == ""


def test_medal_bronze():
    for lv in (1, 3, 5):
        assert tools.medal_for_level(lv) == "🥉"


def test_medal_silver():
    for lv in (6, 10, 15):
        assert tools.medal_for_level(lv) == "🥈"


def test_medal_gold():
    for lv in (16, 25, 30):
        assert tools.medal_for_level(lv) == "🥇"


def test_medal_diamond():
    for lv in (31, 50, 60):
        assert tools.medal_for_level(lv) == "💎"


def test_medal_crown():
    for lv in (61, 100, 999):
        assert tools.medal_for_level(lv) == "👑"
