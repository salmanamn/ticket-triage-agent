# Diagnostics to log-slz-platform for every resource with resource logs, and a closed list of
# data-plane roles (D16).
package main

import rego.v1

# --- Diagnostics -------------------------------------------------------------------------------

# Resource types that must have a diagnostic setting in the same module.
monitored := {
	"azurerm_servicebus_namespace",
	"azurerm_cosmosdb_account",
	"azurerm_eventgrid_topic",
	"azurerm_function_app_flex_consumption",
	"azurerm_storage_account",
	"azurerm_cognitive_account",
}

diag_modules := {object.get(rc, "module_address", "") | some rc in resources("azurerm_monitor_diagnostic_setting")}

deny contains msg if {
	some type in monitored
	some rc in resources(type)
	not object.get(rc, "module_address", "") in diag_modules
	msg := sprintf("%s: no diagnostic setting in %s", [rc.address, object.get(rc, "module_address", "root")])
}

# The Communication Services resource is a template deployment (D20); its module must have a diagnostic setting too.
deny contains msg if {
	some rc in resources("azurerm_resource_group_template_deployment")
	count(template_resources(rc, "Microsoft.Communication/communicationServices")) > 0
	not object.get(rc, "module_address", "") in diag_modules
	msg := sprintf("%s: no diagnostic setting for the Communication Services resource", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_monitor_diagnostic_setting")
	not is_platform_workspace(rc.change.after.log_analytics_workspace_id)
	msg := sprintf("%s: diagnostics must go to log-slz-platform", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_monitor_diagnostic_setting")
	not "allLogs" in {l.category_group | some l in rc.change.after.enabled_log}
	msg := sprintf("%s: enable category group allLogs", [rc.address])
}

deny contains msg if {
	some rc in resources("azurerm_application_insights")
	not is_platform_workspace(rc.change.after.workspace_id)
	msg := sprintf("%s: Application Insights must be workspace-based on log-slz-platform", [rc.address])
}

# --- RBAC --------------------------------------------------------------------------------------

allowed_roles := {
	"b7e6dc6d-f1e8-4753-8033-0f276bb0955b", # Storage Blob Data Owner (host storage)
	"ba92f5b4-2d11-453d-a403-e96b0029c9fe", # Storage Blob Data Contributor (Event Grid dead-letter)
	"69a216fc-b8fb-44d8-bc22-1f3c2cd27a39", # Azure Service Bus Data Sender
	"4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0", # Azure Service Bus Data Receiver
	"d5a91429-5739-47e2-a06b-3470a27159e7", # EventGrid Data Sender
	"3913510d-42f4-4e42-8a64-420c390055eb", # Monitoring Metrics Publisher
	"5e0bd9bd-7b93-4f28-af87-19fc36ad61bd", # Cognitive Services OpenAI User
	"fca60e2f-9abf-5087-a329-0814cea30909", # SLZ Email Sender (custom, Project 1 bootstrap, D20)
}

# The only role a human (the operator, D21) may get from this stack: embeddings/chat for seeding and the eval.
operator_roles := {"5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"}

role_guid(rc) := guid if {
	parts := split(rc.change.after.role_definition_id, "/")
	guid := parts[count(parts) - 1]
}

deny contains msg if {
	some rc in resources("azurerm_role_assignment")
	not role_guid(rc) in allowed_roles
	msg := sprintf("%s: role %v is not on the data-plane allowlist", [rc.address, object.get(rc.change.after, "role_definition_id", "<by name>")])
}

deny contains msg if {
	some rc in resources("azurerm_role_assignment")
	not principal_allowed(rc)
	msg := sprintf("%s: roles go to managed identities (ServicePrincipal); a User only gets Cognitive Services OpenAI User", [rc.address])
}

principal_allowed(rc) if rc.change.after.principal_type == "ServicePrincipal"

principal_allowed(rc) if {
	rc.change.after.principal_type == "User"
	role_guid(rc) in operator_roles
}

# A scope known at plan time must be a resource, never a subscription or resource group.
deny contains msg if {
	some rc in resources("azurerm_role_assignment")
	scope := rc.change.after.scope
	is_string(scope)
	regex.match(`^/subscriptions/[^/]+(/resourceGroups/[^/]+)?/?$`, scope)
	msg := sprintf("%s: scope %s is too broad", [rc.address, scope])
}

# Cosmos data plane: Built-in Data Contributor only (never the account-wide Data Owner equivalent).
deny contains msg if {
	some rc in resources("azurerm_cosmosdb_sql_role_assignment")
	id := rc.change.after.role_definition_id
	is_string(id)
	not endswith(id, "/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002")
	msg := sprintf("%s: Cosmos role must be Built-in Data Contributor", [rc.address])
}
