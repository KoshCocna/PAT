# PAT 시스템 설정 작업 로그

**날짜**: 2026-09-08
**작업자**: Claude Code
**목적**: Optotune MR-E-3 FSM 및 Newport CONEX-PSD 환경 설정 및 초기 테스트

---

## 1. 초기 문제 상황

### 1.1 환경 점검 결과
- **Python 버전**: 3.13.7 (64-bit)
- **문제점**: `optoMDC` 패키지 누락으로 FSM 연결 실패
- **에러 메시지**:
  ```
  ModuleNotFoundError: No module named 'optoMDC'
  ```

---

## 2. optoMDC SDK 설치

### 2.1 필요 패키지
- **optoKummenberg**: 1.0.5422 (의존성)
- **optoMDC**: 1.3.5434 (MR-E-3 지원, 최소 1.3.4781 이상 필요)

### 2.2 설치 방법
```bash
pip install optoKummenberg-1.0.5422-py3-none-any.whl
pip install optoMDC-1.3.5434-py3-none-any.whl
```

**다운로드 출처**: https://www.optotune.com/software-download/

### 2.3 확인
```bash
python -c "import optoMDC; print(optoMDC.__version__)"
# 출력: 1.3.5434
```

---

## 3. 코드 수정 사항

### 3.1 fsm_optotune.py 수정

#### 문제 1: 잘못된 API 사용
**원인**: optoMDC v1.3.x는 `connect()` 대신 `connectmre3()` 사용

**수정 전** (`fsm_optotune.py:70-72`):
```python
if self.port:
    self.mre = optoMDC.connect(port=self.port)
else:
    self.mre = optoMDC.connect()      # 자동 탐색
```

**수정 후**:
```python
if self.port:
    self.mre = optoMDC.connectmre3(port=self.port)
else:
    self.mre = optoMDC.connectmre3()      # 자동 탐색
```

#### 문제 2: 잘못된 객체 경로
**원인**: MRE3Board 객체 구조에 `Mirror` 속성이 없음

**수정 전** (`fsm_optotune.py:75-76`):
```python
for ch, attr in ((self.mre.Mirror.Channel_0, "si_0"),
                 (self.mre.Mirror.Channel_1, "si_1")):
```

**수정 후**:
```python
for ch, attr in ((self.mre.Channel_0, "si_0"),
                 (self.mre.Channel_1, "si_1")):
```

### 3.2 fsm_jog.py 수정

#### 문제: Windows 터미널 UTF-8 인코딩 오류
**원인**: `—` (em dash, U+2014) 문자를 CP949 코덱이 인코딩 불가

**수정** (`fsm_jog.py:32-39` 추가):
```python
import sys
import io

# Windows 터미널 UTF-8 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
```

---

## 4. COM 포트 매핑

### 4.1 하드웨어 구성
3개의 USB 장비가 연결됨:
1. TX Laser
2. FSM (Optotune MR-E-3)
3. PSD (Newport CONEX-PSD10GE)

### 4.2 초기 COM 포트 감지
```
COM3: Newport AG-UC2-UC8 USB Serial Port
COM5: USB Serial Port (FTDI VID:0403:6001)
COM6: USB 직렬 장치 (STMicro VID:0483:A31E)
COM7: USB Serial Port (FTDI VID:0403:6015)
```

### 4.3 물리적 확인 결과
장치 관리자에서 USB 케이블을 하나씩 제거/추가하며 확인:

| 장비 | COM 포트 | 하드웨어 ID |
|------|----------|-------------|
| TX Laser | COM7 | FTDI (VID:0403:6015) |
| FSM (MR-E-3) | COM6 | STMicro (VID:0483:A31E) |
| PSD (CONEX) | COM5 | FTDI (VID:0403:6001) |

### 4.4 포트 설정

**psd_conex.py:16**:
```python
DEFAULT_PORT = "COM5"
```

**fsm_optotune.py:29**:
```python
DEFAULT_PORT = "COM6"
```

---

## 5. 연결 테스트 결과

