"""
CONEX-PSD + Optotune MR-E-3 FSM 폐루프 트래킹

newport_PIDv3.py 의 FSM 버전.
Zaber 판과의 차이 (중요):

  1. PID 출력이 '절대 지령'이다.
     Zaber: new = get_position() + Kp*e*scale   (증분형, 기구 위치 되읽기)
     FSM  : u   = Kp*e + Ki*∫e + Kd*de/dt       (I항이 정상상태 포인팅을 유지)
     FSM은 내부 폐루프 서보가 있으므로 되읽기가 불필요하고, 시리얼 왕복을
     빼면 루프 주기가 그만큼 빨라진다.

  2. 오차를 mm 가 아니라 '액추에이터 unit' 으로 환산한 뒤 PID 에 넣는다.
     e_unit = -J^-1 @ [x_mm, y_mm]
     -> scale_factor 와 y축 부호 뒤집기가 J 안에 흡수된다. 게인이 무차원이 되어
        기하 배치(거리 L)를 바꿔도 재튜닝 폭이 작아진다.

  3. anti-windup 필수.
     Zaber는 느려서 windup 이 잘 안 보였지만, FSM은 대역폭이 훨씬 높아
     빔 로스 구간에서 적분항이 순식간에 레일까지 쌓인다. 클램프 안 하면
     빔이 돌아와도 복귀를 못 한다.
"""

import sys
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from fsm_optotune import OptotuneFSM
from psd_conex import PSD

# ====== 설정 ======
# 포트는 psd_conex.DEFAULT_PORT / fsm_optotune.DEFAULT_PORT 한 곳에서만 고친다.

SAMPLING_INTERVAL = 0.005  # 목표 루프 주기 (s). 실제로는 PSD 시리얼 읽기가 병목.
PSD_LIMIT = 5.0            # PSD 유효 범위 (mm)
DETECTION_THRESHOLD = 5.0  # 빔 검출 광량 임계값
LASER_MAX = 100.0

# PID 게인 (단위: unit / unit -> 무차원)
# Zaber 값(0.15/0.03/0.005)을 그대로 쓰면 안 된다. 아래 "튜닝" 주석 참고.
KP = 0.35
KI = 1.5                   # per second
KD = 0.002                 # seconds
D_LPF_HZ = 40.0            # 미분항 저역통과 (PSD 노이즈 증폭 억제)
I_LIMIT = 0.6              # 적분항 클램프 (unit)

# 나선 스캔 (blind acquisition)
SCAN_STEP = 0.02           # unit
SCAN_MAX = 0.6             # unit
SCAN_DWELL = 0.01          # s


class PID2D:
    """축별 독립 PID. 출력이 곧 FSM 절대 지령(unit)."""

    def __init__(self, kp, ki, kd, i_limit, d_lpf_hz):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.i_limit = i_limit
        self.alpha_tau = 1.0 / (2.0 * np.pi * d_lpf_hz)
        self.reset()

    def reset(self, integral=None):
        self.integral = np.zeros(2) if integral is None else np.array(integral, float)
        self.prev_e = np.zeros(2)
        self.deriv = np.zeros(2)
        self.first = True

    def update(self, e, dt, saturated=False):
        """
        e   : 액추에이터 unit 으로 환산된 오차 (2,)
        dt  : 실측 루프 주기
        saturated : 직전 사이클에서 출력이 클램프됐는지 (anti-windup)
        """
        if self.first:
            self.prev_e = e.copy()
            self.first = False

        # 미분 (측정 노이즈 대비 1차 LPF)
        raw_d = (e - self.prev_e) / max(dt, 1e-6)
        a = dt / (self.alpha_tau + dt)
        self.deriv = self.deriv + a * (raw_d - self.deriv)
        self.prev_e = e.copy()

        # 적분 (포화 시 정지 = conditional integration)
        if not saturated:
            self.integral += e * dt
            self.integral = np.clip(self.integral, -self.i_limit, self.i_limit)

        return self.kp * e + self.ki * self.integral + self.kd * self.deriv


