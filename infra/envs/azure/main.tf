variable "subscription_id" {
  description = "Lab subscription (set in gitignored terraform.tfvars)"
  type        = string
}

variable "location" {
  description = "Must offer Flex Consumption (az functionapp list-flexconsumption-locations)"
  type        = string
  default     = "uaenorth"
}

variable "notify_subscription_enabled" {
  description = "false until the code is deployed (M8): Event Grid validates the notify_ticket function on create"
  type        = bool
  default     = false
}

module "stack" {
  source   = "../../modules/stack"
  name     = "triage-azure"
  location = var.location

  # Project 1 platform workspace. ID built from names: the data source would list its shared keys.
  log_analytics_workspace_id = "/subscriptions/${var.subscription_id}/resourceGroups/rg-slz-platform/providers/Microsoft.OperationalInsights/workspaces/log-slz-platform"

  # components: all on (defaults). Real Azure gets the full stack.
  notify_subscription_enabled = var.notify_subscription_enabled

  tags = {
    project    = "ticket-triage-agent"
    managed_by = "terraform"
    env        = "azure-lab"
  }
}

output "summary" {
  value = module.stack
}
