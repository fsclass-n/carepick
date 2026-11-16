# carepick

식단 기록과 공공데이터 기반 영양 정보를 함께 보여주는 헬스케어 MVP입니다. 신체 정보와 활동량을 입력하지 않은 경우 **일반 성인 예시**를 표시하고, 입력 시 추정 에너지 소모량에 따른 목표를 계산합니다. 의료적 권고 또는 진단이 아닙니다.

## 구성

- `frontend/`: Vite + React + Tailwind CSS v4, 반응형 홈/로그인/식단/리포트/회원 관리
- `backend/`: FastAPI, Argon2 비밀번호, JWT 인증, OAuth, 식단/회원 관리 API
- `rpa/`: 식품의약품안전처 I2790 공공데이터를 TiDB로 동기화
- `docs/`: 설계, 진행 기록 및 기존 HWPX 원본(원본 수정 없이 보존)

## 로컬 실행

Python 3.11 및 Node.js 24 이상을 사용합니다.

```bash
python -m venv .venv
# Windows Git Bash: .venv/Scripts/python / macOS, Linux: .venv/bin/python
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`의 `DATABASE_URL`을 로컬에서도 TiDB 클러스터 접속 주소로 설정하세요. DB URL에 특수문자가 있는 비밀번호는 percent-encode 해야 합니다. TiDB가 준비되지 않은 개발 환경에서는 `DATABASE_URL=sqlite:///./carepick-dev.db`를 설정하여 UI/API만 확인할 수 있습니다. `.env`가 전혀 없다면 개발 환경에서만 동일한 SQLite 임시 DB를 사용하며, **운영 환경에서는 DATABASE_URL과 JWT_SECRET이 반드시 필요**합니다.

```bash
.venv/Scripts/python -m uvicorn backend.main:app --reload
cd frontend
npm ci
npm run dev
```

프런트엔드: http://localhost:5173, API 문서: http://localhost:8000/docs. Vite 개발 프록시가 `/api` 요청을 로컬 백엔드로 전달합니다. 개발/격리 스테이징 환경에서만 `DEMO_ACCOUNTS_ENABLED=true`로 일반 사용자/관리자 테스트 로그인을 활성화할 수 있습니다. 운영 DB에서는 사용하지 마세요.

식품 데이터를 수집하려면 `.env`에 발급받은 `MFDS_API_KEY`를 넣고 저장소 루트에서 다음을 실행합니다.

```bash
.venv/Scripts/python -m rpa.sync_foods
```

AWS S3는 사용하지 않습니다. 동기화 결과는 TiDB에 저장됩니다.

## 배포

- Netlify: 저장소 루트의 `netlify.toml`을 인식하도록 Git 저장소를 연결합니다. 공개 빌드 변수 `VITE_API_URL=https://carepick-api.onrender.com`이 기본으로 설정되며 대시보드에 다른 값이 있다면 같은 주소로 맞춰야 합니다. `frontend/`나 `netlify.toml` 변경에만 재빌드합니다.
- Render: `render.yaml` Blueprint 또는 Docker Web Service를 사용합니다. 서비스 이름은 `carepick-api`이며 `BACKEND_URL`은 실제 Render 서비스 주소와 일치해야 합니다. `DATABASE_URL`과 OAuth/관리자 환경 변수는 Render 대시보드에 등록합니다. 백엔드 관련 파일 변경 시에만 자동 빌드합니다.
- TiDB: `mysql+pymysql://...` 형식으로 접속하고 서버 인증서 검증을 적용합니다. 비공개 CA를 사용하는 경우 컨테이너에 파일을 제공한 뒤 `TIDB_CA_PATH`를 지정합니다.
- OAuth: 제공자 콘솔에 `https://carepick-api.onrender.com/api/auth/oauth/{google|naver|kakao}/callback`을 각각 등록하고 ID/Secret을 Render에 넣습니다. 설정하지 않은 제공자는 503을 반환합니다. 기존 이메일 계정과 소셜 계정은 자동 연결하지 않습니다.
- 공공데이터 동기화: `.github/workflows/sync-foods.yml`은 매주 실행합니다. GitHub Actions secrets `DATABASE_URL`, `MFDS_API_KEY`를 사전에 등록해야 성공합니다.
- `.env.example` 하단에 Render/Netlify/Actions별 등록 변수를 구분해 두었습니다. `.env` 자체는 절대 커밋하지 않습니다.

예정 배포 주소: [GitHub](https://github.com/fsclass-n/carepick) · [안내 페이지](https://fsclass-n.github.io/carepick/) · [프런트엔드](https://carepick.netlify.app) · [API](https://carepick-api.onrender.com/api/health). 현재 배포 상태는 각각의 대시보드에서 별도로 확인해야 합니다.

## 검증

```bash
.venv/Scripts/python -m pytest -q
cd frontend && npm run build
```

기능/데이터 흐름 및 향후 개인화 목표 산정 계획은 `docs/산출물/서비스_설계서.md`에 정리했습니다.
