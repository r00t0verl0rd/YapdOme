"""Shared active-turn policy assembly for all LLM provider adapters."""
import json

from .conversation import (
    character_profile_instruction, character_style, conversational_direction,
    dialogue_pace, language_instruction, live_requested_voice, science_phase, science_protocol,
    social_focus_instructions, turn_protocol,
)


def build_turn_policy(agent, agent_name, peers, topic, turns, history, mode="live",
                      social_focus=None, planned=False, language="ru", donation=False,
                      persistent_context=False, persona_description=""):
    """Build either a complete HTTP policy or only deltas for a persistent session."""
    pace = dialogue_pace(turns, history)
    focus_data = {"social_focus": social_focus} if isinstance(social_focus, dict) else {}
    dynamic = [
        social_focus_instructions(focus_data, agent, peers, mode) if not donation else "",
        science_protocol(science_phase(turns), agent) if mode == "science" else "",
        character_profile_instruction(agent_name, persona_description),
        live_requested_voice(topic) if mode == "live" else "",
        conversational_direction(topic, turns, history, pace, planned=planned, mode=mode),
        language_instruction(language),
    ]
    if persistent_context:
        # Codex already has the stable policy, cast and transcript in its thread.
        # Send only this turn's changes; never repeat the full rules on every turn.
        parts = dynamic
    else:
        parts = [
            character_style(mode, topic),
            *dynamic[:2],
            turn_protocol(agent_name, peers, pace, mode == "science"),
            *dynamic[2:5],
            "Ты " + json.dumps(agent_name, ensure_ascii=False) +
            ". Собеседники: " + json.dumps(peers, ensure_ascii=False) + ". ",
            dynamic[5],
        ]
    return "\n".join(part.strip() for part in parts if part and part.strip())
