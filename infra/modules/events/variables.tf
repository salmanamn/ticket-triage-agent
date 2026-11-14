variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "subscription_id" {
  description = "Azure subscription id, for built-in role definition ids"
  type        = string
}

variable "subscription_enabled" {
  description = "Create the notify subscription. Azure validates the function endpoint, so the code must be deployed first (M8)."
  type        = bool
}

variable "notify_function_id" {
  description = "<function app id>/functions/notify_ticket; used when notify_webhook_url is null"
  type        = string
  default     = null
}

variable "notify_webhook_url" {
  description = "Webhook endpoint instead of the function (floci-az has only WebHook destinations)"
  type        = string
  default     = null
}

variable "deadletter_storage_account_id" {
  description = "Storage account that holds nothing but dead-letters: the topic identity gets its blob role on the whole account (D24, D25)"
  type        = string
}

variable "deadletter_container_name" {
  type = string
}

variable "role_assignments_enabled" {
  type = bool
}

variable "diagnostics_enabled" {
  type = bool
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "tags" {
  type = map(string)
}
