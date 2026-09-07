# PAT 프로젝트 현황

**작성일** 2026-09-07 · **기준 커밋** `ae4d2c8` (origin/main 동기화 완료)

이 문서는 "지금 어디까지 왔고, 무엇이 결정됐고, 다음에 뭘 해야 하는가"를 정리한 것이다.
사용법과 실행 순서는 [README.md](README.md) 에 있다.

---

## 1. 한 줄 요약

이전 담당자의 **Zaber 짐벌 + Newport PSD** 기반 PAT 코드를 **Optotune MR-E-3 FSM** 기반으로
이식했다. 1단계 구성(오정렬 수동 + FSM 단독)으로 코드는 완성됐고 시뮬레이션 검증까지 끝났으나,
**실제 하드웨어에서는 아직 한 번도 돌려보지 않았다.**

---

## 2. 폴더 구조와 현재 위치

```
C:\Users\licsk\research\PAT\
├── pat_legacy\     17개 파일 (.py 16개, 5,614줄)   이전 담당자 작업물. git 추적 안 함
└── pat_ws\         .py 6개 (1,434줄) + README/STATUS  이 저장소 (github.com/KoshCocna/PAT)
```

`pat_legacy` 는 원래 `C:\Users\licsk\Downloads\PAT_zaber-main\` 에 있던
`github.com/imgunkim99/PAT_zaber` 의 zip 다운로드본이다. 오늘 옮겨왔고 Downloads 쪽은 비웠다.
`.gitignore` 에 `pat_legacy/` 가 들어 있어 저장소에 포함되지 않는다.

### pat_legacy 주요 파일 (참고용)

| 파일 | 내용 |
|---|---|
| `v3_paa_ekf_main.py` (720줄) | **이식의 원본.** blind PAA-EKF + PID 추적 |
| `newport_PIDv3.py` | PSD + Zaber 폐루프 추적. `fsm_PID.py` 의 원본 |
| `paa_ekf_main.py`, `v2_...`, `v3_time-dist_...` | v3 이전 버전들 |
| `goto_position.py`, `goto_mis_position.py`, `mov_PAT_home.py` | Zaber homing 전용. FSM 판에서는 **전부 폐기** |
| `newport.py`, `newport_scan*.py`, `KF_PID.py` | 스캔 / 칼만 실험 코드 |

---

## 3. 저장소 구성 (pat_ws)

| 파일 | 줄 | 역할 |
|---|---|---|
| `psd_conex.py` | 74 | CONEX-PSD10GE 읽기 래퍼. `read()` / `read_avg(n)` |
| `fsm_optotune.py` | 210 | MR-E-3 액추에이터 레이어. Zaber `x_axis`/`y_axis` 대체 |
| `fsm_calibrate.py` | 204 | FSM unit ↔ PSD mm 2×2 Jacobian 실측 → `fsm_calib.json` |
| `paa_ekf.py` | 168 | EKF + PAA. `v3_paa_ekf_main.py` 에서 **그대로** 분리 |
| `fsm_PID.py` | 277 | 나선 스캔 + 폐루프 추적. **PID 게인의 단일 출처** |
| `fsm_paa_ekf_main.py` | 501 | `v3_paa_ekf_main.py` 의 FSM 이식판 |

의존 관계:

```
fsm_paa_ekf_main.py ──┬── fsm_optotune.py ── optoMDC (Optotune SDK)
                      ├── psd_conex.py ───── clr → Newport.CONEXPSD DLL
                      ├── paa_ekf.py
                      └── fsm_PID.py (PID2D 클래스 + 게인 상수)

fsm_calibrate.py ─────┬── fsm_optotune.py
                      └── psd_conex.py
