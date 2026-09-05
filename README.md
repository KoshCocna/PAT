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
