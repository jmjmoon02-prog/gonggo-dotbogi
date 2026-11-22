"""AI 호출 상한 (공개 URL 이라 누구나 호출할 수 있으므로 비용 보호).

- 세션 상한: 브라우저 세션(화면) 하나당 호출 수. Streamlit session_state 에 센다.
- 일일 상한: 앱 프로세스 전체 공용, 한국 시간 자정에 초기화. 앱이 재시작되면 0부터 다시 센다(메모리 보관).
  OpenAI 쪽 월 지출 하드 리밋(프로젝트 설정)이 최종 안전장치다.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import MutableMapping

KST = timezone(timedelta(hours=9))
SESSION_KEY = "_ai_calls"


class DailyCounter:
    def __init__(self, limit: int):
        self.limit = limit
        self._lock = threading.Lock()
        self._day: str | None = None
        self._count = 0

    def _roll(self, now: datetime | None = None) -> None:
        day = (now or datetime.now(KST)).strftime("%Y-%m-%d")
        if day != self._day:
            self._day, self._count = day, 0

    def try_acquire(self, now: datetime | None = None) -> bool:
        with self._lock:
            self._roll(now)
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    def remaining(self, now: datetime | None = None) -> int:
        with self._lock:
            self._roll(now)
            return max(self.limit - self._count, 0)


def session_remaining(state: MutableMapping, limit: int) -> int:
    return max(limit - int(state.get(SESSION_KEY, 0)), 0)


def try_consume(state: MutableMapping, session_limit: int, daily: DailyCounter) -> tuple[bool, str | None]:
    """호출 1회를 쓸 수 있으면 (True, None), 아니면 (False, 안내 문구)."""
    if session_remaining(state, session_limit) <= 0:
        return False, f"이 화면에서 AI 판정은 {session_limit}회까지 가능합니다. 새로고침 후 다시 이용해 주세요."
    if not daily.try_acquire():
        return False, "오늘 준비된 AI 판정 횟수를 모두 사용했습니다. 내일 다시 이용하거나 데모 샘플 설명을 참고해 주세요."
    state[SESSION_KEY] = int(state.get(SESSION_KEY, 0)) + 1
    return True, None
