# Service Bus namespace + the `tickets` queue. Same queue contract as emulators/servicebus/config.json,
# except duplicate detection: the emulator caps the window at PT5M, Azure gets PT10M (D4).
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

resource "azurerm_servicebus_namespace" "this" {
  #checkov:skip=CKV_AZURE_202:A namespace identity is only used for CMK (Premium); the app uses its own identity
  #checkov:skip=CKV_AZURE_201:CMK needs the Premium tier (~$680/month); Standard is the lab tier
  #checkov:skip=CKV_AZURE_199:Double encryption needs Premium + CMK; see CKV_AZURE_201
  #checkov:skip=CKV_AZURE_204:Private endpoints and network rules need Premium; access is Entra-only (local auth disabled, D15)
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "Standard" # Basic has no duplicate detection

  local_auth_enabled            = true # no SAS keys or connection strings: managed identity only (D6)
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true # Standard has no private endpoints (D15)

  tags = var.tags
}

resource "azurerm_servicebus_queue" "tickets" {
  name         = "tickets"
  namespace_id = azurerm_servicebus_namespace.this.id

  requires_duplicate_detection            = true # MessageId = ticket_id (D8)
  duplicate_detection_history_time_window = "PT10M"
  max_delivery_count                      = var.max_delivery_count # = TRIAGE_MAX_ATTEMPTS (D11)
  lock_duration                           = "PT1M"
  default_message_ttl                     = "PT1H"
  dead_lettering_on_message_expiration    = true
  requires_session                        = false
  partitioning_enabled                    = false
}

resource "azurerm_monitor_diagnostic_setting" "namespace" {
  count                      = var.diagnostics_enabled ? 1 : 0
  name                       = "diag-to-law"
  target_resource_id         = azurerm_servicebus_namespace.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }
}
