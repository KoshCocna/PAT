"""
FSM 조그 — 하드웨어 첫 확인용

캘리브레이션(fsm_calibrate.py)보다 먼저 돌린다. 목적은 딱 하나:

    "FSM 을 움직이면 PSD 스팟이 정말 따라 움직이는가"

이걸 눈으로 확인하지 않고 폐루프로 넘어가면, 안 될 때 원인이 배선인지
광 경로인지 PID 게인인지 구분이 안 된다.

배치 전제 (2026-09 확정)
    TX ──→ FSM ──→ BS ──┬──→ PSD   (이 스크립트가 보는 것)
                        └──→ PD    (이 단계에서는 무시)
FSM 이 BS 상류에 있으므로 FSM 을 움직이면 두 갈래가 같이 움직인다.
PSD 갈래만 봐도 조향이 되는지 판정할 수 있다.

조작 (그래프 창에 포커스를 둔 상태에서)
    ←  →        FSM x 채널 -/+
    ↑  ↓        FSM y 채널 +/-
    [  ]        스텝 크기 /2, ×2
    0           중앙 복귀 (u = 0, 0)
    m           현재 위치를 기준점으로 마킹
    q  또는 esc 종료

종료할 때, 조그하는 동안 모은 (u, PSD) 표본으로 J 를 최소자승 추정해서
출력한다. 이 값으로 fsm_calibrate.py 가 제대로 돌지 미리 알 수 있고,
감도(mm/unit)를 알면 오정렬 크기와 L 도 검산할 수 있다.

캘리브레이션 파일이 없어도 동작한다 (J 가 필요 없는 스크립트다).
"""

import sys
import time

import numpy as np
import matplotlib.pyplot as plt

from fsm_optotune import OptotuneFSM
from psd_conex import PSD

# ====== 설정 ======
PSD_PORT = "COM6"
FSM_PORT = None            # None = 자동 탐색

STEP_INIT = 0.001          # 초기 조그 스텝 (unit). 감도를 모르므로 작게 시작한다.
STEP_MIN = 1e-5
STEP_MAX = 0.2

PSD_LIMIT = 5.0            # PSD 유효 범위 (mm)
LASER_MAX = 100.0
REFRESH = 0.03             # 화면 갱신 주기 (s)

SETTLE_FRAMES = 3          # u 가 이만큼 연속으로 안 바뀌어야 표본으로 채택
TRAIL_LEN = 400            # 스팟 궤적 길이
FIT_TARGET_MM = 2.5        # 권장 DELTA 계산 시 목표 변위

# 판정 기준. 둘 다 스케일 무관한 양이어야 한다 -- mm/unit 감도는 미러 헤드와 L 에
# 따라 자릿수가 통째로 달라지므로, det 에 절대 임계값을 걸면 판정이 무의미해진다.
RESP_SNR_MIN = 10.0        # (예상 변위)/(잔차 RMS). 이보다 낮으면 "반응 없음"
AXIS_SIN_MIN = 0.10        # |det|/(|c0||c1|) = 두 축 사이 각의 sin. 낮으면 축이 겹침
AXIS_SIN_WARN = 0.30


