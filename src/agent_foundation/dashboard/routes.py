import json
import logging
import os
from fastapi import APIRouter, HTTPException, Security, Depends
from pydantic import BaseModel
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.oauth2 import id_token
from google.auth.transport import requests
import requests as sync_requests
from typing import List, Dict, Any, Optional

os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

from google.genai import types
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner

from ..agent import root_agent
from ..tools import get_table_schema, get_table_samples, apply_policy_tags, apply_countryness_logic, get_raw_table_samples

router = APIRouter(prefix="/api", tags=["Data Steward Workflow"])
logger = logging.getLogger(__name__)

# --- MODELS ---
class AnalyzeRequest(BaseModel):
    table_fqn: str 

class TagApprovalRequest(BaseModel):
    id: int
    approved_tag: str

class BatchTagApprovalRequest(BaseModel):
    ids: list[int]

class BatchApproveItem(BaseModel):
    id: int
    approved_tag: str

class ModifyQueueRequest(BaseModel):
    id: int
    proposal: str
    reason: str

class PushCountrynessRequest(BaseModel):
    table_fqn: str
    row_updates: List[Dict[str, Any]]
    use_case_id: Optional[int] = None


REVIEW_QUEUE = []
_current_id = 1

security = HTTPBearer()

def verify_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """The Bouncer: Verifies an OAuth Access Token and gets the user info."""
    token = credentials.credentials
    
    resp = sync_requests.get(f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={token}")
    
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired Access Token")
        
    user_info = resp.json()
    
    return {"email": user_info.get("email"), "raw_token": token}


# --- ROUTES ---

@router.post("/analyze")
async def trigger_ai_analysis(request: AnalyzeRequest, user = Depends(verify_user)):
    """Uses custom tools to fetch data, then asks the central root_agent to classify."""
    global REVIEW_QUEUE, _current_id
    
    parts = request.table_fqn.split('.')
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Format must be project_id.dataset_id.table_name")
        
    project, dataset, table_name = parts

    try:
        schema_json = get_table_schema(project, dataset, table_name, user_token=user["raw_token"])
        samples_json = get_table_samples(project, dataset, table_name, num_rows=5, user_token=user["raw_token"])
        
        schema_dict = json.loads(schema_json)
        samples_dict = json.loads(samples_json)
        
        if "error" in schema_dict:
            raise Exception(schema_dict["error"])

        session_service = InMemorySessionService()
        session = await session_service.create_session(state={}, app_name='tagging_app', user_id='steward')
        
        runner = Runner(
            app_name='tagging_app', 
            agent=root_agent, 
            session_service=session_service
        )

       
        table_context = {
            "task": "sensitivity_classification",
            "schema": schema_dict,
            "samples": samples_dict
        }
        
    
        content = types.Content(role='user', parts=[types.Part(text=json.dumps(table_context))])
        events_async = runner.run_async(session_id=session.id, user_id=session.user_id, new_message=content)
        
        ai_output = ""
        async for event in events_async:
            if getattr(event, 'content', None) and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        ai_output += part.text
                        
        ai_output = ai_output.strip()
        
        if ai_output.startswith("```"):
            lines = ai_output.split("\n")
            if lines[0].startswith("```"): lines = lines[1:]
            if lines[-1].startswith("```"): lines = lines[:-1]
            ai_output = "\n".join(lines).strip()
            
        try:
            parsed_results = json.loads(ai_output)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI output: {ai_output}")
            raise Exception("AI did not return a valid JSON array. Please try again.")

        added_count = 0
        for item in parsed_results:
            REVIEW_QUEUE.append({
                "id": _current_id, 
                "project": project, 
                "dataset": dataset, 
                "table": table_name, 
                "column": item.get("column", "Unknown"), 
                "proposal": item.get("proposal", "Non-sensitive"),
                "confidence": item.get("confidence", 90), 
                "reason": item.get("reason", "No reason provided.")
            })
            _current_id += 1
            added_count += 1
            
        return {"status": "success", "message": f"AI instantly analyzed {added_count} columns."}
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/countryness/analyze")
async def analyze_countryness(request: AnalyzeRequest, user = Depends(verify_user)):
    """Analyzes a table specifically for OGC Countryness rules using the root agent."""
    parts = request.table_fqn.split('.')
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Format must be project_id.dataset_id.table_name")
        
    project, dataset, table_name = parts

    try:
        # 1. Fetch Schema
        schema_json = get_table_schema(project, dataset, table_name, user_token=user["raw_token"])
        schema_dict = json.loads(schema_json)
        
        if "error" in schema_dict:
            raise Exception(schema_dict["error"])

        # 2. Fetch Raw Rows (Using our new dedicated function)
        samples_json = get_raw_table_samples(project, dataset, table_name, num_rows=10, user_token=user["raw_token"])
        row_samples = json.loads(samples_json) # Already a perfect array of row objects

        # 3. Setup Agent Session
        session_service = InMemorySessionService()
        session = await session_service.create_session(state={}, app_name='tagging_app', user_id='steward')
        runner = Runner(app_name='tagging_app', agent=root_agent, session_service=session_service)

        # Pass the perfectly aligned row_samples
        table_context = {
            "task": "countryness_analysis",
            "schema": schema_dict,
            "samples": row_samples
        }
        
        content = types.Content(role='user', parts=[types.Part(text=json.dumps(table_context))])
        events_async = runner.run_async(session_id=session.id, user_id=session.user_id, new_message=content)
        
        ai_output = ""
        async for event in events_async:
            if getattr(event, 'content', None) and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        ai_output += part.text
                        
        # Clean JSON markdown blocks
        ai_output = ai_output.strip()
        if ai_output.startswith("```"):
            lines = ai_output.split("\n")
            if lines[0].startswith("```"): lines = lines[1:]
            if lines[-1].startswith("```"): lines = lines[:-1]
            ai_output = "\n".join(lines).strip()
            
        try:
            parsed_result = json.loads(ai_output)
            return {"status": "success", "data": parsed_result}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI output: {ai_output}")
            raise Exception("AI did not return a valid JSON object. Please try again.")

    except Exception as e:
        logger.error(f"Countryness Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/queue")
async def get_review_queue(user = Depends(verify_user)):
    return REVIEW_QUEUE

@router.post("/tags/approve")
async def approve_and_commit_tag(request: TagApprovalRequest, user = Depends(verify_user)):
    """Uses your tool to apply the tag directly to BigQuery."""
    
    item_index = next((index for (index, d) in enumerate(REVIEW_QUEUE) if d["id"] == request.id), None)
    if item_index is None:
        raise HTTPException(status_code=404, detail="Item not found.")

    approved_item = REVIEW_QUEUE.pop(item_index)
    classifications_json = json.dumps({approved_item["column"]: request.approved_tag})

    result_str = apply_policy_tags(
        project_id=approved_item["project"],
        dataset_id=approved_item["dataset"],
        table_name=approved_item["table"],
        approved_classifications=classifications_json,
        user_token=user["raw_token"]
    )
    
    result = json.loads(result_str)
    if result.get("status") == "error":
        REVIEW_QUEUE.insert(item_index, approved_item) 
        raise HTTPException(status_code=500, detail=result.get("details"))

    return {"status": "success", "message": result.get("message")}

@router.post("/tags/approve-batch")
async def approve_batch_tags(request: List[BatchApproveItem], user = Depends(verify_user)):
    """Groups pending tags by table and applies them in a single BigQuery call."""
    global REVIEW_QUEUE
    
   
    approved_tags_map = {item.id: item.approved_tag for item in request}
    

    items_to_approve = [item for item in REVIEW_QUEUE if item["id"] in approved_tags_map]
    if not items_to_approve:
        raise HTTPException(status_code=404, detail="No matching items found.")
        
    tables_map = {}
    for item in items_to_approve:
        key = (item["project"], item["dataset"], item["table"])
        if key not in tables_map:
            tables_map[key] = {}
     
        tables_map[key][item["column"]] = approved_tags_map[item["id"]]
        
    successful_ids = []
    
    for (project, dataset, table), classifications in tables_map.items():
        classifications_json = json.dumps(classifications)
        
        result_str = apply_policy_tags(
            project_id=project,
            dataset_id=dataset,
            table_name=table,
            approved_classifications=classifications_json,
            user_token=user["raw_token"]
        )
        
        result = json.loads(result_str)
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"Failed on {table}: {result.get('details')}")
            
        for item in items_to_approve:
            if (item["project"], item["dataset"], item["table"]) == (project, dataset, table):
                successful_ids.append(item["id"])

    # Remove successful items from the backend queue
    REVIEW_QUEUE = [item for item in REVIEW_QUEUE if item["id"] not in successful_ids]
    
    return {
        "status": "success", 
        "message": f"Lightning batch update: applied {len(successful_ids)} tags to BigQuery!"
    }

@router.put("/queue/modify")
async def modify_queue_item(request: ModifyQueueRequest, user = Depends(verify_user)):
    """Instantly syncs frontend modifications to the backend's queue memory."""
    global REVIEW_QUEUE
    for item in REVIEW_QUEUE:
        if item["id"] == request.id:
            item["proposal"] = request.proposal
            item["reason"] = request.reason
            return {"status": "success", "message": "Backend synced"}
    raise HTTPException(status_code=404, detail="Item not found")

@router.delete("/queue")
async def clear_queue(user = Depends(verify_user)):
    """Wipes the review queue clean if the user cancels."""
    global REVIEW_QUEUE
    REVIEW_QUEUE.clear()
    return {"status": "success", "message": "Queue cleared"}


@router.post("/countryness/apply")
async def apply_countryness(request: PushCountrynessRequest, user = Depends(verify_user)):
    parts = request.table_fqn.split('.')
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Format must be project_id.dataset_id.table_name")

    result_str = apply_countryness_logic(
        table_fqn=request.table_fqn,
        row_updates=request.row_updates,
        user_token=user["raw_token"]
    )
    

    result = json.loads(result_str)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("details"))

    return {"status": "success", "message": result.get("message")}