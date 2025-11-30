import docker
import requests
import semver
from datetime import datetime
from typing import Dict, List, Optional, Callable


class N8NManager:
    def __init__(self, container_name: str = "n8n"):
        """Initialize the n8n manager with Docker client."""
        self.container_name = container_name
        self._client = None
        self.image_name = "n8nio/n8n"
    
    @property
    def client(self):
        """Lazy initialization of Docker client."""
        if self._client is None:
            try:
                # Initialize client without immediate ping to avoid build-time errors
                self._client = docker.from_env()
                # Only test connection when actually needed (at runtime)
            except Exception as e:
                raise Exception(f"Failed to connect to Docker: {str(e)}. Make sure Docker Desktop is running.")
        return self._client

    def get_available_versions(self, limit: int = 20) -> List[Dict[str, str]]:
        """
        Fetch available n8n versions from Docker Hub and GitHub releases.
        
        Args:
            limit: Maximum number of versions to return
            
        Returns:
            List of dicts with 'version', 'updated', and 'is_latest' keys, sorted newest first
        """
        try:
            # First, get the latest production release from GitHub
            latest_production_version = None
            try:
                github_response = requests.get(
                    "https://api.github.com/repos/n8n-io/n8n/releases/latest",
                    headers={"Accept": "application/vnd.github+json"},
                    timeout=5
                )
                if github_response.status_code == 200:
                    latest_release = github_response.json()
                    tag_name = latest_release.get("tag_name", "")
                    # Remove 'n8n@' prefix if present (e.g., "n8n@1.121.3" -> "1.121.3")
                    if tag_name.startswith("n8n@"):
                        tag_name = tag_name[4:]
                    # Remove 'v' prefix if present (e.g., "v1.121.3" -> "1.121.3")
                    if tag_name.startswith("v"):
                        tag_name = tag_name[1:]
                    # Only use if it's not a pre-release
                    if not latest_release.get("prerelease", False):
                        latest_production_version = tag_name
            except Exception:
                # If GitHub API fails, continue without latest marker
                pass
            
            # Fetch versions from Docker Hub
            url = "https://hub.docker.com/v2/repositories/n8nio/n8n/tags"
            params = {"page_size": 100}
            versions = []
            
            while len(versions) < limit:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                for tag in data.get("results", []):
                    tag_name = tag.get("name", "")
                    
                    # Skip non-semver tags
                    if tag_name in ["latest", "next"]:
                        continue
                    
                    # Skip architecture-specific tags (amd64, arm64, etc.)
                    # Only include base versions without architecture suffixes
                    if any(arch in tag_name for arch in ["-amd64", "-arm64"]):
                        continue
                    
                    # Skip pre-release versions (experimental, alpha, beta, rc)
                    # Only include production releases
                    if any(pre in tag_name.lower() for pre in ["-exp.", "-exp", ".exp", "-alpha", "-beta", "-rc", ".alpha", ".beta", ".rc"]):
                        continue
                    
                    # Validate semver and ensure it's a production release
                    try:
                        version_obj = semver.Version.parse(tag_name)
                        # Skip if it's a pre-release version (has prerelease component)
                        if version_obj.prerelease:
                            continue
                        updated = tag.get("last_updated", "")
                        versions.append({
                            "version": tag_name,
                            "updated": updated,
                            "is_latest": False  # Will be set below based on GitHub
                        })
                    except ValueError:
                        continue
                    
                    if len(versions) >= limit:
                        break
                
                # Check for next page
                if data.get("next"):
                    url = data["next"]
                    params = {}
                else:
                    break
            
            # Sort by version descending (newest first)
            versions.sort(key=lambda x: semver.Version.parse(x["version"]), reverse=True)
            
            # Mark the latest production version from GitHub
            if latest_production_version:
                for version in versions:
                    if version["version"] == latest_production_version:
                        version["is_latest"] = True
                        break
            
            return versions[:limit]
        except Exception as e:
            raise Exception(f"Failed to fetch versions: {str(e)}")

    def get_container_status(self) -> Dict:
        """
        Get the current status of the n8n container.
        
        Returns:
            Dict with status, current_version, started_at, health keys
        """
        try:
            container = self.client.containers.get(self.container_name)
            
            # Extract version from image tags
            image_tags = container.image.tags
            current_version = "unknown"
            for tag in image_tags:
                if self.image_name in tag:
                    # Extract version from tag like "n8nio/n8n:1.0.0"
                    parts = tag.split(":")
                    if len(parts) == 2:
                        current_version = parts[1]
                    break
            
            # If version is "latest", try to get actual version from image labels or inspect
            if current_version == "latest":
                try:
                    image = container.image
                    # Get labels from image attributes
                    labels = image.attrs.get("Config", {}).get("Labels", {})
                    # Try multiple possible label keys for version
                    version_label = (
                        labels.get("org.opencontainers.image.version") or
                        labels.get("version") or
                        labels.get("n8n.version") or
                        labels.get("io.n8n.version")
                    )
                    if version_label:
                        current_version = version_label
                    else:
                        # Try to get from image repo tags - sometimes latest points to a specific version
                        # Check all tags for this image
                        image_repo_tags = image.attrs.get("RepoTags", [])
                        for repo_tag in image_repo_tags:
                            if ":" in repo_tag and not repo_tag.endswith(":latest"):
                                tag_part = repo_tag.split(":")[-1]
                                # If it looks like a version number, use it
                                if tag_part and tag_part.replace(".", "").replace("-", "").isdigit():
                                    current_version = tag_part
                                    break
                except Exception:
                    pass
            
            status = container.status
            started_at = container.attrs.get("State", {}).get("StartedAt", "")
            
            # Get health status - check if health check is configured
            health_state = container.attrs.get("State", {}).get("Health", {})
            if health_state:
                # Health check is configured, use its status
                health = health_state.get("Status", "unknown")
            else:
                # No health check configured, infer from container status
                if status == "running":
                    # Try to determine if service is responsive
                    # For n8n, if it's running, we'll assume it's healthy
                    # (could be enhanced with actual HTTP check)
                    health = "healthy (no health check)"
                elif status in ["stopped", "exited"]:
                    health = "stopped"
                else:
                    health = "unknown"
            
            # Get CPU and memory usage if container is running
            cpu_percent = None
            memory_usage = None
            memory_limit = None
            memory_percent = None
            
            if status == "running":
                try:
                    stats = container.stats(stream=False)
                    
                    # Calculate CPU percentage
                    cpu_stats = stats.get("cpu_stats", {})
                    precpu_stats = stats.get("precpu_stats", {})
                    
                    if cpu_stats and precpu_stats:
                        cpu_usage = cpu_stats.get("cpu_usage", {})
                        precpu_usage = precpu_stats.get("cpu_usage", {})
                        
                        if cpu_usage and precpu_usage:
                            cpu_delta = cpu_usage.get("total_usage", 0) - precpu_usage.get("total_usage", 0)
                            system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
                            
                            if system_delta > 0 and cpu_delta > 0:
                                # Get number of CPUs
                                percpu_usage = cpu_usage.get("percpu_usage", [])
                                num_cpus = len(percpu_usage) if percpu_usage else 1
                                
                                cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
                                cpu_percent = round(cpu_percent, 2)
                    
                    # Get memory usage
                    memory_stats = stats.get("memory_stats", {})
                    if memory_stats:
                        memory_usage = memory_stats.get("usage", 0)
                        memory_limit = memory_stats.get("limit", 0)
                        
                        if memory_limit and memory_limit > 0:
                            memory_percent = (memory_usage / memory_limit) * 100.0
                            memory_percent = round(memory_percent, 2)
                except Exception as e:
                    # If stats fail, just continue without them
                    import logging
                    logging.warning(f"Failed to get container stats: {str(e)}")
                    pass
            
            return {
                "status": status,
                "current_version": current_version,
                "started_at": started_at,
                "health": health,
                "cpu_percent": cpu_percent,
                "memory_usage": memory_usage,
                "memory_limit": memory_limit,
                "memory_percent": memory_percent
            }
        except docker.errors.NotFound:
            return {
                "status": "not_found",
                "current_version": None,
                "started_at": None,
                "health": None,
                "cpu_percent": None,
                "memory_usage": None,
                "memory_limit": None,
                "memory_percent": None
            }
        except Exception as e:
            raise Exception(f"Failed to get container status: {str(e)}")

    def backup_volume(self, backup_dir: str = "/app/backups") -> str:
        """
        Create a backup of the n8n_data volume.
        
        Args:
            backup_dir: Directory to store backup files (inside container)
            
        Returns:
            Filename of the created backup
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"n8n_backup_{timestamp}.tar.gz"
            
            # Get the actual host path for backups by checking the dashboard container's mounts
            # This is necessary for Docker Desktop on Mac which requires shared paths
            dashboard_container = self.client.containers.get("n8n-manager-dashboard")
            dashboard_mounts = dashboard_container.attrs.get("Mounts", [])
            host_backup_path = None
            
            for mount in dashboard_mounts:
                if mount.get("Destination") == "/app/backups":
                    host_backup_path = mount.get("Source")
                    break
            
            if not host_backup_path:
                raise Exception("Could not find backup directory mount. Ensure ./backups is mounted in docker-compose.yml")
            
            # Use busybox to create tarball with the host path
            self.client.containers.run(
                "busybox:latest",
                command=f"sh -c 'tar czf /backup/{backup_filename} -C /source . && chmod 666 /backup/{backup_filename}'",
                volumes={
                    "n8n_data": {"bind": "/source", "mode": "ro"},
                    host_backup_path: {"bind": "/backup", "mode": "rw"}
                },
                remove=True
            )
            
            return backup_filename
        except Exception as e:
            raise Exception(f"Failed to create backup: {str(e)}")

    def pre_upgrade_checks(self, target_version: str) -> Dict:
        """
        Perform safety checks before upgrading.
        
        Args:
            target_version: Version to upgrade to
            
        Returns:
            Dict with 'safe' boolean and 'warnings' list
        """
        warnings = []
        
        try:
            status = self.get_container_status()
            current_version = status.get("current_version")
            
            if not current_version or current_version == "unknown":
                return {
                    "safe": True,
                    "warnings": ["Current version unknown, proceeding with caution"]
                }
            
            current = semver.Version.parse(current_version)
            target = semver.Version.parse(target_version)
            
            # Check for major version jump
            if target.major > current.major:
                warnings.append(
                    f"Major version jump detected: {current_version} -> {target_version}. "
                    "Please review n8n release notes for breaking changes."
                )
            
            # Check for large version gap
            if target.major == current.major:
                minor_diff = target.minor - current.minor
                if minor_diff > 10:
                    warnings.append(
                        f"Large version gap detected ({minor_diff} minor versions). "
                        "Consider incremental upgrades."
                    )
            
            # Check for downgrade
            if target < current:
                warnings.append(
                    f"Downgrading from {current_version} to {target_version}. "
                    "This may cause data compatibility issues."
                )
            
            return {
                "safe": len(warnings) == 0 or all("consider" in w.lower() for w in warnings),
                "warnings": warnings
            }
        except Exception as e:
            return {
                "safe": False,
                "warnings": [f"Version check failed: {str(e)}"]
            }

    def update_to_version(self, target_version: str, callback: Optional[Callable] = None) -> str:
        """
        Update n8n container to a specific version.
        
        Args:
            target_version: Version tag to upgrade to
            callback: Optional function to report progress (message: str)
            
        Returns:
            New container ID
        """
        try:
            if callback:
                callback("Getting current container configuration...")
            
            # Get current container configuration
            ports_config = None
            volumes_config = None
            network_config = None
            env_dict = {}
            
            try:
                container = self.client.containers.get(self.container_name)
                config = container.attrs.get("Config", {})
                host_config = container.attrs.get("HostConfig", {})
                env_vars = config.get("Env", [])
                
                # Parse environment variables
                for env in env_vars:
                    if "=" in env:
                        key, value = env.split("=", 1)
                        env_dict[key] = value
                
                # Extract port bindings
                port_bindings = host_config.get("PortBindings", {})
                if port_bindings:
                    ports_config = {}
                    for container_port, host_bindings in port_bindings.items():
                        if host_bindings:
                            # Extract port number from "5678/tcp" format if needed
                            port_num = container_port
                            if isinstance(container_port, str) and "/" in container_port:
                                port_num = int(container_port.split("/")[0])
                            ports_config[port_num] = int(host_bindings[0]["HostPort"])
                
                # Extract volume mounts
                mounts = host_config.get("Mounts", [])
                if mounts:
                    volumes_config = {}
                    for mount in mounts:
                        if mount.get("Type") == "volume":
                            # Handle both "Destination" and "destination" keys
                            destination = mount.get("Destination") or mount.get("destination")
                            mount_name = mount.get("Name")
                            if mount_name and destination:
                                volumes_config[mount_name] = {
                                    "bind": destination,
                                    "mode": mount.get("Mode", mount.get("mode", "rw"))
                                }
                
                # Extract network information
                network_settings = container.attrs.get("NetworkSettings", {})
                networks = network_settings.get("Networks", {})
                if networks:
                    # Get the first network (usually the main one)
                    network_config = list(networks.keys())[0]
                
                if callback:
                    callback("Stopping current container...")
                
                # Stop container
                container.stop(timeout=60)
                
                if callback:
                    callback("Removing old container...")
                
                # Remove container
                container.remove()
            except docker.errors.NotFound:
                if callback:
                    callback("Container not found, creating new one...")
                # Use defaults if container doesn't exist
                ports_config = {5678: 5678}
                volumes_config = {"n8n_data": {"bind": "/home/node/.n8n", "mode": "rw"}}
            
            if callback:
                callback(f"Pulling image n8nio/n8n:{target_version}...")
            
            # Pull new image
            image_tag = f"{self.image_name}:{target_version}"
            self.client.images.pull(image_tag)
            
            if callback:
                callback("Creating new container...")
            
            # Prepare port bindings in the correct format for host_config
            # Format: {container_port: host_port} - simple integer mapping
            port_bindings_dict = {}
            ports_list = []
            if ports_config:
                for container_port, host_port in ports_config.items():
                    # Extract port number if it's in "5678/tcp" format
                    if isinstance(container_port, str) and "/" in container_port:
                        container_port = int(container_port.split("/")[0])
                    port_bindings_dict[int(container_port)] = int(host_port)
                    ports_list.append(int(container_port))
            else:
                port_bindings_dict[5678] = 5678
                ports_list = [5678]
            
            # Convert env_dict back to list format
            env_list = [f"{k}={v}" for k, v in env_dict.items()]
            
            # Use volumes format expected by docker-py
            # Format: {volume_name: {"bind": mount_point, "mode": "rw"}}
            volumes = volumes_config or {"n8n_data": {"bind": "/home/node/.n8n", "mode": "rw"}}
            
            # Ensure volumes dict is properly formatted
            if not volumes or not isinstance(volumes, dict):
                volumes = {"n8n_data": {"bind": "/home/node/.n8n", "mode": "rw"}}
            
            # Validate volumes format
            validated_volumes = {}
            for vol_name, vol_config in volumes.items():
                if isinstance(vol_config, dict) and "bind" in vol_config:
                    validated_volumes[vol_name] = vol_config
                else:
                    # If format is wrong, use default
                    validated_volumes[vol_name] = {"bind": "/home/node/.n8n", "mode": "rw"}
            
            # Use the low-level API to create container with proper host_config
            # The high-level containers.create() doesn't accept host_config in newer docker-py versions
            host_config_dict = self.client.api.create_host_config(
                port_bindings=port_bindings_dict,
                restart_policy={"Name": "unless-stopped"},
                binds={vol_name: vol_config["bind"] for vol_name, vol_config in validated_volumes.items()}
            )
            
            # Prepare volumes list for create_container
            # Format: list of mount points
            volumes_list = [vol_config["bind"] for vol_config in validated_volumes.values()]
            
            # Create container using low-level API
            # The API expects image as first param, not in a config dict
            container_response = self.client.api.create_container(
                image=image_tag,
                name=self.container_name,
                ports=ports_list,
                host_config=host_config_dict,
                environment=env_list,
                volumes=volumes_list
            )
            
            # Get the container object from the response
            new_container = self.client.containers.get(container_response["Id"])
            
            # Connect to network if specified
            if network_config:
                try:
                    network = self.client.networks.get(network_config)
                    network.connect(new_container)
                except Exception:
                    # If network connection fails, try to find network by container name pattern
                    # This handles docker-compose network naming (project_name_web)
                    all_networks = self.client.networks.list()
                    for net in all_networks:
                        if "web" in net.name.lower() or network_config in net.name:
                            try:
                                net.connect(new_container)
                                break
                            except Exception:
                                continue
            
            if callback:
                callback("Starting new container...")
            
            # Start container
            new_container.start()
            
            if callback:
                callback("Upgrade complete!")
            
            return new_container.id
        except Exception as e:
            raise Exception(f"Failed to update container: {str(e)}")

    def rollback_to_previous(self) -> str:
        """
        Rollback to the previous version by using the first local image that's different from current.
        
        Returns:
            New container ID
        """
        try:
            # Get current container status to check current version
            current_status = self.get_container_status()
            current_version = current_status.get("current_version")
            
            images = self.get_local_images()
            if len(images) < 2:
                raise Exception("No previous version found locally")
            
            # Find the first image that's different from current version
            # Try index 1 first (second-newest), then check others
            rollback_version = None
            rollback_index = 1  # Default to second-newest
            
            if len(images) > 1 and images[1]["version"] != current_version:
                rollback_version = images[1]["version"]
            else:
                # Find first image that's different from current
                for i, image in enumerate(images):
                    if image["version"] != current_version:
                        rollback_version = image["version"]
                        rollback_index = i
                        break
            
            if not rollback_version:
                raise Exception(f"Already running version {current_version}. Cannot rollback to the same version.")
            
            # Double-check we're not trying to rollback to current version
            if rollback_version == current_version:
                raise Exception(f"Already running version {rollback_version}. Cannot rollback to the same version.")
            
            return self.update_to_version(rollback_version)
        except Exception as e:
            raise Exception(f"Failed to rollback: {str(e)}")

    def get_local_images(self) -> List[Dict[str, str]]:
        """
        Get list of locally available n8n images.
        
        Returns:
            List of dicts with 'version' and 'created' keys, sorted newest first
        """
        try:
            images = self.client.images.list(name=self.image_name)
            result = []
            
            for image in images:
                for tag in image.tags:
                    if self.image_name in tag:
                        parts = tag.split(":")
                        if len(parts) == 2:
                            version = parts[1]
                            created = image.attrs.get("Created", "")
                            
                            # If version is "latest", try to resolve to actual version
                            if version == "latest":
                                try:
                                    # Get labels from image attributes
                                    labels = image.attrs.get("Config", {}).get("Labels", {})
                                    # Try multiple possible label keys for version
                                    version_label = (
                                        labels.get("org.opencontainers.image.version") or
                                        labels.get("version") or
                                        labels.get("n8n.version") or
                                        labels.get("io.n8n.version")
                                    )
                                    if version_label:
                                        version = version_label
                                    else:
                                        # Try to get from image repo tags - sometimes latest points to a specific version
                                        image_repo_tags = image.attrs.get("RepoTags", [])
                                        for repo_tag in image_repo_tags:
                                            if ":" in repo_tag and not repo_tag.endswith(":latest"):
                                                tag_part = repo_tag.split(":")[-1]
                                                # If it looks like a version number, use it
                                                if tag_part and tag_part.replace(".", "").replace("-", "").isdigit():
                                                    version = tag_part
                                                    break
                                except Exception:
                                    pass  # Keep "latest" if we can't resolve it
                            
                            result.append({
                                "version": version,
                                "created": created
                            })
                            break
            
            # Sort by creation date descending
            result.sort(key=lambda x: x["created"], reverse=True)
            return result
        except Exception as e:
            raise Exception(f"Failed to get local images: {str(e)}")

    def start_container(self):
        """Start the n8n container."""
        try:
            container = self.client.containers.get(self.container_name)
            container.start()
        except docker.errors.NotFound:
            raise Exception("Container not found")
        except Exception as e:
            raise Exception(f"Failed to start container: {str(e)}")

    def stop_container(self):
        """Stop the n8n container."""
        try:
            container = self.client.containers.get(self.container_name)
            container.stop(timeout=60)
        except docker.errors.NotFound:
            raise Exception("Container not found")
        except Exception as e:
            raise Exception(f"Failed to stop container: {str(e)}")

    def restart_container(self):
        """Restart the n8n container."""
        try:
            container = self.client.containers.get(self.container_name)
            container.restart(timeout=60)
        except docker.errors.NotFound:
            raise Exception("Container not found")
        except Exception as e:
            raise Exception(f"Failed to restart container: {str(e)}")

