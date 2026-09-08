"""
PAA-EKF (Point-Ahead Angle + Extended Kalman Filter)

pat_legacy/v3_paa_ekf_main.py 의 ExtendedKalmanFilter 를 그대로 옮긴 것.
액추에이터에 의존하지 않는 순수 추정 로직이라 Zaber -> FSM 이식과 무관하게
원본을 유지한다. (수정하지 말 것. 고칠 일이 생기면 여기서 고치고 이유를 적을 것.)

각도 규약 (이식하면서 확정한 것)
--------------------------------
상태 theta 는 "빔 편향각(beam deflection angle)" [rad] 이고, FSM 중앙(u=0)이 원점이다.
미러 기계각이 아니다. 빔 편향각을 쓰면
    d_mm = theta_rad * L_mm          (L = FSM -> PSD 광 경로 길이)
가 그대로 성립하고, 미러 반사의 2배 계수는 fsm_calib.json 의 J 안에 이미
녹아 있으므로 코드 어디에도 하드코딩된 2가 남지 않는다.

주의: omega_virtual 상쇄 (원본 동작)
------------------------------------
predict() 는 x[0] 에 x[2]*dt (상태 전이) 와 omega_virtual*dt (가상 궤도운동) 를
둘 다 더한다. 따라서 x[2] 를 -omega_virtual 로 초기화하면 두 항이 정확히
상쇄되어 blind 표적이 전혀 움직이지 않고, get_paa() 도 0 을 돌려준다.
원본 v3 는 x[2] = -7.5e-3, omega_virtual = +7.5e-3 이라 실제로 이 상태였다
(원본은 표적이 이미 시야에 있어서 blind 가 즉시 끝났으므로 드러나지 않았다).
FSM 판에서는 blind 스윕이 실제로 필요하므로 초기 omega 를 0 으로 둔다.
자세한 것은 fsm_paa_ekf_main.py 의 EKF_INIT_OMEGA 주석 참고.
"""

import numpy as np


class ExtendedKalmanFilter:
    """
    4D EKF for fixed plate position estimation
    State: [θ_plate_az, θ_plate_el, ω_plate_az, ω_plate_el]

    Virtual orbital motion injection:
    - omega_virtual: LEO relative angular velocity (7.5 mrad/s)
    - Emulates moving target scenario
    - Can be disabled for tracking phase
    """

    def __init__(self, dt=0.01, omega_virtual=7.5e-3, tau_virtual=3.3e-3):
        self.dt = dt
        self.omega_virtual = omega_virtual  # Virtual angular velocity (rad/s)
        self.tau_virtual = tau_virtual      # Virtual propagation delay (s)
        self.virtual_motion_enabled = True  # Can be toggled

        # State: [θ_az, θ_el, ω_az, ω_el]
        self.x = np.zeros(4)

        # Initial covariance (large uncertainty)
        self.P = np.diag([
            (25e-3)**2,   # θ_az: 25 mrad (TLE-like error)
            (25e-3)**2,   # θ_el
            (1e-3)**2,    # ω_az: 1 mrad/s
            (1e-3)**2     # ω_el
        ])

        # State transition matrix (Constant Velocity)
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])

        # Process noise
        self.Q = np.diag([
            (50e-6)**2,   # Position noise
            (50e-6)**2,
            (10e-6)**2,   # Velocity noise
            (10e-6)**2
        ])

        # Measurement matrix (position only)
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ])

        # Measurement noise
        self.R = np.diag([
            (20e-6)**2,   # 20 µrad
            (20e-6)**2
        ])

    def predict(self, dt=None):
        """
        Prediction with optional virtual orbital motion injection
        """
        if dt is not None:
            self.dt = dt
            self.F[0, 2] = dt
            self.F[1, 3] = dt

        # Standard EKF predict
        self.x = self.F @ self.x

        # Add virtual orbital motion (only if enabled)
        if self.virtual_motion_enabled:
            self.x[0] += self.omega_virtual * self.dt  # Azimuth
            # self.x[1] += 0.0 * self.dt  # Elevation (if needed)

        # Covariance update
        self.P = self.F @ self.P @ self.F.T + self.Q

        return self.x.copy()

    def update(self, z):
        """
        Measurement update
        z: [θ_plate_az_measured, θ_plate_el_measured]
        """
        # Innovation
        y = z - self.H @ self.x

        # Innovation covariance
        S = self.H @ self.P @ self.H.T + self.R

        # Kalman gain
        K = self.P @ self.H.T @ np.linalg.inv(S)

        # Update state
        self.x = self.x + K @ y

        # Update covariance
        I = np.eye(4)
        self.P = (I - K @ self.H) @ self.P

        return self.x.copy()

    def get_paa(self):
        """
        Calculate Point-Ahead Angle
        PAA = (ω_estimated + ω_virtual) × tau (only when virtual motion enabled)
        """
        if self.virtual_motion_enabled:
            omega_total_az = self.x[2] + self.omega_virtual
            omega_total_el = self.x[3]
        else:
            # No virtual motion in tracking phase
            omega_total_az = self.x[2]
            omega_total_el = self.x[3]

        paa_az = omega_total_az * self.tau_virtual
        paa_el = omega_total_el * self.tau_virtual

        return np.array([paa_az, paa_el])

    def enable_virtual_motion(self):
        """Enable virtual motion for blind acquisition"""
        self.virtual_motion_enabled = True

    def disable_virtual_motion(self):
        """Disable virtual motion for tracking phase"""
        self.virtual_motion_enabled = False

    def reset(self):
        """Reset EKF state"""
        self.x = np.zeros(4)
        self.P = np.diag([
            (25e-3)**2,
            (25e-3)**2,
            (1e-3)**2,
            (1e-3)**2
        ])
        self.virtual_motion_enabled = True


