"""
PAA-EKF Pointing, Acquisition, and Tracking  --  Optotune MR-E-3 FSM 판

pat_legacy/v3_paa_ekf_main.py (Zaber 짐벌판) 의 이식.
1단계 구성: 오정렬은 사람이 수동으로 주고, 획득/추적은 FSM 단독으로 한다.
(Zaber 조동축 + FSM 미동축 2단 구성은 나중 단계. 여기엔 Zaber 코드가 전혀 없다.)

    Blind    : EKF 가상 궤도운동 + PAA 로 표적 방향을 예측하며 스윕  (원본 유지)
    Tracking : PSD 오차 -> J^-1 -> PID2D -> FSM 절대 지령            (fsm_PID.py 와 동일)


각도 규약 (이식하면서 확정)
---------------------------
모든 각도는 "빔 편향각" [rad], 원점은 FSM 중앙(u=0), 축은 PSD 에 정렬.
즉 theta_x 가 양이면 PSD 상에서 빔이 +X 로 간다.

    d_mm  = theta_rad * L_mm            (L = FSM -> PSD 광 경로 길이)
    d_mm  = J @ du                      (J 는 fsm_calibrate.py 실측)
    => du = J^-1 @ (theta * L_mm)       (fsm.rad_to_unit)

원본의 PSD_SENSITIVITY = 250e-6 rad/mm @ 4m 상수는 사라졌다. 250e-6 = 1/4000mm 로
위 식의 1/L_mm 과 같은 값이고, 이제 J 와 L 에서 유도되므로 따로 둘 이유가 없다.
(9/4 분석 때 "FSM 이면 125e-6 으로 바꿔야 한다"고 적었는데, 그건 지령을 미러
 '기계각'으로 줄 때의 이야기다. 여기서는 지령이 정규화 unit 이고 반사 2배 계수가
 실측 J 안에 이미 들어있으므로, 빔 편향각 기준인 250e-6 쪽이 맞고 코드에는 2가
 어디에도 하드코딩되지 않는다.)


원본과 달라진 점 (전부 의도적)
------------------------------
1. Zaber / homing 제거.
   read_home_from_goto_position(), goto_position.py 파싱, move_absolute(HOME+25mrad)
   전부 삭제. FSM 은 "approximate HOME" 개념이 없다 -- 정규화 0 이 곧 기계적 중앙이고
   그게 기준점이다. 25 mrad 오정렬은 사람이 광학 마운트로 물리적으로 준다.

2. EKF 초기 각속도 0.
   원본은 x[2] = -7.5e-3, omega_virtual = +7.5e-3 이었는데 predict() 가 두 항을
   모두 x[0] 에 더하므로 정확히 상쇄된다 -> blind 표적이 안 움직이고 PAA 도 0.
   원본은 표적이 이미 시야 안에 있어 blind 가 즉시 끝나서 드러나지 않았지만,
   수동 오정렬 상태에서는 스윕이 실제로 필요하다. EKF_INIT_OMEGA 참고.

3. blind 스윕 레일 반전.
   스윕이 FSM 가동범위 끝(max_unit)에 닿으면 원본 로직은 거기서 영원히 멈춘다.
   가상 궤도운동 방향을 뒤집어 왕복하게 했다. 없으면 blind 가 교착된다.

4. 재획득 루프.
   원본 phase_tracking() 은 빔 로스 때 "Returning to BLIND phase..." 를 찍고
   False 를 반환하는데, run() 이 그걸 받아서 그냥 종료한다 (메시지와 동작 불일치).
   메시지가 말하는 대로 blind 로 되돌아가도록 run() 에 루프를 넣었다.

5. PID 교체.
   원본 PIDController(증분형, scale_factor=0.1, y축 부호 수동 반전) 대신
   fsm_PID.py 의 PID2D (절대 지령형, anti-windup, 미분 LPF) + J^-1.
   게인은 fsm_PID.py 한 곳에서만 튜닝한다.


실행 순서
---------
    python fsm_calibrate.py      # fsm_calib.json 생성 (선행 필수)
    python fsm_paa_ekf_main.py
"""

