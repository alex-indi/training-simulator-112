from app.modules.scenario_library.variants import (
    SCHOOL_FIRE_CODE,
    SCHOOL_FIRE_OPTIONS,
    render_variant_text,
    variant_facts,
)


def test_template_choices_override_seed_defaults_and_are_repeatable():
    options = {"floor": [2, 4], "room": ["кабинет", "коридор"]}
    first = variant_facts(SCHOOL_FIRE_CODE, 42, options)
    assert first == variant_facts(SCHOOL_FIRE_CODE, 42, options)
    assert set(first) == set(options)
    assert first["floor"] in options["floor"]
    assert first["room"] in options["room"]
    assert set(variant_facts(SCHOOL_FIRE_CODE, 42)) == set(SCHOOL_FIRE_OPTIONS)
    assert render_variant_text("дым на {floor} этаже, {room}", first) == (
        f"дым на {first['floor']} этаже, {first['room']}"
    )
