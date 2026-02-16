"""Load Balancer API endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime
from pydantic import BaseModel
import logging

from app.database import get_db
from app.models import LoadBalancer, Node, Tunnel
from app.node_client import NodeClient

logger = logging.getLogger(__name__)

router = APIRouter()


class LoadBalancerCreate(BaseModel):
    name: str
    iran_node_id: str
    tunnel_ids: List[str]
    listen_port: int
    algorithm: str = "round_robin"


class LoadBalancerUpdate(BaseModel):
    name: str | None = None
    tunnel_ids: List[str] | None = None
    listen_port: int | None = None
    algorithm: str | None = None


class LoadBalancerResponse(BaseModel):
    id: str
    name: str
    iran_node_id: str
    tunnel_ids: List[str]
    listen_port: int
    algorithm: str
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


@router.post("", response_model=LoadBalancerResponse)
async def create_load_balancer(lb: LoadBalancerCreate, db: AsyncSession = Depends(get_db)):
    """Create a new load balancer"""
    from app.node_client import NodeClient
    
    # Validate Iran node
    result = await db.execute(select(Node).where(Node.id == lb.iran_node_id))
    iran_node = result.scalar_one_or_none()
    if not iran_node:
        raise HTTPException(status_code=404, detail="Iran node not found")
    
    if iran_node.node_metadata.get("role") != "iran":
        raise HTTPException(status_code=400, detail="Selected node must be an Iran node")
    
    # Validate tunnels
    if not lb.tunnel_ids:
        raise HTTPException(status_code=400, detail="At least one tunnel must be selected")
    
    tunnels = []
    tunnel_port_sets = []  # List of port sets, one per tunnel
    tunnel_transmission_types = []
    
    for tunnel_id in lb.tunnel_ids:
        result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
        tunnel = result.scalar_one_or_none()
        if not tunnel:
            raise HTTPException(status_code=404, detail=f"Tunnel {tunnel_id} not found")
        
        # Validate tunnel has Iran node
        if not tunnel.iran_node_id:
            raise HTTPException(status_code=400, detail=f"Tunnel {tunnel.name} is not a reverse tunnel (no Iran node)")
        
        tunnels.append(tunnel)
        
        # Get tunnel ports from spec - for reverse tunnels, these are the ports on Iran node
        spec = tunnel.spec or {}
        ports = spec.get("ports", [])
        tunnel_ports = []
        
        if ports:
            # Extract port numbers from ports array (handle "port" or "port=target" format)
            for p in ports:
                if isinstance(p, (int, str)):
                    port_str = str(p)
                    # Handle "port=target" format
                    if "=" in port_str:
                        port_str = port_str.split("=")[0]
                    # Handle "host:port" format
                    if ":" in port_str:
                        port_str = port_str.split(":")[-1]
                    try:
                        tunnel_ports.append(int(port_str))
                    except ValueError:
                        tunnel_ports.append(port_str)
        else:
            # Try to get port from other fields (order matters for different tunnel types)
            port = (
                spec.get("remote_port") or  # FRP
                spec.get("listen_port") or  # General
                spec.get("public_port") or  # Backhaul
                spec.get("bind_port") or    # Rathole
                spec.get("proxy_port") or   # General
                spec.get("reverse_port")    # Chisel
            )
            if port:
                # Handle port in "host:port" format
                if isinstance(port, str) and ":" in port:
                    port = port.split(":")[-1]
                port_int = int(port) if isinstance(port, (int, str)) and str(port).isdigit() else port
                tunnel_ports.append(port_int)
        
        if not tunnel_ports:
            raise HTTPException(status_code=400, detail=f"Tunnel {tunnel.name} must have at least one port configured")
        
        tunnel_port_sets.append(set(tunnel_ports))
        
        # Get transmission type
        tunnel_type = tunnel.type
        tunnel_transmission_types.append(tunnel_type)
    
    # Validate all tunnels have the same set of ports
    if not tunnel_port_sets:
        raise HTTPException(status_code=400, detail="Tunnels must have ports configured")
    
    # Check if all tunnels have the same port set
    first_port_set = tunnel_port_sets[0]
    for i, port_set in enumerate(tunnel_port_sets[1:], 1):
        if port_set != first_port_set:
            raise HTTPException(
                status_code=400,
                detail=f"All tunnels must have the same set of ports. Tunnel 1 has {sorted(first_port_set)}, Tunnel {i+1} has {sorted(port_set)}"
            )
    
    # Validate all tunnels have the same transmission type
    unique_types = set(tunnel_transmission_types)
    if len(unique_types) > 1:
        raise HTTPException(status_code=400, detail=f"All tunnels must have the same transmission type. Found types: {unique_types}")
    
    # Check if port is already in use by another load balancer on this node
    result = await db.execute(
        select(LoadBalancer).where(
            LoadBalancer.iran_node_id == lb.iran_node_id,
            LoadBalancer.listen_port == lb.listen_port,
            LoadBalancer.status != "deleted"
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Port {lb.listen_port} is already in use by load balancer {existing.name}")
    
    # Create load balancer
    db_lb = LoadBalancer(
        name=lb.name,
        iran_node_id=lb.iran_node_id,
        tunnel_ids=lb.tunnel_ids,
        listen_port=lb.listen_port,
        algorithm=lb.algorithm,
        status="pending"
    )
    db.add(db_lb)
    await db.commit()
    await db.refresh(db_lb)
    
    # Apply load balancer to node
    client = NodeClient()
    try:
        # Build upstreams: Iran node IPs and ports
        upstreams = []
        for tunnel in tunnels:
            iran_node_id = tunnel.iran_node_id
            result = await db.execute(select(Node).where(Node.id == iran_node_id))
            tunnel_iran_node = result.scalar_one_or_none()
            if tunnel_iran_node:
                iran_ip = tunnel_iran_node.node_metadata.get("ip_address", "")
                if iran_ip:
                    # Use the listen_port as the target port (already validated to be in common port set)
                    target_port = lb.listen_port
                    upstreams.append({
                        "host": iran_ip,
                        "port": target_port
                    })
        
        if not upstreams:
            raise HTTPException(status_code=400, detail="Could not determine upstream servers from tunnels")
        
        response = await client.send_to_node(
            node_id=lb.iran_node_id,
            endpoint="/api/agent/load-balancer/apply",
            data={
                "load_balancer_id": db_lb.id,
                "listen_port": lb.listen_port,
                "algorithm": lb.algorithm,
                "upstreams": upstreams
            }
        )
        
        if response.get("status") == "error":
            db_lb.status = "error"
            db_lb.error_message = response.get("message", "Unknown error from node")
            await db.commit()
            await db.refresh(db_lb)
            logger.error(f"Load balancer {db_lb.id}: Node error: {db_lb.error_message}")
            return db_lb
        
        db_lb.status = "active"
        await db.commit()
        await db.refresh(db_lb)
        logger.info(f"Load balancer {db_lb.id} created and applied successfully")
        
    except Exception as e:
        db_lb.status = "error"
        db_lb.error_message = str(e)
        await db.commit()
        await db.refresh(db_lb)
        logger.error(f"Failed to apply load balancer {db_lb.id}: {e}", exc_info=True)
    
    return db_lb


@router.get("", response_model=List[LoadBalancerResponse])
async def list_load_balancers(db: AsyncSession = Depends(get_db)):
    """List all load balancers"""
    result = await db.execute(select(LoadBalancer).where(LoadBalancer.status != "deleted"))
    load_balancers = result.scalars().all()
    return load_balancers


@router.get("/{lb_id}", response_model=LoadBalancerResponse)
async def get_load_balancer(lb_id: str, db: AsyncSession = Depends(get_db)):
    """Get a load balancer by ID"""
    result = await db.execute(select(LoadBalancer).where(LoadBalancer.id == lb_id))
    lb = result.scalar_one_or_none()
    if not lb:
        raise HTTPException(status_code=404, detail="Load balancer not found")
    return lb


@router.put("/{lb_id}", response_model=LoadBalancerResponse)
async def update_load_balancer(lb_id: str, lb_update: LoadBalancerUpdate, db: AsyncSession = Depends(get_db)):
    """Update a load balancer"""
    from app.node_client import NodeClient
    
    result = await db.execute(select(LoadBalancer).where(LoadBalancer.id == lb_id))
    db_lb = result.scalar_one_or_none()
    if not db_lb:
        raise HTTPException(status_code=404, detail="Load balancer not found")
    
    # Update fields
    if lb_update.name is not None:
        db_lb.name = lb_update.name
    if lb_update.listen_port is not None:
        db_lb.listen_port = lb_update.listen_port
    if lb_update.algorithm is not None:
        db_lb.algorithm = lb_update.algorithm
    if lb_update.tunnel_ids is not None:
        # Validate new tunnels
        tunnels = []
        tunnel_port_sets = []
        for tunnel_id in lb_update.tunnel_ids:
            result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
            tunnel = result.scalar_one_or_none()
            if not tunnel:
                raise HTTPException(status_code=404, detail=f"Tunnel {tunnel_id} not found")
            if not tunnel.iran_node_id:
                raise HTTPException(status_code=400, detail=f"Tunnel {tunnel.name} is not a reverse tunnel")
            tunnels.append(tunnel)
            
            spec = tunnel.spec or {}
            ports = spec.get("ports", [])
            tunnel_ports = []
            
            if ports:
                # Extract port numbers from ports array (handle "port" or "port=target" format)
                for p in ports:
                    if isinstance(p, (int, str)):
                        port_str = str(p)
                        # Handle "port=target" format
                        if "=" in port_str:
                            port_str = port_str.split("=")[0]
                        # Handle "host:port" format
                        if ":" in port_str:
                            port_str = port_str.split(":")[-1]
                        try:
                            tunnel_ports.append(int(port_str))
                        except ValueError:
                            tunnel_ports.append(port_str)
            else:
                # Try to get port from other fields (order matters for different tunnel types)
                port = (
                    spec.get("remote_port") or  # FRP
                    spec.get("listen_port") or  # General
                    spec.get("public_port") or  # Backhaul
                    spec.get("bind_port") or    # Rathole
                    spec.get("proxy_port") or   # General
                    spec.get("reverse_port")    # Chisel
                )
                if port:
                    # Handle port in "host:port" format
                    if isinstance(port, str) and ":" in port:
                        port = port.split(":")[-1]
                    port_int = int(port) if isinstance(port, (int, str)) and str(port).isdigit() else port
                    tunnel_ports.append(port_int)
            
            if not tunnel_ports:
                raise HTTPException(status_code=400, detail=f"Tunnel {tunnel.name} must have at least one port configured")
            
            tunnel_port_sets.append(set(tunnel_ports))
        
        # Check if all tunnels have the same port set
        if tunnel_port_sets:
            first_port_set = tunnel_port_sets[0]
            for i, port_set in enumerate(tunnel_port_sets[1:], 1):
                if port_set != first_port_set:
                    raise HTTPException(
                        status_code=400,
                        detail=f"All tunnels must have the same set of ports. Tunnel 1 has {sorted(first_port_set)}, Tunnel {i+1} has {sorted(port_set)}"
                    )
            
            # Validate listen_port is in the common port set
            common_ports = sorted(first_port_set)
            listen_port_to_check = lb_update.listen_port if lb_update.listen_port is not None else db_lb.listen_port
            if listen_port_to_check not in common_ports:
                raise HTTPException(
                    status_code=400,
                    detail=f"Listen port {listen_port_to_check} must be one of the tunnel ports: {common_ports}"
                )
        
        db_lb.tunnel_ids = lb_update.tunnel_ids
    
    await db.commit()
    await db.refresh(db_lb)
    
    # Reapply to node
    client = NodeClient()
    try:
        # Build upstreams
        upstreams = []
        for tunnel_id in db_lb.tunnel_ids:
            result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
            tunnel = result.scalar_one_or_none()
            if tunnel and tunnel.iran_node_id:
                result = await db.execute(select(Node).where(Node.id == tunnel.iran_node_id))
                tunnel_iran_node = result.scalar_one_or_none()
                if tunnel_iran_node:
                    iran_ip = tunnel_iran_node.node_metadata.get("ip_address", "")
                    if iran_ip:
                        # Use the listen_port as the target port (already validated to be in common port set)
                        target_port = db_lb.listen_port
                        upstreams.append({
                            "host": iran_ip,
                            "port": target_port
                        })
        
        response = await client.send_to_node(
            node_id=db_lb.iran_node_id,
            endpoint="/api/agent/load-balancer/apply",
            data={
                "load_balancer_id": db_lb.id,
                "listen_port": db_lb.listen_port,
                "algorithm": db_lb.algorithm,
                "upstreams": upstreams
            }
        )
        
        if response.get("status") == "error":
            db_lb.status = "error"
            db_lb.error_message = response.get("message", "Unknown error from node")
        else:
            db_lb.status = "active"
            db_lb.error_message = None
        
        await db.commit()
        await db.refresh(db_lb)
        
    except Exception as e:
        db_lb.status = "error"
        db_lb.error_message = str(e)
        await db.commit()
        await db.refresh(db_lb)
        logger.error(f"Failed to update load balancer {db_lb.id}: {e}", exc_info=True)
    
    return db_lb


@router.delete("/{lb_id}")
async def delete_load_balancer(lb_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a load balancer"""
    from app.node_client import NodeClient
    
    result = await db.execute(select(LoadBalancer).where(LoadBalancer.id == lb_id))
    db_lb = result.scalar_one_or_none()
    if not db_lb:
        raise HTTPException(status_code=404, detail="Load balancer not found")
    
    # Remove from node
    client = NodeClient()
    try:
        await client.send_to_node(
            node_id=db_lb.iran_node_id,
            endpoint="/api/agent/load-balancer/remove",
            data={"load_balancer_id": lb_id}
        )
    except Exception as e:
        logger.error(f"Failed to remove load balancer from node: {e}")
    
    # Mark as deleted
    db_lb.status = "deleted"
    await db.commit()
    
    return {"status": "success", "message": "Load balancer deleted"}