import os
import sys
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from fsm_optotune import OptotuneFSM
from psd_conex import PSD
from paa_ekf import ExtendedKalmanFilter
# 게인은 fsm_PID.py 가 단일 출처. 튜닝은 저기서만 한다.
from fsm_PID import PID2D, KP, KI, KD, I_LIMIT, D_LPF_HZ


# ====== 하드웨어 ======
# 포트는 psd_conex.DEFAULT_PORT / fsm_optotune.DEFAULT_PORT 한 곳에서만 고친다.

# ====== 기하 ======
L_M = 4.0                   # FSM -> PSD 광 경로 길이 (m). J 를 측정한 그 배치여야 한다.

# ====== 루프 ======
SAMPLING_INTERVAL = 0.01    # 100 Hz 목표. 실제로는 CONEX 시리얼 읽기가 병목.
PSD_LIMIT = 5.0             # PSD 유효 범위 (mm)
DETECTION_THRESHOLD = 5.0   # 빔 검출 광량 임계값
LASER_MAX = 100.0
BEAM_LOSS_STREAK = 20       # 연속 로스 이 횟수를 넘으면 blind 로 복귀

# ====== EKF / PAA (원본 값 유지) ======
OMEGA_VIRTUAL = 7.5e-3      # 가상 궤도 각속도 (rad/s) -- LEO 상대 각속도
TAU_VIRTUAL = 3.3e-3        # 가상 전파 지연 (s)

# blind 시작 시점의 표적 방향 추정치와 각속도.
#   THETA: FSM 중앙을 공칭 정렬 방향으로 본다. 25 mrad 급의 사전 불확실성은
#          EKF 의 초기 공분산 P(=(25e-3)^2)에 이미 들어 있다.
#   OMEGA: 0 으로 둔다. 원본처럼 -OMEGA_VIRTUAL 을 넣으면 predict() 안에서
#          가상 궤도운동과 상쇄되어 스윕도 PAA 도 0 이 된다 (paa_ekf.py 주석 참고).
#          0 이면 순 스윕 속도 = +OMEGA_VIRTUAL = 7.5 mrad/s, PAA = 24.75 urad.
EKF_INIT_THETA = (0.0, 0.0)
EKF_INIT_OMEGA = (0.0, 0.0)

# blind 스윕은 x(=PSD X) 축으로만 진행한다 (원본이 az 축만 흔들었던 것과 동일).
# 따라서 수동 오정렬의 Y 성분은 PSD 반범위 안에 들어와야 한다:
#     |theta_y| <= PSD_LIMIT / L_mm   (4m 에서 5mm -> 1.25 mrad)
# 이걸 넘으면 X 를 아무리 훑어도 빔이 PSD 세로 범위 안으로 안 들어와서
# blind 가 영원히 끝나지 않는다. 2D 스캔이 필요하면 fsm_PID.py 의 나선 스캔을 볼 것.
SWEEP_SAT_STREAK = 10       # 연속 포화 이 횟수를 넘으면 스윕 방향 반전
SWEEP_HINT_AFTER = 2        # 반전 이 횟수까지 못 찾으면 원인 힌트를 찍는다

MISALIGN_NOMINAL_RAD = 25e-3    # 수동으로 줄 오정렬의 공칭값 (안내 출력용)


