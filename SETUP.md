# 작업용 노트북 셋업 & 첫 테스트

작성 2026-09-08 · 대상: 장비가 연결된 실험용 PC

이 문서 하나만 따라가면 클론부터 폐루프 추적까지 간다.
막히면 각 단계의 **막혔을 때** 를 볼 것.

> **참고할 것 없는 이야기**: 개발용 노트북과 똑같은 환경을 만들 필요는 없다.
> 개발용은 Python 3.14 에 하드웨어 라이브러리가 없는 상태이고, 여기서는
> 벤더 SDK 가 도는 게 우선이라 **Python 3.12** 를 쓴다.

---

## Phase 0 — 시작 전 확인

| 항목 | 확인 |
|---|---|
| Optotune MR-E-3 컨트롤러 + 미러 헤드 | USB 케이블, 전원 |
| Newport CONEX-PSD | USB 케이블 |
| TX 레이저 | 전원, 안전 |
| BS, 미러 마운트, 광학 보드 | |
| 자 또는 캘리퍼스 | `L` 실측용 |
| 뷰어 카드 / IR 뷰어 | 빔 경로 확인용 (파장에 따라) |

> **레이저 안전.** 정렬 중에는 빔 높이에 눈이 가지 않도록 하고, 필요하면 보안경을 쓸 것.
> FSM 은 소프트웨어로 빔을 예고 없이 크게 흔든다 — 특히 `fsm_jog.py` 와 blind 스윕.

---

## Phase 1 — 소프트웨어 환경

### 1-1. Python 설치

**64-bit Python 3.12** 를 설치한다. python.org 의 "Windows installer (64-bit)".

- **64-bit 여야 한다.** CONEX DLL 이 `GAC_64` 에 있는 .NET 64-bit 어셈블리다.
- 3.13 / 3.14 도 될 수는 있지만 벤더 SDK 에서 검증되지 않았다. 3.12 가 안전하다.
- 설치할 때 "Add python.exe to PATH" 체크.

### 1-2. 저장소 클론

```powershell
mkdir ~\research\PAT
cd ~\research\PAT
git clone https://github.com/KoshCocna/PAT.git pat_ws
cd pat_ws
```

git 계정 설정을 아직 안 했다면 (커밋할 계획이면):

```powershell
git config --global user.name "KoshCocna"
git config --global user.email "76080450+KoshCocna@users.noreply.github.com"
```

### 1-3. 가상환경

전역에 깔면 나중에 버전 충돌을 되돌리기 어렵다.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

**막혔을 때** — `Activate.ps1` 이 실행 정책 때문에 막히면:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

프롬프트 앞에 `(.venv)` 가 붙으면 성공. **이후 모든 명령은 이 상태에서 실행한다.**
새 터미널을 열 때마다 `.venv\Scripts\Activate.ps1` 를 다시 해야 한다.

### 1-4. pip 패키지

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

numpy, matplotlib, pythonnet, zaber-motion, keyboard, scipy, pyserial 이 깔린다.

### 1-5. Optotune SDK (PyPI 에 없음)

<https://www.optotune.com/software-download> 에서 MR-E-3 용 Python SDK 를 받는다.
압축을 풀면 wheel 두 개가 있다. **순서가 중요하다** (`optoMDC` 가 `optoKummenberg` 에 의존).

```powershell
python -m pip install optoKummenberg-<버전>-py3-none-any.whl
python -m pip install optoMDC-<버전>-py3-none-any.whl
```

MR-E-3 지원은 **optoMDC 1.3.4781 이상**. 더 낮은 버전이면 MR-E-3 를 못 잡는다.

### 1-6. Newport CONEX-PSD 소프트웨어

CONEX-PSD 설치 프로그램을 돌린다. 설치되면 .NET 어셈블리가 GAC 에 등록되고
`psd_conex.py` 가 그걸 직접 참조한다. 별도 pip 설치는 없다.

### 1-7. 환경 점검

```powershell
python check_env.py
```

