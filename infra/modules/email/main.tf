# Azure Communication Services Email (D20): an Email service with an Azure-managed domain (DoNotReply@<guid>.azurecomm.net)
# linked to a Communication Services resource the app sends through with its managed identity.
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

resource "azurerm_email_communication_service" "this" {
  name                = "ecs-${var.name}"
  resource_group_name = var.resource_group_name
  data_location       = var.data_location
  tags                = var.tags
}

resource "azurerm_email_communication_service_domain" "managed" {
  name                             = "AzureManagedDomain" # required name for domain_management = AzureManaged
  email_service_id                 = azurerm_email_communication_service.this.id
  domain_management                = "AzureManaged"
  user_engagement_tracking_enabled = false
  tags                             = var.tags
}

# The Communication Services resource is an ARM template deployment: azurerm 4.81 has no disableLocalAuth on
# azurerm_communication_service (keys would stay usable), and its refresh lists the keys on every plan (D20, same
# pattern as D17). linkedDomains replaces azurerm_communication_service_email_domain_association.
resource "azurerm_resource_group_template_deployment" "communication" {
  name                = "acs-communication-service"
  resource_group_name = var.resource_group_name
  deployment_mode     = "Incremental"
  template_content    = file("${path.module}/communication-service.json")
  parameters_content = jsonencode({
    name         = { value = "acs-${var.name}" }
    dataLocation = { value = var.data_location }
    domainId     = { value = azurerm_email_communication_service_domain.managed.id }
    tags         = { value = var.tags }
  })
}

locals {
  acs = jsondecode(azurerm_resource_group_template_deployment.communication.output_content)
}

resource "azurerm_monitor_diagnostic_setting" "communication" {
  count                          = var.diagnostics_enabled ? 1 : 0
  name                           = "diag-to-law"
  target_resource_id             = local.acs.id.value
  log_analytics_workspace_id     = var.log_analytics_workspace_id
  log_analytics_destination_type = "Dedicated" # ACSEmailSendMailOperational, ACSEmailStatusUpdateOperational, ...

  enabled_log {
    category_group = "allLogs"
  }
}
