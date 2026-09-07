# PAT

연구 작업 저장소.

## 로컬 폴더 구조

이 저장소(`PAT`)는 로컬에서 `pat_ws` 폴더에 클론해서 사용한다.
`pat_legacy`는 이전 담당자의 작업물로, **저장소에 포함하지 않는다** (참고/분석 용도).

```
PAT/                 # 일반 폴더 (git 아님)
├── pat_legacy/      # 이전 작업물 — git 추적 안 함
└── pat_ws/          # 이 저장소 (git 루트)
```

## 새 PC에서 세팅하기

```bash
mkdir -p ~/research/PAT && cd ~/research/PAT
git clone https://github.com/KoshCocna/PAT.git pat_ws
mkdir -p pat_legacy   # 이전 작업물은 따로 복사해서 넣기
```

커밋이 GitHub 프로필에 연결되도록, 새 PC마다 아래 설정을 한 번 실행한다.

```bash
git config --global user.name "KoshCocna"
git config --global user.email "76080450+KoshCocna@users.noreply.github.com"
```

## 일상적인 작업 흐름

```bash
cd pat_ws
git pull            # 작업 시작할 때
# ... 작업 ...
git add -A
git commit -m "메시지"
git push            # 작업 끝낼 때
```

> 여러 PC를 오갈 때는 **시작 전 `git pull`, 끝날 때 `git push`** 를 습관화할 것.

## 코드 구성 (FSM 기반 PAT)

이전 담당자 코드(`../pat_legacy`)는 **Zaber 짐벌 + Newport PSD** 조합이었다.
이 저장소는 액추에이터를 **Optotune MR-E-3 FSM** 으로 바꾼 판이다.

| 파일 | 역할 |
|---|---|
| `psd_conex.py` | Newport CONEX-PSD 읽기 래퍼 |
| `fsm_jog.py` | 키보드로 FSM을 밀며 PSD 반응을 눈으로 확인. **하드웨어 첫 실행용** |
| `fsm_optotune.py` | MR-E-3 액추에이터 레이어 (Zaber `x_axis`/`y_axis` 대체) |
| `fsm_calibrate.py` | FSM unit ↔ PSD mm 2×2 Jacobian 실측 → `fsm_calib.json` |
| `paa_ekf.py` | EKF + PAA. `pat_legacy/v3_paa_ekf_main.py` 에서 그대로 가져옴 |
| `fsm_PID.py` | 나선 스캔 + 폐루프 추적. PID 게인의 단일 출처 |
| `fsm_paa_ekf_main.py` | `v3_paa_ekf_main.py` 의 FSM 이식판 (blind PAA-EKF → PID 추적) |

### 광학 배치 (2026-09-07 확정)

```
TX ──→ FSM ──→ BS ──┬──→ PSD  (피드백 센서, PC 모니터링)
                    └──→ PD   (최종 수신. 현재 단계에서는 사용 안 함)
```

모든 장비는 20×30 cm 보드 위에 놓인다. **FSM이 BS 상류**에 있는 것이 핵심이다.
그래야 FSM 조향이 PSD 갈래에 나타나 폐루프가 성립한다.
FSM을 BS 하류(PD 쪽 갈래)에 두면 FSM을 움직여도 PSD가 반응하지 않아
제어 자체가 불가능하다.

### 현재 단계

**1단계: 오정렬 수동 + FSM 단독 + PD 무시.**
PSD만 보고 "FSM으로 빔이 잡히는가"를 확인하는 것이 목표다.
Zaber 코드는 이 저장소에 없다.

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | PSD 폐루프. PD 무시 | 코드 완료, 하드웨어 미검증 |
| 2 | PD 추가 + setpoint 교정 | 미착수 |
| 3 | Zaber 조동축 + FSM 미동축 | 미착수 |

### 실행 순서

```powershell
# SDK 설치 (PyPI 아님. Optotune Download Center 에서 wheel 을 받는다)
pip install optoKummenberg-<ver>-py3-none-any.whl
pip install optoMDC-<ver>-py3-none-any.whl        # MR-E-3 는 1.3.4781 이상

python fsm_jog.py              # 1. FSM 움직이면 PSD가 따라오는지 눈으로 확인
python fsm_calibrate.py        # 2. J 실측 -> fsm_calib.json
python fsm_PID.py              # 3. 폐루프 추적. PID 튜닝은 여기서
python fsm_paa_ekf_main.py     # 4. blind PAA-EKF 획득 + 추적
```

### 각도 규약

모든 각도는 **빔 편향각** [rad] 이고 원점은 FSM 중앙(u=0), 축은 PSD 에 정렬돼 있다.
미러 기계각이 아니다. 미러 반사의 2배 계수와 FSM/PSD 축 회전은 전부 실측 `J` 안에
들어 있으므로 코드 어디에도 하드코딩된 2가 없다.

```
d_mm  = theta_rad * L_mm        # L = FSM -> BS -> PSD 광 경로 길이 (실측 필요)
d_mm  = J @ du                  # J = fsm_calib.json
```

### 실행 전 확인

- 순서를 지킬 것. `fsm_jog.py` 로 조향이 보이는 걸 확인하지 않고 폐루프로 넘어가면,
  안 될 때 원인이 배선인지 광 경로인지 게인인지 구분이 안 된다.
- `fsm_calibrate.py` 는 FSM 중앙에서 **빔이 이미 PSD 위에 있어야** 시작할 수 있다.
- `fsm_paa_ekf_main.py` 의 blind 스윕은 **X 축 1차원**이다. 수동 오정렬의
  Y 성분은 `PSD_LIMIT / L` 이내여야 한다 (L=200mm 면 ±25 mrad).
- PID 게인은 `fsm_PID.py` 에서만 튜닝한다. 현재 값은 출발점일 뿐 실측 튜닝이 필요하다.