### 5.1 PSD 연결
```bash
python -c "from psd_conex import PSD; psd = PSD().open(); print('PSD OK'); psd.close()"
```
**결과**: ✅ 성공
```
[PSD] connected on COM5
PSD OK
```

### 5.2 FSM 연결
```bash
python -c "from fsm_optotune import OptotuneFSM; fsm = OptotuneFSM().connect(); print('FSM OK'); fsm.close()"
```
**결과**: ✅ 성공
```
[FSM] 캘리브레이션 파일 없음 (fsm_calib.json). fsm_calibrate.py 를 먼저 실행할 것.
[FSM] MR-E-3 connected, closed-loop XY mode, centered
FSM OK
[FSM] disconnected
```

---

## 6. fsm_jog.py 실행 결과

### 6.1 실행 성공
```bash
cd pat_ws
python fsm_jog.py
```

**결과**: ✅ GUI 창 열림, 키보드 제어 가능

### 6.2 조작 테스트
**제어 명령**:
- `← →`: FSM x 채널 조정
- `↑ ↓`: FSM y 채널 조정
- `0`: 중앙 복귀
- `m`: 현재 위치 마킹
- `q`: 종료

**첫 번째 정렬 시도**:
- FSM: `u = (+0.071, +0.028)`
- PSD: `(+0.198, -0.085) mm`, power = 15.00 ✅

### 6.3 발견된 문제점

**재현성 이슈**:
1. FSM을 `u = (+0.071, +0.028)`로 조정 → PSD power = 15 (성공)
2. `0` 키로 중앙 복귀 (`u = (0, 0)`)
3. 다시 같은 위치 `u = (+0.071, +0.028)`로 이동
4. **결과**: PSD `(-5, -5) mm`, power = 0 (빔 손실)

**가능한 원인**:
- FSM 히스테리시스
- 개루프 제어의 한계 (폐루프 제어 필요)
- FSM 상태 불일치
- PSD 읽기 오류

**권장 조치**:
- `fsm_calibrate.py` 실행하여 Jacobian 캘리브레이션 완료
- `fsm_PID.py` 폐루프 제어로 전환

---

## 7. 생성된 진단 스크립트

### 7.1 test_ports.py
각 COM 포트에서 PSD와 FSM을 자동으로 찾는 진단 스크립트

### 7.2 find_fsm_port.py
FSM 포트를 빠른 타임아웃으로 탐색하는 스크립트

---

## 8. 다음 단계

### 8.1 캘리브레이션 (필수)
```bash
python fsm_calibrate.py
```
- Jacobian 행렬 측정
- `fsm_calib.json` 생성

### 8.2 폐루프 제어 테스트
```bash
python fsm_PID.py
```
- PID 제어로 빔 안정화
- 재현성 개선

### 8.3 확인 사항
- [ ] FSM 물리적 동작 육안 확인
- [ ] 캘리브레이션 완료
- [ ] 폐루프 제어 안정성 확인
- [ ] 장시간 드리프트 측정

---

## 9. 요약

### 9.1 성공 항목
✅ optoMDC SDK 설치 완료
✅ fsm_optotune.py API 수정
✅ UTF-8 인코딩 문제 해결
✅ COM 포트 올바르게 매핑
✅ PSD 연결 성공 (COM5)
✅ FSM 연결 성공 (COM6)
✅ fsm_jog.py 실행 성공
✅ FSM 키보드 제어 가능

### 9.2 남은 이슈
⚠️ FSM 재현성 문제 (개루프 제어의 한계)
⚠️ 캘리브레이션 미완료

### 9.3 수정된 파일
1. `pat_ws/fsm_optotune.py` - API 수정, COM 포트 설정
2. `pat_ws/psd_conex.py` - COM 포트 설정
3. `pat_ws/fsm_jog.py` - UTF-8 인코딩 설정
4. `pat_ws/test_ports.py` - 생성 (진단용)
5. `pat_ws/find_fsm_port.py` - 생성 (진단용)

---

**문서 작성일**: 2026-09-08
**환경**: Windows 10/11, Python 3.13.7
**상태**: 초기 설정 완료, 캘리브레이션 대기 중
