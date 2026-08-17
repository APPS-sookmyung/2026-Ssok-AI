from fastapi import FastAPI
from app.routes import router as ai_router

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

app.include_router(ai_router)