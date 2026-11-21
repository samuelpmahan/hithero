"""Endpoints the external cron service calls to start the scheduled jobs."""

import threading

from fastapi import APIRouter, Depends, HTTPException, Request

from config import settings
from jobs import daily_job, thursday_job, tuesday_job, wednesday_job

router = APIRouter()


###cronjob ip white list
CRONJOB_ALLOWED_IPS = {
    "116.203.129.16",
    "116.203.134.67",
    "23.88.105.37",
    "128.140.8.200",
    "91.99.23.109",
}

######   EMAILER FUNCTIONS FOR CRONJOBS  ###########
def verify_cronjob_request(request: Request):
    secret = request.headers.get("x-secret-key")
    if not secret or secret != settings.internal_job_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

@router.post("/internal/run-wednesday-job")
async def run_wednesday_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=wednesday_job, daemon=True).start()
    return {"status": "wednesday job started"}

@router.post("/internal/run-tuesday-job")
async def run_tuesday_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=tuesday_job, daemon=True).start()
    return {"status": "tuesday job started"}

@router.post("/internal/run-thursday-job")
async def run_thursday_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=thursday_job, daemon=True).start()
    return {"status": "thursday job started"}

@router.post("/internal/run-daily-job")
async def run_daily_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=daily_job, daemon=True).start()
    return {"status": "daily job started"}
