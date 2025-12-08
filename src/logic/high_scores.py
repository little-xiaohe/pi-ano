# src/logic/high_scores.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class HighScoreStore:
    """
    簡單的節奏遊戲最高分儲存：
      - 以 JSON 檔紀錄 easy / medium / hard 的最高分
      - 分數型態：整數
    """

    def __init__(self, path: str = "high_scores.json") -> None:
        self._path = Path(path)
        # 預設 0 分（你也可以改成 None 代表「尚未遊玩」）
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
            # 檔案壞掉就忽略
            pass

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._scores))
        except Exception:
            # 儲存失敗就算了，不要讓遊戲掛掉
            pass

    # ----------------------------------------------------------
    # public API
    # ----------------------------------------------------------

    def get_best(self, difficulty: str) -> int:
        """
        取得該難度目前最高分（拿不到就回傳 0）。
        """
        return self._scores.get(difficulty, 0)

    def update_if_better(self, difficulty: str, new_score: int) -> bool:
        """
        如果 new_score >= 舊紀錄，就更新並回傳 True（代表新紀錄）。
        否則回傳 False。
        """
        old = self._scores.get(difficulty, 0)
        if new_score >= old:
            self._scores[difficulty] = int(new_score)
            self._save()
            return True
        return False
