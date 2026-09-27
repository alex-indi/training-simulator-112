"""Целостность версионированного демонстрационного набора."""

from app.scripts.seed_demo import load_rows
from app.scripts.seed_demo_content import load_content
from app.scripts.seed_demo_history import load_sessions
from seed.scenario_templates.import_seed import load_seed


def test_demo_content_references_are_complete() -> None:
    users = {row["username"]: row for row in load_rows("users.json", "username")}
    groups = load_rows("user_groups.json", "code")
    templates = {row["seed_code"]: row for row in load_seed()}
    cards = {row["seed_code"]: row for row in load_content("cards.json")}
    packages = load_content("card_packages.json")
    sessions = load_sessions()

    assert len(groups) == 2
    assert len(templates) >= 4
    assert len(cards) == 8
    assert len(packages) == 2
    assert len(sessions) == 2
    for group in groups:
        assert group["members"]
        assert all(users[name]["role"] == "TRAINEE" for name in group["members"])
    for card in cards.values():
        assert card["template"] in templates
        assert card["seed"] >= 0
        assert card["object_index"] >= 0
        assert len(card["narrative"]) > 60
    for package in packages:
        assert package["cards"]
        assert len(package["cards"]) == len(set(package["cards"]))
        assert all(code in cards for code in package["cards"])
    for session in sessions:
        group = next(row for row in groups if row["code"] == session["group_code"])
        assert len(session["cases"]) >= 4
        for case in session["cases"]:
            assert case["card"] in cards
            assert case["trainee"] in group["members"]
            assert case["outcome"] in {"COMPLETED", "UNFINISHED"}
            assert case["decision_delay"] > 0
            assert len(case["stage_delays"]) == 4
            assert all(delay >= 0 for delay in case["stage_delays"])
            if case["outcome"] == "UNFINISHED":
                assert case["stage_delays"][-1] == 0
