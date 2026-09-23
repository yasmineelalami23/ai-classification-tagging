"""Custom tools for the LLM agent."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
from google.adk.tools import ToolContext
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
import logging
logger = logging.getLogger(__name__)

def get_table_schema(project_id: str, dataset_id: str, table_name: str, user_token: str) -> str:
    """
    Retrieves the schema metadata for a specific BigQuery table.
    Returns a JSON string of column names, their data types, and descriptions.
    """
    # 1. Create credentials from the user's token
    creds = Credentials(token=user_token)
    
    # 2. Initialize BigQuery client with the user's credentials
    client = bigquery.Client(credentials=creds, project=project_id)
    table_fqn = f"{project_id}.{dataset_id}.{table_name}"
    
    try:
        table = client.get_table(table_fqn)
        
        schema = {
            field.name: {
                "type": field.field_type,
                "description": field.description or ""
            }
            for field in table.schema
        }
        return json.dumps(schema, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})

def get_table_samples(project_id: str, dataset_id: str, table_name: str, user_token: str, num_rows: int = 10) -> str:
    """
    Retrieves a sample of rows from a BigQuery table directly from storage without 
    requiring query job creation permissions, and pivots them into column arrays.
    """
    # 1. Create credentials from the user's token
    creds = Credentials(token=user_token)
    
    # 2. Initialize BigQuery client with the user's credentials
    client = bigquery.Client(credentials=creds, project=project_id)
    table_fqn = f"{project_id}.{dataset_id}.{table_name}"
    
    try:
        rows = client.list_rows(table_fqn, max_results=num_rows)
        
        pivoted_samples = {}
        
        for row in rows:
            for col_name, val in row.items():
                if col_name not in pivoted_samples:
                    pivoted_samples[col_name] = []
                    
                # Keep unique, non-null samples to keep the prompt lean
                if val is not None and str(val) not in pivoted_samples[col_name]:
                    pivoted_samples[col_name].append(str(val))
                    
        return json.dumps(pivoted_samples, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})

def get_raw_table_samples(project_id: str, dataset_id: str, table_name: str, user_token: str, num_rows: int = 10) -> str:
    """
    Retrieves a sample of raw, intact rows from a BigQuery table.
    Used for row-level evaluation (like Countryness) where horizontal data alignment is critical.
    """
    creds = Credentials(token=user_token)
    client = bigquery.Client(credentials=creds, project=project_id)
    table_fqn = f"{project_id}.{dataset_id}.{table_name}"
    
    try:
        rows = client.list_rows(table_fqn, max_results=num_rows)
        return json.dumps([dict(row.items()) for row in rows], default=str)
        
    except Exception as e:
        return json.dumps({"error": str(e)})


def apply_policy_tags(
    project_id: str,
    dataset_id: str,
    table_name: str,
    approved_classifications: str,
    user_token: str
) -> str:
    """Applies approved Policy Tags directly to BigQuery table column schema.

    approved_classifications must be a JSON string mapping column_name ->
    tag_type (e.g. '{"email": "PII"}'). ONLY call this tool AFTER the human user
    explicitly approves the proposal in the chat.
    """
    try:
        # 1. Create credentials from the user's token
        creds = Credentials(token=user_token)
        
        # 2. Initialize BigQuery client with the user's credentials
        client = bigquery.Client(credentials=creds, project=project_id)
        
        table_fqn = f"{project_id}.{dataset_id}.{table_name}"
        table = client.get_table(table_fqn)

        tags_map = (
            json.loads(approved_classifications)
            if isinstance(approved_classifications, str)
            else approved_classifications
        )

        TAXONOMY_MAP = {
            "Non-sensitive": "projects/search-ahmed/locations/us/taxonomies/3115733225721264165/policyTags/8463002324035971336",
            "PII": "projects/search-ahmed/locations/us/taxonomies/3115733225721264165/policyTags/5588035927081414315",
            "SPII": "projects/search-ahmed/locations/us/taxonomies/3115733225721264165/policyTags/6855687727075655768",
        }

        updated_schema = []
        applied_count = 0

        for field in table.schema:
            field_dict = field.to_api_repr()
            if field.name in tags_map and tags_map[field.name] in TAXONOMY_MAP:
                field_dict["policyTags"] = {
                    "names": [TAXONOMY_MAP[tags_map[field.name]]]
                }
                applied_count += 1
            updated_schema.append(
                bigquery.SchemaField.from_api_repr(field_dict)
            )

        table.schema = updated_schema
        client.update_table(table, ["schema"])

        return json.dumps(
            {
                "status": "success",
                "message": f"Successfully applied {applied_count} policy tags to {table_fqn}.",
            }
        )
    except Exception as e:
        return json.dumps({"status": "error", "details": str(e)})

def apply_countryness_logic(table_fqn: str, row_updates: list, user_token: str) -> str:
    """
    Adds ISO_Country column if missing, and safely updates rows based on AI predictions.
    """
    if not row_updates:
        return json.dumps({"status": "error", "details": "No row updates provided by AI."})

    try:
        # 1. Parse table_fqn to get project_id
        parts = table_fqn.split('.')
        if len(parts) != 3:
            return json.dumps({"status": "error", "details": "table_fqn must be in format project_id.dataset_id.table_name"})
        
        project_id = parts[0]

        # 2. Initialize BigQuery Client using user_token credentials
        creds = Credentials(token=user_token)
        client = bigquery.Client(credentials=creds, project=project_id)

        logger.info(f"Starting Countryness update for {table_fqn}...")

        # 3. Safely add the column if it doesn't exist
        alter_sql = f"ALTER TABLE `{table_fqn}` ADD COLUMN IF NOT EXISTS _dfgdia_iso3_country_std_cnty STRING;"
        logger.info(f"Executing: {alter_sql}")
        client.query(alter_sql).result()

        # 4. Dynamically detect the Primary Key column from the AI payload
        first_row = row_updates[0]
        ignore_keys = {"source_field", "value", "proposed_iso_country", "_dfgdia_iso3_country_std_cnty", "reasoning", "confidence"}
        
        # Find key column name (e.g., contract_or_offer_id, cust_id_nb, or record_id)
        pk_col = next((k for k in first_row.keys() if k not in ignore_keys), "record_id")

        # 5. Build CASE statement for dynamic update
        cases = []
        record_ids = []

        for row in row_updates:
            rec_id = row.get(pk_col) or row.get("record_id") or row.get("id")
            iso_val = row.get("proposed_iso_country") or row.get("_dfgdia_iso3_country_std_cnty")

            if rec_id and iso_val and str(iso_val).upper() != "NULL":
                cases.append(f"WHEN `{pk_col}` = '{rec_id}' THEN '{iso_val}'")
                record_ids.append(f"'{rec_id}'")

        if not cases:
            return json.dumps({"status": "success", "message": "Column verified. No country updates required."})

        cases_str = "\n            ".join(cases)
        ids_str = ", ".join(record_ids)

        update_sql = f"""
        UPDATE `{table_fqn}`
        SET _dfgdia_iso3_country_std_cnty = CASE 
            {cases_str}
            ELSE _dfgdia_iso3_country_std_cnty
        END
        WHERE `{pk_col}` IN ({ids_str});
        """

        logger.info(f"Executing UPDATE:\n{update_sql}")
        client.query(update_sql).result()

        return json.dumps({"status": "success", "message": f"Successfully updated {len(cases)} rows in {table_fqn}."})

    except Exception as e:
        error_msg = f"BigQuery execution failed for {table_fqn}: {str(e)}"
        logger.error(error_msg)
        return json.dumps({"status": "error", "details": error_msg})