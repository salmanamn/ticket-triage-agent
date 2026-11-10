variable "full_stack" {
  description = <<-EOT
    false (default): only what floci-az 0.16.0 can create, for plan and apply.
    true: every component, for `plan` only (the CI policy gate). Never apply with true:
    floci-az 0.16.0 answers 404 for Service Bus, Cosmos DB, App Service plans, App Insights and role assignments (D18).
  EOT
  type        = bool
  default     = false
}

data "azurerm_client_config" "current" {}

module "stack" {
  source   = "../../modules/stack"
  name     = "triage-local"
  location = "eastus"

  # Same id shape as on Azure. floci-az can't create workspaces (no deletedWorkspaces API), but it stores
  # diagnostic settings without checking their destination, so the settings are still created locally.
  log_analytics_workspace_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-slz-platform/providers/Microsoft.OperationalInsights/workspaces/log-slz-platform"

  components = {
    servicebus   = var.full_stack
    cosmos       = var.full_stack
    eventgrid    = var.full_stack
    function_app = var.full_stack
    rbac         = var.full_stack
  }

  # floci-az has WebHook destinations only, and azurerm accepts https webhooks only. The local Functions host
  # serves plain http, so this subscription is stored but not used: locally the Event Grid stub delivers (D13).
  notify_webhook_url = "https://host.docker.internal:7071/runtime/webhooks/EventGrid?functionName=notify_ticket"

  tags = {
    project    = "ticket-triage-agent"
    managed_by = "terraform"
    env        = "local"
  }
}

output "summary" {
  value = module.stack
}
