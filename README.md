# n8n Management Dashboard

A self-hosted management dashboard for n8n that provides a web UI for version upgrades, container lifecycle management, and backup operations. This dashboard replicates n8n Cloud's version upgrade experience for Docker Desktop deployments.

## Features

- **One-Click Upgrades**: Select and upgrade to any available n8n version from Docker Hub
- **Container Management**: Start, stop, and restart n8n containers with a simple interface
- **Automatic Backups**: Automatic volume backups before each upgrade
- **Version Safety Checks**: Pre-upgrade validation with warnings for major version jumps
- **Rollback Support**: Quick rollback to previous versions
- **Localhost Security**: Dashboard only accessible from localhost
- **Password Protection**: Simple password-based authentication

<img width="1297" height="792" alt="Screenshot 2025-11-30 at 12 30 59" src="https://github.com/user-attachments/assets/831f53d5-1304-4711-b4e5-1ceb28cce1e0" />

## Prerequisites

- Docker Desktop installed and running
- Docker Compose (included with Docker Desktop)
- Port 8080 available for the dashboard
- Port 5678 available for n8n (or modify in docker-compose.yml)

### Docker Desktop File Sharing (Mac/Windows)

**Important for Mac and Windows users**: Docker Desktop requires explicit file sharing permissions for backup functionality to work.

1. Open Docker Desktop
2. Go to **Settings** (gear icon) → **Resources** → **File Sharing**
3. Ensure your project directory is in the shared paths list:
   - For Mac: `/Users/your-username/Projects` or the full path to this project
   - For Windows: `C:\Users\your-username\Projects` or the full path to this project
4. If not listed, click **"+ Add"** and add the directory containing this project
5. Click **"Apply & Restart"** (Docker Desktop will restart)

Without this configuration, backup operations will fail with a "path is not shared" error.

## Quick Start

1. **Clone or download this repository**

2. **Create environment file**:
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env` file** with your configuration:
   ```bash
   # Generate a secure random key for SECRET_KEY
   # Set a strong password for DASHBOARD_PASSWORD
   # Configure your n8n encryption key (or leave empty for auto-generation)
   ```

4. **Start the services**:
   ```bash
   docker-compose up -d
   ```

5. **Access the dashboard**:
   Open your browser and navigate to `http://localhost:8080`

6. **Login**:
   Use the password you set in `DASHBOARD_PASSWORD`

## Environment Variables

### Dashboard Security

- `SECRET_KEY`: Flask session secret key (generate a random string)
- `DASHBOARD_PASSWORD`: Password for dashboard login

### n8n Configuration

- `N8N_VERSION`: Initial n8n version to deploy (default: `latest`)
- `N8N_ENCRYPTION_KEY`: Encryption key for n8n credentials (required for persistence)
- `TZ`: Timezone for n8n (default: `Europe/London`)

## Usage Guide

### Viewing Container Status

The dashboard displays:
- Current container status (Running/Stopped/Not Found)
- Installed n8n version
- Container start time
- Health status

### Upgrading n8n

1. Select a version from the dropdown menu
2. Click "Check Upgrade" to validate the upgrade
3. Review any warnings displayed
4. Click "Upgrade" to proceed (a backup is created automatically)

### Container Controls

- **Start**: Start a stopped container
- **Stop**: Stop a running container
- **Restart**: Restart a running container
- **Refresh**: Update the status display

### Rolling Back

If you need to rollback to a previous version:
1. Find the previous version in the "Local Images" section
2. Click "Rollback" (only available for the second-newest image)
3. Confirm the rollback operation

## Security Notes

### Localhost Binding

The dashboard is configured to bind only to `127.0.0.1:8080`, making it accessible only from your local machine. This prevents external network access to the management interface.

### Docker Socket Security

The dashboard uses `tecnativa/docker-socket-proxy` to securely access the Docker API. The proxy:
- Filters which Docker API calls are permitted
- Prevents direct socket access from the dashboard container
- Only allows necessary operations (container management, image pulling)

**Never mount the Docker socket directly into the dashboard container.**

### Password Protection

Always set a strong `DASHBOARD_PASSWORD` in your `.env` file. The dashboard uses Flask sessions for authentication.

