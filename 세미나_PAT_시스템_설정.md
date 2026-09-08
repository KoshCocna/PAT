# PAT 시스템 초기 설정 및 테스트

**날짜**: 2026-09-08
**발표자**: [이름]
**주제**: Optotune FSM 기반 빔 조향 시스템 구축

---

## 1. 프로젝트 개요

### 시스템 구성
- **TX Laser**: 송신 레이저 (COM7)
- **FSM**: Optotune MR-E-3 Fast Steering Mirror (COM6)
- **PSD**: Newport CONEX-PSD 위치 감지기 (COM5)

### 목표
빔 조향을 위한 FSM 제어 시스템 구축 및 폐루프 제어 준비

---

## 2. 초기 문제 상황

### 환경 점검 실패
```
ModuleNotFoundError: No module named 'optoMDC'
```

**원인**:
- optoMDC SDK가 PyPI에 없음 (수동 설치 필요)
- Python 3.13.7 사용 중 (벤더 SDK 미검증 버전)

---

## 3. 해결 과정 (1) - SDK 설치

### optoMDC 설치
**출처**: https://www.optotune.com/software-download/

**설치 순서** (중요!):
```bash
pip install optoKummenberg-1.0.5422-py3-none-any.whl
pip install optoMDC-1.3.5434-py3-none-any.whl
```

**요구사항**:
- MR-E-3 장비는 optoMDC 1.3.4781 이상 필요
- optoKummenberg 의존성 먼저 설치

**결과**: ✅ optoMDC 1.3.5434 설치 성공

---

## 4. 해결 과정 (2) - API 수정

### 문제 1: 잘못된 함수명
**오류**:
```python
AttributeError: module 'optoMDC' has no attribute 'connect'
```

**수정**:
```python
# 수정 전
self.mre = optoMDC.connect()

# 수정 후
self.mre = optoMDC.connectmre3()  # MR-E-3 전용 함수
```

---

## 5. 해결 과정 (3) - 객체 구조

### 문제 2: 잘못된 객체 경로
**오류**:
```python
AttributeError: 'MRE3Board' object has no attribute 'Mirror'
```

**수정**:
```python
# 수정 전
for ch in (self.mre.Mirror.Channel_0, self.mre.Mirror.Channel_1):

# 수정 후
for ch in (self.mre.Channel_0, self.mre.Channel_1):
```

---

## 6. 해결 과정 (4) - COM 포트 매핑

### 초기 혼란
- 4개의 COM 포트 감지
- 어떤 장비가 어느 포트인지 불명확
- PSD와 FSM이 같은 포트(COM6) 사용 시도 → 충돌

### 물리적 확인 방법
**장치 관리자에서 USB 케이블을 하나씩 제거/추가**

| 장비 | COM 포트 | 하드웨어 ID |
|------|----------|-------------|
| TX Laser | COM7 | FTDI VID:0403:6015 |
| FSM | COM6 | STMicro VID:0483:A31E |
| PSD | COM5 | FTDI VID:0403:6001 |

---

## 7. 해결 과정 (5) - 인코딩 문제

### Windows 터미널 UTF-8 오류
**오류**:
```
UnicodeEncodeError: 'cp949' codec can't encode character '\u2014'
```

**원인**: em dash (—) 문자를 CP949가 인코딩 불가

**해결**:
```python
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        errors='replace'
    )
```

---

## 8. 연결 테스트 결과

### PSD 연결
```bash
python -c "from psd_conex import PSD; psd = PSD().open()"
```
**결과**: ✅ `[PSD] connected on COM5`

### FSM 연결
```bash
python -c "from fsm_optotune import OptotuneFSM; fsm = OptotuneFSM().connect()"
```
**결과**: ✅ `[FSM] MR-E-3 connected, closed-loop XY mode, centered`

---

## 9. fsm_jog.py 실행

### GUI 조작 인터페이스
![FSM Jog Screenshot](placeholder)

**키보드 제어**:
- `← →`: FSM x 채널 조정
- `↑ ↓`: FSM y 채널 조정
- `0`: 중앙 복귀
- `m`: 현재 위치 마킹
- `q`: 종료

---

## 10. 초기 정렬 테스트

