# Flex Consumption Function App (Python 3.13, D1) on a user-assigned identity, sending telemetry to
# the stack's workspace-based Application Insights. Every connection is identity-based: no keys or
# connection strings in app settings (D6, enforced by infra/policy).
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

resource "azurerm_service_plan" "this" {
  #checkov:skip=CKV_AZURE_225:Zone redundancy needs always-ready instances (billed while idle); not for a lab
  #checkov:skip=CKV_AZURE_212:Flex Consumption scales from zero; a minimum instance count is always-ready billing
  name                = "asp-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "FC1" # Flex Consumption
  tags                = var.tags
}

locals {
  # The host's own connections. AzureWebJobsStorage as an account name + identity, never a connection string.
  host_settings = {
    AzureWebJobsStorage__accountName          = var.storage_account_name
    AzureWebJobsStorage__credential           = "managedidentity"
    AzureWebJobsStorage__clientId             = var.identity_client_id
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING = "ClientId=${var.identity_client_id};Authorization=AAD"
  }
}

resource "azurerm_function_app_flex_consumption" "this" {
  name                = "func-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.this.id

  runtime_name    = "python"
  runtime_version = "3.13"

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${var.storage_primary_blob_endpoint}${var.deployment_container_name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = var.identity_id

  instance_memory_in_mb  = 2048
  maximum_instance_count = var.maximum_instance_count

  https_only                                     = true
  public_network_access_enabled                  = true # POST /api/tickets is the public entry point (function key)
  webdeploy_publish_basic_authentication_enabled = false
  client_certificate_mode                        = "Optional"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  site_config {
    application_insights_connection_string = var.application_insights_connection_string
    minimum_tls_version                    = "1.2"
    scm_minimum_tls_version                = "1.2"
    http2_enabled                          = true
  }

  app_settings = merge(var.app_settings, local.host_settings)

  tags = var.tags
}

resource "azurerm_monitor_diagnostic_setting" "app" {
  count                      = var.diagnostics_enabled ? 1 : 0
  name                       = "diag-to-law"
  target_resource_id         = azurerm_function_app_flex_consumption.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }
}
