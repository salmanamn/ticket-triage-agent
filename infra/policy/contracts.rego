# Contracts the application code depends on: queue semantics (D8, D11), vector search (D9),
# the Ticket.Triaged subscription (D13) and the Flex Consumption host (D1).
package main

import rego.v1

# --- Service Bus: tickets queue ---------------------------------------------------------------

deny contains msg if {
	some rc in resources("azurerm_servicebus_namespace")
	rc.change.after.sku == "Basic"
	msg := sprintf("%s: Basic tier has no duplicate detection (D8)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_servicebus_queue")
	rc.change.after.requires_duplicate_detection != true
	msg := sprintf("%s: duplicate detection must be on (MessageId = ticket_id, D8)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_servicebus_queue")
	rc.change.after.max_delivery_count != 5
	msg := sprintf("%s: max_delivery_count must be 5 = TRIAGE_MAX_ATTEMPTS (D11)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_servicebus_queue")
	rc.change.after.dead_lettering_on_message_expiration != true
	msg := sprintf("%s: expired tickets must be dead-lettered, not dropped", [rc.address])
}

# --- Cosmos DB: serverless + vector search --------------------------------------------------

capabilities(rc) := {c.name | some c in rc.change.after.capabilities}

deny contains msg if {
	some rc in resources("azurerm_cosmosdb_account")
	some needed in {"EnableServerless", "EnableNoSQLVectorSearch"}
	not needed in capabilities(rc)
	msg := sprintf("%s: capability %s is required (D2, D9)", [rc.address, needed])
}

knowledge_container(rc) := c if {
	template := json.unmarshal(rc.change.after.template_content)
	some c in template.resources
	c.type == "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers"
}

deny contains msg if {
	some rc in resources("azurerm_resource_group_template_deployment")
	rc.name == "knowledge"
	not knowledge_container(rc)
	msg := sprintf("%s: template must create the knowledge container", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_resource_group_template_deployment")
	c := knowledge_container(rc).properties.resource
	not vector_policy_ok(c)
	msg := sprintf("%s: knowledge needs /embedding float32 cosine with a diskANN index, excluded from the regular index (D9)", [rc.address])
}

vector_policy_ok(c) if {
	c.partitionKey.paths == ["/kind"]
	[e] := c.vectorEmbeddingPolicy.vectorEmbeddings
	e.path == "/embedding"
	e.dataType == "float32"
	e.distanceFunction == "cosine"
	c.indexingPolicy.vectorIndexes == [{"path": "/embedding", "type": "diskANN"}]
	{"path": "/embedding/*"} in c.indexingPolicy.excludedPaths
}

# --- Event Grid: Ticket.Triaged -------------------------------------------------------------

deny contains msg if {
	some rc in resources("azurerm_eventgrid_topic")
	rc.change.after.input_schema != "CloudEventSchemaV1_0"
	msg := sprintf("%s: topic input schema must be CloudEvents 1.0 (D13)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_eventgrid_event_subscription")
	rc.change.after.event_delivery_schema != "CloudEventSchemaV1_0"
	msg := sprintf("%s: deliver CloudEvents 1.0 (notify_ticket takes func.CloudEvent)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_eventgrid_event_subscription")
	count(object.get(rc.change.after, "storage_blob_dead_letter_destination", [])) == 0
	msg := sprintf("%s: undeliverable events must be dead-lettered to blob (D16)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_eventgrid_event_subscription")
	count(object.get(rc.change.after, "dead_letter_identity", [])) == 0
	msg := sprintf("%s: dead-lettering must use the topic's managed identity (storage has no keys)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_eventgrid_event_subscription")
	rc.change.after.included_event_types != ["Ticket.Triaged"]
	msg := sprintf("%s: subscription filters on Ticket.Triaged only; routing is in code (D13)", [rc.address])
}

# --- Function App: Flex Consumption ---------------------------------------------------------

deny contains msg if {
	some rc in resources("azurerm_function_app_flex_consumption")
	not flex_runtime_ok(rc.change.after)
	msg := sprintf("%s: runtime must be python 3.13 (D1)", [rc.address])
}

flex_runtime_ok(a) if {
	a.runtime_name == "python"
	a.runtime_version == "3.13"
}

deny contains msg if {
	some rc in resources("azurerm_function_app_flex_consumption")
	rc.change.after.storage_authentication_type == "StorageAccountConnectionString"
	msg := sprintf("%s: deployment storage must use a managed identity, not a connection string", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_function_app_flex_consumption")
	rc.change.after.https_only != true
	msg := sprintf("%s: HTTPS only", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_function_app_flex_consumption")
	rc.change.after.webdeploy_publish_basic_authentication_enabled != false
	msg := sprintf("%s: basic-auth publishing credentials must be disabled", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_function_app_flex_consumption")
	not rc.change.after.site_config[0].minimum_tls_version == "1.2"
	msg := sprintf("%s: minimum TLS must be 1.2", [rc.address])
}
# --- Azure OpenAI: pay-per-token only ---------------------------------------------------------

deny contains msg if {
	some rc in resources("azurerm_cognitive_deployment")
	some sku in rc.change.after.sku
	contains(sku.name, "Provisioned")
	msg := sprintf("%s: provisioned throughput (%s) is billed per hour whether used or not; use a Standard SKU", [rc.address, sku.name])
}
