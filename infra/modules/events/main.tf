# Event Grid custom topic for Ticket.Triaged (CloudEvents 1.0, D13) and the `notify` subscription.
# Publishers authenticate with Entra ID only (EventGrid Data Sender, local auth disabled).
# Undeliverable events go to a blob container, written with the topic's own managed identity (D16).
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

resource "azurerm_eventgrid_topic" "this" {
  #checkov:skip=CKV_AZURE_193:Public network access: the Flex app has no VNet integration in the lab (D15); Entra-only publish
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name

  input_schema                  = "CloudEventSchemaV1_0"
  local_auth_enabled            = false # no topic keys: managed identity only (D6)
  public_network_access_enabled = true  # D15

  identity {
    type = "SystemAssigned" # writes dead-letters to blob
  }

  tags = var.tags
}

resource "azurerm_role_assignment" "topic_deadletter" {
  count              = var.role_assignments_enabled ? 1 : 0
  scope              = var.deadletter_container_id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe" # Storage Blob Data Contributor
  principal_id       = azurerm_eventgrid_topic.this.identity[0].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_eventgrid_event_subscription" "notify" {
  count                 = var.subscription_enabled ? 1 : 0
  name                  = "notify"
  scope                 = azurerm_eventgrid_topic.this.id
  event_delivery_schema = "CloudEventSchemaV1_0"
  included_event_types  = ["Ticket.Triaged"] # routing is in code (D13)

  # Azure: the notify_ticket function. Local (floci-az): the Functions host's Event Grid webhook.
  dynamic "azure_function_endpoint" {
    for_each = var.notify_webhook_url == null ? [1] : []
    content {
      function_id                       = var.notify_function_id
      max_events_per_batch              = 1
      preferred_batch_size_in_kilobytes = 64
    }
  }

  dynamic "webhook_endpoint" {
    for_each = var.notify_webhook_url == null ? [] : [1]
    content {
      url = var.notify_webhook_url
    }
  }

  retry_policy {
    max_delivery_attempts = 5    # same as the local stub
    event_time_to_live    = 1440 # minutes
  }

  dead_letter_identity {
    type = "SystemAssigned"
  }

  storage_blob_dead_letter_destination {
    storage_account_id          = var.deadletter_storage_account_id
    storage_blob_container_name = var.deadletter_container_name
  }

  depends_on = [azurerm_role_assignment.topic_deadletter]
}

resource "azurerm_monitor_diagnostic_setting" "topic" {
  count                      = var.diagnostics_enabled ? 1 : 0
  name                       = "diag-to-law"
  target_resource_id         = azurerm_eventgrid_topic.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }
}
