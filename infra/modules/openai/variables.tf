variable "name" {
  description = "Account name and custom subdomain (globally unique)"
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "chat" {
  description = "Chat deployment: model, version, sku (GlobalStandard), capacity in thousands of TPM"
  type = object({
    model    = string
    version  = string
    sku      = string
    capacity = number
  })
}

variable "embedding" {
  description = "Embedding deployment; the model must return var.dimensions-sized vectors (text-embedding-3-small, dimensions = 768)"
  type = object({
    model    = string
    version  = string
    sku      = string
    capacity = number
  })
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
