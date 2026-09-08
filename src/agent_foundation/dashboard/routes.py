import json
import logging
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

# --- ADK IMPORTS ---
from google.genai import types
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner

from ..agent import root_agent
from ..tools import get_table_schema, get_table_samples, apply_policy_tags

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

class ModifyQueueRequest(BaseModel):
    id: int
    proposal: str
    reason: str

# --- QUEUE ---
REVIEW_QUEUE = []
_current_id = 1

# --- ROUTES ---
@router.post("/analyze")
async def trigger_ai_analysis(request: AnalyzeRequest):
    """Uses custom tools to fetch data, then asks the central root_agent to classify."""
    global REVIEW_QUEUE, _current_id
    
    parts = request.table_fqn.split('.')
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Format must be project_id.dataset_id.table_name")
        
    project, dataset, table_name = parts

    try:

        schema_json = get_table_schema(project, dataset, table_name)
        samples_json = get_table_samples(project, dataset, table_name, num_rows=5)
        
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
            "schema": schema_dict,
            "samples": samples_dict
        }
        

        prompt = f"Please analyze this table data and return a JSON array with 'column', 'proposal', 'reason', and a 'confidence' integer between 0 and 100:\n{json.dumps(table_context, indent=2)}"
        

        content = types.Content(role='user', parts=[types.Part(text=prompt)])
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

@router.get("/queue")
async def get_review_queue():
    return REVIEW_QUEUE

@router.post("/tags/approve")
async def approve_and_commit_tag(request: TagApprovalRequest):
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
        approved_classifications=classifications_json
    )
    
    result = json.loads(result_str)
    if result.get("status") == "error":
        REVIEW_QUEUE.insert(item_index, approved_item) 
        raise HTTPException(status_code=500, detail=result.get("details"))

    return {"status": "success", "message": result.get("message")}

@router.post("/tags/approve-batch")
async def approve_batch_tags(request: BatchTagApprovalRequest):
    """Groups pending tags by table and applies them in a single BigQuery call."""
    global REVIEW_QUEUE, APPROVED_QUEUE
    
    # 1. Isolate the items the user wants to approve
    items_to_approve = [item for item in REVIEW_QUEUE if item["id"] in request.ids]
    if not items_to_approve:
        raise HTTPException(status_code=404, detail="No matching items found.")
        
    # 2. Group items by their BigQuery table
    # Format: (project, dataset, table) -> {"col1": "tag1", "col2": "tag2"}
    tables_map = {}
    for item in items_to_approve:
        key = (item["project"], item["dataset"], item["table"])
        if key not in tables_map:
            tables_map[key] = {}
        # Use the currently proposed tag in the UI memory
        tables_map[key][item["column"]] = item["proposal"]
        
    # 3. Send one API call per table to BigQuery
    successful_ids = []
    
    for (project, dataset, table), classifications in tables_map.items():
        classifications_json = json.dumps(classifications)
        
        result_str = apply_policy_tags(
            project_id=project,
            dataset_id=dataset,
            table_name=table,
            approved_classifications=classifications_json
        )
        
        result = json.loads(result_str)
        if result.get("status") == "error":

            raise HTTPException(status_code=500, detail=f"Failed on {table}: {result.get('details')}")
            
       
        for item in items_to_approve:
            if (item["project"], item["dataset"], item["table"]) == (project, dataset, table):
                successful_ids.append(item["id"])
                

                item_copy = item.copy()
          
                    

    REVIEW_QUEUE = [item for item in REVIEW_QUEUE if item["id"] not in successful_ids]
    
    return {
        "status": "success", 
        "message": f"Lightning batch update: applied {len(successful_ids)} tags to BigQuery!"
    }


@router.put("/queue/modify")
async def modify_queue_item(request: ModifyQueueRequest):
    """Instantly syncs frontend modifications to the backend's queue memory."""
    global REVIEW_QUEUE
    for item in REVIEW_QUEUE:
        if item["id"] == request.id:
            item["proposal"] = request.proposal
            item["reason"] = request.reason
            return {"status": "success", "message": "Backend synced"}
    raise HTTPException(status_code=404, detail="Item not found")