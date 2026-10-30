from __future__ import annotations

import pytest

from src.personality import (
    PERSONALITIES,
    UnknownPersonalityError,
    find_personality,
    get_personality,
    next_personality,
    personality_slugs,
)


def test_all_four_presences_exist():
    assert set(PERSONALITIES) == {"phantom", "wraith", "oracle", "nightmare"}
    assert personality_slugs() == ["phantom", "wraith", "oracle", "nightmare"]


def test_each_presence_has_distinct_material():
    prompts = set()
    greetings = set()
    farewells = set()
    for personality in PERSONALITIES.values():
        assert personality.name
        assert personality.epithet
        assert personality.description
        assert personality.system_prompt.strip()
        assert personality.greeting.strip()
        assert personality.farewell.strip()
        assert personality.glyph
        prompts.add(personality.system_prompt)
        greetings.add(personality.greeting)
        farewells.add(personality.farewell)

    assert len(prompts) == 4
    assert len(greetings) == 4
    assert len(farewells) == 4


def test_get_personality_is_case_insensitive():
    assert get_personality("WRAITH").slug == "wraith"
    assert get_personality("  Oracle ").slug == "oracle"


def test_get_personality_raises_for_unknown():
    with pytest.raises(UnknownPersonalityError):
        get_personality("ghost")


def test_find_personality_returns_none_for_unknown():
    assert find_personality("ghost") is None
    assert find_personality("phantom").slug == "phantom"


def test_next_personality_cycles_stably():
    assert next_personality("phantom").slug == "wraith"
    assert next_personality("wraith").slug == "oracle"
    assert next_personality("oracle").slug == "nightmare"
    assert next_personality("nightmare").slug == "phantom"
    assert next_personality("unknown").slug == "phantom"
