from __future__ import annotations

import json

from .pipeline import build_state_packet_from_sessions, validate_state_packet


def demo() -> dict:
    sessions = [
        {
            "session_id": "s1",
            "date": "2023/05/20 (Sat) 09:00",
            "turns": [
                {
                    "role": "user",
                    "content": "I usually drink coffee in the morning. I like strong coffee before work.",
                }
            ],
        },
        {
            "session_id": "s2",
            "date": "2023/05/28 (Sun) 10:00",
            "turns": [
                {
                    "role": "user",
                    "content": "Actually, I no longer drink coffee. I switched to green tea in the morning now.",
                }
            ],
        },
    ]
    packet = build_state_packet_from_sessions(
        sessions=sessions,
        question="What drink do I currently prefer in the morning?",
        question_type="knowledge-update",
        question_date="2023/05/30 (Tue) 10:00",
    )
    validate_state_packet(packet)
    return packet


if __name__ == "__main__":
    print(json.dumps(demo(), ensure_ascii=False, indent=2))

