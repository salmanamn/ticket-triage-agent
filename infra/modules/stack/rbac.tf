# Every data-plane permission the app identity holds, each at the narrowest scope (D16).
# Built-in roles by id, not name (no lookup at apply). Nothing at resource-group or subscription scope.
locals {
  role_ids = {
    storage_blob_data_owner      = "b7e6dc6d-f1e8-4753-8033-0f276bb0955b"
    servicebus_data_sender       = "69a216fc-b8fb-44d8-bc22-1f3c2cd27a39"
    servicebus_data_receiver     = "4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0"
    eventgrid_data_sender        = "d5a91429-5739-47e2-a06b-3470a27159e7"
    monitoring_metrics_publisher = "3913510d-42f4-4e42-8a64-420c390055eb"
  }

  app_roles = merge(
    var.components.eventgrid ? {
      # Ticket.Triaged publisher (events.EventGridPublisher)
      eventgrid_sender = { scope = module.events[0].topic_id, role = "eventgrid_data_sender" }
    } : {},
    var.components.function_app ? {
      # Host storage (leases, keys) and the Flex deployment package
      storage_host = { scope = module.storage.account_id, role = "storage_blob_data_owner" }
      # Telemetry ingestion with local auth disabled
      appinsights = { scope = azurerm_application_insights.this[0].id, role = "monitoring_metrics_publisher" }
    } : {},
    var.components.servicebus ? {
      # submit_ticket sends, triage_ticket receives; both only on the tickets queue
      queue_send    = { scope = module.messaging[0].queue_id, role = "servicebus_data_sender" }
      queue_receive = { scope = module.messaging[0].queue_id, role = "servicebus_data_receiver" }
    } : {},
  )
}

resource "azurerm_role_assignment" "app" {
  for_each           = var.components.rbac ? local.app_roles : {}
  scope              = each.value.scope
  role_definition_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.role_ids[each.value.role]}"
  principal_id       = azurerm_user_assigned_identity.app.principal_id
  principal_type     = "ServicePrincipal"
  description        = "ticket-triage app identity: ${each.key}"
}

# Cosmos data plane has its own RBAC. Built-in Data Contributor, scoped to the triage database only.
resource "azurerm_cosmosdb_sql_role_assignment" "app" {
  count               = var.components.rbac && var.components.cosmos ? 1 : 0
  resource_group_name = azurerm_resource_group.this.name
  account_name        = module.cosmos[0].account_name
  role_definition_id  = "${module.cosmos[0].account_id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.app.principal_id
  scope               = "${module.cosmos[0].account_id}/dbs/${module.cosmos[0].database_name}"
}
