variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "max_delivery_count" {
  description = "Deliveries before the broker dead-letters a ticket. The app's TRIAGE_MAX_ATTEMPTS must match."
  type        = number
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
