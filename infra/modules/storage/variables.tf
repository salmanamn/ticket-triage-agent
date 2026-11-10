variable "name" {
  description = "Storage account name (3-24 lowercase letters and digits, globally unique)"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.name))
    error_message = "name: 3-24 lowercase letters and digits."
  }
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
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
