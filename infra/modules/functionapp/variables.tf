variable "name" {
  description = "Name stem plus suffix; the app is func-<name>, the plan asp-<name>"
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "identity_id" {
  description = "User-assigned identity the app runs as (also reads its deployment package)"
  type        = string
}

variable "identity_client_id" {
  type = string
}

variable "storage_account_name" {
  type = string
}

variable "storage_primary_blob_endpoint" {
  type = string
}

variable "deployment_container_name" {
  type = string
}

variable "application_insights_connection_string" {
  description = "Connection string of the stack's Application Insights (not a secret: ingestion needs Entra, local auth is off)"
  type        = string
}

variable "maximum_instance_count" {
  description = "Flex scale-out ceiling (1-1000). Small on purpose: the lab budget and the LLM's throughput bound it."
  type        = number
}

variable "app_settings" {
  description = "Application settings (endpoints and names only; infra/policy denies keys and connection strings)"
  type        = map(string)
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
