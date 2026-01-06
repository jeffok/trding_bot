# api/main.py
from fastapi import FastAPI
from api.routes import router
from config.settings import settings

app = FastAPI(title=settings.PROJECT_NAME, version="8.3")

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    # 生产环境通常用 docker 启动，这里用于本地测试
    uvicorn.run(app, host="0.0.0.0", port=8000)