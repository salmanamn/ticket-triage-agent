variable "name" {
  description = "Name stem plus suffix: ecs-<name> (email service), acs-<name> (communication service)"
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "data_location" {
  description = "Where ACS stores email data at rest (UAE for a uaenorth stack)"
  type        = string
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
