# Run: conftest verify --policy infra/policy/
# A minimal plan with one compliant resource of each type passes; each test breaks one property.
package main

import rego.v1

ws := "/subscriptions/s/resourceGroups/rg-slz-platform/providers/Microsoft.OperationalInsights/workspaces/log-slz-platform"

role(guid) := sprintf("/subscriptions/s/providers/Microsoft.Authorization/roleDefinitions/%s", [guid])

knowledge_template := {"resources": [{
	"type": "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers",
	"properties": {"resource": {
		"partitionKey": {"paths": ["/kind"]},
		"vectorEmbeddingPolicy": {"vectorEmbeddings": [{"path": "/embedding", "dataType": "float32", "distanceFunction": "cosine", "dimensions": 768}]},
		"indexingPolicy": {
			"excludedPaths": [{"path": "/\"_etag\"/?"}, {"path": "/embedding/*"}],
			"vectorIndexes": [{"path": "/embedding", "type": "diskANN"}],
		},
	}},
}]}

acs_template := {"resources": [{
	"type": "Microsoft.Communication/communicationServices",
	"properties": {"dataLocation": "UAE", "disableLocalAuth": true},
}]}

rc(module, type, name, after) := {
	"address": sprintf("%s.%s.%s", [module, type, name]),
	"module_address": module,
	"type": type,
	"name": name,
	"change": {"actions": ["create"], "after": after},
}

diag(module) := rc(module, "azurerm_monitor_diagnostic_setting", "d", {
	"log_analytics_workspace_id": ws,
	"enabled_log": [{"category": "", "category_group": "allLogs"}],
})

good_resources := [
	rc("module.sb", "azurerm_servicebus_namespace", "this", {"sku": "Standard", "local_auth_enabled": false, "minimum_tls_version": "1.2"}),
	rc("module.sb", "azurerm_servicebus_queue", "tickets", {"requires_duplicate_detection": true, "max_delivery_count": 5, "dead_lettering_on_message_expiration": true}),
	diag("module.sb"),
	rc("module.cosmos", "azurerm_cosmosdb_account", "this", {
		"local_authentication_enabled": false, "access_key_metadata_writes_enabled": false, "minimal_tls_version": "Tls12",
		"capabilities": [{"name": "EnableServerless"}, {"name": "EnableNoSQLVectorSearch"}],
	}),
	rc("module.cosmos", "azurerm_resource_group_template_deployment", "knowledge", {"template_content": json.marshal(knowledge_template)}),
	rc("module.cosmos", "azurerm_cosmosdb_sql_role_assignment", "app", {"role_definition_id": "/x/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"}),
	diag("module.cosmos"),
	rc("module.events", "azurerm_eventgrid_topic", "this", {"input_schema": "CloudEventSchemaV1_0", "local_auth_enabled": false}),
	rc("module.events", "azurerm_eventgrid_event_subscription", "notify", {
		"event_delivery_schema": "CloudEventSchemaV1_0", "included_event_types": ["Ticket.Triaged"],
		"dead_letter_identity": [{"type": "SystemAssigned"}],
		"storage_blob_dead_letter_destination": [{"storage_blob_container_name": "eventgrid-deadletter"}],
	}),
	diag("module.events"),
	rc("module.st", "azurerm_storage_account", "this", {
		"shared_access_key_enabled": false, "allow_nested_items_to_be_public": false,
		"min_tls_version": "TLS1_2", "https_traffic_only_enabled": true,
	}),
	diag("module.st"),
	rc("module.func", "azurerm_function_app_flex_consumption", "this", {
		"runtime_name": "python", "runtime_version": "3.13", "storage_authentication_type": "UserAssignedIdentity",
		"https_only": true, "webdeploy_publish_basic_authentication_enabled": false,
		"site_config": [{"minimum_tls_version": "1.2"}],
	}),
	diag("module.func"),
	rc("module.stack", "azurerm_application_insights", "this", {"local_authentication_enabled": false, "workspace_id": ws}),
	rc("module.stack", "azurerm_role_assignment", "app", {"role_definition_id": role("69a216fc-b8fb-44d8-bc22-1f3c2cd27a39"), "principal_type": "ServicePrincipal"}),
	rc("module.oai", "azurerm_cognitive_account", "this", {"local_auth_enabled": false, "custom_subdomain_name": "oai-x"}),
	diag("module.oai"),
	rc("module.email", "azurerm_resource_group_template_deployment", "communication", {"template_content": json.marshal(acs_template)}),
	diag("module.email"),
	rc("module.stack", "azurerm_role_assignment", "operator_openai", {"role_definition_id": role("5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"), "principal_type": "User"}),
	rc("module.oai", "azurerm_cognitive_deployment", "chat", {"sku": [{"name": "GlobalStandard", "capacity": 50}]}),
	rc("module.st", "azurerm_storage_container", "this[\"app-package\"]", {"name": "app-package"}),
	rc("module.dl", "azurerm_storage_container", "this[\"eventgrid-deadletter\"]", {"name": "eventgrid-deadletter"}),
]

plan_of(resources, settings) := {
	"resource_changes": resources,
	"output_changes": {"summary": {"after": {"app_setting_names": settings}}},
}

good := plan_of(good_resources, ["AzureWebJobsStorage__accountName", "ServiceBusConnection__fullyQualifiedNamespace", "AZURE_CLIENT_ID"])

