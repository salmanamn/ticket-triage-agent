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
    openai       = optional(bool, true) # Microsoft.CognitiveServices accounts + deployments
    email        = optional(bool, true) # Microsoft.Communication email service, domain, communication service
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

variable "chat_deployment" {
  description = "Azure OpenAI chat deployment (D19). gpt-5.4-mini: GA, Global Standard in uaenorth, strict structured outputs."
  type = object({
    model    = string
    version  = string
    sku      = string
    capacity = number
  })
  default = {
    model    = "gpt-5.4-mini"
    version  = "2026-03-17"
    sku      = "GlobalStandard"
    capacity = 50
  }
}

variable "chat_reasoning_effort" {
  description = "reasoning_effort for the chat model; empty for a classic (non-reasoning) model (D19)"
  type        = string
  default     = "low"
}

variable "chat_max_output_tokens" {
  description = "max_completion_tokens for a reasoning model: hidden reasoning tokens count against it"
  type        = number
  default     = 4000
}

variable "embedding_deployment" {
  description = "Azure OpenAI embedding deployment; asked for embedding_dimensions-sized vectors (D9)"
  type = object({
    model    = string
    version  = string
    sku      = string
    capacity = number
  })
  default = {
    model    = "text-embedding-3-small"
    version  = "1"
    sku      = "Standard"
    capacity = 50
  }
}

variable "email_data_location" {
  description = "ACS data location (data at rest)"
  type        = string
  default     = "UAE"
}

variable "notify_mailboxes" {
  description = "Where notify_ticket sends mail on Azure: High/Critical escalations and injection reviews"
  type = object({
    escalation = string
    review     = string
  })
  sensitive = true
}

variable "email_sender_role_definition_id" {
  description = "Custom role 'SLZ Email Sender' (Project 1 bootstrap): send email through ACS with Entra ID (D20)"
  type        = string
  default     = "fca60e2f-9abf-5087-a329-0814cea30909"
}

variable "operator_object_id" {
  description = "Entra object id of the human operator: data roles to seed the KB and read records from the laptop (D21). Empty = none."
  type        = string
  default     = ""
}

variable "extra_app_settings" {
  description = "More app settings. Names/endpoints only, no secrets."
  type        = map(string)
  default     = {}
}
