"""
交易对管理路由
实现完整的CRUD和三级筛选功能
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from ..auth import get_current_user
from ...infrastructure.database.session import get_db
from ...infrastructure.database.models import (
    TradingPair, AccountType, AssetAccount, ExecutionPolicy
)
from ...infrastructure.logging.logger import get_logger
from ...services.trading_pair_service import TradingPairService

logger = get_logger(__name__)
router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def trading_pair_list_page(
        request: Request,
        exchange: Optional[str] = Query(None),
        account_type: Optional[str] = Query(None),
        enabled_only: bool = Query(True),
        current_user=Depends(get_current_user),
):
    """交易对列表页面"""
    from ...main import app

    # 获取所有交易所和账户类型用于筛选
    db = next(get_db())

    # 获取所有唯一的交易所
    exchanges = db.query(TradingPair.exchange).distinct().all()
    exchanges = [e[0] for e in exchanges]

    # 获取所有账户类型
    account_types = [t.value for t in AccountType]

    # 获取执行策略用于关联显示
    policies = db.query(ExecutionPolicy).filter_by(is_active=True).all()

    return app.state.templates.TemplateResponse(
        "trading_pair/list.html",
        {
            "request": request,
            "title": "交易对管理",
            "exchanges": exchanges,
            "account_types": account_types,
            "selected_exchange": exchange,
            "selected_account_type": account_type,
            "enabled_only": enabled_only,
            "policies": policies,
        },
    )


@router.get("/api/trading-pairs", response_model=Dict[str, Any])
async def get_trading_pairs_api(
        exchange: Optional[str] = Query(None),
        account_type: Optional[str] = Query(None),
        enabled_only: bool = Query(True),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """获取交易对列表（API）"""
    service = TradingPairService(db)

    # 构建查询条件
    filters = []
    if exchange:
        filters.append(TradingPair.exchange == exchange)
    if account_type:
        filters.append(TradingPair.account_type == account_type)
    if enabled_only:
        filters.append(TradingPair.is_enabled == True)

    # 执行查询
    total, trading_pairs = service.get_trading_pairs(
        filters=filters,
        page=page,
        page_size=page_size,
    )

    # 转换为字典
    pairs_data = []
    for pair in trading_pairs:
        pair_dict = {
            "id": pair.id,
            "base_symbol": pair.base_symbol,
            "exchange": pair.exchange,
            "account_type": pair.account_type.value,
            "exchange_symbol": pair.exchange_symbol,
            "is_enabled": pair.is_enabled,
            "config": pair.config or {},
            "description": pair.description,
            "created_at": pair.created_at.isoformat() if pair.created_at else None,
            "updated_at": pair.updated_at.isoformat() if pair.updated_at else None,
        }
        pairs_data.append(pair_dict)

    return {
        "success": True,
        "data": {
            "items": pairs_data,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@router.get("/create", response_class=HTMLResponse)
async def create_trading_pair_page(
        request: Request,
        current_user=Depends(get_current_user),
):
    """创建交易对页面"""
    from ...main import app

    db = next(get_db())

    # 获取所有账户用于关联
    accounts = db.query(AssetAccount).filter_by(is_active=True).all()

    # 获取所有执行策略
    policies = db.query(ExecutionPolicy).filter_by(is_active=True).all()

    return app.state.templates.TemplateResponse(
        "trading_pair/edit.html",
        {
            "request": request,
            "title": "创建交易对",
            "trading_pair": None,
            "accounts": accounts,
            "policies": policies,
            "account_types": [t.value for t in AccountType],
            "exchanges": ["binance", "bybit", "okx", "huobi"],  # 支持的交易所
        },
    )


@router.get("/{pair_id}/edit", response_class=HTMLResponse)
async def edit_trading_pair_page(
        request: Request,
        pair_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """编辑交易对页面"""
    from ...main import app

    # 获取交易对
    trading_pair = db.query(TradingPair).filter_by(id=pair_id).first()
    if not trading_pair:
        raise HTTPException(status_code=404, detail="交易对不存在")

    # 获取所有账户
    accounts = db.query(AssetAccount).filter_by(is_active=True).all()

    # 获取所有执行策略
    policies = db.query(ExecutionPolicy).filter_by(is_active=True).all()

    return app.state.templates.TemplateResponse(
        "trading_pair/edit.html",
        {
            "request": request,
            "title": f"编辑交易对 - {trading_pair.base_symbol}",
            "trading_pair": trading_pair,
            "accounts": accounts,
            "policies": policies,
            "account_types": [t.value for t in AccountType],
            "exchanges": ["binance", "bybit", "okx", "huobi"],
        },
    )


@router.post("/api/trading-pairs", response_model=Dict[str, Any])
async def create_trading_pair_api(
        base_symbol: str = Form(...),
        exchange: str = Form(...),
        account_type: str = Form(...),
        exchange_symbol: str = Form(...),
        is_enabled: bool = Form(True),
        config: Optional[str] = Form("{}"),
        description: Optional[str] = Form(None),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """创建交易对（API）"""
    import json

    try:
        # 验证账户类型
        if account_type not in [t.value for t in AccountType]:
            raise HTTPException(status_code=400, detail="无效的账户类型")

        # 验证配置JSON
        config_dict = {}
        if config:
            try:
                config_dict = json.loads(config)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="配置必须是有效的JSON")

        # 检查是否已存在
        existing = db.query(TradingPair).filter_by(
            base_symbol=base_symbol,
            exchange=exchange,
            account_type=account_type,
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail="交易对已存在")

        # 创建交易对
        trading_pair = TradingPair(
            base_symbol=base_symbol,
            exchange=exchange,
            account_type=account_type,
            exchange_symbol=exchange_symbol,
            is_enabled=is_enabled,
            config=config_dict,
            description=description,
        )

        db.add(trading_pair)
        db.commit()
        db.refresh(trading_pair)

        # 记录审计日志
        from ...infrastructure.database.models import AuditLog
        audit_log = AuditLog(
            user_identity=f"web:{current_user.username}",
            action="TRADING_PAIR_CREATE",
            resource_type="trading_pair",
            resource_id=str(trading_pair.id),
            details={
                "base_symbol": base_symbol,
                "exchange": exchange,
                "account_type": account_type,
                "exchange_symbol": exchange_symbol,
            },
        )
        db.add(audit_log)
        db.commit()

        logger.info(f"创建交易对: {trading_pair.get_full_identifier()}")

        return {
            "success": True,
            "message": "交易对创建成功",
            "data": {
                "id": trading_pair.id,
                "base_symbol": trading_pair.base_symbol,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建交易对失败: {e}")
        raise HTTPException(status_code=500, detail="创建交易对失败")


@router.put("/api/trading-pairs/{pair_id}", response_model=Dict[str, Any])
async def update_trading_pair_api(
        pair_id: int,
        base_symbol: str = Form(...),
        exchange: str = Form(...),
        account_type: str = Form(...),
        exchange_symbol: str = Form(...),
        is_enabled: bool = Form(...),
        config: Optional[str] = Form("{}"),
        description: Optional[str] = Form(None),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """更新交易对（API）"""
    import json

    try:
        # 获取交易对
        trading_pair = db.query(TradingPair).filter_by(id=pair_id).first()
        if not trading_pair:
            raise HTTPException(status_code=404, detail="交易对不存在")

        # 验证账户类型
        if account_type not in [t.value for t in AccountType]:
            raise HTTPException(status_code=400, detail="无效的账户类型")

        # 验证配置JSON
        config_dict = {}
        if config:
            try:
                config_dict = json.loads(config)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="配置必须是有效的JSON")

        # 检查是否与其他交易对冲突
        existing = db.query(TradingPair).filter(
            and_(
                TradingPair.id != pair_id,
                TradingPair.base_symbol == base_symbol,
                TradingPair.exchange == exchange,
                TradingPair.account_type == account_type,
            )
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail="交易对已存在")

        # 记录修改前的值
        old_values = {
            "base_symbol": trading_pair.base_symbol,
            "exchange": trading_pair.exchange,
            "account_type": trading_pair.account_type.value,
            "exchange_symbol": trading_pair.exchange_symbol,
            "is_enabled": trading_pair.is_enabled,
            "config": trading_pair.config,
        }

        # 更新交易对
        trading_pair.base_symbol = base_symbol
        trading_pair.exchange = exchange
        trading_pair.account_type = account_type
        trading_pair.exchange_symbol = exchange_symbol
        trading_pair.is_enabled = is_enabled
        trading_pair.config = config_dict
        trading_pair.description = description

        db.commit()

        # 记录审计日志
        from ...infrastructure.database.models import AuditLog
        audit_log = AuditLog(
            user_identity=f"web:{current_user.username}",
            action="TRADING_PAIR_UPDATE",
            resource_type="trading_pair",
            resource_id=str(trading_pair.id),
            details={
                "old": old_values,
                "new": {
                    "base_symbol": base_symbol,
                    "exchange": exchange,
                    "account_type": account_type,
                    "exchange_symbol": exchange_symbol,
                    "is_enabled": is_enabled,
                    "config": config_dict,
                },
            },
        )
        db.add(audit_log)
        db.commit()

        logger.info(f"更新交易对: {trading_pair.get_full_identifier()}")

        return {
            "success": True,
            "message": "交易对更新成功",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新交易对失败: {e}")
        raise HTTPException(status_code=500, detail="更新交易对失败")


@router.delete("/api/trading-pairs/{pair_id}")
async def delete_trading_pair_api(
        pair_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """删除交易对（API）"""
    try:
        # 获取交易对
        trading_pair = db.query(TradingPair).filter_by(id=pair_id).first()
        if not trading_pair:
            raise HTTPException(status_code=404, detail="交易对不存在")

        # 记录删除信息
        pair_info = trading_pair.get_full_identifier()

        # 删除交易对
        db.delete(trading_pair)
        db.commit()

        # 记录审计日志
        from ...infrastructure.database.models import AuditLog
        audit_log = AuditLog(
            user_identity=f"web:{current_user.username}",
            action="TRADING_PAIR_DELETE",
            resource_type="trading_pair",
            resource_id=str(pair_id),
            details={
                "base_symbol": trading_pair.base_symbol,
                "exchange": trading_pair.exchange,
                "account_type": trading_pair.account_type.value,
                "exchange_symbol": trading_pair.exchange_symbol,
            },
        )
        db.add(audit_log)
        db.commit()

        logger.info(f"删除交易对: {pair_info}")

        return {
            "success": True,
            "message": "交易对删除成功",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除交易对失败: {e}")
        raise HTTPException(status_code=500, detail="删除交易对失败")


@router.post("/api/trading-pairs/batch-enable")
async def batch_enable_trading_pairs_api(
        pair_ids: List[int] = Form(...),
        enable: bool = Form(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """批量启用/禁用交易对"""
    try:
        if not pair_ids:
            raise HTTPException(status_code=400, detail="未选择交易对")

        # 更新交易对状态
        updated_count = db.query(TradingPair).filter(
            TradingPair.id.in_(pair_ids)
        ).update(
            {"is_enabled": enable},
            synchronize_session=False
        )

        db.commit()

        # 记录审计日志
        from ...infrastructure.database.models import AuditLog
        action = "TRADING_PAIR_BATCH_ENABLE" if enable else "TRADING_PAIR_BATCH_DISABLE"
        audit_log = AuditLog(
            user_identity=f"web:{current_user.username}",
            action=action,
            resource_type="trading_pair",
            resource_id=",".join(str(pid) for pid in pair_ids),
            details={
                "count": updated_count,
                "enable": enable,
                "pair_ids": pair_ids,
            },
        )
        db.add(audit_log)
        db.commit()

        action_text = "启用" if enable else "禁用"
        logger.info(f"批量{action_text} {updated_count} 个交易对")

        return {
            "success": True,
            "message": f"成功{action_text} {updated_count} 个交易对",
            "data": {"updated_count": updated_count},
        }

    except Exception as e:
        db.rollback()
        logger.error(f"批量更新交易对状态失败: {e}")
        raise HTTPException(status_code=500, detail="批量操作失败")


@router.get("/api/exchanges")
async def get_supported_exchanges_api(
        current_user=Depends(get_current_user),
):
    """获取支持的交易所列表"""
    # 这里可以返回更详细的信息，如支持的账户类型、限制等
    exchanges = [
        {
            "id": "binance",
            "name": "币安",
            "supported_account_types": ["spot", "future"],
            "testnet_available": True,
            "limits": {
                "requests_per_second": 10,
                "orders_per_second": 50,
            },
        },
        {
            "id": "bybit",
            "name": "Bybit",
            "supported_account_types": ["spot", "future"],
            "testnet_available": True,
            "limits": {
                "requests_per_second": 20,
                "orders_per_second": 100,
            },
        },
        {
            "id": "okx",
            "name": "OKX",
            "supported_account_types": ["spot", "future", "margin"],
            "testnet_available": False,
            "limits": {
                "requests_per_second": 10,
                "orders_per_second": 60,
            },
        },
    ]

    return {
        "success": True,
        "data": exchanges,
    }


@router.get("/api/symbol-suggestions")
async def get_symbol_suggestions_api(
        exchange: str = Query(...),
        account_type: str = Query(...),
        query: str = Query(""),
        limit: int = Query(20),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """获取交易对建议（用于自动补全）"""
    try:
        # 这里可以调用交易所API获取可用的交易对
        # 暂时返回数据库中已有的交易对

        suggestions = db.query(TradingPair).filter(
            TradingPair.exchange == exchange,
            TradingPair.account_type == account_type,
            TradingPair.exchange_symbol.like(f"%{query}%"),
        ).limit(limit).all()

        result = [
            {
                "value": tp.exchange_symbol,
                "label": f"{tp.exchange_symbol} ({tp.base_symbol})",
                "base_symbol": tp.base_symbol,
            }
            for tp in suggestions
        ]

        return {
            "success": True,
            "data": result,
        }

    except Exception as e:
        logger.error(f"获取交易对建议失败: {e}")
        return {
            "success": False,
            "data": [],
        }