Python 버전/아키텍처, 패키지 7종, CONEX DLL 경로, COM 포트를 한 번에 본다.
**하드웨어를 건드리지 않는다.** "막는 문제 없음" 이 나올 때까지 여기서 반복한다.

**막혔을 때**

| 증상 | 대응 |
|---|---|
| `optoMDC` FAIL | 1-5 를 안 했거나 venv 밖에 깔았다. `(.venv)` 프롬프트 확인 |
| `check_env.py` 자체가 안 돌아감 | 표준 라이브러리만 쓰므로 Python 설치 문제다. 1-1 확인 |
| CONEX DLL 을 못 찾음 | 스크립트가 GAC 를 뒤져 다른 버전 경로를 찾아준다. 나오면 `psd_conex.py` 의 `DLL_PATH` 를 그 경로로 수정 |
| `clr` import 실패 | `pip install pythonnet`. 그래도 안 되면 .NET Framework 4.x 런타임 확인 |
| `clr.AddReference` 만 실패 | pythonnet 이 .NET Core 를 물었을 수 있다. `$env:PYTHONNET_RUNTIME="netfx"` 후 재시도 |
| 32-bit Python 경고 | 64-bit 로 다시 설치 |

---

## Phase 2 — 장비 연결

### 2-1. USB 연결 & 포트 확인

MR-E-3 와 CONEX-PSD 를 USB 로 연결하고:

```powershell
python check_env.py
```

"4. COM 포트" 에 두 장치가 보여야 한다. 설명 문자열로 어느 쪽이 CONEX 인지 판단한다.
헷갈리면 한쪽 USB 를 뺐다 꽂으며 목록 변화를 본다.

### 2-2. 포트 번호 반영

포트 설정은 **한 곳뿐이다.** `psd_conex.py` 상단의 `DEFAULT_PORT` (기본 `"COM6"`) 를
실제 포트로 고치면 모든 스크립트에 반영된다.

```python
# psd_conex.py
DEFAULT_PORT = "COM6"      # <- 여기만 고친다
```

FSM 은 `fsm_optotune.py` 의 `DEFAULT_PORT = None` 으로 자동 탐색한다.
자동 탐색이 실패할 때만 포트를 지정한다.

### 2-3. 연결 확인

```powershell
python check_env.py --connect
```

**FSM 이 중앙(u = 0)으로 이동한다.** PSD 읽음값과 광량, FSM 연결 상태를 출력한다.
"캘리브레이션 없음" 은 이 시점에 정상이다.

---

## Phase 3 — 광학 정렬

소프트웨어보다 이쪽이 오래 걸린다. 자세한 근거는 [OPTICS.md](OPTICS.md).

### 3-1. 배치

```
TX ──→ FSM(45°) ──→ BS ──┬──→ PSD   (피드백)
                         └──→ PD    (1단계 미사용)
```

**FSM 이 BS 상류에 있어야 한다.** 하류에 두면 FSM 을 움직여도 PSD 가 반응하지 않아
제어가 성립하지 않는다.

### 3-2. 미러 각도

- 미러면이 입사빔·반사빔과 각각 **45°**. **법선이 두 빔을 이등분**하면 맞다.
- **이 45° 가 `u = 0` 이어야 한다.** FSM 을 소프트웨어로 중앙에 보낸 상태
  (`check_env.py --connect` 직후가 그 상태다)에서 기구적으로 45° 를 맞춘다.
- `u = 0` 에서 빔이 미러 **중심**에 오도록 높이와 좌우를 맞춘다.
- FSM 채널 축 하나를 보드면과 나란하게 클로킹한다 (`J` 가 거의 대각이 된다).

### 3-3. PSD 에 빔 올리기

FSM 중앙 상태에서 빔이 **PSD 중앙 근처**에 오도록 BS 와 PSD 를 조정한다.
`check_env.py --connect` 로 읽음값을 보면서 맞추면 편하다. 목표는 `(0, 0)` 근처, 광량 충분.