# Replace one value in the `after` of the resource at index i.
patched(i, key, value) := plan_of(
	array.concat(
		array.concat(array.slice(good_resources, 0, i), [json.patch(good_resources[i], [{"op": "add", "path": sprintf("/change/after/%s", [key]), "value": value}])]),
		array.slice(good_resources, i + 1, count(good_resources)),
	),
	good.output_changes.summary.after.app_setting_names,
)

test_good_plan_passes if {
	count(deny) == 0 with input as good
}

test_servicebus_sas_fails if {
	count(deny) == 1 with input as patched(0, "local_auth_enabled", true)
}

test_servicebus_basic_fails if {
	count(deny) == 1 with input as patched(0, "sku", "Basic")
}

test_queue_without_duplicate_detection_fails if {
	count(deny) == 1 with input as patched(1, "requires_duplicate_detection", false)
}

test_queue_delivery_count_must_match_app if {
	count(deny) == 1 with input as patched(1, "max_delivery_count", 10)
}

test_cosmos_keys_fail if {
	count(deny) == 1 with input as patched(3, "local_authentication_enabled", true)
}

test_cosmos_without_vector_search_fails if {
	count(deny) == 1 with input as patched(3, "capabilities", [{"name": "EnableServerless"}])
}

test_flat_vector_index_fails if {
	bad := json.patch(knowledge_template, [{"op": "replace", "path": "/resources/0/properties/resource/indexingPolicy/vectorIndexes/0/type", "value": "flat"}])
	count(deny) == 1 with input as patched(4, "template_content", json.marshal(bad))
}

test_cosmos_owner_like_role_fails if {
	count(deny) == 1 with input as patched(5, "role_definition_id", "/x/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001")
}

test_topic_keys_fail if {
	count(deny) == 1 with input as patched(7, "local_auth_enabled", true)
}

test_subscription_without_deadletter_fails if {
	count(deny) == 1 with input as patched(8, "storage_blob_dead_letter_destination", [])
}

test_shared_key_storage_fails if {
	count(deny) == 1 with input as patched(10, "shared_access_key_enabled", true)
}

test_connection_string_deployment_storage_fails if {
	count(deny) == 1 with input as patched(12, "storage_authentication_type", "StorageAccountConnectionString")
}

test_wrong_python_fails if {
	count(deny) == 1 with input as patched(12, "runtime_version", "3.12")
}

test_diagnostics_elsewhere_fail if {
	count(deny) == 1 with input as patched(13, "log_analytics_workspace_id", "/subscriptions/s/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/other")
}

test_missing_diagnostics_fail if {
	without := [r | some i, r in good_resources; i != 6] # drop the Cosmos diagnostic setting
	count(deny) == 1 with input as plan_of(without, good.output_changes.summary.after.app_setting_names)
}

test_owner_role_fails if {
	count(deny) == 1 with input as patched(15, "role_definition_id", role("8e3af657-a8ff-443c-a75c-2fe8c4bcb635"))
}

test_subscription_scope_fails if {
	count(deny) == 1 with input as patched(15, "scope", "/subscriptions/s")
}

test_connection_string_setting_fails if {
	count(deny) == 1 with input as plan_of(good_resources, ["ServiceBusConnection", "AZURE_CLIENT_ID"])
}

test_key_named_setting_fails if {
	count(deny) == 1 with input as plan_of(good_resources, ["OPENAI_API_KEY"])
}

test_openai_keys_fail if {
	count(deny) == 1 with input as patched(16, "local_auth_enabled", true)
}

test_openai_without_subdomain_fails if {
	count(deny) == 1 with input as patched(16, "custom_subdomain_name", null)
}

test_acs_keys_fail if {
	bad := json.patch(acs_template, [{"op": "replace", "path": "/resources/0/properties/disableLocalAuth", "value": false}])
	count(deny) == 1 with input as patched(18, "template_content", json.marshal(bad))
}

test_acs_without_diagnostics_fails if {
	without := [r | some i, r in good_resources; i != 19]
	count(deny) == 1 with input as plan_of(without, good.output_changes.summary.after.app_setting_names)
}

test_azurerm_communication_service_denied if {
	extra := array.concat(good_resources, [rc("module.email", "azurerm_communication_service", "this", {"data_location": "UAE"})])
	count(deny) == 1 with input as plan_of(extra, good.output_changes.summary.after.app_setting_names)
}

test_operator_with_data_owner_role_fails if {
	count(deny) == 1 with input as patched(20, "role_definition_id", role("b7e6dc6d-f1e8-4753-8033-0f276bb0955b"))
}

test_provisioned_deployment_fails if {
	count(deny) == 1 with input as patched(21, "sku", [{"name": "GlobalProvisionedManaged", "capacity": 15}])
}

test_deadletter_container_sharing_an_account_fails if {
	extra := array.concat(good_resources, [rc("module.dl", "azurerm_storage_container", "this[\"app-package\"]", {"name": "app-package"})])
	count(deny) == 1 with input as plan_of(extra, good.output_changes.summary.after.app_setting_names)
}

test_deadletter_container_in_host_storage_fails if {
	moved := array.concat(
		[r | some i, r in good_resources; i != 23],
		[rc("module.st", "azurerm_storage_container", "this[\"eventgrid-deadletter\"]", {"name": "eventgrid-deadletter"})],
	)
	count(deny) == 1 with input as plan_of(moved, good.output_changes.summary.after.app_setting_names)
}

test_deadletter_to_another_container_fails if {
	count(deny) == 1 with input as patched(8, "storage_blob_dead_letter_destination", [{"storage_blob_container_name": "app-package"}])
}
