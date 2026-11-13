# D6: managed identity everywhere. No local auth (keys, SAS, connection strings) on any data service,
# TLS 1.2 minimum, and no secret-bearing app settings.
package main

import rego.v1

deny contains msg if {
	some rc in resources("azurerm_servicebus_namespace")
	rc.change.after.local_auth_enabled != false
	msg := sprintf("%s: Service Bus local (SAS) auth must be disabled", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_servicebus_namespace")
	rc.change.after.minimum_tls_version != "1.2"
	msg := sprintf("%s: Service Bus minimum TLS must be 1.2", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_cosmosdb_account")
	rc.change.after.local_authentication_enabled != false
	msg := sprintf("%s: Cosmos DB key auth must be disabled (local_authentication_enabled = false)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_cosmosdb_account")
	rc.change.after.access_key_metadata_writes_enabled != false
	msg := sprintf("%s: Cosmos DB metadata writes through account keys must be disabled", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_cosmosdb_account")
	rc.change.after.minimal_tls_version != "Tls12"
	msg := sprintf("%s: Cosmos DB minimum TLS must be 1.2", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_eventgrid_topic")
	rc.change.after.local_auth_enabled != false
	msg := sprintf("%s: Event Grid topic keys must be disabled", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_application_insights")
	rc.change.after.local_authentication_enabled != false
	msg := sprintf("%s: Application Insights ingestion must require Entra ID", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_storage_account")
	rc.change.after.shared_access_key_enabled != false
	msg := sprintf("%s: storage Shared Key auth must be disabled", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_storage_account")
	rc.change.after.allow_nested_items_to_be_public != false
	msg := sprintf("%s: anonymous blob access must be disabled", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_storage_account")
	rc.change.after.min_tls_version != "TLS1_2"
	msg := sprintf("%s: storage minimum TLS must be TLS1_2", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_storage_account")
	rc.change.after.https_traffic_only_enabled != true
	msg := sprintf("%s: storage must be HTTPS-only", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_cognitive_account")
	rc.change.after.local_auth_enabled != false
	msg := sprintf("%s: Azure OpenAI key auth must be disabled (local_auth_enabled = false)", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_cognitive_account")
	object.get(rc.change.after, "custom_subdomain_name", null) in {null, ""}
	object.get(rc.change, ["after_unknown", "custom_subdomain_name"], false) != true # known only after apply: fine
	msg := sprintf("%s: a custom subdomain is required for Entra ID tokens", [rc.address])
}

# ACS: azurerm_communication_service can't disable its access keys (azurerm 4.81) -> ARM template only (D20).
deny contains msg if {
	some rc in resources("azurerm_communication_service")
	msg := sprintf("%s: use the ARM template (disableLocalAuth); azurerm_communication_service keeps its keys usable", [rc.address])
}

template_resources(rc, type) := [r |
	template := json.unmarshal(rc.change.after.template_content)
	some r in template.resources
	r.type == type
]

deny contains msg if {
	some rc in resources("azurerm_resource_group_template_deployment")
	some acs in template_resources(rc, "Microsoft.Communication/communicationServices")
	acs.properties.disableLocalAuth != true
	msg := sprintf("%s: Communication Services access keys must be disabled (disableLocalAuth = true)", [rc.address])
}

# App settings: the Function App's map is unknown in a plan, so the stack outputs the names it will set.
# A plain connection-string setting, or anything named like a key or secret, is a credential in config.
forbidden_setting(name) if name in {"AzureWebJobsStorage", "ServiceBusConnection", "COSMOS_KEY", "EVENTGRID_TOPIC_KEY"}

forbidden_setting(name) if regex.match(`(?i)(key|secret|password|connectionstring)$`, name)

deny contains msg if {
	some name in input.output_changes.summary.after.app_setting_names
	forbidden_setting(name)
	msg := sprintf("app setting %s: credentials in app settings are not allowed; use identity-based settings", [name])
}

deny contains msg if {
	not input.output_changes.summary.after.app_setting_names
	msg := "output summary.app_setting_names missing: the app settings gate can't run"
}
