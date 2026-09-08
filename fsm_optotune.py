"""
Optotune MR-E-3 FSM 액추에이터 래퍼

기존 Zaber 짐벌(x_axis / y_axis)을 대체한다.
Zaber와의 인터페이스 차이:

    Zaber                                   FSM (MR-E-3)
    ------------------------------------    ------------------------------------
    x_axis.get_position(ANGLE_DEGREES)      self.ux (소프트웨어 지령값 유지)
    x_axis.move_absolute(deg, DEGREES)      self.set_units(ux, uy)
    단위: degree (기구 각도)                단위: optoMDC XY 정규화 [-1, +1]
    빔 변위 Δd = Δθ · L                     빔 변위 Δd = 2 · Δθ_mech · L  (반사 2배!)
    위치 되읽기 필요 (실제 기구 위치)       되읽기 불필요 (내부 폐루프 서보)

SDK 설치 (PyPI 아님. Optotune Download Center에서 wheel 받아서):
    pip install optoKummenberg-<ver>-py3-none-any.whl
    pip install optoMDC-<ver>-py3-none-any.whl
MR-E-3 지원은 optoMDC 1.3.4781 이상.
"""

import json
import os

import numpy as np
import optoMDC

# 포트 설정의 단일 출처. None = 자동 탐색 (보통 이대로 두면 된다).
# 자동 탐색이 실패할 때만 "COM5" 같은 값을 넣는다.
DEFAULT_PORT = None

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fsm_calib.json")


