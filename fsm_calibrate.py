"""
FSM(unit) <-> PSD(mm) 2x2 Jacobian 실측

기존 코드의
    scale_factor = 0.1
    y_adjust = -y_pid.output      # 부호 감으로 뒤집기
를 대체한다. FSM 축과 PSD 축 사이에는 광학 배치에 따라 회전/반전이 섞이므로
대각 성분만 맞춰서는 축간 커플링 때문에 루프가 발산한다.

절차
  0. FSM 중앙 -> PSD 기준점 측정
  1. 가진 크기(DELTA) 자동 결정  <- 아래 "자동 레인징" 참고
  2. ux 를 +-DELTA 만큼 흔들고 PSD 변위 측정 -> J 의 1열
  3. uy 를 +-DELTA 만큼 흔들고 PSD 변위 측정 -> J 의 2열
  4. fsm_calib.json 저장 + 검증 스텝

자동 레인징
-----------
unit 1 이 몇 mrad 인지는 장착된 미러 헤드에 따라 크게 다르고, 우리는 그 값을
아직 확정하지 못했다. 고정 DELTA 를 쓰면
  - 너무 크면  : 빔이 PSD(+-5mm) 밖으로 나가 측정 자체가 불가능
  - 너무 작으면: 변위가 PSD 노이즈에 묻혀 J 가 엉망이 된다
그래서 작은 값에서 시작해 PSD 변위가 TARGET_MM 근처가 되도록 DELTA 를 스스로
맞춘다. 강제로 지정하고 싶으면 DELTA 에 숫자를 넣으면 된다.

실행 전 조건: FSM 중앙(u=0)에서 빔이 이미 PSD 위에 들어와 있어야 한다.
"""

import json
import time

import numpy as np

from fsm_optotune import CALIB_FILE, OptotuneFSM
from psd_conex import PSD

# 포트는 psd_conex.DEFAULT_PORT / fsm_optotune.DEFAULT_PORT 한 곳에서만 고친다.

DELTA = None             # None = 자동 레인징. 숫자를 넣으면 그 값으로 고정.
DELTA_START = 0.002      # 자동 레인징 시작값 (unit). 안전하게 작은 쪽에서 시작.
DELTA_MIN = 1e-5
DELTA_MAX = 0.5
TARGET_MM = 2.5          # 가진했을 때 목표로 하는 PSD 변위 (PSD 범위의 절반)
AUTORANGE_TRIES = 12

SETTLE = 0.15            # 스텝 후 정정 대기 (s)
N_AVG = 30               # 평균 샘플 수
PSD_LIMIT = 5.0          # PSD 유효 범위 (mm)
NOISE_FLOOR_MM = 0.01    # 이보다 작은 변위는 "응답 없음"으로 본다

# 축 독립성 판정. fsm_jog.py 와 같은 기준을 쓴다 (스케일 무관).
AXIS_SIN_MIN = 0.10      # |det|/(|c0||c1|) = 두 축 사이 각의 sin
AXIS_SIN_WARN = 0.30


class BeamOutOfRange(RuntimeError):
    """가진했더니 빔이 PSD 밖으로 나갔다. DELTA 를 줄여야 한다."""


def measure(psd, fsm, ux, uy):
    fsm.set_units(ux, uy)
    time.sleep(SETTLE)
    x, y, p = psd.read_avg(N_AVG)
    if x is None:
        raise RuntimeError("PSD 읽기 실패")
    if abs(x) > PSD_LIMIT or abs(y) > PSD_LIMIT:
        raise BeamOutOfRange(
            f"빔이 PSD 범위를 벗어남 ({x:.3f}, {y:.3f}) mm @ u=({ux:.4f}, {uy:.4f})")
    return np.array([x, y]), p


def autorange(psd, fsm, base):
    """
    PSD 변위가 TARGET_MM 근처가 되는 가진 크기(unit)를 찾는다.
    두 채널 중 감도가 큰 쪽을 기준으로 잡는다 (그쪽이 먼저 범위를 벗어나므로).
    """
    d = DELTA_START
    print(f"\n자동 레인징 (목표 변위 {TARGET_MM:.1f} mm, 시작 {d:.5f} unit)")

    for attempt in range(1, AUTORANGE_TRIES + 1):
        try:
            px, _ = measure(psd, fsm, +d, 0.0)
            py, _ = measure(psd, fsm, 0.0, +d)
        except BeamOutOfRange as e:
            print(f"  [{attempt}] d={d:.5f} -> 범위 밖. 축소. ({e})")
            d = max(d * 0.3, DELTA_MIN)
            if d <= DELTA_MIN:
                raise RuntimeError(
                    "DELTA_MIN 까지 줄여도 빔이 PSD 밖으로 나간다. "
                    "FSM 중앙에서의 초기 정렬을 다시 확인할 것.")
            continue

        r = max(np.linalg.norm(px - base), np.linalg.norm(py - base))
        print(f"  [{attempt}] d={d:.5f} -> 최대 변위 {r:.3f} mm")

        if r < NOISE_FLOOR_MM:
            # 응답이 노이즈에 묻힘. 크게 키운다.
            d = min(d * 10.0, DELTA_MAX)
            if d >= DELTA_MAX:
                raise RuntimeError(
                    "DELTA_MAX 까지 키워도 PSD 변위가 없다. FSM 이 실제로 움직이는지, "
                    "채널 배선과 광 경로를 확인할 것.")
            continue

        scale = TARGET_MM / r
        if 0.6 <= scale <= 1.6:
            print(f"  확정: DELTA = {d:.5f} unit  (변위 {r:.3f} mm)")
            return d

        d = float(np.clip(d * scale, DELTA_MIN, DELTA_MAX))

    print(f"  수렴 실패. 마지막 값 {d:.5f} 로 진행한다.")
    return d


