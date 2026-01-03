"""
用户认证系统
提供单用户密码登录、JWT令牌管理
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..infrastructure.database.session import get_db
from ..infrastructure.config.service import get_config_service
from ..infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


# ==================== 数据模型 ====================

class LoginRequest(BaseModel):
    """登录请求模型"""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)
    remember_me: bool = Field(default=False)


class TokenResponse(BaseModel):
    """令牌响应模型"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict[str, Any]


class UserInfo(BaseModel):
    """用户信息模型"""
    username: str
    is_authenticated: bool = True


# ==================== 配置 ====================

# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT配置
SECRET_KEY = "your-secret-key-change-in-production"  # 实际应从配置读取
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时

# 单用户配置（可存储在数据库或配置文件中）
SINGLE_USER_CONFIG = {
    "username": "admin",
    "password_hash": pwd_context.hash("admin123"),  # 首次使用后应从数据库读取
    "full_name": "系统管理员",
    "email": "admin@quant-bot.com",
    "is_active": True,
    "permissions": ["admin", "trade", "config", "monitor"],
}

# HTTP Bearer认证方案
security_scheme = HTTPBearer(auto_error=False)


# ==================== 工具函数 ====================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def create_access_token(
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None
) -> str:
    """创建JWT访问令牌"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


async def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """用户认证"""
    # 验证用户名
    if username != SINGLE_USER_CONFIG["username"]:
        logger.warning(f"登录失败: 用户名不存在 - {username}")
        return None

    # 验证密码
    if not verify_password(password, SINGLE_USER_CONFIG["password_hash"]):
        logger.warning(f"登录失败: 密码错误 - {username}")
        return None

    # 检查用户是否激活
    if not SINGLE_USER_CONFIG["is_active"]:
        logger.warning(f"登录失败: 用户未激活 - {username}")
        return None

    logger.info(f"用户登录成功: {username}")

    # 返回用户信息（排除敏感字段）
    user_info = SINGLE_USER_CONFIG.copy()
    user_info.pop("password_hash", None)

    return user_info


async def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
        db: Session = Depends(get_db),
) -> UserInfo:
    """
    获取当前认证用户（依赖注入）
    支持Cookie和Bearer Token两种方式
    """
    # 1. 尝试从Authorization头获取
    token = None
    if credentials:
        token = credentials.credentials

    # 2. 尝试从Cookie获取
    if not token:
        token = request.cookies.get("access_token")

    # 3. 尝试从Session获取（向后兼容）
    if not token and "user" in request.session:
        # 这里可以处理旧的Session认证方式
        pass

    if not token:
        logger.debug("未提供认证令牌")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要认证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # 验证JWT令牌
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")

        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证令牌",
            )

        # 验证用户是否存在且激活
        if username != SINGLE_USER_CONFIG["username"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在",
            )

        if not SINGLE_USER_CONFIG["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户未激活",
            )

        # 记录审计日志
        from ..infrastructure.database.models import AuditLog
        audit_log = AuditLog(
            user_identity=f"web:{username}",
            action="AUTH_VALIDATE",
            resource_type="user",
            resource_id=username,
            details={"method": "jwt", "ip": request.client.host},
        )
        db.add(audit_log)
        db.commit()

        return UserInfo(username=username)

    except JWTError as e:
        logger.warning(f"JWT令牌验证失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
        )


async def get_current_active_user(
        current_user: UserInfo = Depends(get_current_user),
) -> UserInfo:
    """获取当前活跃用户（简单包装）"""
    return current_user


# ==================== 路由 ====================

router = APIRouter()


@router.post("/api/auth/login", response_model=TokenResponse)
async def login(
        request: Request,
        login_data: LoginRequest,
        db: Session = Depends(get_db),
):
    """用户登录"""
    # 认证用户
    user = await authenticate_user(login_data.username, login_data.password)
    if not user:
        # 记录失败尝试
        audit_log = AuditLog(
            user_identity=f"web:{login_data.username}",
            action="AUTH_FAILED",
            resource_type="user",
            resource_id=login_data.username,
            details={
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent"),
            },
            status="failed",
            error_message="用户名或密码错误",
        )
        db.add(audit_log)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 创建访问令牌
    access_token_expires = timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES * (30 if login_data.remember_me else 1)
    )
    access_token = create_access_token(
        data={"sub": user["username"], "permissions": user["permissions"]},
        expires_delta=access_token_expires,
    )

    # 记录成功登录
    audit_log = AuditLog(
        user_identity=f"web:{user['username']}",
        action="AUTH_LOGIN",
        resource_type="user",
        resource_id=user["username"],
        details={
            "ip": request.client.host,
            "remember_me": login_data.remember_me,
        },
    )
    db.add(audit_log)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        expires_in=int(access_token_expires.total_seconds()),
        user={
            "username": user["username"],
            "full_name": user["full_name"],
            "email": user["email"],
            "permissions": user["permissions"],
        },
    )


@router.post("/api/auth/logout")
async def logout(
        request: Request,
        current_user: UserInfo = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """用户登出"""
    # 记录登出
    audit_log = AuditLog(
        user_identity=f"web:{current_user.username}",
        action="AUTH_LOGOUT",
        resource_type="user",
        resource_id=current_user.username,
        details={"ip": request.client.host},
    )
    db.add(audit_log)
    db.commit()

    return {"success": True, "message": "登出成功"}


@router.get("/api/auth/me", response_model=Dict[str, Any])
async def get_current_user_info(
        current_user: UserInfo = Depends(get_current_active_user),
):
    """获取当前用户信息"""
    user_info = SINGLE_USER_CONFIG.copy()
    user_info.pop("password_hash", None)

    return {
        "success": True,
        "data": user_info,
    }


@router.post("/api/auth/change-password")
async def change_password(
        old_password: str,
        new_password: str,
        current_user: UserInfo = Depends(get_current_active_user),
        db: Session = Depends(get_db),
):
    """修改密码"""
    # 验证旧密码
    if not verify_password(old_password, SINGLE_USER_CONFIG["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )

    # 更新密码哈希
    new_hash = get_password_hash(new_password)
    # 这里应该将新哈希保存到数据库或配置文件

    # 记录密码修改
    audit_log = AuditLog(
        user_identity=f"web:{current_user.username}",
        action="AUTH_CHANGE_PASSWORD",
        resource_type="user",
        resource_id=current_user.username,
        details={},
    )
    db.add(audit_log)
    db.commit()

    return {"success": True, "message": "密码修改成功"}


# ==================== 页面路由 ====================

@router.get("/login", include_in_schema=False)
async def login_page(request: Request):
    """登录页面"""
    from ..main import app

    # 如果已登录，重定向到仪表盘
    try:
        await get_current_user(request)
        return RedirectResponse(url="/dashboard")
    except HTTPException:
        pass

    # 渲染登录页面
    return app.state.templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "title": "登录"},
    )


@router.get("/logout", include_in_schema=False)
async def logout_page(request: Request):
    """登出页面"""
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")

    # 清除Session（如果有）
    if "user" in request.session:
        request.session.clear()

    return response


def setup_auth(app: FastAPI):
    """设置认证系统"""
    # 这里可以配置JWT密钥等
    global SECRET_KEY

    # 尝试从配置服务获取密钥
    try:
        config_service = get_config_service()
        secret_key = config_service.get_config("web", "secret_key")
        if secret_key:
            SECRET_KEY = secret_key
            logger.info("从配置服务加载JWT密钥")
    except Exception as e:
        logger.warning(f"无法从配置服务加载JWT密钥: {e}")

    # 添加密码重置端点（如果支持）
    # ...