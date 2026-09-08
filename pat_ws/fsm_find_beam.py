"""
자동 빔 탐색 — FSM을 스캔하여 PSD 파워가 최대인 위치를 찾는다.

결과는 beam_position.json에 저장되며, fsm_calibrate.py가 자동으로 읽어간다.

    python fsm_find_beam.py              # 기본 그리드 (0.05 간격)
    python fsm_find_beam.py --fine       # 정밀 그리드 (0.01 간격, 느림)
    python fsm_find_beam.py --range 0.3  # 탐색 범위 ±0.3
"""

import json
import sys
import time
import numpy as np
from psd_conex import PSD
from fsm_optotune import OptotuneFSM

# Windows 터미널 UTF-8 인코딩 설정
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 기본 탐색 파라미터
DEFAULT_RANGE = 0.2      # ±0.2 범위 스캔
DEFAULT_STEP = 0.05      # 0.05 간격
FINE_STEP = 0.01         # --fine 옵션 시 간격
MIN_POWER = 1.0          # 유효 빔으로 간주할 최소 파워
RESULT_FILE = "beam_position.json"


def scan_grid(psd, fsm, u_range, step):
    """
    그리드 서치로 최대 파워 위치를 찾는다.

    Returns:
        (ux_best, uy_best, power_best, psd_x, psd_y) or None
    """
    u_vals = np.arange(-u_range, u_range + step/2, step)
    total = len(u_vals) ** 2
    print(f"\n탐색 범위: ±{u_range}, 간격: {step}")
    print(f"총 {total}개 위치 스캔 시작...\n")

    best = None
    count = 0

    for uy in u_vals:
        for ux in u_vals:
            count += 1
            fsm.set_units(ux, uy)
            time.sleep(0.05)  # FSM 안정화 대기

            x, y, pwr = psd.read()
            if x is None:
                pwr = 0.0

            # 진행률 표시 (10%마다)
            if count % max(1, total // 10) == 0:
                progress = count / total * 100
                print(f"  {progress:5.1f}% | 현재 최대: {best[2] if best else 0:.2f}")

            # 최댓값 갱신
            if pwr > MIN_POWER and (best is None or pwr > best[2]):
                best = (ux, uy, pwr, x, y)
                print(f"    → 신기록: u=({ux:+.5f}, {uy:+.5f}), "
                      f"PSD=({x:+.3f}, {y:+.3f})mm, power={pwr:.2f}")

    return best


def save_result(ux, uy, power, psd_x, psd_y):
    """결과를 JSON 파일로 저장"""
    result = {
        "fsm_u": [float(ux), float(uy)],
        "psd_mm": [float(psd_x), float(psd_y)],
        "power": float(power),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n결과 저장: {RESULT_FILE}")


def main():
    # 명령행 인자 파싱
    fine = "--fine" in sys.argv
    step = FINE_STEP if fine else DEFAULT_STEP

    u_range = DEFAULT_RANGE
    for i, arg in enumerate(sys.argv):
        if arg == "--range" and i + 1 < len(sys.argv):
            u_range = float(sys.argv[i + 1])

    print("=" * 68)
    print("  자동 빔 탐색")
    print("=" * 68)

    # 장비 연결
    print("\n장비 연결 중...")
    psd = PSD().open()
    fsm = OptotuneFSM().connect()
    print("  PSD: OK")
    print("  FSM: OK")

    try:
        # 그리드 스캔
        result = scan_grid(psd, fsm, u_range, step)

        if result is None:
            print(f"\n빔을 찾지 못했습니다 (파워 >= {MIN_POWER} 인 위치 없음)")
            print("  1) 광학계 정렬 확인")
            print("  2) 탐색 범위 확대: python fsm_find_beam.py --range 0.3")
            return 1

        ux, uy, pwr, px, py = result

        # FSM을 최적 위치로 이동
        fsm.set_units(ux, uy)
        time.sleep(0.1)

        # 결과 출력
        print("\n" + "=" * 68)
        print("  최적 빔 위치 발견!")
        print("=" * 68)
        print(f"\n  FSM u = ({ux:+.5f}, {uy:+.5f})")
        print(f"  PSD   = ({px:+.3f}, {py:+.3f}) mm")
        print(f"  Power = {pwr:.2f}")

        # 파일 저장
        save_result(ux, uy, pwr, px, py)

        print("\n다음 단계:")
        print("  python fsm_calibrate.py")
        print("  (자동으로 이 위치를 CENTER_OFFSET으로 사용합니다)")

        return 0

    finally:
        # FSM 원점 복귀
        fsm.set_units(0, 0)
        fsm.close()
        psd.close()


if __name__ == "__main__":
    sys.exit(main())
