# 2026-Ssok-AI
지능형 북마크 서비스 '쏙(Ssok)' AI 레포지토리

## 📌 Git Convention

### 🔵 Commit Convention

- `Feat` : 새로운 기능 추가
- `Fix` : 버그, 오류 해결
- `Modify` : 코드 수정 (기능의 변화가 있을 때)
- `Docs` : README나 WIKI 등의 문서 수정
- `Remove` : 폴더 또는 파일 삭제, 쓸모없는 코드 삭제
- `Rename` : 파일 이름 변경 또는 파일 이동시
- `Refactor` : 기능 추가나 버그 수정이 없는 코드 변경 ( 코드 구조 변경 등의 리팩토링 )
- `Style` : 코드 formatting, 세미콜론 누락, 코드 자체의 변경이 없는 경우
- `Design` : CSS 등 사용자 UI 디자인 변경
- `Chore` : src 또는 test 파일을 수정하지 않는 기타 변경 사항 ( 빌드/패키지 매니저 설정 변경 등 )
- `Merge` : merge 하는 경우
- `Hotfix` : 급하게 치명적인 버그를 고쳐야 하는 경우

### 커밋 예시

- git commit -m "#이슈번호 커밋 태그: 커밋 내용"
    - ex) `git commit -m "#198 Feat: Header 기능 구현"`

<br>

### 🔵 Branch Convention

- `main` : 최종 배포
- `develop` : 주요 개발, main merge 이전에 거치는 branch
- `feat` : 각자 개발, 기능 추가
- `fix` : 에러 수정, 버그 수정
- `docs` : README, 문서
- `refactor` : 코드 리펙토링 (기능 변경 없이 코드만 수정할 때)
- `modify` : 코드 수정 (기능의 변화가 있을 때)

### 브랜치 명 예시

- feat/#이슈번호-기능 이름
    - ex) `feat/#21-header`

<br>

### 🔵 Branch Strategy

- Git-flow 전략을 기반으로 `main`, `dev` 브랜치와 `feat` 보조 브랜치를 운용했습니다.
- `main`, `dev`, `feat` 브랜치로 나누어 개발을 하였습니다.
    - `main` 브랜치는 배포 단계에서만 사용하는 브랜치입니다.
    - `dev` 브랜치는 개발 단계에서 git-flow의 master 역할을 하는 브랜치입니다.
    - `feat` 브랜치는 기능 단위로 독립적인 개발 환경을 위하여 사용하고 merge 후 각 브랜치를 삭제해주었습니다.

<br>

### 🔵 Issue Convention

- [Feat] : 기능 추가
- [Fix] : 에러 및 버그 수정
- [Docs] : README 등 문서
- [Refactor] : 코드 리펙토링 (기능 변경 없이 코드만 수정할 때)
- [Modify] : 코드 수정 (기능의 변화가 있을 때)
- [Chore] : 그 외 작업 내용

### 이슈 명 예시

- [이슈 항목] 개발 내용
    - `ex) [Feat] Header 구현`

<br>