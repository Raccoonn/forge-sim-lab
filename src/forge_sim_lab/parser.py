from __future__ import annotations

import re

_WINNER_PATTERNS = [
    re.compile(r"winner\s*[:=]\s*(.+)", re.IGNORECASE),
    re.compile(r"won(?: the game| the match)?\s*[:=]?\s*(.+)", re.IGNORECASE),
    re.compile(r"(.+?)\s+wins\b", re.IGNORECASE),
    re.compile(r"(.+?)\s+won\b", re.IGNORECASE),
]


def parse_winners(stdout: str) -> list[str]:
    winners: list[str] = []
    seen: set[str] = set()

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        for pattern in _WINNER_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue

            winner = match.group(1).strip(" -:\t")
            key = winner.lower()
            if winner and key not in seen:
                winners.append(winner)
                seen.add(key)
            break

    return winners
