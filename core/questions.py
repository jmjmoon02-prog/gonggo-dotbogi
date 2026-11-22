"""구인자에게 보낼 확인 질문 만들기.

규칙 엔진이 고른 질문(걸린 신호별 질문 → 일반 질문)을 우선순위대로 자르고, 그대로 복사해 보낼 수 있는
메시지 형태로 만든다. 질문 문구는 rules.yaml 의 check_question(레드플래그 유도형)에서 온다.
"""
from __future__ import annotations

from .rules_engine import Verdict

DEFAULT_MAX_QUESTIONS = 6


def select_questions(verdict: Verdict, max_n: int = DEFAULT_MAX_QUESTIONS) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in verdict.check_questions:
        text = (q.get("question") or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= max_n:
            break
    return out


def compose_message(questions: list[str]) -> str:
    """구인자에게 그대로 보낼 수 있는 문장. 개인정보는 넣지 않는다."""
    if not questions:
        return ""
    lines = ["안녕하세요. 공고를 보고 연락드립니다.", "지원하기 전에 몇 가지 확인하고 싶습니다.", ""]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    lines += ["", "답변 주시면 검토 후 지원 여부를 말씀드리겠습니다."]
    return "\n".join(lines)


def stop_advice(verdict: Verdict) -> str | None:
    """🔴 일 때는 질문보다 중단을 먼저 안내한다."""
    if verdict.grade != "red":
        return None
    return ("결정적 위험 신호가 있습니다. 지원·연락을 멈추고, 이미 돈·개인정보·통장을 넘겼다면 "
            "아래 신고처에 바로 연락하세요.")
