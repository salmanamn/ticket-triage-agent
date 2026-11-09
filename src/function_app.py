import json

import azure.functions as func

from triage.ingest import handle_submission
from triage.queue import ServiceBusPublisher

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_publisher = ServiceBusPublisher()


@app.route(route="tickets", methods=["POST"])
def submit_ticket(req: func.HttpRequest) -> func.HttpResponse:
    result = handle_submission(req.get_body(), _publisher)
    return func.HttpResponse(json.dumps(result.payload), status_code=result.status, mimetype="application/json")


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"status":"ok"}', mimetype="application/json")
