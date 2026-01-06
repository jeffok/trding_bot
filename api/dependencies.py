# api/dependencies.py
from fastapi import Header, HTTPException, Depends
from pydantic import BaseModel
from config.settings import settings

# 简单的静态 Token 验证 (生产环境可接驳 OAuth2 或 Vault)
ADMIN_TOKEN = settings.API_SECRET  # 复用 API Secret 或单独配置


async def verify_admin_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    token = authorization.split(" ")[1]
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


class AdminRequest(BaseModel):
    """V8.3 4.3.2 强制参数"""
    actor: str
    reason_code: str
    reason: str
    params: dict = {}