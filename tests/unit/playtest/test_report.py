from tta.playtest.report import Commentary, PlaytestReport, TurnRecord


def test_playtest_report_to_dict_includes_genesis_fields() -> None:
    report = PlaytestReport(
        run_id="run-1",
        run_seed=7,
        scenario_seed_id="seed-1",
        persona_id="persona-1",
        persona_jitter_seed=3,
        model="test-model",
        status="complete",
        genesis_phases_completed=7,
        gameplay_turns_completed=1,
        turns=[
            TurnRecord(
                turn_index=0,
                phase="gameplay",
                player_input="look",
                narrative="You look around.",
                commentary=Commentary(
                    turn_index=0,
                    agent_intent="inspect",
                    surprise_level=0.2,
                    surprise_note="steady",
                    coherence_rating=0.9,
                    coherence_note="consistent",
                ),
            )
        ],
        genesis_character_name="Arika",
        genesis_traits=["curious", "brave"],
    )

    payload = report.to_dict()

    assert payload["genesis_character_name"] == "Arika"
    assert payload["genesis_traits"] == ["curious", "brave"]
    assert payload["turns"][0]["commentary"]["agent_intent"] == "inspect"