class Tracker:
    def __init__(self):
        self.psd = PSD()
        self.fsm = OptotuneFSM()
        self.pid = PID2D(KP, KI, KD, I_LIMIT, D_LPF_HZ)
        self.running = True
        self.saturated = False

    # ---------------- 하드웨어 ----------------

    def connect(self):
        self.psd.open()
        self.fsm.connect()
        if self.fsm.Jinv is None:
            print("\n캘리브레이션이 없다. 먼저 실행할 것:\n    python fsm_calibrate.py\n")
            sys.exit(-1)

    def cleanup(self):
        try:
            self.fsm.center()
        except Exception:
            pass
        self.fsm.close()
        self.psd.close()
        plt.ioff()
        plt.close("all")

    # ---------------- GUI ----------------

    def setup_gui(self):
        plt.ion()
        self.fig, self.ax = plt.subplots()
        self.scatter = self.ax.scatter([], [], c="red", s=100, label="Beam Position")
        self.ax.set_xlim(-PSD_LIMIT, PSD_LIMIT)
        self.ax.set_ylim(-PSD_LIMIT, PSD_LIMIT)
        self.ax.set_xlabel("X Position (mm)")
        self.ax.set_ylabel("Y Position (mm)")
        self.ax.set_title("FSM Closed-Loop Tracking")
        self.ax.grid(True, color="darkgray", alpha=0.5)
        self.ax.set_aspect("equal")

        self.gauge_ax = self.fig.add_axes([0.83, 0.13, 0.05, 0.6])
        self.gauge_ax.set_xlim(0, 1)
        self.gauge_ax.set_ylim(0, LASER_MAX)
        self.gauge_ax.axis("off")
        self.gauge_ax.add_patch(Rectangle((0.2, 0), 0.6, LASER_MAX,
                                          edgecolor="black", facecolor="none", linewidth=1.5))
        self.gauge_fill = Rectangle((0.2, 0), 0.6, 0, edgecolor="none", facecolor="green")
        self.gauge_ax.add_patch(self.gauge_fill)

        self.ax.scatter([], [], c="green", marker="s", s=100, label="Laser Power")
        self.ax.legend()
        self.power_text = self.fig.text(0.855, 0.75, "", ha="center", va="bottom", fontsize=12)

    def update_gui(self, x_mm, y_mm, power):
        self.scatter.set_offsets([[x_mm, y_mm]])
        self.gauge_fill.set_height(min(power, LASER_MAX))
        self.power_text.set_text(f"{power:.1f}%")
        plt.pause(0.001)

    # ---------------- 획득 ----------------

    def beam_present(self, x, y, power):
        return (x is not None and abs(x) <= PSD_LIMIT and abs(y) <= PSD_LIMIT
                and power > DETECTION_THRESHOLD)

    def spiral_scan(self):
        """
        FSM 나선 스캔. Zaber 기구 스캔과 달리 전 범위를 1초 이내에 훑는다.
        (Zaber를 조동축으로 남겨둔 경우 이 단계 전에 Zaber 를 대략 위치로 보낸다.)
        """
        print("\n[ACQ] spiral scan...")
        ux = uy = 0.0
        dx, dy = SCAN_STEP, 0.0
        leg, step_in_leg, legs_done = 1, 0, 0

        while self.running:
            self.fsm.set_units(ux, uy)
            time.sleep(SCAN_DWELL)
            x, y, p = self.psd.read()
            if x is not None:
                self.update_gui(x, y, p)
            if self.beam_present(x, y, p):
                print(f"[ACQ] BEAM DETECTED at u=({ux:.3f}, {uy:.3f}), "
                      f"PSD=({x:.3f}, {y:.3f}) mm, power={p:.2f}")
                return True

            ux += dx
            uy += dy
            step_in_leg += 1
            if step_in_leg >= leg:                    # 나선: 우,상,좌,하 순으로 변길이 증가
                step_in_leg = 0
                dx, dy = -dy, dx
                legs_done += 1
                if legs_done % 2 == 0:
                    leg += 1

            if max(abs(ux), abs(uy)) > SCAN_MAX:
                print("[ACQ] 스캔 범위 소진. 중앙으로 복귀 후 재시작.")
                self.fsm.center()
                ux = uy = 0.0
                dx, dy = SCAN_STEP, 0.0
                leg, step_in_leg, legs_done = 1, 0, 0

        return False

    # ---------------- 추적 ----------------

    def track(self):
        print("\n[TRACK] closed loop. Ctrl+C to stop.")
        # Bumpless transfer: 인계 시점에 u = Ki*I 가 현재 지령과 같아지도록 적분항을 역산.
        # 이걸 안 하면 스캔으로 찾아놓은 지령이 0으로 리셋되면서 빔을 즉시 놓친다.
        u_now = np.array(self.fsm.get_units(), dtype=float)
        self.pid.reset(integral=np.clip(u_now / KI, -I_LIMIT, I_LIMIT))

        t_prev = time.time()
        t0 = t_prev
        n = 0
        loss_count = 0

        while self.running:
            x_mm, y_mm, power = self.psd.read()

            now = time.time()
            dt = now - t_prev
            t_prev = now

            if not self.beam_present(x_mm, y_mm, power):
                loss_count += 1
                if loss_count > 20:                   # ~100ms 연속 로스
                    print(f"\n[TRACK] BEAM LOST. 재획득으로 전환.")
                    return False
                time.sleep(SAMPLING_INTERVAL)
                continue
            loss_count = 0

            # mm 오차 -> 액추에이터 unit 오차 (J^-1). 부호는 오차를 없애는 방향.
            e_unit = -self.fsm.mm_to_unit(x_mm, y_mm)

            u = self.pid.update(e_unit, dt, saturated=self.saturated)
            _, _, self.saturated = self.fsm.set_units(u[0], u[1])

            self.update_gui(x_mm, y_mm, power)

            n += 1
            if n % 50 == 0:
                rate = n / (now - t0)
                rms = np.hypot(x_mm, y_mm)
                print(f"[{now - t0:6.2f}s] PSD=({x_mm:+.4f}, {y_mm:+.4f})mm  "
                      f"|e|={rms:.4f}mm  u=({u[0]:+.4f}, {u[1]:+.4f})  "
                      f"{'SAT ' if self.saturated else ''}{rate:.0f}Hz")

            elapsed = time.time() - now
            time.sleep(max(0.0, SAMPLING_INTERVAL - elapsed))

        return True

    # ---------------- 실행 ----------------

    def run(self):
        print("=" * 70)
        print("  CONEX-PSD + Optotune MR-E-3 FSM Tracking")
        print("=" * 70)
        self.connect()
        self.setup_gui()
        try:
            while self.running:
                x, y, p = self.psd.read()
                if not self.beam_present(x, y, p):
                    if not self.spiral_scan():
                        break
                self.track()
        except KeyboardInterrupt:
            print("\n\nCtrl+C -> 종료")
            self.running = False
        finally:
            self.cleanup()
            print("Done.")


if __name__ == "__main__":
    Tracker().run()
