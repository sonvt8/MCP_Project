
import os
import json
import logging
from typing import Any, Dict, List, Optional

import requests
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Match behavior of your working script: suppress insecure https warnings when verify=False
warnings.simplefilter('ignore', InsecureRequestWarning)

logger = logging.getLogger("openstack-client-requests")

class OpenStackError(Exception):
    def __init__(self, message: str, http_status: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.http_status = http_status
        self.details = details or {}

class OpenStackRequestsClient:
    """
    Requests-based OpenStack API client that mirrors the original script's behavior (fixed host:ports).
    Endpoints:
      - Keystone: http://{host}:5000/v3
      - Nova:     http://{host}:8774/v2.1
      - Neutron:  http://{host}:9696/v2.0
      - Cinder:   http://{host}:8776/v3/{project_id}
      - Glance:   http://{host}:9292/v2
    """
    def __init__(
        self,
        host: str,
        username: Optional[str],
        password: Optional[str],
        project_id: Optional[str],
        user_domain: str = "Default",
        verify: bool = False,
        timeout: float = 15.0,
    ) -> None:
        if not username or not password or not project_id:
            raise OpenStackError("OS_USERNAME, OS_PASSWORD, and OS_PROJECT_ID are required")
        self.host = host
        self.username = username
        self.password = password
        self.project_id = project_id
        self.user_domain = user_domain
        self.verify = verify
        self.timeout = timeout

        self.session = requests.Session()
        self.session.verify = verify
        self.session.headers.update({"Content-Type": "application/json"})
        self.token: Optional[str] = None

    # ---------------- Keystone ----------------
    def _auth_payload(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": self.username,
                            "domain": {"name": self.user_domain},
                            "password": self.password,
                        }
                    },
                },
                "scope": {"project": {"id": project_id or self.project_id}},
            }
        }

    def renew_openstack_token(self) -> str:
        if self.token:
            # Fast check current token via catalog (best-effort)
            try:
                url = f"http://{self.host}:5000/v3/auth/catalog"
                r = self.session.get(url, headers={"X-Auth-Token": self.token}, timeout=self.timeout)
                if r.status_code == 200:
                    return self.token
            except Exception:
                pass

        url = f"http://{self.host}:5000/v3/auth/tokens"
        r = self.session.post(url, data=json.dumps(self._auth_payload()), timeout=self.timeout)
        if r.status_code != 201:
            raise OpenStackError(f"Keystone auth failed: {r.status_code} {r.text}", http_status=r.status_code)
        token = r.headers.get("X-Subject-Token")
        if not token:
            raise OpenStackError("Missing X-Subject-Token in Keystone response")
        self.token = token
        return token

    def renew_token_project(self, project_id: str) -> str:
        url = f"http://{self.host}:5000/v3/auth/tokens"
        r = self.session.post(url, data=json.dumps(self._auth_payload(project_id=project_id)), timeout=self.timeout)
        if r.status_code != 201:
            raise OpenStackError(f"Keystone project-scope auth failed: {r.status_code} {r.text}", http_status=r.status_code)
        token = r.headers.get("X-Subject-Token")
        if not token:
            raise OpenStackError("Missing X-Subject-Token in Keystone response (project-scope)")
        return token

    # ---------------- Nova / Neutron / Cinder / Glance helpers ----------------
    def _headers(self, token: Optional[str] = None) -> Dict[str, str]:
        return {"X-Auth-Token": token or self.token or "" , "Content-Type": "application/json"}

    def _nova_get(self, path: str, token: Optional[str] = None) -> requests.Response:
        base = f"http://{self.host}:8774/v2.1"
        return self.session.get(base + path, headers=self._headers(token), timeout=self.timeout)

    def _neutron_get(self, path: str, token: Optional[str] = None) -> requests.Response:
        base = f"http://{self.host}:9696/v2.0"
        return self.session.get(base + path, headers=self._headers(token), timeout=self.timeout)

    def _cinder_get(self, path: str, token: Optional[str] = None) -> requests.Response:
        base = f"http://{self.host}:8776/v3/{self.project_id}"
        return self.session.get(base + path, headers=self._headers(token), timeout=self.timeout)

    def _glance_get(self, path: str, token: Optional[str] = None) -> requests.Response:
        base = f"http://{self.host}:9292/v2"
        return self.session.get(base + path, headers=self._headers(token), timeout=self.timeout)

    # ---------------- High-level getters ----------------
    def get_project_name(self, tenant_id: str) -> Optional[str]:
        self.renew_openstack_token()
        url = f"http://{self.host}:5000/v3/projects/{tenant_id}"
        r = self.session.get(url, headers=self._headers(), timeout=self.timeout)
        if r.status_code == 200:
            try:
                return r.json().get("project", {}).get("name")
            except Exception:
                return None
        return None

    def get_server_raw(self, instance_id: str) -> Dict[str, Any]:
        self.renew_openstack_token()
        # Keep the same path style as your working script (with project id segment)
        r = self._nova_get(f"/{self.project_id}/servers/{instance_id}")
        if r.status_code >= 400:
            raise OpenStackError(f"Nova server fetch failed: {r.status_code} {r.text}", http_status=r.status_code)
        try:
            data = r.json()
            return data.get("server", data)
        except Exception as e:
            raise OpenStackError(f"Invalid JSON from Nova: {e}")

    def get_server_interfaces(self, instance_id: str) -> List[Dict[str, Any]]:
        # Your script used the form without project id segment; we keep that for compatibility
        r = self._nova_get(f"/servers/{instance_id}/os-interface")
        if r.status_code >= 400:
            # Not fatal; just return empty list
            logger.debug("Failed to fetch interfaces: %s %s", r.status_code, r.text)
            return []
        try:
            data = r.json()
            return data.get("interfaceAttachments", []) or []
        except Exception:
            return []

    def get_port(self, port_id: str) -> Optional[Dict[str, Any]]:
        r = self._neutron_get(f"/ports/{port_id}")
        if r.status_code >= 400:
            return None
        try:
            return r.json().get("port", {})
        except Exception:
            return None

    def get_volume(self, volume_id: str) -> Optional[Dict[str, Any]]:
        r = self._cinder_get(f"/volumes/{volume_id}")
        if r.status_code >= 400:
            return None
        try:
            return r.json().get("volume", {})
        except Exception:
            return None

    def get_server_groups(self, project_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
        # Requires project-scoped token (some clouds)
        try:
            token = self.renew_token_project(project_id)
        except OpenStackError as e:
            logger.debug("Project-scope token failed; skip server-groups: %s", e)
            return None
        r = self._nova_get("/os-server-groups?all_projects=False", token=token)
        if r.status_code >= 400:
            return None
        try:
            groups = r.json().get("server_groups", [])
            for g in groups:
                if instance_id in (g.get("members") or []):
                    return {"id": g.get("id"), "name": g.get("name")}
        except Exception:
            pass
        return None

    def get_image(self, image_id: str) -> Optional[Dict[str, Any]]:
        # Best-effort to resolve image name
        try:
            r = self._glance_get(f"/images/{image_id}")
            if r.status_code >= 400:
                return None
            return r.json()
        except Exception:
            return None

    # ---------------- Composite (normalized) ----------------
    def get_server_composite(self, instance_id: str) -> Dict[str, Any]:
        server = self.get_server_raw(instance_id)

        srv_id = server.get("id", instance_id)
        name = server.get("name")
        status = server.get("status")
        project_id = server.get("tenant_id") or server.get("project_id") or self.project_id

        # Flavor (do not expand to model specs to keep latency/compat)
        flavor_info = server.get("flavor") or {}
        flavor = {
            "id": flavor_info.get("id"),
            "name": flavor_info.get("original_name") or flavor_info.get("name"),
            "vcpus": None,
            "ram_mb": None,
            "disk_gb": None,
        }

        # Image
        image_obj = server.get("image") or {}
        image_id = image_obj.get("id")
        image = {"id": image_id, "name": None}
        if image_id:
            img = self.get_image(image_id)
            if img:
                image["name"] = img.get("name")

        # Interfaces & ports
        iface_list = self.get_server_interfaces(instance_id)
        interfaces: List[Dict[str, Any]] = []
        for ia in iface_list:
            port_id = ia.get("port_id")
            net_id = ia.get("net_id")
            mac = ia.get("mac_addr") or ia.get("mac_address")
            fixed_ips = [ip.get("ip_address") for ip in (ia.get("fixed_ips") or []) if ip.get("ip_address")]
            allowed_pairs: List[str] = []
            if port_id:
                p = self.get_port(port_id)
                if p:
                    pairs = p.get("allowed_address_pairs") or []
                    allowed_pairs = [pp.get("ip_address") for pp in pairs if pp.get("ip_address")]
                    if not fixed_ips:
                        fixed_ips = [ip.get("ip_address") for ip in (p.get("fixed_ips") or []) if ip.get("ip_address")]
                    if not mac:
                        mac = p.get("mac_address")
                    if not net_id:
                        net_id = p.get("network_id")

            interfaces.append({
                "port_id": port_id,
                "net_id": net_id,
                "mac": mac,
                "fixed_ips": fixed_ips,
                "allowed_address_pairs": allowed_pairs,
            })

        # Volumes & boot-from-volume
        vol_attachments = server.get("os-extended-volumes:volumes_attached", []) or []
        volumes: List[Dict[str, Any]] = []
        for va in vol_attachments:
            vid = va.get("id")
            if not vid:
                continue
            v = self.get_volume(vid)
            if v:
                device = (v.get("attachments") or [{}])[0].get("device")
                volumes.append({
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "size_gb": v.get("size"),
                    "status": v.get("status"),
                    "bootable": (v.get("bootable") == "true"),
                    "device": device,
                })
            else:
                volumes.append({"id": vid})
        boot_from_volume = bool(vol_attachments) and not image_id

        # Server group (best-effort)
        server_group = self.get_server_groups(project_id, srv_id)

        result: Dict[str, Any] = {
            "instance_id": srv_id,
            "name": name,
            "status": status,
            "project": {"id": project_id, "name": self.get_project_name(project_id)},
            "flavor": flavor,
            "image": image,
            "boot_from_volume": boot_from_volume,
            "volumes": volumes,
            "interfaces": interfaces,
            "availability_zone": server.get("OS-EXT-AZ:availability_zone"),
            "host": server.get("OS-EXT-SRV-ATTR:host"),
            "hypervisor_hostname": server.get("OS-EXT-SRV-ATTR:hypervisor_hostname"),
            "security_groups": [sg.get("name") for sg in (server.get("security_groups") or []) if sg.get("name")],
            "tags": server.get("tags", []),
            "metadata": server.get("metadata", {}),
            "created": server.get("created"),
            "updated": server.get("updated"),
            "server_group": server_group,
            "raw": {"nova": server},
        }
        return result
