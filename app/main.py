# app/main.py
from fastapi import FastAPI
from app.routes import router as ai_router

app = FastAPI(
    title="AI Bookmark Core API (No DB Mode)",
    description="URL 요약 및 태깅 테스트용 서버",
    version="1.0.0"
)

app.include_router(ai_router)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Server is running without DB."}