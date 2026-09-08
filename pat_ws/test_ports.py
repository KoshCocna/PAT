"""COM 포트 진단 스크립트"""
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

print("=" * 60)
print("COM 포트 진단")
print("=" * 60)

# PSD 테스트
print("\n[1] PSD (Newport CONEX) 테스트")
for port in ["COM3", "COM6"]:
    try:
        print(f"\n  {port} 시도 중...", end=" ")
        from psd_conex import PSD
        psd = PSD(port=port).open()
        print(f"✓ 성공")
        psd.close()
        print(f"  → PSD는 {port}에 연결됨")
        break
    except Exception as e:
        print(f"✗ 실패: {str(e)[:50]}")

# FSM 테스트
print("\n[2] FSM (Optotune MR-E-3) 테스트")
import optoMDC
for port in ["COM5", "COM7", "COM3", "COM6"]:
    try:
        print(f"\n  {port} 시도 중... (최대 3초 대기)", end=" ", flush=True)
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("연결 타임아웃")

        # Windows에서는 signal.alarm 사용 불가, 다른 방법 사용
        mre = optoMDC.connectmre3(port=port)
        print(f"✓ 성공")
        if hasattr(mre, 'disconnect'):
            mre.disconnect()
        else:
            mre.close()
        print(f"  → FSM은 {port}에 연결됨")
        break
    except Exception as e:
        print(f"✗ 실패: {type(e).__name__}")

print("\n" + "=" * 60)
print("진단 완료")
print("=" * 60)