> 이게 `fsm_calibrate.py` 의 전제조건이다. FSM 중앙에서 빔이 PSD 밖에 있으면
> 캘리브레이션을 시작할 수 없다.

### 3-4. L 실측

FSM → BS → PSD **접힌 경로 전체 길이** 를 잰다. BS 는 경로를 꺾을 뿐이라 그대로 더한다.

```
L = (FSM→BS) + (BS→PSD)
```

메모해 둔다. 지금은 코드에 넣지 않아도 된다 (Phase 4 에서 안 쓴다).

---

## Phase 4 — 소프트웨어 검증

**순서를 지킬 것.** 건너뛰면 안 될 때 원인이 배선인지 광 경로인지 게인인지 구분이 안 된다.

### 4-1. 조향이 보이는가 — `fsm_jog.py`

```powershell
python fsm_jog.py
```

그래프 창을 클릭해 포커스를 준 뒤:

| 키 | 동작 |
|---|---|
| `←` `→` | FSM x 채널 |
| `↑` `↓` | FSM y 채널 |
| `[` `]` | 스텝 크기 ÷2, ×2 |
| `0` | 중앙 복귀 |
| `m` | 기준점 마킹 |
| `q` / `esc` | 종료 |

**할 일**: 먼저 `→` 를 여러 번 눌러 스팟이 움직이는지 본다. 안 움직이면 `]` 로 스텝을
키워가며 반응이 나올 때까지 올린다. 반응이 보이면 **두 축 모두** 양·음 방향으로
충분히 밀어본다 (J 추정에 두 축 표본이 다 필요하다).

**종료 시 출력** — 여기서 나오는 값이 이후 모든 판단의 기준이다:

| 값 | 정상 범위 | 의미 |
|---|---|---|
| 응답 SNR | > 10 | 낮으면 FSM 이 PSD 에 영향 없음 |
| 축 독립성 | > 0.9 | 낮으면 두 축이 겹침 |
| cond(J) | **1.4 근처** | 45° 입사의 이득 비대칭. 정상이다 |
| 감도 mm/unit | — | **기록할 것.** 미러 헤드 스케일 |
| 권장 DELTA | — | 다음 단계 참고값 |

**막혔을 때 — "FSM 이 PSD 스팟에 사실상 영향을 주지 않는다"**

스크립트가 원인 4가지를 출력한다. 순서대로 확인:
1. FSM 이 BS 하류에 있지 않은가 (배치 문제)
2. FSM 반사광이 PSD 갈래로 실제로 가는가 (광 경로 막힘/이탈)
3. optoMDC 채널 배선, `SetControlMode(XY)` 가 걸렸는가
4. 조그 범위가 너무 작지 않은가 (`]` 로 키워 재시도)

### 4-2. J 실측 — `fsm_calibrate.py`

```powershell
python fsm_calibrate.py
```

가진 크기(DELTA)를 자동으로 맞추고 2×2 Jacobian 을 재서 `fsm_calib.json` 을 만든다.
마지막에 검증 스텝까지 돈다.

**확인할 것**

| 출력 | 판정 |
|---|---|
| 자동 레인징 확정 DELTA | 4-1 의 권장값과 자릿수가 비슷하면 정상 |
| 축 독립성 | 0.3 이상. 0.1 미만이면 실패로 중단된다 |
| cond(J) | 1.4 근처 |
| unit 당 빔 편향각 | **기록할 것** (L=4m 가정 출력이므로 실제 L 로 환산 필요) |
| 검증 오차 | 목표의 10% 이내면 정상 |

**막혔을 때**

| 증상 | 대응 |
|---|---|
| "빔이 PSD 범위를 벗어남" 반복 | 3-3 으로 돌아가 FSM 중앙에서 빔을 PSD 중앙에 다시 올릴 것 |
| "DELTA_MAX 까지 키워도 변위 없음" | 4-1 과 같은 문제. 광 경로/배선 |
| "J 가 특이행렬에 가깝다" | 두 축이 겹친다. 클로킹과 채널 배선 확인 |
| 광량 경고 | 빔 정렬 또는 레이저 출력 확인 |

