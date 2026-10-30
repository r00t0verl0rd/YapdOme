"""Shared active-turn policy assembly for all LLM provider adapters."""
import json

from .conversation import (
    character_style, conversational_direction, dialogue_pace, language_instruction,
    live_requested_voice, science_phase, science_protocol,
    social_focus_instructions, turn_protocol,
)


def build_turn_policy(agent, agent_name, peers, topic, turns, history, mode="live",
                      social_focus=None, planned=False, language="ru", donation=False):
    pace = dialogue_pace(turns, history)
    focus_data = {"social_focus": social_focus} if isinstance(social_focus, dict) else {}
    parts = [
        character_style(mode, topic),
        live_requested_voice(topic) if mode == "live" else "",
        social_focus_instructions(focus_data, agent, peers, mode) if not donation else "",
        science_protocol(science_phase(turns), agent) if mode == "science" else "",
        turn_protocol(agent_name, peers, pace, mode == "science"),
        conversational_direction(topic, turns, history, pace, planned=planned, mode=mode),
        "Ты " + json.dumps(agent_name, ensure_ascii=False) +
        ". Собеседники: " + json.dumps(peers, ensure_ascii=False) + ". ",
        language_instruction(language),
    ]
    return "\\n".join(part.strip() for part in parts if part and part.strip())
