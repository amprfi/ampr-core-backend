from fastapi import FastAPI, Depends
from src.api.auth.router import router as auth_router
from src.api.dependencies import get_authenticated_session

app = FastAPI()

app.include_router(auth_router, prefix="/auth", tags=["auth"])

@app.get("/")
async def root():
    return {"message": "Hello World"}