# Job Application Tracker API

A real-time email monitoring system that detects job applications in Gmail and stores them in Databricks.

## Features

- **Real-time Gmail Monitoring**: Continuously monitors Gmail for job application keywords
- **Intelligent Parsing**: Extracts company, job title, status, and application URL from emails
- **Databricks Integration**: Stores all applications in Databricks for analysis
- **RESTful API**: Complete API for managing and querying applications
- **Background Processing**: Runs monitoring in a background thread

## Setup

### 1. Gmail API Configuration

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop Application)
5. Download credentials and save as `credentials.json` in this directory

### 2. Databricks Configuration

1. Get your Databricks workspace URL and personal access token
2. Create a `.env` file with:

```
DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-token
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
DATABRICKS_CATALOG=default
DATABRICKS_SCHEMA=job_applications
DATABRICKS_TABLE=applications
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the API

```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Monitoring Control

- `POST /monitor/start` - Start email monitoring
- `POST /monitor/stop` - Stop email monitoring
- `GET /monitor/status` - Get monitoring status

### Data Retrieval

- `GET /applications` - Get all applications (limit: 100)
- `GET /applications/status/{status}` - Filter by status (received, interview, rejected, pending)
- `GET /applications/company/{company}` - Filter by company
- `POST /sync` - Manually sync emails

### System

- `GET /health` - Health check

## Example Usage

```bash
# Start monitoring
curl -X POST http://localhost:8000/monitor/start

# Get all applications
curl http://localhost:8000/applications

# Get pending interviews
curl http://localhost:8000/applications/status/interview

# Get applications from specific company
curl http://localhost:8000/applications/company/Google
```

## Customization

### Modify Job Keywords

Edit `config.py` and update `JOB_KEYWORDS` list with keywords that match your use case.

### Change Monitoring Interval

In `main.py`, modify the `time.sleep(300)` value (currently 5 minutes).

### Add More Extraction Logic

Enhance `_extract_job_info()` in `email_monitor.py` to extract additional fields.

## Troubleshooting

**No emails being detected**:

- Verify `credentials.json` is in the correct location
- Check that Gmail OAuth token is valid
- Ensure keywords in `config.py` match your emails

**Databricks connection error**:

- Verify `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `DATABRICKS_HTTP_PATH`
- Check that workspace and warehouse are running

**Missing dependencies**:

```bash
pip install -r requirements.txt --upgrade
```

## Database Architecture

### Two-Schema Design (OLTP + OLAP)

This application uses a **hybrid database architecture** combining transactional and analytical schemas for optimal performance:

#### Transactional Schema (OLTP - Star Schema)

Optimized for write operations and analytical modeling using a star schema (single fact table + dimension tables):

| Table               | Purpose                                                                                                                                                                      |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dim_company`       | Company dimension (company_dim_id, company_name, domain, timestamps)                                                                                                         |
| `dim_job_title`     | Job title dimension (job_title_dim_id, title, category)                                                                                                                      |
| `dim_date`          | Date dimension (date_dim_id, the_date, year, month, day, iso_week)                                                                                                           |
| `dim_sender`        | Email sender dimension (sender_dim_id, sender_email, sender_name)                                                                                                            |
| `fact_applications` | Fact table storing application events and foreign keys to dimensions (application_id, message_id, company_dim_id, job_title_dim_id, sender_dim_id, date_dim_id, measures...) |

**Benefits:**

- Clear separation of measures (fact) and context (dimensions)
- Simplifies analytical queries and star-joins
- Efficient aggregation over dimensions (time, company, title)
- Keeps transactional data optimized for both writes and downstream analytics

#### Analytics Schema (OLAP - Denormalized)

Optimized for read operations and analytical queries:

| Table                    | Purpose                                                     |
| ------------------------ | ----------------------------------------------------------- |
| `applications_analytics` | Flattened, denormalized view combining all application data |

**Columns:** application_id, message_id, company_name, company_id, job_title, job_title_id, from_email, to_email, subject, email_date, application_status, application_url, received_timestamp, keywords_found, email_body_length, processed_timestamp, synced_to_analytics

**Benefits:**

- Lightning-fast queries (no joins needed)
- Pre-aggregated data for dashboards
- Simplified BI tool integration
- Ready for time-series analysis

#### Data Synchronization Flow

```
Email from Gmail
	↓
Email Parsing & Extraction
	↓
┌─ Transactional Schema (Write) ─┐
│ 1. Get/Create company record   │
│ 2. Get/Create job title record │
│ 3. Insert job_applications     │
│ 4. Insert keywords mapping     │
└────────────────────────────────┘
	↓
Automatic Sync Function
	↓
┌─ Analytics Schema (Read) ──┐
│ applications_analytics     │
│ (denormalized, flattened)  │
└────────────────────────────┘
	↓
API Endpoints / BI Tools / Dashboards
```

#### Query Examples

**From Transactional Schema (normalized):**

```sql
-- Find all applications for a company with the job title
SELECT ja.*, c.company_name, jt.title
FROM job_applications ja
JOIN companies c ON ja.company_id = c.company_id
JOIN job_titles jt ON ja.job_title_id = jt.job_title_id
WHERE c.company_name = 'Google';
```

**From Analytics Schema (denormalized):**

```sql
-- Same query is much simpler!
SELECT * FROM applications_analytics
WHERE company_name = 'Google';
```

This design ensures your system is optimized for both transactional integrity and analytical performance.