### 4-3. 폐루프 추적 — `fsm_PID.py`

```powershell
python fsm_PID.py
```

**여기까지가 "FSM 으로 제어가 되네" 의 확인 지점이다.**
빔이 PSD 에 있으면 바로 추적으로 들어가고, 없으면 나선 스캔으로 찾는다.

**확인할 것**

- 스팟이 PSD 원점으로 수렴하는가
- 정착 후 `|e|` 가 얼마인가 (µm 단위면 성공)
- **루프 주파수 (Hz)** — 출력 줄 끝에 나온다. **기록할 것.** CONEX 시리얼이 병목이라
  100~200 Hz 예상. 이 값이 이 시스템의 실질 대역폭 상한이다
- 보드를 살짝 건드려 외란을 줬을 때 다시 잡는가

**PID 튜닝은 여기서 한다.** `fsm_PID.py` 상단의 `KP`, `KI`, `KD` 가 단일 출처다
(다른 스크립트가 여기서 가져다 쓴다). 현재 값 `0.35 / 1.5 / 0.002` 는 시뮬레이션
기준일 뿐이므로 실측 튜닝이 필요하다:

1. `KI = KD = 0` 으로 두고 `KP` 를 진동 직전까지 올린다
2. 그 값의 **0.4 ~ 0.5 배** 로 낮춘다
3. `KI` 를 올려 정상상태 오차를 잡는다
4. `KD` 는 PSD 노이즈를 증폭하므로 마지막에 최소한만

**막혔을 때**

| 증상 | 원인 |
|---|---|
| 발산한다 | `KP` 가 너무 크거나, `J` 가 잘못됐다 (4-2 축 독립성 확인) |
| 한 방향으로 밀려나 `SAT` | `J` 부호/축 문제. 4-2 재실행 |
| 느리게 수렴 | `KP` 를 올린다 |
| 정상상태 오차가 남음 | `KI` 를 올린다 |
| 떨린다 | `KD` 를 줄이거나 `D_LPF_HZ` 를 낮춘다 |

---

## Phase 5 — 여기서 멈춘다

**1단계 목표는 4-3 까지다.** blind PAA-EKF (`fsm_paa_ekf_main.py`) 는 아직 돌리지 않는다.
그전에 두 상수를 실측값으로 갱신해야 하기 때문이다:

| 상수 | 현재 | 필요 |
|---|---|---|
| `L_M` | `4.0` | Phase 3-4 에서 잰 값 (미터) |
| `MISALIGN_NOMINAL_RAD` | `25e-3` | `L` 과 FSM 가동범위 확정 후 재산정 |

두 번째가 특히 중요하다. `L` 이 짧으면 25 mrad 오정렬이 **PSD 안쪽**에 들어와서
blind 단계가 시작하자마자 끝나 무의미해진다. 예를 들어 `L = 175 mm` 면
25 mrad → 4.4 mm 로 PSD(±5mm) 안이다. `L` 과 4-1 의 감도가 나오면 다시 정한다.

---

## 기록해서 넘길 값

Phase 4 를 마치면 아래를 정리해 둘 것. 이 값들로 남은 상수를 확정한다.

```
L (FSM→BS→PSD)      :        mm
감도 (mm/unit)       :             (fsm_jog 종료 출력)
축 독립성            :             (fsm_jog / fsm_calibrate)
cond(J)             :
J 행렬              :             (fsm_calib.json)
루프 주파수          :        Hz   (fsm_PID 출력)
정착 후 |e|          :        mm
튜닝된 KP/KI/KD      :
FSM 가동범위 (실측)   :        mrad (u=±0.8 에서의 빔 편향각)
```

---

## 관련 문서

- [README.md](README.md) — 저장소 개요, 파일 구성
- [OPTICS.md](OPTICS.md) — 미러 각도 근거, 두 축 이득 비대칭, 마운팅 상세
- [STATUS.md](STATUS.md) — 프로젝트 현황, 설계 결정, 이식하면서 고친 것
