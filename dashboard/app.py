import os
import functools
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from dotenv import load_dotenv
from docker_manager import N8NManager

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Initialize n8n manager
container_name = os.getenv("N8N_CONTAINER_NAME", "n8n")
manager = N8NManager(container_name=container_name)


def login_required(f):
    """Decorator to require authentication for routes."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle login page."""
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        expected_password = os.getenv("DASHBOARD_PASSWORD", "").strip()
        
        # Check if password is configured
        if not expected_password or expected_password == "your-secure-password":
            flash("Password not configured. Please set DASHBOARD_PASSWORD in your .env file and restart the container.", "error")
        elif password == expected_password:
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        else:
            # More detailed error for debugging
            flash(f"Invalid password. Please check your password and try again.", "error")
    
    return render_template("login.html")


@app.route("/logout")
def logout():
    """Handle logout."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    """Main dashboard page."""
    try:
        status = manager.get_container_status()
        versions = manager.get_available_versions(limit=20)
        local_images = manager.get_local_images()
    except Exception as e:
        flash(f"Error loading dashboard: {str(e)}", "error")
        status = {"status": "error", "current_version": None}
        versions = []
        local_images = []
    
    return render_template(
        "dashboard.html",
        status=status,
        versions=versions,
        local_images=local_images
    )


@app.route("/api/status")
@login_required
def api_status():
    """API endpoint for container status."""
    try:
        status = manager.get_container_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/versions")
@login_required
def api_versions():
    """API endpoint for available versions."""
    try:
        versions = manager.get_available_versions(limit=20)
        return jsonify(versions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/check-upgrade", methods=["POST"])
@login_required
def api_check_upgrade():
    """API endpoint for pre-upgrade checks."""
    try:
        data = request.get_json()
        target_version = data.get("target_version")
        
        if not target_version:
            return jsonify({"error": "target_version is required"}), 400
        
        checks = manager.pre_upgrade_checks(target_version)
        return jsonify(checks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/update", methods=["POST"])
@login_required
def api_update():
    """API endpoint for updating n8n version."""
    try:
        data = request.get_json()
        target_version = data.get("target_version")
        
        if not target_version:
            return jsonify({"error": "target_version is required"}), 400
        
        # Create backup before upgrade
        backup_filename = manager.backup_volume()
        
        # Perform upgrade
        container_id = manager.update_to_version(target_version)
        
        return jsonify({
            "success": True,
            "backup_filename": backup_filename,
            "container_id": container_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rollback", methods=["POST"])
@login_required
def api_rollback():
    """API endpoint for rolling back to previous version."""
    try:
        container_id = manager.rollback_to_previous()
        return jsonify({
            "success": True,
            "container_id": container_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/control/<action>", methods=["POST"])
@login_required
def api_control(action):
    """API endpoint for container control (start, stop, restart)."""
    try:
        if action == "start":
            manager.start_container()
        elif action == "stop":
            manager.stop_container()
        elif action == "restart":
            manager.restart_container()
        else:
            return jsonify({"error": "Invalid action"}), 400
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)

