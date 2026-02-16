"""Agent API endpoints"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import logging

router = APIRouter()
logger = logging.getLogger(__name__)



class TunnelApply(BaseModel):
    tunnel_id: str
    core: str
    type: str
    spec: Dict[str, Any]


class TunnelRemove(BaseModel):
    tunnel_id: str


@router.post("/tunnels/apply")
async def apply_tunnel(data: TunnelApply, request: Request):
    """Apply tunnel configuration"""
    logger = logging.getLogger(__name__)
    adapter_manager = request.app.state.adapter_manager
    
    logger.info(f"Applying tunnel {data.tunnel_id}: core={data.core}, type={data.type}")
    try:
        await adapter_manager.apply_tunnel(
            tunnel_id=data.tunnel_id,
            tunnel_core=data.core,
            spec=data.spec
        )
        logger.info(f"Tunnel {data.tunnel_id} applied successfully")
        return {"status": "success", "message": "Tunnel applied"}
    except Exception as e:
        logger.error(f"Failed to apply tunnel {data.tunnel_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tunnels/remove")
async def remove_tunnel(data: TunnelRemove, request: Request):
    """Remove tunnel"""
    adapter_manager = request.app.state.adapter_manager
    
    try:
        await adapter_manager.remove_tunnel(data.tunnel_id)
        return {"status": "success", "message": "Tunnel removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tunnels/status")
async def get_tunnel_status(tunnel_id: str, request: Request):
    """Get tunnel status"""
    adapter_manager = request.app.state.adapter_manager
    
    try:
        status = await adapter_manager.get_tunnel_status(tunnel_id)
        return {"status": "success", "data": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_status(request: Request):
    """Get node status"""
    adapter_manager = request.app.state.adapter_manager
    
    return {
        "status": "ok",
        "active_tunnels": len(adapter_manager.active_tunnels),
        "tunnels": list(adapter_manager.active_tunnels.keys())
    }


class LoadBalancerApply(BaseModel):
    load_balancer_id: str
    listen_port: int
    algorithm: str
    upstreams: list[Dict[str, Any]]


class LoadBalancerRemove(BaseModel):
    load_balancer_id: str


@router.post("/load-balancer/apply")
async def apply_load_balancer(data: LoadBalancerApply, request: Request):
    """Apply load balancer configuration"""
    load_balancer_manager = request.app.state.load_balancer_manager
    
    logger.info(f"Applying load balancer {data.load_balancer_id}: port={data.listen_port}, upstreams={len(data.upstreams)}")
    try:
        await load_balancer_manager.apply_load_balancer(
            load_balancer_id=data.load_balancer_id,
            listen_port=data.listen_port,
            algorithm=data.algorithm,
            upstreams=data.upstreams
        )
        logger.info(f"Load balancer {data.load_balancer_id} applied successfully")
        return {"status": "success", "message": "Load balancer applied"}
    except Exception as e:
        logger.error(f"Failed to apply load balancer {data.load_balancer_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load-balancer/remove")
async def remove_load_balancer(data: LoadBalancerRemove, request: Request):
    """Remove load balancer"""
    load_balancer_manager = request.app.state.load_balancer_manager
    
    try:
        await load_balancer_manager.remove_load_balancer(data.load_balancer_id)
        return {"status": "success", "message": "Load balancer removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

