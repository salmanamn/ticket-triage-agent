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

variable "notify_mailboxes" {
  description = "Mail recipients on Azure (CI: secret NOTIFY_MAILBOXES as JSON). Kept out of logs and the plan summary."
  type = object({
    escalation = string
    review     = string
  })
  sensitive = true
}

variable "operator_object_id" {
  description = "Your Entra object id (az ad signed-in-user show --query id -o tsv); empty = no operator data roles (D21)"
  type        = string
  default     = ""
}

module "stack" {
  source   = "../../modules/stack"
  name     = "triage-azure"
  location = var.location

  # Project 1 platform workspace. ID built from names: the data source would list its shared keys.
  log_analytics_workspace_id = "/subscriptions/${var.subscription_id}/resourceGroups/rg-slz-platform/providers/Microsoft.OperationalInsights/workspaces/log-slz-platform"

  # components: all on (defaults). Real Azure gets the full stack.
  notify_subscription_enabled = var.notify_subscription_enabled
  notify_mailboxes            = var.notify_mailboxes
  operator_object_id          = var.operator_object_id

  tags = {
    project    = "ticket-triage-agent"
    managed_by = "terraform"
    env        = "azure-lab"
  }
}

output "summary" {
  value = module.stack
}
