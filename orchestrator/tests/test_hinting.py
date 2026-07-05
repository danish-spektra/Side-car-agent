from app.hinting import HINT_INSTRUCTIONS, bump, get_hint_level, hint_block, task_ref
from app.storage import LocalStorage

def test_task_ref_extraction():
    assert task_ref("I'm stuck on Task 2") == "task2"
    assert task_ref("exercise 2 task 3 help") == "ex2-task3"
    assert task_ref("Ex. 4, Task 1") == "ex4-task1"
    assert task_ref("EX2 is confusing") == "ex2"
    assert task_ref("where is the storage account?") == "general"
    assert task_ref("my index 2 is broken") == "general"  # 'ex' inside a word

def test_counter_persists_across_calls(tmp_path):
    s = LocalStorage(str(tmp_path))
    assert get_hint_level(s, "ev", "dep", "task2") == 0
    bump(s, "ev", "dep", "task2")
    assert get_hint_level(s, "ev", "dep", "task2") == 1
    assert get_hint_level(s, "ev", "dep", "general") == 0     # per-task isolation
    assert get_hint_level(s, "ev", "other", "task2") == 0     # per-learner isolation
    s2 = LocalStorage(str(tmp_path))                          # fresh instance = disk read
    assert get_hint_level(s2, "ev", "dep", "task2") == 1

def test_level_caps_at_3(tmp_path):
    s = LocalStorage(str(tmp_path))
    for _ in range(6):
        bump(s, "ev", "dep", "task1")
    assert get_hint_level(s, "ev", "dep", "task1") == 3

def test_hint_block_selects_tier():
    assert hint_block(0) == HINT_INSTRUCTIONS[0]
    assert hint_block(1) == HINT_INSTRUCTIONS[1]
    assert hint_block(2) == HINT_INSTRUCTIONS[2]
    assert hint_block(3) == HINT_INSTRUCTIONS[2]  # 2+ uses the top tier
