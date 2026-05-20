from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import threading
import time
from typing import List, Dict, Any
import config
from email_monitor import GmailMonitor
from databricks_handler import DatabricksHandler

app = FastAPI(title="Job Application Tracker API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
gmail_monitor = None
databricks_handler = None
monitoring_thread = None
is_monitoring = False


@app.on_event("startup")
async def startup_event():
    """Initialize components on startup"""
    global gmail_monitor, databricks_handler
    
    try:
        gmail_monitor = GmailMonitor()
        databricks_handler = DatabricksHandler()
            databricks_handler.create_tables_if_not_exist()
        print("✓ Gmail Monitor and Databricks Handler initialized")
    except Exception as e:
        print(f"✗ Startup error: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global is_monitoring
    is_monitoring = False
    if databricks_handler:
        databricks_handler.close()
    print("✓ API shutdown complete")


def monitor_emails_loop():
    """Background thread that continuously monitors for new job applications"""
    global is_monitoring
    
    while is_monitoring:
        try:
            # Get recent messages with job keywords
            messages = gmail_monitor.get_messages_with_keywords()
            
            if messages:
                for msg in messages:
                    msg_id = msg['id']
                    # Get full message details
                    email_data = gmail_monitor.get_message_details(msg_id)
                    
                    if email_data:
                        # Store in Databricks
                        databricks_handler.store_application(email_data)
                        print(f"✓ Processed: {email_data['subject']}")
            
            # Check every 5 minutes (adjust as needed)
            time.sleep(300)
        
        except Exception as e:
            print(f"✗ Error in monitoring loop: {e}")
            time.sleep(60)  # Wait before retrying


@app.post("/monitor/start")
async def start_monitoring(background_tasks: BackgroundTasks):
    """Start the email monitoring service"""
    global is_monitoring, monitoring_thread
    
    if is_monitoring:
        return {"status": "already running", "message": "Email monitoring is already active"}
    
    is_monitoring = True
    monitoring_thread = threading.Thread(target=monitor_emails_loop, daemon=True)
    monitoring_thread.start()
    
    return {
        "status": "started",
        "message": "Email monitoring service started",
        "check_interval": "5 minutes"
    }


@app.post("/monitor/stop")
async def stop_monitoring():
    """Stop the email monitoring service"""
    global is_monitoring
    
    if not is_monitoring:
        return {"status": "not running", "message": "Email monitoring is not active"}
    
    is_monitoring = False
    return {"status": "stopped", "message": "Email monitoring service stopped"}


@app.get("/monitor/status")
async def get_monitoring_status():
    """Get current monitoring status"""
    return {"is_monitoring": is_monitoring}


@app.post("/sync")
async def sync_emails():
    """Manual sync: check for new job applications and store them"""
    try:
        messages = gmail_monitor.get_messages_with_keywords()
        synced_count = 0
        
        for msg in messages:
            msg_id = msg['id']
            email_data = gmail_monitor.get_message_details(msg_id)
            
            if email_data and databricks_handler.store_application(email_data):
                synced_count += 1
        
        return {
            "status": "success",
            "messages_checked": len(messages),
            "messages_stored": synced_count
        }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/applications")
async def get_all_applications(limit: int = 100) -> Dict[str, Any]:
    """Retrieve all stored job applications"""
    applications = databricks_handler.get_all_applications(limit=limit)
    return {
        "total": len(applications),
        "applications": applications
    }


@app.get("/applications/status/{status}")
async def get_applications_by_status(status: str, limit: int = 50) -> Dict[str, Any]:
    """Retrieve applications filtered by status (received, interview, rejected, pending)"""
    valid_statuses = ["received", "interview", "rejected", "pending"]
    
    if status.lower() not in valid_statuses:
        return {
            "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        }
    
    applications = databricks_handler.get_applications_by_status(status.lower(), limit=limit)
    return {
        "status": status,
        "total": len(applications),
        "applications": applications
    }


@app.get("/applications/company/{company}")
async def get_applications_by_company(company: str, limit: int = 50) -> Dict[str, Any]:
    """Retrieve applications for a specific company"""
    all_apps = databricks_handler.get_all_applications(limit=1000)
    filtered = [app for app in all_apps if app['company'].lower() == company.lower()][:limit]
    
    return {
        "company": company,
        "total": len(filtered),
        "applications": filtered
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "monitoring_active": is_monitoring,
        "components": {
            "gmail": gmail_monitor is not None,
            "databricks": databricks_handler is not None
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