```

---

## 4. 확정된 설계 결정

### 4-1. 구성 단계 (사용자 결정)

장기적으로는 **Zaber 조동축 + FSM 미동축 2단 구성**이 실제 PAT 표준이고 실험의 독립성도
확보된다. 다만 지금은 초기 단계라 결합도를 낮추기로 했다.

| 단계 | 오정렬 생성 | 획득 | 추적 | 상태 |
|---|---|---|---|---|
| **1단계 (현재)** | 사람이 수동 | FSM | FSM | 코드 완료, 하드웨어 미검증 |
| 2단계 (예정) | Zaber 조동 | Zaber + FSM | FSM 미동 | 미착수 |

현재 저장소에 **Zaber 코드는 한 줄도 없다.**

### 4-2. 각도 규약 — 이식의 핵심

모든 각도를 **빔 편향각(beam deflection angle)** 으로 통일했다.
원점은 FSM 중앙(u=0), 축은 PSD 에 정렬(θ_x 가 양이면 PSD 상에서 빔이 +X).

```
d_mm  = theta_rad * L_mm        # L = FSM → PSD 광 경로 길이 (4 m)
d_mm  = J @ du                  # J = fsm_calib.json, [mm per unit]
─────────────────────────────────────────────────────────────
du    = J^-1 @ (theta * L_mm)   # fsm.rad_to_unit()
```

**왜 중요한가.** 미러 기계각을 쓰면 반사 때문에 `d = 2·θ_mech·L` 이 되어 곳곳에 2가 붙는다.
빔 편향각을 쓰면 `d = θ·L` 이 그대로 성립하고, **반사 2배 계수와 FSM/PSD 축 회전·반전이
전부 실측 J 안에 흡수되어** 코드 어디에도 하드코딩된 2가 남지 않는다.

> **9/4 분석 내용 정정.** 그때 "`PSD_SENSITIVITY = 250e-6` → `125e-6` 으로 바꿔야 한다"고
> 적었는데, 그건 지령을 미러 **기계각**으로 줄 때의 이야기다. 지금처럼 정규화 unit + 실측 J
> 를 쓰면 그 상수 자체가 필요 없어서 **삭제했다**. (250e-6 = 1/4000mm 로 위 식의 `1/L_mm`
> 과 같은 값이다.)

이것이 원본의 `scale_factor = 0.1` 과 `y_adjust = -y_pid.output` (부호 감으로 뒤집기)를
대체한다.

### 4-3. 지령 방식

| | Zaber (원본) | FSM (현재) |
|---|---|---|
| 제어 출력 | 증분 `new = get_position() + adjust` | **절대 지령** `u = Kp·e + Ki·∫e + Kd·de/dt` |
| 위치 되읽기 | 매 루프 시리얼 왕복 | 불필요 (내부 폐루프 서보, 소프트웨어 상태 유지) |
| 정상상태 유지 | 기구 위치 자체 | PID 의 I항 |
| anti-windup | 없음 (느려서 안 보였음) | **필수** (`I_LIMIT` + 포화 시 적분 정지) |

### 4-4. blind acquisition (사용자 결정: 원본 유지)

EKF 가상 궤도운동 + PAA 로 표적 방향을 예측하며 스윕하는 원본 로직을 그대로 살렸다.
`fsm_PID.py` 의 나선 스캔은 별도 스크립트로 남아 있고, `fsm_paa_ekf_main.py` 는 쓰지 않는다.

---

## 5. 이식하면서 고친 것 5가지

### (1) EKF 초기 각속도를 0으로 — 원본의 상쇄 버그

`predict()` 는 `x[0]` 에 상태 전이 `x[2]·dt` 와 가상 궤도운동 `omega_virtual·dt` 를 **둘 다**
더한다. 원본은 `x[2] = -7.5e-3`, `omega_virtual = +7.5e-3` 이라 두 항이 정확히 상쇄된다.

```
순 스윕 속도 = x[2] + omega_virtual = -7.5e-3 + 7.5e-3 = 0
PAA         = (x[2] + omega_virtual) · tau = 0
```

즉 **blind 표적이 전혀 움직이지 않고 PAA 도 0** 이었다. 원본은 Zaber 를 HOME 으로 보내면
표적이 이미 시야 안에 있어 blind 가 즉시 끝났기 때문에 드러나지 않았다.
수동 오정렬 상태에서는 스윕이 실제로 필요하므로 `EKF_INIT_OMEGA = (0.0, 0.0)` 으로 두었다.
→ 순 스윕 속도 `+7.5 mrad/s`, PAA `24.75 µrad`.

### (2) blind 스윕 레일 반전

스윕이 FSM 가동범위 끝(`max_unit = 0.8`)에 닿으면 원본 로직은 거기서 **영원히 멈춘다.**
연속 포화가 `SWEEP_SAT_STREAK = 10` 회를 넘으면 `omega_virtual` 부호를 뒤집고, EKF 추정치를
실제 인가된 지령으로 되돌려 왕복하게 했다.

### (3) 재획득 루프

원본 `phase_tracking()` 은 빔 로스 시 `"Returning to BLIND phase..."` 를 출력하고 `False` 를
반환하는데, `run()` 이 그걸 받아서 **그냥 종료한다** (메시지와 동작 불일치).
메시지가 말하는 대로 blind 로 되돌아가도록 `run()` 에 루프를 넣었다.

### (4) 캘리브레이션 자동 레인징

`fsm_calibrate.py` 의 고정값 `DELTA = 0.05` 는 **첫 실행이 거의 확실히 실패한다.**
장착된 미러 헤드의 unit 당 편향각을 아직 모르는데, 감도가 조금만 높아도 가진 즉시 빔이
PSD(±5mm) 밖으로 나간다. `DELTA_START = 0.002` 에서 시작해 PSD 변위가 `TARGET_MM = 2.5mm`
근처가 되도록 스스로 맞추는 방식으로 교체했다. 강제 지정하려면 `DELTA` 에 숫자를 넣으면 된다.

### (5) PID 교체

원본 `PIDController` (증분형, `scale_factor = 0.1`, y축 부호 수동 반전, 미분 필터 없음, dt 무시)
→ `fsm_PID.py` 의 `PID2D` (절대 지령형, 2×2 J⁻¹, anti-windup, 미분 1차 LPF, 실측 dt).

---

## 6. 검증 현황

**이 PC(licsk 노트북)에는 실험 하드웨어도 파이썬 과학 스택도 없다.**
기본 python 3.14 에 numpy 조차 없다. 그래서 scratchpad 에 numpy 를 따로 설치하고,
`optoMDC` / `clr`(CONEX) / `matplotlib` 를 스텁으로 갈아끼운 뒤 플랜트를 시뮬레이션했다.

```
플랜트:  PSD 변위[mm] = (theta_cmd - theta_true) · L_mm
         theta_cmd    = J @ u / L_mm
         PSD 노이즈    = 2 µm RMS
