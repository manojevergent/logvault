"""Load a BigQuery-format CSV into a BigQuery table.

Auth:
  - credentials_json set → service account key file (JSON string)
  - credentials_json absent/null → Application Default Credentials (ADC)

The table must already exist with the correct schema. Rows are appended.
"""

from __future__ import annotations

import json
import logging

from google.cloud import bigquery
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_BQ_SCOPES = ["https://www.googleapis.com/auth/bigquery"]


def load_csv_to_bigquery(csv_path: str, bq_config: dict) -> int:
    """Load *csv_path* into BigQuery with WRITE_APPEND.

    Returns the number of rows loaded.

    bq_config keys:
        project_id      GCP project
        dataset_id      BQ dataset
        table_id        BQ table
        credentials_json  Service-account JSON string; omit/null for ADC
    """
    project_id = bq_config["project_id"]
    dataset_id = bq_config["dataset_id"]
    table_id = bq_config["table_id"]
    creds_json = bq_config.get("credentials_json")

    if creds_json:
        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=_BQ_SCOPES)
        client = bigquery.Client(project=project_id, credentials=credentials)
    else:
        client = bigquery.Client(project=project_id)

    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=[
            bigquery.SchemaField("bu_name", "STRING"),
            bigquery.SchemaField("timestamp", "STRING"),
            bigquery.SchemaField("session_token", "STRING"),
            bigquery.SchemaField("sp_account_id", "STRING"),
            bigquery.SchemaField("api_name", "STRING"),
            bigquery.SchemaField("channel_partner_id", "STRING"),
        ],
        autodetect=False,
    )

    with open(csv_path, "rb") as f:
        load_job = client.load_table_from_file(f, table_ref, job_config=job_config)

    load_job.result()  # blocks until complete; raises on error
    rows = load_job.output_rows or 0
    logger.info("BQ load complete: %d rows → %s", rows, table_ref)
    return rows


__all__ = ["load_csv_to_bigquery"]
