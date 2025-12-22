# src/logic/high_scores.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class HighScoreStore:
    """
    Simple rhythm game high score storage:
      - Stores the highest scores for easy / medium / hard in a JSON file
      - Score type: integer
    """

    def __init__(self, path: str = "high_scores.json") -> None:
        self._path = Path(path)
        # Default to 0 points (you can also change to None to represent "not played yet")
        self._scores: Dict[str, int] = {
            "easy": 0,
            "medium": 0,
            "hard": 0,
        }
        self._load()

    # ----------------------------------------------------------
    # internal: load / save
    # ----------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            if isinstance(data, dict):
                for k in self._scores.keys():
                    if k in data and isinstance(data[k], int):
                        self._scores[k] = data[k]
        except Exception:
            # Ignore if the file is corrupted
            pass

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._scores))
        except Exception:
            # Ignore save failure, don't crash the game
            pass

    # ----------------------------------------------------------
    # public API
    # ----------------------------------------------------------

    def get_best(self, difficulty: str) -> int:
        """
        Get the current high score for the given difficulty (returns 0 if not found).
        """
        return self._scores.get(difficulty, 0)

    def update_if_better(self, difficulty: str, new_score: int) -> bool:
        """
        If new_score >= old record, update and return True (means new record).
        Otherwise, return False.
        """
        old = self._scores.get(difficulty, 0)
        if new_score >= old:
            self._scores[difficulty] = int(new_score)
            self._save()
            return True
        return False
