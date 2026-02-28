from fastapi import FastAPI
from routers import clinic

app = FastAPI()

app.include_router(clinic.router)

