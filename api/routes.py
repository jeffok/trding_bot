# api/routes.py
import uuid
import json
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from database.db_manager import db
from config.settings import settings, HK_TZ
from config.logging_config import setup_logger
from utils.telegram_bot import tg_bot
from api.dependencies import verify_admin_token, AdminRequest

router = APIRouter()
logger = setup_logger("api_service")
engine = db.get_engine()


def _audit_action(req: AdminRequest, action_type: str, trace_id: str):
    """写 control_commands 表与日志"""
    now_hk = datetime.now(HK_TZ)

    # 1. DB Audit
    stmt = text("""
                INSERT INTO control_commands
                (command_type, params_json, status, actor, reason_code, reason, trace_id, created_at_hk)
                VALUES (:type, :params, 'PROCESSED', :actor, :rcode, :reason, :tid, :ts)
                """)
    try:
        with engine.begin() as conn:
            conn.execute(stmt, {
                "type": action_type,
                "params": json.dumps(req.params),
                "actor": req.actor,
                "rcode": req.reason_code,
                "reason": req.reason,
                "tid": trace_id,
                "ts": now_hk
            })

            # 如果是 HALT/RESUME，同时更新 system_config 以便 Engine 快速读取
            if action_type in ["HALT", "RESUME"]:
                status_val = "TRUE" if action_type == "HALT" else "FALSE"
                conn.execute(text("""
                                  INSERT INTO system_config (key_name, value_json, updated_at_hk, updated_by)
                                  VALUES ('global_halt', :val, :ts, :actor) ON DUPLICATE KEY
                                  UPDATE value_json=:val, updated_at_hk=:ts, updated_by=:actor
                                  """), {"val": json.dumps(status_val), "ts": now_hk, "actor": req.actor})

    except Exception as e:
        logger.error(f"Audit failed: {e}", extra={"action": "AUDIT_FAIL", "reason_code": "DB_ERR", "reason": str(e)})
        raise HTTPException(status_code=500, detail="Audit write failed")

    # 2. Log
    logger.info(f"Admin Action: {action_type}", extra={
        "action": action_type,
        "actor": req.actor,
        "reason_code": req.reason_code,
        "reason": req.reason,
        "trace_id": trace_id
    })

    # 3. Telegram
    tg_bot.send_alert(
        f"👮 Admin Action: {action_type}",
        f"By: {req.actor}\nReason: {req.reason}",
        level="WARNING",
        fields={"code": req.reason_code, "trace": trace_id}
    )


@router.get("/health")
def health_check():
    """V8.3 9.1"""
    # 简单查 DB
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except:
        db_status = "error"

    return {"status": "ok", "db": db_status, "ts": datetime.now(HK_TZ).isoformat()}


@router.post("/admin/halt", dependencies=[Depends(verify_admin_token)])
def halt_system(req: AdminRequest):
    tid = str(uuid.uuid4())
    _audit_action(req, "HALT", tid)
    return {"status": "ok", "trace_id": tid, "message": "Global HALT flag set"}


@router.post("/admin/resume", dependencies=[Depends(verify_admin_token)])
def resume_system(req: AdminRequest):
    tid = str(uuid.uuid4())
    _audit_action(req, "RESUME", tid)
    return {"status": "ok", "trace_id": tid, "message": "Global HALT flag cleared"}


@router.post("/admin/update_config", dependencies=[Depends(verify_admin_token)])
def update_config(req: AdminRequest):
    """通用配置更新"""
    tid = str(uuid.uuid4())
    # 实际逻辑应解析 req.params 中的 key/value 并写入 system_config
    # 这里简化为直接记录 Audit
    _audit_action(req, "UPDATE_CONFIG", tid)

    # 真实写入 system_config
    key = req.params.get("key")
    val = req.params.get("value")
    if key and val:
        with engine.begin() as conn:
            conn.execute(text("""
                              INSERT INTO system_config (key_name, value_json, updated_at_hk, updated_by)
                              VALUES (:k, :v, :ts, :actor) ON DUPLICATE KEY
                              UPDATE value_json=:v, updated_at_hk=:ts, updated_by=:actor
                              """), {"k": key, "v": json.dumps(val), "ts": datetime.now(HK_TZ), "actor": req.actor})

    return {"status": "ok", "trace_id": tid}