"""데모용 가상 캡처 이미지 만들기 (한 번만 실행, 결과 PNG 를 data/samples/ 에 둔다).

- 내용은 지어낸 팀미션 사기 문구(테스트셋 G1 유형). 실제 개인정보·실존 업체·특정 메신저 화면 모양 없음.
- 글꼴: Noto Sans KR (SIL Open Font License 1.1). 글꼴 파일은 저장소에 넣지 않고, 렌더링한 이미지만 둔다.
실행: python scripts/make_demo_image.py [글꼴 경로]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "data" / "samples" / "demo_image_team_mission.png"
FONT = sys.argv[1] if len(sys.argv) > 1 else "C:/Windows/Fonts/NotoSansKR-Regular.ttf"

LINES = [
    "[재택 부업 안내] 가상 데모 이미지",
    "",
    "쇼핑몰 상품 리뷰 미션, 1건당 3,000원!",
    "첫 미션은 무료 체험으로 바로 정산해 드려요.",
    "2단계부터는 미션 금액을 먼저 입금하고 진행합니다.",
    "(입금액 + 수익 20% 당일 환급)",
    "",
    "문의: 오픈채팅방 '부업미션방'으로 들어오세요",
]


def main() -> None:
    font = ImageFont.truetype(FONT, 30)
    title = ImageFont.truetype(FONT, 34)
    w, line_h, pad = 900, 50, 40
    h = pad * 2 + line_h * len(LINES)
    img = Image.new("RGB", (w, h), (250, 250, 247))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 12, w - 12, h - 12], radius=24, outline=(200, 200, 200), width=3, fill=(255, 255, 255))
    y = pad
    for i, line in enumerate(LINES):
        d.text((pad + 10, y), line, font=title if i == 0 else font, fill=(30, 30, 30))
        y += line_h
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"saved {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
