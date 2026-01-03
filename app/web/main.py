"""
FastAPI Web应用主入口
集成所有路由、中间件、异常处理
"""

import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from .auth import get_current_user, setup_auth
from .middleware import (
    LoggingMiddleware,
    SecurityHeadersMiddleware,
    DatabaseSessionMiddleware
)
from .routes import (
    auth as auth_router,
    dashboard as dashboard_router,
    trading_pair as trading_pair_router,
    config as config_router,
    policy as policy_router,
    monitor as monitor_router,
    log as log_router,
    control as control_router,
)
from ..infrastructure.database.session import db_manager
from ..infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    - 启动时初始化
    - 关闭时清理
    """
    # 启动时
    logger.info("🚀 Web应用启动中...")

    # 初始化数据库连接（如果还没初始化）
    try:
        from ..infrastructure.config.service import get_config_service
        from ..infrastructure.config.crypto_util import CryptoUtil

        # 这里可以初始化一些全局服务
        logger.info("应用服务初始化完成")
    except Exception as e:
        logger.error(f"应用启动初始化失败: {e}")

    yield

    # 关闭时
    logger.info("🛑 Web应用关闭中...")
    db_manager.dispose_pool()
    logger.info("数据库连接池已释放")


def create_app() -> FastAPI:
    """
    创建并配置FastAPI应用实例
    """
    app = FastAPI(
        title="量化交易系统管理后台",
        description="自动化交易系统的Web管理界面",
        version="2.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ==================== 中间件配置 ====================

    # CORS（如果需要前端独立部署）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],  # 前端开发地址
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 信任主机头
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "quant-bot.example.com"],
    )

    # GZip压缩
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 自定义中间件
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(DatabaseSessionMiddleware)

    # ==================== 静态文件和模板 ====================

    # 挂载静态文件
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    # 创建模板引擎（全局可用）
    templates = Jinja2Templates(directory="app/web/templates")
    app.state.templates = templates

    # ==================== 全局异常处理 ====================

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
            request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """请求验证异常处理"""
        logger.warning(f"请求验证失败: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "message": "请求参数验证失败",
                "errors": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(
            request: Request, exc: Exception
    ) -> JSONResponse:
        """全局异常处理"""
        logger.error(f"未处理的异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "服务器内部错误",
                "detail": str(exc) if app.debug else "Internal Server Error",
            },
        )

    # ==================== 初始化认证系统 ====================

    setup_auth(app)

    # ==================== 路由注册 ====================

    # 公开路由（无需认证）
    app.include_router(auth_router.router, prefix="", tags=["认证"])

    # 需要认证的路由
    protected_routers = [
        (dashboard_router.router, "", "仪表盘"),
        (trading_pair_router.router, "/trading-pair", "交易对管理"),
        (config_router.router, "/config", "配置管理"),
        (policy_router.router, "/policy", "执行策略"),
        (monitor_router.router, "/monitor", "监控"),
        (log_router.router, "/log", "日志"),
        (control_router.router, "/control", "交易控制"),
    ]

    for router, prefix, tag in protected_routers:
        app.include_router(
            router,
            prefix=prefix,
            tags=[tag],
            dependencies=[Depends(get_current_user)],  # 需要认证
        )

    # ==================== 根路径和健康检查 ====================

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        """根路径重定向到仪表盘"""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard")

    @app.get("/health")
    async def health_check() -> Dict[str, Any]:
        """健康检查端点"""
        db_healthy = db_manager.health_check()

        return {
            "status": "healthy" if db_healthy else "degraded",
            "version": app.version,
            "database": "connected" if db_healthy else "disconnected",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    @app.get("/version")
    async def version_info() -> Dict[str, str]:
        """版本信息"""
        return {
            "name": app.title,
            "version": app.version,
            "description": app.description,
        }

    logger.info("✅ FastAPI应用配置完成")
    return app


# 创建应用实例
app = create_app()

if __name__ == "__main__":
    """开发环境直接运行"""
    uvicorn.run(
        "app.web.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )