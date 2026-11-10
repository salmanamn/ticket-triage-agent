variable "name" {
  description = "Name stem, e.g. triage-local or triage-azure"
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,13}$", var.name))
    error_message = "name: 3-14 chars, lowercase letters/digits/hyphens, starts with a letter."
  }
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "log_analytics_workspace_id" {
  description = "Central workspace for diagnostics and Application Insights (log-slz-platform)"
  type        = string
}

variable "diagnostics_enabled" {
  description = "Diagnostic settings on every resource that has logs"
  type        = bool
  default     = true
}

variable "components" {
  description = "Everything is on by default. envs/local turns off what floci-az 0.16.0 can't create (D18)."
  type = object({
    servicebus   = optional(bool, true) # Microsoft.ServiceBus
    cosmos       = optional(bool, true) # Microsoft.DocumentDB
    eventgrid    = optional(bool, true) # Microsoft.EventGrid topics + subscriptions
    function_app = optional(bool, true) # Microsoft.Web/serverfarms (FC1) + sites + Microsoft.Insights/components
    rbac         = optional(bool, true) # Microsoft.Authorization/roleAssignments + Cosmos sqlRoleAssignments
  })
  default = {}
}

variable "notify_subscription_enabled" {
  description = "Create the Event Grid notify subscription. On Azure only after the code is deployed (Event Grid validates the function)."
  type        = bool
  default     = true
}

variable "notify_webhook_url" {
  description = "Deliver notify events to this webhook instead of the notify_ticket function (floci-az)"
  type        = string
  default     = null
}

variable "max_delivery_count" {
  description = "Service Bus MaxDeliveryCount for tickets = the app's TRIAGE_MAX_ATTEMPTS (D11)"
  type        = number
  default     = 5
}

variable "embedding_dimensions" {
  description = "Vector size in the knowledge container and EMBEDDING_DIMENSIONS (D9)"
  type        = number
  default     = 768
}

variable "function_maximum_instance_count" {
  type    = number
  default = 10
}

variable "extra_app_settings" {
  description = "More app settings (M8: model endpoints and email). Names/endpoints only, no secrets."
  type        = map(string)
  default     = {}
}
