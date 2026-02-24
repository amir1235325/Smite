"""Load Balancer Manager using Nginx stream module"""
import subprocess
import logging
import time
from pathlib import Path
from typing import Dict, Any, List
import shutil

logger = logging.getLogger(__name__)


class LoadBalancerManager:
    """Manages Nginx-based load balancers"""
    
    def __init__(self):
        self.config_dir = Path("/etc/smite-node/nginx")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.nginx_config_dir = Path("/etc/nginx")
        self.nginx_config_dir.mkdir(parents=True, exist_ok=True)
        self.stream_config_dir = self.nginx_config_dir / "stream.d"
        self.stream_config_dir.mkdir(parents=True, exist_ok=True)
        self.load_balancers = {}
        self._ensure_nginx_installed()
        self._setup_nginx_config()
    
    def _ensure_nginx_installed(self):
        """Check if nginx is installed, install if not"""
        nginx_path = shutil.which("nginx")
        if not nginx_path:
            logger.warning("Nginx not found. Attempting to install...")
            try:
                subprocess.run(["apt-get", "update"], check=True, capture_output=True)
                subprocess.run(["apt-get", "install", "-y", "nginx"], check=True, capture_output=True)
                logger.info("Nginx installed successfully")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to install nginx: {e}")
                raise RuntimeError("Nginx is required for load balancing but could not be installed")
        else:
            logger.debug(f"Nginx found at {nginx_path}")
    
    def _nginx_supports_stream(self) -> bool:
        try:
            result = subprocess.run(
                ["nginx", "-V"],
                capture_output=True,
                text=True,
                timeout=5
            )
            out = (result.stdout or "") + (result.stderr or "")
            return "stream" in out.lower() or "with-stream" in out.lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _setup_nginx_config(self):
        """Setup main nginx config to include stream module"""
        nginx_conf = self.nginx_config_dir / "nginx.conf"
        if not self._nginx_supports_stream():
            raise RuntimeError(
                "Nginx is not built with stream module. Use the official Smite node Docker image "
                "or install nginx with stream support (e.g. apt install nginx on Debian/Ubuntu)."
            )
        if nginx_conf.exists():
            with open(nginx_conf, "r") as f:
                content = f.read()
                if "stream {" in content:
                    logger.debug("Nginx stream module already configured")
                    return
        stream_config = """
stream {
    include /etc/nginx/stream.d/*.conf;
}
"""
        if nginx_conf.exists():
            with open(nginx_conf, "a") as f:
                f.write("\n" + stream_config)
        else:
            basic_config = f"""
events {{
    worker_connections 1024;
}}

{stream_config}
"""
            with open(nginx_conf, "w") as f:
                f.write(basic_config)
        logger.info("Nginx stream module configured")
    
    def _generate_upstream_config(self, upstreams: List[Dict[str, Any]], algorithm: str) -> str:
        """Generate upstream server configuration"""
        upstream_block = "    upstream backend {\n"
        
        if algorithm == "least_conn":
            upstream_block += "        least_conn;\n"
        # round_robin is default, no directive needed
        
        for upstream in upstreams:
            host = upstream.get("host", "")
            port = upstream.get("port", "")
            upstream_block += f"        server {host}:{port};\n"
        
        upstream_block += "    }\n"
        return upstream_block
    
    def _generate_stream_config(self, load_balancer_id: str, listen_port: int, upstreams: List[Dict[str, Any]], algorithm: str) -> str:
        """Generate Nginx stream configuration"""
        config = f"""
# Load balancer: {load_balancer_id}
upstream lb_{load_balancer_id} {{
"""
        
        if algorithm == "least_conn":
            config += "    least_conn;\n"
        
        for upstream in upstreams:
            host = upstream.get("host", "")
            port = upstream.get("port", "")
            config += f"    server {host}:{port};\n"
        
        config += f"""}}

server {{
    listen {listen_port};
    proxy_pass lb_{load_balancer_id};
    proxy_timeout 1s;
    proxy_responses 1;
    error_log /var/log/nginx/lb_{load_balancer_id}.error.log;
}}
"""
        return config
    
    async def apply_load_balancer(self, load_balancer_id: str, listen_port: int, algorithm: str, upstreams: List[Dict[str, Any]]):
        """Apply load balancer configuration"""
        if load_balancer_id in self.load_balancers:
            logger.info(f"Load balancer {load_balancer_id} already exists, removing it first")
            await self.remove_load_balancer(load_balancer_id)
        
        if not upstreams:
            raise ValueError("At least one upstream server is required")
        
        # Generate config
        config = self._generate_stream_config(load_balancer_id, listen_port, upstreams, algorithm)
        
        # Write config file
        config_file = self.stream_config_dir / f"{load_balancer_id}.conf"
        with open(config_file, "w") as f:
            f.write(config)
        
        logger.info(f"Load balancer config written to {config_file}")
        
        # Test nginx configuration
        try:
            result = subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                raise RuntimeError(f"Nginx configuration test failed: {result.stderr}")
        except FileNotFoundError:
            raise RuntimeError("Nginx not found. Please install nginx.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Nginx configuration test timed out")
        
        # Reload nginx
        try:
            result = subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                # Try to start nginx if it's not running
                subprocess.run(["nginx"], capture_output=True, timeout=5)
                logger.info("Nginx started")
            else:
                logger.info("Nginx reloaded successfully")
        except FileNotFoundError:
            raise RuntimeError("Nginx not found. Please install nginx.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Nginx reload timed out")
        
        self.load_balancers[load_balancer_id] = {
            "listen_port": listen_port,
            "algorithm": algorithm,
            "upstreams": upstreams,
            "config_file": config_file
        }
        
        logger.info(f"Load balancer {load_balancer_id} applied successfully on port {listen_port}")
    
    async def remove_load_balancer(self, load_balancer_id: str):
        """Remove load balancer"""
        if load_balancer_id not in self.load_balancers:
            logger.warning(f"Load balancer {load_balancer_id} not found")
            return
        
        # Remove config file
        config_file = self.stream_config_dir / f"{load_balancer_id}.conf"
        if config_file.exists():
            config_file.unlink()
            logger.info(f"Removed load balancer config file: {config_file}")
        
        # Test and reload nginx
        try:
            result = subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                subprocess.run(
                    ["nginx", "-s", "reload"],
                    capture_output=True,
                    timeout=5
                )
                logger.info("Nginx reloaded after removing load balancer")
        except Exception as e:
            logger.warning(f"Failed to reload nginx after removing load balancer: {e}")
        
        if load_balancer_id in self.load_balancers:
            del self.load_balancers[load_balancer_id]
        
        logger.info(f"Load balancer {load_balancer_id} removed successfully")
    
    def get_status(self, load_balancer_id: str) -> Dict[str, Any]:
        """Get load balancer status"""
        if load_balancer_id not in self.load_balancers:
            return {"status": "not_found"}
        
        lb = self.load_balancers[load_balancer_id]
        config_file = lb["config_file"]
        
        return {
            "status": "active" if config_file.exists() else "inactive",
            "listen_port": lb["listen_port"],
            "algorithm": lb["algorithm"],
            "upstreams": lb["upstreams"]
        }