class OptotuneFSM:
    """
    MR-E-3 2축 FSM.

    좌표계
      - "unit" : optoMDC XY 폐루프 정규화 지령. -1..+1 이 미러 전 편향 범위에 대응.
      - "mm"   : PSD 위에서의 빔 변위.

    Jacobian J (2x2): [dx_mm, dy_mm] = J @ [du_x, du_y]
      -> 제어에 필요한 것은 J^-1 (mm 오차를 unit 지령으로 환산).
      J는 fsm_calibrate.py 가 실측해서 fsm_calib.json 에 저장한다.
      이게 기존 코드의 scale_factor=0.1 과 y축 부호 뒤집기(-y_pid.output)를 대체한다.
    """

    def __init__(self, port=None, calib_file=CALIB_FILE, max_unit=0.8):
        self.port = port if port is not None else DEFAULT_PORT
        self.calib_file = calib_file
        self.max_unit = max_unit          # 레일 여유. 1.0을 그대로 쓰면 포화 시 복구가 어렵다.

        self.mre = None
        self.si_0 = None                  # Channel_0 StaticInput (x)
        self.si_1 = None                  # Channel_1 StaticInput (y)

        self.ux = 0.0                     # 현재 지령 (소프트웨어 상태)
        self.uy = 0.0

        self.J = None                     # mm per unit
        self.Jinv = None
        self.load_calibration()

    # ----------------------------------------------------------------
    # 연결 / 종료
    # ----------------------------------------------------------------

    def connect(self):
        if self.port:
            self.mre = optoMDC.connect(port=self.port)
        else:
            self.mre = optoMDC.connect()      # 자동 탐색
        self.mre.reset()

        for ch, attr in ((self.mre.Mirror.Channel_0, "si_0"),
                         (self.mre.Mirror.Channel_1, "si_1")):
            ch.StaticInput.SetAsInput()                 # 입력원 = static value
            ch.SetControlMode(optoMDC.Units.XY)         # XY = closed loop (Current = open loop)
            ch.Manager.CheckSignalFlow()                # 신호 경로 검증
            setattr(self, attr, ch.StaticInput)

        self.set_units(0.0, 0.0)
        print("[FSM] MR-E-3 connected, closed-loop XY mode, centered")
        return self

    def close(self):
        if self.mre is None:
            return
        try:
            self.set_units(0.0, 0.0)
        except Exception:
            pass
        # SDK 버전에 따라 종료 메서드 이름이 다르다.
        for name in ("disconnect", "close"):
            fn = getattr(self.mre, name, None)
            if callable(fn):
                try:
                    fn()
                    break
                except Exception:
                    pass
        self.mre = None
        print("[FSM] disconnected")

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # ----------------------------------------------------------------
    # 지령
    # ----------------------------------------------------------------

    def set_units(self, ux, uy):
        """
        절대 지령. 반환값은 실제로 인가된 (클램프된) 값 + 포화 플래그.
        포화 플래그는 PID anti-windup 에 쓴다.
        """
        cx = float(np.clip(ux, -self.max_unit, self.max_unit))
        cy = float(np.clip(uy, -self.max_unit, self.max_unit))
        saturated = (cx != ux) or (cy != uy)

        self.si_0.SetXY(cx)
        self.si_1.SetXY(cy)
        self.ux, self.uy = cx, cy
        return cx, cy, saturated

    def get_units(self):
        """
        현재 지령값. 하드웨어 되읽기가 아니라 소프트웨어 상태다 (의도적).
        루프마다 시리얼 왕복을 넣으면 지연만 늘고 얻는 게 없다.
        내부 폐루프 서보가 이미 지령을 추종하고 있다.
        """
        return self.ux, self.uy

    def center(self):
        return self.set_units(0.0, 0.0)

    # ----------------------------------------------------------------
    # 캘리브레이션 (mm <-> unit)
    # ----------------------------------------------------------------

    def load_calibration(self):
        if not os.path.exists(self.calib_file):
            print(f"[FSM] 캘리브레이션 파일 없음 ({self.calib_file}). "
                  f"fsm_calibrate.py 를 먼저 실행할 것.")
            return False
        with open(self.calib_file, "r") as f:
            data = json.load(f)
        self.J = np.array(data["J_mm_per_unit"], dtype=float)
        self.Jinv = np.linalg.inv(self.J)
        print(f"[FSM] calibration loaded: J =\n{self.J}")
        return True

    def mm_to_unit(self, dx_mm, dy_mm):
        """PSD 상의 변위(mm)를 만들어내는 데 필요한 unit 지령 변화량."""
        if self.Jinv is None:
            raise RuntimeError("캘리브레이션이 없다. fsm_calibrate.py 먼저 실행.")
        return self.Jinv @ np.array([dx_mm, dy_mm], dtype=float)

    def unit_to_mm(self, du_x, du_y):
        return self.J @ np.array([du_x, du_y], dtype=float)

    # ----------------------------------------------------------------
    # 각도 <-> 지령 (EKF 연동용)
    # ----------------------------------------------------------------

    def rad_to_unit(self, th_x, th_y, L_mm):
        """
        빔 편향각(rad) -> unit 절대 지령.

        th 는 미러 기계각이 아니라 '빔이 꺾이는 각' 이고, PSD 축에 정렬된 좌표계다
        (th_x 가 양이면 PSD 상에서 +X 로 빔이 움직인다). 그래서
            d_mm = th_rad * L_mm
        가 그대로 성립하고, 반사 2배 계수와 FSM/PSD 축 회전은 전부 J 안에 있다.

        units_per_rad() 의 대각 근사와 달리 2x2 J^-1 을 그대로 쓰므로
        축간 커플링이 반영된다. 제어 루프에서는 이쪽을 쓸 것.
        """
        if self.Jinv is None:
            raise RuntimeError("캘리브레이션이 없다. fsm_calibrate.py 먼저 실행.")
        return self.Jinv @ (np.array([th_x, th_y], dtype=float) * L_mm)

    def unit_to_rad(self, ux, uy, L_mm):
        """unit 지령 -> 빔 편향각(rad). rad_to_unit 의 역."""
        if self.J is None:
            raise RuntimeError("캘리브레이션이 없다. fsm_calibrate.py 먼저 실행.")
        return (self.J @ np.array([ux, uy], dtype=float)) / L_mm

    def reachable_rad(self, L_mm):
        """
        max_unit 클램프 안에서 도달 가능한 빔 편향각의 상한 (PSD 축별, rad).
        두 채널을 동시에 레일까지 밀었을 때이므로 최선의 경우다.
        blind 스윕 범위가 물리적으로 말이 되는지 시작할 때 찍어보는 용도.
        """
        if self.J is None:
            raise RuntimeError("캘리브레이션이 없다. fsm_calibrate.py 먼저 실행.")
        return np.abs(self.J) @ np.array([self.max_unit, self.max_unit]) / L_mm

    def units_per_rad(self, L_m, mech=True):
        """
        기하학 기반 근사 환산. 캘리브레이션 J와 교차검증용.

        미러 기계각 Δθ 이면 빔은 2Δθ 로 꺾이므로, 거리 L 에서
            Δd[mm] = 2 · Δθ[rad] · L[mm]
        J 대각성분 [mm/unit] 을 쓰면
            unit/rad = 2 · L[mm] / J_ii
        """
        if self.J is None:
            raise RuntimeError("캘리브레이션이 없다.")
        L_mm = L_m * 1000.0
        k = 2.0 * L_mm if mech else L_mm
        return np.array([k / self.J[0, 0], k / self.J[1, 1]])