## Backup and Restore

### Automatic Backups

Before each upgrade, the dashboard automatically creates a backup of the `n8n_data` volume. Backups are stored in the `./backups` directory with timestamps.

### Manual Backup

To create a manual backup:

```bash
docker run --rm -v n8n-manager_n8n_data:/source -v $(pwd)/backups:/backup busybox tar czf /backup/n8n_backup_manual_$(date +%Y%m%d_%H%M%S).tar.gz -C /source .
```

### Restore from Backup

1. Stop the n8n container:
   ```bash
   docker-compose stop n8n
   ```

2. Restore the backup:
   ```bash
   docker run --rm -v n8n-manager_n8n_data:/target -v $(pwd)/backups:/backup busybox tar xzf /backup/n8n_backup_YYYYMMDD_HHMMSS.tar.gz -C /target
   ```

3. Start the container:
   ```bash
   docker-compose start n8n
   ```

## Project Structure

```
n8n-manager/
├── docker-compose.yml          # Main orchestration file
├── .env.example                 # Environment variable template
├── .env                         # Local environment variables (gitignored)
├── dashboard/
│   ├── Dockerfile              # Dashboard container build
│   ├── requirements.txt        # Python dependencies
│   ├── app.py                  # Flask application entry point
│   ├── docker_manager.py       # Docker operations class
│   ├── static/
│   │   └── css/
│   │       └── custom.css      # Custom styles
│   └── templates/
│       ├── base.html           # Base template with Tailwind CDN
│       ├── dashboard.html      # Main dashboard view
│       └── login.html          # Authentication page
├── backups/                    # Volume backup storage (gitignored)
└── README.md                   # This file
```

## Troubleshooting

### Dashboard not accessible

- Check that Docker Desktop is running
- Verify port 8080 is not in use: `lsof -i :8080`
- Check container logs: `docker-compose logs dashboard`

### Upgrade fails

- Check Docker has enough disk space
- Verify network connectivity to Docker Hub
- Review container logs: `docker-compose logs n8n`

### Container not found

- Ensure the n8n container name matches `N8N_CONTAINER_NAME` in `.env`
- Check if container exists: `docker ps -a | grep n8n`

### Backup creation fails

**Error: "mounts denied: The path is not shared from the host"**

This error occurs on Docker Desktop for Mac/Windows when the project directory isn't shared:

1. Open Docker Desktop
2. Go to **Settings** → **Resources** → **File Sharing**
3. Add your project directory to the shared paths:
   - Mac: `/Users/your-username/Projects` (or the full path to this project)
   - Windows: `C:\Users\your-username\Projects` (or the full path to this project)
4. Click **"Apply & Restart"**
5. Try the backup operation again

**Other backup issues:**
- Ensure `./backups` directory exists and is writable
- Check disk space availability
- Verify volume name matches: `docker volume ls | grep n8n_data`

### Version list empty

- Check internet connectivity
- Verify Docker Hub API is accessible
- Review dashboard logs for API errors

## Encryption Key Management

**Important**: The `N8N_ENCRYPTION_KEY` must remain constant across upgrades. Changing this key will break all stored credentials in n8n workflows.

- If not set, n8n auto-generates a key on first run and stores it in the volume
- To retrieve an existing key, check n8n's environment or volume data
- Always backup your encryption key separately

## Stopping the Services

To stop all services:

```bash
docker-compose down
```

To stop and remove volumes (⚠️ **WARNING**: This deletes n8n data):

```bash
docker-compose down -v
```

## Updating the Dashboard

To update the dashboard itself:

```bash
docker-compose build dashboard
docker-compose up -d dashboard
```

## License

This project is provided as-is for self-hosted n8n management.

## Support

For issues related to:
- **n8n itself**: Visit [n8n documentation](https://docs.n8n.io)
- **This dashboard**: Check the troubleshooting section above or review logs

## Optional Enhancements

Future enhancements could include:
- WebSocket for real-time upgrade progress
- Changelog display from n8n GitHub releases
- Scheduled update checks with notifications
- Multiple n8n instance management
- Database backup for PostgreSQL deployments
- Dark/light theme toggle