def main():
    print("=" * 70)
    print("  FSM <-> PSD Jacobian Calibration")
    print("=" * 70)

    psd = PSD().open()
    fsm = OptotuneFSM().connect()

    try:
        # 0. 중앙 기준점
        p0, pwr = measure(psd, fsm, 0.0, 0.0)
        print(f"\ncenter: PSD = ({p0[0]:.4f}, {p0[1]:.4f}) mm, power = {pwr:.2f}")
        if pwr < 1.0:
            print("경고: 광량이 너무 낮다. 빔 정렬 먼저 확인할 것.")

        # 1. 가진 크기 결정
        delta = DELTA if DELTA is not None else autorange(psd, fsm, p0)

        # 2. X 채널 가진 (중앙차분 -> 오프셋/드리프트 상쇄)
        px_p, _ = measure(psd, fsm, +delta, 0.0)
        px_m, _ = measure(psd, fsm, -delta, 0.0)
        col_x = (px_p - px_m) / (2.0 * delta)      # [mm / unit]

        # 3. Y 채널 가진
        py_p, _ = measure(psd, fsm, 0.0, +delta)
        py_m, _ = measure(psd, fsm, 0.0, -delta)
        col_y = (py_p - py_m) / (2.0 * delta)

        J = np.column_stack([col_x, col_y])        # [dx_mm, dy_mm] = J @ [du_x, du_y]

        print("\nJ [mm per unit] =")
        print(J)

        det = np.linalg.det(J)
        cond = np.linalg.cond(J)
        # 축 독립성은 |det|/(|c0||c1|) = 두 축 사이 각의 sin 으로 본다.
        # det 자체에 절대 임계값을 걸면 안 된다 -- det 는 (mm/unit)^2 스케일이라
        # 미러 헤드와 L 에 따라 자릿수가 통째로 달라진다.
        sin_ax = abs(det) / max(np.linalg.norm(J[:, 0]) * np.linalg.norm(J[:, 1]), 1e-12)
        print(f"\ndet(J)     = {det:.6g}")
        print(f"cond(J)    = {cond:.2f}")
        print(f"축 독립성   = {sin_ax:.3f} "
              f"({np.degrees(np.arcsin(min(sin_ax, 1.0))):.1f}deg)")

        if sin_ax < AXIS_SIN_MIN:
            print("\n실패: J 가 특이행렬에 가깝다. 두 축이 PSD 상에서 거의 같은 방향으로 "
                  "움직인다는 뜻이다. 광학 배치 또는 채널 배선을 확인할 것.")
            return
        if sin_ax < AXIS_SIN_WARN:
            print("\n경고: 축간 커플링이 심하다. 제어는 되지만 게인 튜닝이 까다로워진다.")

        # 축 회전각 (참고용)
        angle = np.degrees(np.arctan2(J[1, 0], J[0, 0]))
        print(f"\nFSM x축 -> PSD 상 방향: {angle:.2f}° "
              f"(0°=PSD +X, 90°=PSD +Y)")

        # 기하 환산 참고값: 4m 기준 unit 당 빔 편향각
        L_mm = 4000.0
        print(f"unit 당 빔 편향각 (L=4m 가정): "
              f"({J[0, 0]/L_mm*1e3:.3f}, {J[1, 1]/L_mm*1e3:.3f}) mrad/unit")

        # 4. 저장
        with open(CALIB_FILE, "w") as f:
            json.dump({
                "J_mm_per_unit": J.tolist(),
                "delta_unit": delta,
                "psd_port": psd.port,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, indent=2)
        print(f"\n저장됨: {CALIB_FILE}")

        # 5. 검증: J^-1 로 계산한 지령이 실제로 목표 변위를 만드는지
        print("\n--- 검증 ---")
        fsm.J = J
        fsm.Jinv = np.linalg.inv(J)
        fsm.center()
        time.sleep(SETTLE)
        base, _ = measure(psd, fsm, 0.0, 0.0)

        for target in ([0.5, 0.0], [0.0, 0.5], [0.3, -0.3]):
            du = fsm.mm_to_unit(*target)
            got, _ = measure(psd, fsm, du[0], du[1])
            moved = got - base
            err = np.linalg.norm(moved - np.array(target))
            print(f"  목표 ({target[0]:+.2f}, {target[1]:+.2f}) mm  ->  "
                  f"실측 ({moved[0]:+.3f}, {moved[1]:+.3f}) mm   오차 {err:.3f} mm")

        fsm.center()
        print("\n완료. 오차가 목표의 10% 이내면 정상이다.")

    finally:
        fsm.close()
        psd.close()


if __name__ == "__main__":
    main()