class FSMPAAEKFSystem:
    """FSM 단독 PAA-EKF PAT 시스템"""

    def __init__(self):
        self.psd = PSD()
        self.fsm = OptotuneFSM()

        self.ekf = ExtendedKalmanFilter(
            dt=SAMPLING_INTERVAL,
            omega_virtual=OMEGA_VIRTUAL,
            tau_virtual=TAU_VIRTUAL,
        )
        self.pid = PID2D(KP, KI, KD, I_LIMIT, D_LPF_HZ)

        self.L_mm = L_M * 1000.0
        self.phase = "INIT"
        self.running = True
        self.saturated = False

        # GUI
        self.fig = None
        self.ax = None
        self.scatter = None
        self.gauge_fill = None
        self.power_text = None

    # ================================================================
    # 초기화
    # ================================================================

    def initialize_hardware(self):
        self.psd.open()
        self.fsm.connect()

        if self.fsm.Jinv is None:
            print("\n캘리브레이션이 없다. 먼저 실행할 것:\n    python fsm_calibrate.py\n")
            sys.exit(-1)

        reach = self.fsm.reachable_rad(self.L_mm)
        print(f"  L (FSM -> PSD)        : {L_M:.3f} m")
        print(f"  도달 가능 빔 편향각    : (+-{reach[0]*1e3:.2f}, +-{reach[1]*1e3:.2f}) mrad "
              f"@ max_unit={self.fsm.max_unit}")
        if reach[0] < MISALIGN_NOMINAL_RAD:
            print(f"  경고: X 가동범위가 공칭 오정렬 {MISALIGN_NOMINAL_RAD*1e3:.1f} mrad 보다 좁다. "
                  f"오정렬을 줄이거나 L 을 늘릴 것.")

    def seed_ekf(self):
        """blind 시작 상태로 EKF 를 되돌린다. 재획득 때도 매번 호출."""
        self.ekf.reset()                      # x=0, P 초기화, virtual motion on
        self.ekf.x[0], self.ekf.x[1] = EKF_INIT_THETA
        self.ekf.x[2], self.ekf.x[3] = EKF_INIT_OMEGA
        self.ekf.omega_virtual = abs(OMEGA_VIRTUAL)   # 레일 반전으로 뒤집힌 부호 복구

    # ================================================================
    # GUI (원본과 동일)
    # ================================================================

    def setup_gui(self):
        import matplotlib.image as mpimg

        plt.ion()
        self.fig, self.ax = plt.subplots()

        self.scatter = self.ax.scatter([], [], c='red', s=100, label="Beam Position")
        self.ax.set_xlim(-PSD_LIMIT, PSD_LIMIT)
        self.ax.set_ylim(-PSD_LIMIT, PSD_LIMIT)
        self.ax.set_xticks(range(-5, 6, 1))
        self.ax.set_yticks(range(-5, 6, 1))
        self.ax.set_xlabel("X Position (mm)")
        self.ax.set_ylabel("Y Position (mm)")
        self.ax.set_title("FSM PAA-EKF Tracking")
        self.ax.grid(True, color='darkgray', alpha=0.5)
        self.ax.set_aspect('equal')

        # LICS 로고 (있으면)
        try:
            logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lics.png")
            if os.path.exists(logo_path):
                logo = mpimg.imread(logo_path)
                logo_ax = self.fig.add_axes([0.73, 0.80, 0.20, 0.20], anchor='NE', zorder=10)
                logo_ax.imshow(logo)
                logo_ax.axis('off')
        except Exception as e:
            print(f"[GUI] Could not load logo: {e}")

        self.gauge_ax = self.fig.add_axes([0.83, 0.13, 0.05, 0.6])
        self.gauge_ax.set_xlim(0, 1)
        self.gauge_ax.set_ylim(0, LASER_MAX)
        self.gauge_ax.axis('off')
        self.gauge_ax.add_patch(Rectangle((0.2, 0), 0.6, LASER_MAX,
                                          edgecolor='black', facecolor='none', linewidth=1.5))
        self.gauge_fill = Rectangle((0.2, 0), 0.6, 0, edgecolor='none', facecolor='green')
        self.gauge_ax.add_patch(self.gauge_fill)

        self.ax.scatter([], [], c='green', marker='s', s=100, label="Laser Power")
        self.ax.legend()
        self.power_text = self.fig.text(0.855, 0.75, '', ha='center', va='bottom', fontsize=12)

    def update_gui(self, x_mm, y_mm, power):
        try:
            self.scatter.set_offsets([[x_mm, y_mm]])
            self.gauge_fill.set_height(min(power, LASER_MAX))
            self.power_text.set_text(f"{power:.1f}%")
            plt.pause(0.001)
        except Exception as e:
            print(f"[GUI] Update error: {e}")

    # ================================================================
    # 공통
    # ================================================================

    def beam_present(self, x_mm, y_mm, power):
        return (x_mm is not None
                and abs(x_mm) <= PSD_LIMIT and abs(y_mm) <= PSD_LIMIT
                and power > DETECTION_THRESHOLD)

    def point_at(self, th_x, th_y):
        """빔 편향각(rad) 으로 FSM 을 절대 지령. 포화 여부를 돌려준다."""
        u = self.fsm.rad_to_unit(th_x, th_y, self.L_mm)
        _, _, saturated = self.fsm.set_units(u[0], u[1])
        return u, saturated

    # ================================================================
    # Phase 1: BLIND ACQUISITION  (EKF 가상 궤도운동 + PAA)
    # ================================================================

    def phase_blind_acquisition(self):
        print("\n" + "=" * 70)
        print("PHASE 1: BLIND ACQUISITION (PAA-EKF)")
        print("=" * 70)

        self.phase = "BLIND"
        self.ekf.enable_virtual_motion()

        loop_count = 0
        sat_streak = 0
        reversals = 0
        hinted = False
        last_loop_time = time.time()

        while self.running and self.phase == "BLIND":
            loop_start = time.time()

            # 1. PSD 읽기
            x_mm, y_mm, power = self.psd.read()
            if x_mm is not None:
                self.update_gui(x_mm, y_mm, power)

            # 2. 검출 확인
            if self.beam_present(x_mm, y_mm, power):
                print(f"\nBEAM DETECTED!")
                print(f"  Position: ({x_mm:.3f}, {y_mm:.3f}) mm")
                print(f"  Power:    {power:.2f}")
                self.phase = "TRACKING"
                return True

            # 3. EKF predict (가상 궤도운동 포함)
            dt_actual = (time.time() - last_loop_time) if loop_count > 0 else SAMPLING_INTERVAL
            predicted = self.ekf.predict(dt=dt_actual)

            # 4. PAA
            paa = self.ekf.get_paa()

            # 5. 지향 목표 = 예측 위치 + PAA
            target_x = predicted[0] + paa[0]
            target_y = predicted[1] + paa[1]

            # 6. FSM 지령
            u, saturated = self.point_at(target_x, target_y)

            # 7. 레일에 닿으면 스윕 방향 반전 (원본에 없던 처리, 없으면 여기서 교착)
            if saturated:
                sat_streak += 1
                if sat_streak >= SWEEP_SAT_STREAK:
                    self.ekf.omega_virtual = -self.ekf.omega_virtual
                    # 추정치를 실제 인가된 지령으로 되돌려 놓지 않으면 EKF 가
                    # 레일 바깥에 머물러 있어서 반전 후에도 한참 안 움직인다.
                    th_now = self.fsm.unit_to_rad(self.fsm.ux, self.fsm.uy, self.L_mm)
                    self.ekf.x[0], self.ekf.x[1] = th_now[0], th_now[1]
                    sat_streak = 0
                    reversals += 1
                    print(f"[BLIND] 가동범위 끝. 스윕 반전 -> "
                          f"omega_virtual = {self.ekf.omega_virtual*1e3:+.3f} mrad/s")

                    # X 를 양쪽 끝까지 훑고도 못 찾았다면 X 문제가 아니다.
                    if reversals >= SWEEP_HINT_AFTER and not hinted:
                        hinted = True
                        y_tol = PSD_LIMIT / self.L_mm
                        print(f"\n[BLIND] X 가동범위를 전부 훑었는데 빔이 안 잡힌다. "
                              f"거의 항상 아래 둘 중 하나다:")
                        print(f"        1) 오정렬의 Y 성분이 너무 크다. "
                              f"스윕은 X 축 1차원이라 |theta_y| <= {y_tol*1e3:.2f} mrad "
                              f"(PSD 에서 {PSD_LIMIT:.1f} mm) 안에 들어와야 한다.")
                        print(f"        2) 오정렬이 FSM 가동범위 밖이다. "
                              f"오정렬을 줄이거나 L 을 늘릴 것.\n")
            else:
                sat_streak = 0

            # 8. 상태 출력
            loop_count += 1
            if loop_count % 10 == 0:
                print(f"\nBlind PAA-EKF... Step {loop_count}")
                print(f"  theta_est = ({predicted[0]*1e3:+.3f}, {predicted[1]*1e3:+.3f}) mrad")
                print(f"  omega_est = ({predicted[2]*1e6:+.1f}, {predicted[3]*1e6:+.1f}) urad/s")
                print(f"  omega_virtual = {self.ekf.omega_virtual*1e3:+.3f} mrad/s")
                print(f"  PAA = ({paa[0]*1e6:+.1f}, {paa[1]*1e6:+.1f}) urad")
                print(f"  FSM u = ({u[0]:+.4f}, {u[1]:+.4f}){'  SAT' if saturated else ''}")
                if x_mm is not None:
                    print(f"  PSD = ({x_mm:.3f}, {y_mm:.3f}) mm, Power={power:.2f}")

            # 9. 주기 맞추기
            last_loop_time = loop_start
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, SAMPLING_INTERVAL - elapsed))

        return False

    # ================================================================
    # Phase 2: TRACKING  (PSD -> J^-1 -> PID2D -> FSM 절대 지령)
    # ================================================================

    def phase_tracking(self):
        print("\n" + "=" * 70)
        print("PHASE 2: TRACKING (PID, closed loop)")
        print("=" * 70)

        self.phase = "TRACKING"

        # Bumpless transfer: 인계 시점의 지령이 u = Ki*I 로 재현되도록 적분항 역산.
        # 안 하면 blind 로 찾아둔 지향이 0 으로 리셋되면서 빔을 즉시 놓친다.
        u_now = np.array(self.fsm.get_units(), dtype=float)
        self.pid.reset(integral=np.clip(u_now / KI, -I_LIMIT, I_LIMIT))
        self.saturated = False

        loop_count = 0
        loss_streak = 0
        t_prev = time.time()
        t0 = t_prev

        while self.running and self.phase == "TRACKING":
            x_mm, y_mm, power = self.psd.read()

            now = time.time()
            dt = now - t_prev
            t_prev = now

            # 빔 로스 판정 (순간적인 읽기 실패로 blind 로 튀지 않도록 연속 카운트)
            if not self.beam_present(x_mm, y_mm, power):
                loss_streak += 1
                if loss_streak > BEAM_LOSS_STREAK:
                    print(f"\nBEAM LOST. Returning to BLIND phase...")
                    self.phase = "BLIND"
                    return False
                time.sleep(SAMPLING_INTERVAL)
                continue
            loss_streak = 0

            # mm 오차 -> 액추에이터 unit 오차. 목표는 PSD (0, 0).
            # 부호는 오차를 없애는 방향. scale_factor 와 y축 반전은 J 안에 흡수됨.
            e_unit = -self.fsm.mm_to_unit(x_mm, y_mm)

            u = self.pid.update(e_unit, dt, saturated=self.saturated)
            _, _, self.saturated = self.fsm.set_units(u[0], u[1])

            self.update_gui(x_mm, y_mm, power)

            loop_count += 1
            if loop_count % 50 == 0:
                rate = loop_count / (now - t0)
                rms = np.hypot(x_mm, y_mm)
                print(f"[{now - t0:6.2f}s] PSD=({x_mm:+.4f}, {y_mm:+.4f})mm  "
                      f"|e|={rms:.4f}mm  u=({u[0]:+.4f}, {u[1]:+.4f})  "
                      f"{'SAT ' if self.saturated else ''}{rate:.0f}Hz")

            elapsed = time.time() - now
            time.sleep(max(0.0, SAMPLING_INTERVAL - elapsed))

        return True

    # ================================================================
    # 수동 오정렬 절차
    # ================================================================

    def manual_misalignment(self):
        """
        1단계 구성에서는 오정렬을 사람이 준다.
        FSM 을 중앙에 세워놓고 정렬 -> 수동으로 틀기, 두 단계로 나눈다.
        """
        print("\n" + "=" * 70)
        print("수동 오정렬 (1단계 구성)")
        print("=" * 70)

        self.fsm.center()
        print("\nFSM 을 중앙(u=0)으로 보냈다. 이게 기준점이다.")
        print("먼저 이 상태에서 빔이 PSD 중앙 근처에 오도록 광학 정렬을 맞출 것.")

        input("\n  정렬이 끝나면 Enter > ")

        x, y, p = self.psd.read_avg(20)
        if self.beam_present(x, y, p):
            print(f"  기준 정렬 확인: PSD = ({x:+.3f}, {y:+.3f}) mm, power = {p:.2f}")
        else:
            print("  경고: FSM 중앙에서 빔이 PSD 에 안 잡힌다. 기준점이 불확실하다.")
            print("        그래도 진행은 되지만 blind 스윕이 오래 걸릴 수 있다.")

        y_tol = PSD_LIMIT / self.L_mm
        reach = self.fsm.reachable_rad(self.L_mm)
        print(f"\n이제 수동으로 오정렬을 줄 것. 공칭 {MISALIGN_NOMINAL_RAD*1e3:.0f} mrad "
              f"(= {np.rad2deg(MISALIGN_NOMINAL_RAD):.3f}deg, {L_M:.1f}m 에서 "
              f"{MISALIGN_NOMINAL_RAD*self.L_mm:.0f} mm).")
        print(f"  * 방향: PSD X 축. blind 스윕이 X 1차원이라 X 성분이 지배적이어야 한다.")
        print(f"  * Y 성분은 +-{y_tol*1e3:.2f} mrad (PSD 에서 {PSD_LIMIT:.1f} mm) 이내로 "
              f"유지할 것. 넘으면 blind 가 절대 못 찾는다.")
        print(f"  * X 성분은 +-{reach[0]*1e3:.1f} mrad (FSM 가동범위) 이내여야 한다.")
        print(f"  * 오정렬 후 PSD 에서 빔이 사라져 있어야 정상이다.")

        input("\n  오정렬을 준 뒤 Enter > ")

        x, y, p = self.psd.read()
        if self.beam_present(x, y, p):
            print(f"  주의: 빔이 아직 PSD 위에 있다 ({x:+.3f}, {y:+.3f}) mm. "
                  f"오정렬이 부족하면 blind 단계가 즉시 끝나서 의미가 없다.")
        else:
            print("  빔이 PSD 밖으로 나갔다. blind acquisition 준비 완료.")

    # ================================================================
    # 실행
    # ================================================================

    def run(self):
        print("=" * 70)
        print("  PAA-EKF Pointing, Acquisition, and Tracking  (FSM 판)")
        print("  Optotune MR-E-3 + Newport CONEX-PSD  /  4m Lab Demo")
        print("  - Blind    : virtual orbital motion + PAA")
        print("  - Tracking : PID only (no virtual motion, no PAA)")
        print("=" * 70)

        print("\nInitializing hardware...")
        self.initialize_hardware()

        print("\nSetting up GUI...")
        self.setup_gui()

        try:
            self.manual_misalignment()

            while self.running:
                self.seed_ekf()
                paa0 = self.ekf.get_paa()
                print(f"\nEKF seeded: theta = ({self.ekf.x[0]*1e3:+.3f}, {self.ekf.x[1]*1e3:+.3f}) mrad, "
                      f"omega = ({self.ekf.x[2]*1e3:+.3f}, {self.ekf.x[3]*1e3:+.3f}) mrad/s")
                print(f"            omega_virtual = {self.ekf.omega_virtual*1e3:+.3f} mrad/s, "
                      f"PAA = ({paa0[0]*1e6:+.1f}, {paa0[1]*1e6:+.1f}) urad")

                if not self.phase_blind_acquisition():
                    break
                if self.phase_tracking():
                    break
                # tracking 이 False -> 빔 로스. 위로 돌아가 blind 재시작.

        except KeyboardInterrupt:
            print("\n\nUser interrupted (Ctrl+C)")
            self.running = False

        finally:
            print("\nShutting down...")
            self.cleanup()

    def cleanup(self):
        try:
            self.fsm.center()
        except Exception:
            pass
        self.fsm.close()
        self.psd.close()
        plt.ioff()
        plt.close('all')
        print("Done!")


def main():
    FSMPAAEKFSystem().run()


if __name__ == "__main__":
    main()
