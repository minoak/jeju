# 프론트(web/) + API(app/server.py)를 한 컨테이너에서 서빙 — Render 무료 티어 배포용
FROM python:3.12-slim
WORKDIR /app

# 의존성 먼저 (레이어 캐시: 코드만 바뀌면 재설치 안 함)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 + 데이터(chroma_smoke, data/processed 등) 복사 — .dockerignore 가 불필요/비밀 파일 제외
COPY . .

# Render 는 리슨 포트를 $PORT 로 주입한다. 로컬 도커 테스트는 기본 8000.
ENV PORT=8000
EXPOSE 8000

# shell 형태 CMD: ${PORT} 환경변수 확장을 위해 (exec 형태 [".."] 는 확장 안 됨)
CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT}"]