```

### 통과한 항목

| 항목 | 결과 |
|---|---|
| 추적 수렴 (오정렬 +25 mrad) | 잔류 RMS **1.84 µm**, 0.05mm 진입 401 스텝 |
| 추적 수렴 (오정렬 −20 mrad) | 잔류 RMS **1.86 µm**, 0.05mm 진입 407 스텝 |
| J⁻¹ 정확도 | 최종 지령이 해석해 `J⁻¹@[100, 4]mm = (0.24481, −0.034571)` 와 자릿수까지 일치 → 축간 커플링 보상 정상 |
| 레일 반전 경로 | 스윕 반대방향 오정렬에서 반전 후 획득 성공 |
| 빔 로스 → 재획득 | tracking → BEAM LOST → blind 재스윕 → BEAM DETECTED → 재수렴 전 구간 |
| 캘리브레이션 자동 레인징 | 감도 **4 / 400 / 5000 mm/unit** 세 시나리오 모두 J 복원 상대오차 **0.25% 이내**, 3·2·2회 반복으로 수렴 |
| 캘리브레이션 검증 스텝 | 목표 변위 0.5mm 지령에 대해 실측 오차 0.002mm 이내 |

### 검증되지 않은 것 — 중요

- **실제 하드웨어 전부.** optoMDC 연결, `SetControlMode(Units.XY)`, `StaticInput.SetXY()` 의
  실제 동작, CONEX DLL 경로, COM 포트 번호 어느 것도 확인 못 했다.
- **optoMDC 종료 메서드 이름.** SDK 버전마다 `disconnect` / `close` 로 갈려서
  [fsm_optotune.py](fsm_optotune.py) 에서 둘 다 시도하도록 처리해 뒀다.
- **MR-15-30 미러 헤드 스펙.** 데이터시트 PDF 파싱에 실패해서 편향 범위·대역폭 수치를
  인용하지 못했다. `SCAN_MAX = 0.6`, `max_unit = 0.8` 같은 값은 보유 헤드에 맞춰 조정 필요.
- **PID 게인.** 시뮬레이션 플랜트 기준으로만 확인된 값이다. 실측 튜닝 필요.
- **실제 루프 주파수.** 시뮬레이션은 100Hz 로 돌았지만, 실기에서는 CONEX 의 `GP()` 시리얼
  왕복이 병목이라 100~200Hz 정도로 예상된다.

---

## 7. 현재 설정값

### fsm_paa_ekf_main.py

| 상수 | 값 | 비고 |
|---|---|---|
| `PSD_PORT` | `"COM6"` | 원본과 동일 |
| `FSM_PORT` | `None` | 자동 탐색 |
| `L_M` | `4.0` m | **J 를 측정한 그 배치여야 한다** |
| `SAMPLING_INTERVAL` | `0.01` s | 100Hz 목표 |
| `PSD_LIMIT` | `5.0` mm | |
| `DETECTION_THRESHOLD` | `5.0` | 광량 |
| `BEAM_LOSS_STREAK` | `20` | ≈200ms 연속 로스 시 blind 복귀 |
| `OMEGA_VIRTUAL` | `7.5e-3` rad/s | LEO 상대 각속도. 원본 유지 |
| `TAU_VIRTUAL` | `3.3e-3` s | LEO 전파 지연. 원본 유지 |
| `EKF_INIT_THETA` | `(0.0, 0.0)` | FSM 중앙 = 공칭 정렬 방향 |
| `EKF_INIT_OMEGA` | `(0.0, 0.0)` | **원본은 `(-7.5e-3, 0)`. 5-(1) 참고** |
| `SWEEP_SAT_STREAK` | `10` | 레일 반전 임계 |
| `SWEEP_HINT_AFTER` | `2` | 반전 2회 후 진단 출력 |
| `MISALIGN_NOMINAL_RAD` | `25e-3` | 안내 출력용 |

### fsm_PID.py (PID 게인 단일 출처)

| 상수 | 값 | 비고 |
|---|---|---|
| `KP` / `KI` / `KD` | `0.35` / `1.5` / `0.002` | **무차원. 출발점일 뿐** |
| `D_LPF_HZ` | `40.0` Hz | 미분항 저역통과 |
| `I_LIMIT` | `0.6` unit | 적분 클램프 |
| `SCAN_STEP` / `SCAN_MAX` / `SCAN_DWELL` | `0.02` / `0.6` / `0.01` | 나선 스캔 |

> Zaber 판 게인 `P=0.15, I=0.03, D=0.005` + `scale_factor=0.1` 은 **차원이 있는 게인**
> (mm 입력 → degree 출력)이었다. 지금은 오차를 액추에이터 unit 으로 환산해 넣으므로
> 게인이 **무차원**이 되고 값이 완전히 달라진다. 그대로 쓰면 안 된다.

### fsm_calibrate.py

| 상수 | 값 |
|---|---|
| `DELTA` | `None` (자동 레인징) |
| `DELTA_START` / `MIN` / `MAX` | `0.002` / `1e-5` / `0.5` |
| `TARGET_MM` | `2.5` mm |
| `AUTORANGE_TRIES` | `12` |
| `SETTLE` / `N_AVG` | `0.15` s / `30` |

### fsm_optotune.py

| 상수 | 값 | 비고 |
|---|---|---|
| `max_unit` | `0.8` | 레일 여유. 1.0 이면 포화 복구가 어렵다 |

---

## 8. 알려진 제약

### 8-1. blind 스윕은 X축 1차원 — 가장 걸리기 쉬운 함정

원본이 az 축만 흔들었던 것을 그대로 유지했다. 따라서 **수동 오정렬의 Y 성분**은

```
|theta_y| <= PSD_LIMIT / L_mm = 5mm / 4000mm = 1.25 mrad
```

이내여야 한다. 넘으면 X 를 아무리 훑어도 빔이 PSD 세로 범위 안으로 안 들어와서
**blind 가 영원히 끝나지 않는다.** 시뮬레이션 검증 중에 실제로 이 케이스에 걸렸다.

대응으로 X 가동범위를 전부 훑고도(반전 2회) 못 찾으면 원인 두 가지를 짚어주는 진단 메시지를
출력하게 해 뒀다. 2D 탐색이 필요해지면 `fsm_PID.py` 의 나선 스캔을 가져다 쓰면 된다.

### 8-2. 기타

- `fsm_calibrate.py` 는 **FSM 중앙(u=0)에서 빔이 이미 PSD 위에 있어야** 시작할 수 있다.
- 오정렬의 X 성분은 FSM 가동범위 이내여야 한다. 시작 시 도달 가능 각도를 출력한다.
- CONEX 시리얼 왕복이 대역폭 병목이다. MR-E-3 는 kHz급인데 Python 루프로는 그 장점을
  다 못 쓴다. 대역폭이 정말 필요하면 **CONEX 아날로그 출력 → MR-E-3 아날로그 입력**
  (`ch.Analog.SetAsInput()`)으로 하드웨어 루프를 구성하고 Python 은 게인 설정·모니터링만
  하는 선택지가 있다.

---

## 9. 다음에 할 일

### 랩 PC에서 (하드웨어 필요)

1. **SDK 설치** — PyPI 아님. Optotune Download Center 에서 wheel 을 받는다.
   MR-E-3 는 `optoMDC` **1.3.4781 이상**.
   ```powershell
   pip install optoKummenberg-<ver>-py3-none-any.whl
   pip install optoMDC-<ver>-py3-none-any.whl
   ```
2. **COM 포트 확인** — PSD `COM6` 은 원본에서 가져온 값. FSM 은 자동 탐색이지만 실패하면
   `FSM_PORT` 에 명시.
3. **`python fsm_calibrate.py`** — 가장 먼저. 여기서 나오는 값이 이후 모든 판단의 기준이다.
   - `cond(J)` 가 10 이하인지 (넘으면 축간 커플링이 심하거나 한 축 감도가 낮다)
   - **`unit 당 빔 편향각 [mrad/unit]`** ← 미러 헤드 실제 스케일. 이 값을 알아야
     `SCAN_MAX`, `max_unit`, PID 게인 출발점을 제대로 잡을 수 있다
   - 검증 스텝 오차가 목표의 10% 이내인지
4. **`python fsm_PID.py`** — 나선 스캔 + 추적만 먼저. PAA-EKF 없이 루프가 도는지,
   실제 루프 주파수가 몇 Hz 인지 확인. **PID 튜닝은 여기서 한다.**
   - `KI = KD = 0` 으로 두고 `KP` 를 진동 직전까지 올린 뒤 그 값의 0.4~0.5배로 낮춘다
   - 그다음 `KI` 를 올려 정상상태 오차를 잡는다
   - `KD` 는 PSD 노이즈를 증폭하므로 마지막에 최소한만
5. **`python fsm_paa_ekf_main.py`** — blind PAA-EKF 획득까지 포함한 전체 흐름.
   수동 오정렬 시 8-1 의 Y 제약을 지킬 것.

### 이후 단계

6. **2단계 구성** — Zaber 조동축 복원. `pat_legacy` 의 `goto_position.py` /
   `mov_PAT_home.py` homing 자산을 되살려 오정렬 생성과 초기 획득을 Zaber 가 맡고,
   FSM 은 미동 추적만 담당하게 한다.
7. 필요 시 2D 나선 스캔을 blind 단계에 통합 (8-1 제약 해소).

---

## 10. 참고

- 원본 저장소: https://github.com/imgunkim99/PAT_zaber
- 이 저장소: https://github.com/KoshCocna/PAT
- Optotune MR-E-3: https://www.optotune.com/product/mr-e-3/
- optoMDC 사용 예시: https://github.com/QI2lab/mcSIM/blob/master/mcsim/expt_ctrl/setup_optotune_mre2.py