class Jog:
    def __init__(self):
        self.psd = PSD(port=PSD_PORT)
        self.fsm = OptotuneFSM(port=FSM_PORT)

        self.ux = 0.0
        self.uy = 0.0
        self.step = STEP_INIT
        self.running = True

        self.stable = 0                 # u 가 안 바뀐 프레임 수
        self.samples = []               # (ux, uy, x_mm, y_mm)
        self.trail = []
        self.mark = None                # 기준점 (ux, uy, x_mm, y_mm)

    # ---------------- 하드웨어 ----------------

    def connect(self):
        self.psd.open()
        self.fsm.connect()
        # 이 스크립트는 J 가 필요 없다. 없다고 막지 않는다.
        if self.fsm.Jinv is None:
            print("[JOG] 캘리브레이션 없이 진행한다 (이 스크립트에는 필요 없다).")

    def cleanup(self):
        try:
            self.fsm.center()
        except Exception:
            pass
        self.fsm.close()
        self.psd.close()
        plt.ioff()
        plt.close("all")

    def apply(self):
        _, _, sat = self.fsm.set_units(self.ux, self.uy)
        self.ux, self.uy = self.fsm.get_units()     # 클램프된 값으로 되돌려 받는다
        self.stable = 0
        return sat

    # ---------------- 입력 ----------------

    def on_key(self, event):
        k = event.key
        if k in ("q", "escape"):
            self.running = False
        elif k == "left":
            self.ux -= self.step
            self.apply()
        elif k == "right":
            self.ux += self.step
            self.apply()
        elif k == "up":
            self.uy += self.step
            self.apply()
        elif k == "down":
            self.uy -= self.step
            self.apply()
        elif k == "[":
            self.step = max(self.step / 2.0, STEP_MIN)
        elif k == "]":
            self.step = min(self.step * 2.0, STEP_MAX)
        elif k == "0":
            self.ux = self.uy = 0.0
            self.apply()
        elif k == "m":
            if self.samples:
                self.mark = self.samples[-1]
                print(f"[JOG] 기준점 마킹: u=({self.mark[0]:+.5f}, {self.mark[1]:+.5f}) "
                      f"PSD=({self.mark[2]:+.3f}, {self.mark[3]:+.3f}) mm")

    def on_close(self, event):
        self.running = False

    # ---------------- 화면 ----------------

    def setup_gui(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(7, 7))
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.mpl_connect("close_event", self.on_close)

        self.ax.set_xlim(-PSD_LIMIT, PSD_LIMIT)
        self.ax.set_ylim(-PSD_LIMIT, PSD_LIMIT)
        self.ax.set_xlabel("PSD X (mm)")
        self.ax.set_ylabel("PSD Y (mm)")
        self.ax.set_title("FSM Jog — 화살표로 FSM 을 밀어보고 스팟이 따라오는지 본다")
        self.ax.grid(True, color="darkgray", alpha=0.5)
        self.ax.set_aspect("equal")
        self.ax.axhline(0, color="gray", lw=0.8)
        self.ax.axvline(0, color="gray", lw=0.8)

        (self.trail_line,) = self.ax.plot([], [], "-", color="tab:blue", lw=1, alpha=0.5)
        self.spot = self.ax.scatter([], [], c="red", s=120, zorder=5)
        self.mark_spot = self.ax.scatter([], [], c="tab:green", marker="+", s=200, zorder=4)

        self.hud = self.ax.text(
            0.02, 0.98, "", transform=self.ax.transAxes, va="top", ha="left",
            family="monospace", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    def update_gui(self, x, y, power, sat):
        if x is not None:
            self.spot.set_offsets([[x, y]])
            self.trail.append((x, y))
            if len(self.trail) > TRAIL_LEN:
                self.trail.pop(0)
            t = np.array(self.trail)
            self.trail_line.set_data(t[:, 0], t[:, 1])
        if self.mark is not None:
            self.mark_spot.set_offsets([[self.mark[2], self.mark[3]]])

        pos = f"({x:+.3f}, {y:+.3f}) mm" if x is not None else "읽기 실패"
        self.hud.set_text(
            f"FSM u  = ({self.ux:+.5f}, {self.uy:+.5f}){'  SAT' if sat else ''}\n"
            f"step   = {self.step:.5f} unit   ([ ] 로 조절)\n"
            f"PSD    = {pos}\n"
            f"power  = {power:.2f}\n"
            f"표본    = {len(self.samples)}"
        )
        plt.pause(REFRESH)

    # ---------------- 실행 ----------------

    def run(self):
        print("=" * 70)
        print("  FSM Jog  —  FSM 을 움직이면 PSD 가 따라오는지 확인")
        print("=" * 70)
        self.connect()
        self.setup_gui()

        print("\n그래프 창을 클릭해서 포커스를 준 뒤:")
        print("  ← →      FSM x 채널")
        print("  ↑ ↓      FSM y 채널")
        print("  [ ]      스텝 /2, ×2")
        print("  0        중앙 복귀")
        print("  m        기준점 마킹")
        print("  q / esc  종료\n")
        print("먼저 → 를 여러 번 눌러 스팟이 움직이는지 보고, 안 움직이면")
        print("] 로 스텝을 키워가며 반응이 나올 때까지 올려볼 것.\n")

        sat = False
        try:
            while self.running:
                x, y, power = self.psd.read()

                # u 가 안정된 뒤에만 표본으로 채택 (이동 중 값은 J 추정을 망친다)
                if x is not None and abs(x) <= PSD_LIMIT and abs(y) <= PSD_LIMIT:
                    self.stable += 1
                    if self.stable >= SETTLE_FRAMES:
                        self.samples.append((self.ux, self.uy, x, y))
                else:
                    self.stable = 0

                self.update_gui(x, y, power, sat)
        except KeyboardInterrupt:
            print("\nCtrl+C -> 종료")
        finally:
            self.report()
            self.cleanup()
            print("Done.")

    # ---------------- 결과 ----------------

    def report(self):
        print("\n" + "=" * 70)
        print("  결과")
        print("=" * 70)

        n = len(self.samples)
        print(f"  표본 수: {n}")
        if n < 8:
            print("  표본이 너무 적어 J 를 추정하지 않는다. 두 축 모두 충분히 밀어볼 것.")
            return

        s = np.array(self.samples)
        u = s[:, :2]
        d = s[:, 2:]

        span = u.max(axis=0) - u.min(axis=0)
        print(f"  조그 범위: x {span[0]:.5f} unit, y {span[1]:.5f} unit")
        if min(span) < 1e-9:
            print("  한 축을 전혀 안 움직였다. J 추정 불가 — 두 축 모두 밀어볼 것.")
            return

        # d_mm = J @ u + c  를 최소자승으로 푼다
        A = np.column_stack([u, np.ones(n)])
        if np.linalg.matrix_rank(A) < 3:
            print("  표본이 한 직선 위에만 있다. 두 축을 따로따로 밀어볼 것.")
            return

        sol, *_ = np.linalg.lstsq(A, d, rcond=None)   # (3, 2)
        J = sol[:2, :].T                              # [dx,dy] = J @ [ux,uy]

        resid = d - A @ sol
        rms = float(np.sqrt(np.mean(np.sum(resid**2, axis=1))))

        print("\n  J [mm per unit] (최소자승 추정) =")
        print("   ", str(J).replace("\n", "\n    "))
        print(f"\n  잔차 RMS = {rms:.4f} mm")

        # --- 판정 1: FSM 이 PSD 에 영향을 주긴 하는가 ---
        # 조그 범위 절반을 지령했을 때의 예상 변위를 잔차 노이즈와 비교한다.
        # 감도가 몇 mm/unit 이든 무관하게 성립하는 기준이다.
        resp = float(np.linalg.norm(J @ (span / 2.0)))
        snr = resp / max(rms, 1e-12)
        print(f"  예상 변위 = {resp:.4f} mm  (조그 범위 절반 기준)")
        print(f"  응답 SNR  = {snr:.1f}   (잔차 대비)")

        if snr < RESP_SNR_MIN:
            print("\n  ** FSM 이 PSD 스팟에 사실상 영향을 주지 않는다. **")
            print("     추정된 J 는 전부 노이즈다. 아래를 확인할 것:")
            print("       1) FSM 이 BS 하류에 있지 않은가."
                  " PSD 가 FSM 하류에 있어야 조향이 보인다.")
            print("       2) FSM 반사광이 PSD 갈래로 실제로 가는가 (광 경로 막힘/이탈).")
            print("       3) optoMDC 채널 배선과 SetControlMode(XY) 가 걸렸는가.")
            print("       4) 조그 범위가 너무 작지 않은가 (] 로 스텝을 키워 재시도).")
            return

        # --- 판정 2: 두 축이 독립인가 ---
        c0, c1 = J[:, 0], J[:, 1]
        det = float(np.linalg.det(J))
        sin_ax = abs(det) / max(np.linalg.norm(c0) * np.linalg.norm(c1), 1e-12)
        print(f"  det(J)    = {det:.6g}")
        print(f"  cond(J)   = {np.linalg.cond(J):.2f}")
        print(f"  축 독립성  = {sin_ax:.3f}  (두 축 사이 각의 sin, "
              f"{np.degrees(np.arcsin(min(sin_ax, 1.0))):.1f}deg)")

        if sin_ax < AXIS_SIN_MIN:
            print("\n  ** 두 축이 PSD 상에서 거의 같은 방향으로 움직인다. **")
            print("     J 가 특이행렬에 가까워 역행렬이 폭주한다. 이대로 폐루프를 걸면")
            print("     한 방향으로 발산한다. 광학 배치 또는 채널 배선을 확인할 것.")
            return
        if sin_ax < AXIS_SIN_WARN:
            print("\n  경고: 축간 커플링이 심하다. 제어는 되지만 게인 튜닝이 까다로워진다.")

        ang = np.degrees(np.arctan2(J[1, 0], J[0, 0]))
        print(f"\n  FSM x축 -> PSD 상 방향: {ang:.1f}deg  (0=PSD +X, 90=PSD +Y)")

        colmax = max(np.linalg.norm(c0), np.linalg.norm(c1))
        print(f"  감도 (열 노름 최대): {colmax:.4g} mm/unit")
        print(f"\n  -> fsm_calibrate.py 권장 DELTA ~= {FIT_TARGET_MM / colmax:.5f} unit")
        print("     (자동 레인징이 알아서 찾지만, 이 값과 크게 다르면 뭔가 이상한 것이다)")

        print("\n  L 검산: FSM->BS->PSD 광 경로 길이를 L[mm] 이라 하면")
        print("          unit 당 빔 편향각 = (J 대각) / L")
        for L in (100.0, 150.0, 200.0, 250.0, 300.0):
            print(f"            L={L:5.0f}mm -> ({J[0,0]/L*1e3:8.2f}, {J[1,1]/L*1e3:8.2f}) mrad/unit")


def main():
    Jog().run()


if __name__ == "__main__":
    main()
