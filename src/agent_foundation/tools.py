"""Custom tools for the LLM agent."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
from google.adk.tools import ToolContext
from google.cloud import bigquery

def get_table_schema(project_id: str, dataset_id: str, table_name: str) -> str:
    """
    Retrieves the schema metadata for a specific BigQuery table.
    Returns a JSON string of column names, their data types, and descriptions.
    """
    client = bigquery.Client(project=project_id)
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

def get_table_samples(project_id: str, dataset_id: str, table_name: str, num_rows: int = 10) -> str:
    """
    Retrieves a sample of rows from a BigQuery table directly from storage without 
    requiring query job creation permissions, and pivots them into column arrays.
    """
    client = bigquery.Client(project=project_id)
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


def apply_policy_tags(
    project_id: str,
    dataset_id: str,
    table_name: str,
    approved_classifications: str,
) -> str:
    """Applies approved Policy Tags directly to BigQuery table column schema.

    approved_classifications must be a JSON string mapping column_name ->
    tag_type (e.g. '{"email": "PII"}'). ONLY call this tool AFTER the human user
    explicitly approves the proposal in the chat.
    """
    try:
        client = bigquery.Client(project=project_id)
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