### 성공 사례
**FSM 위치**: `u = (+0.071, +0.028)`
**PSD 읽기**: `(+0.198, -0.085) mm`, power = 15.00 ✅

### 발견된 문제: 재현성
1. 첫 시도: power = 15 (성공)
2. 중앙 복귀 (`u = 0, 0`)
3. 같은 위치로 재이동 (`u = +0.071, +0.028`)
4. **결과**: PSD `(-5, -5) mm`, power = 0 ❌ (빔 손실)

---

## 11. 재현성 문제 분석

### 가능한 원인
1. **개루프 제어의 한계**
   - FSM 히스테리시스
   - 경로 의존성

2. **캘리브레이션 미완료**
   - Jacobian 행렬 없음
   - unit ↔ mm 변환 불가

3. **열적 드리프트**
   - 시간에 따른 위치 변화

### 해결 방향
→ **폐루프 PID 제어 필요**

---

## 12. 작성된 진단 도구

### test_ports.py
각 COM 포트에서 PSD와 FSM 자동 탐색

### find_fsm_port.py
3초 타임아웃으로 FSM 포트 빠른 검색

### SETUP_LOG.md
전체 작업 과정 상세 문서화

---

## 13. 다음 단계

### 1단계: 캘리브레이션 (필수)
```bash
python fsm_calibrate.py
```
- Jacobian 행렬 측정
- `fsm_calib.json` 생성
- FSM unit ↔ PSD mm 관계 확립

### 2단계: 폐루프 제어
```bash
python fsm_PID.py
```
- PID 제어로 빔 위치 안정화
- 드리프트 보상
- 재현성 향상

---

## 14. 프로젝트 관리

### Git 저장소
**GitHub**: https://github.com/KoshCocna/PAT

**커밋 내역**:
- 초기 설정 및 optoMDC 설치
- API 수정 (connectmre3, Channel 경로)
- UTF-8 인코딩 추가
- COM 포트 설정
- 진단 스크립트 추가

### 폴더 구조
```
PAT/
├── SETUP_LOG.md     # 작업 로그
└── pat_ws/          # 소스 코드
    ├── fsm_optotune.py
    ├── psd_conex.py
    ├── fsm_jog.py
    ├── fsm_calibrate.py
    ├── fsm_PID.py
    └── ...
```

---

## 15. 주요 성과

### ✅ 완료 항목
1. optoMDC SDK 설치 및 검증
2. FSM API 수정 완료
3. COM 포트 올바르게 매핑
4. PSD/FSM 연결 성공
5. GUI 조작 도구 작동 확인
6. 문제점 파악 (재현성)

### ⚠️ 남은 과제
1. Jacobian 캘리브레이션
2. 폐루프 PID 제어 구현
3. 장시간 안정성 테스트
4. 드리프트 특성 측정

---

## 16. 교훈 및 팁

### 1. SDK 설치
- PyPI에 없는 패키지는 공식 웹사이트 확인
- 의존성 순서 중요 (optoKummenberg → optoMDC)

### 2. COM 포트 매핑
- 장치 관리자 + 물리적 제거/추가로 확인
- 하드웨어 ID (VID:PID) 기록 필수

### 3. API 버전 차이
- 공식 문서와 실제 API가 다를 수 있음
- `dir()` 함수로 객체 구조 확인

### 4. Windows 인코딩
- UTF-8 설정 필수 (특수문자 출력 시)

---

## 17. 질문 및 토론

### Q&A

**Q1**: Python 3.13에서 문제 발생 가능성은?
**A**: 현재까지 작동하나, 문제 발생 시 3.12로 다운그레이드 권장

**Q2**: FSM 재현성을 높이려면?
**A**: 캘리브레이션 + 폐루프 PID 제어 필수

**Q3**: 다른 FSM 장비에도 적용 가능한가?
**A**: Optotune MR-E-2는 `connectmre2()` 사용, API 일부 상이

---

## 감사합니다!

**참고 자료**:
- GitHub: https://github.com/KoshCocna/PAT
- 작업 로그: [SETUP_LOG.md](https://github.com/KoshCocna/PAT/blob/main/SETUP_LOG.md)
- Optotune: https://www.optotune.com/

**연락처**: [이메일/연구실]
