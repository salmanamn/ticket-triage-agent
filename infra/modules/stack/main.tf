# Composition root: everything both environments deploy.
# envs/local and envs/azure call only this module and differ ONLY in provider config and inputs.
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
    random  = { source = "hashicorp/random" }
  }
}

data "azurerm_client_config" "current" {}

# Storage, Service Bus, Cosmos, Event Grid and Function App names are global DNS names -> random suffix
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  suffixed = "${var.name}-${random_string.suffix.result}"

  deployment_container = "app-package"          # Flex Consumption deployment package
  deadletter_container = "eventgrid-deadletter" # undeliverable Ticket.Triaged events
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = var.tags
}

# The one identity the app runs as. User-assigned, so its roles exist before the app starts (D16).
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name}-app"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
}

# Host storage of the Function App: AzureWebJobsStorage and the Flex deployment package. Only the app identity
# has a data role here (Storage Blob Data Owner, rbac.tf).
module "storage" {
  source                     = "../storage"
  name                       = "st${replace(var.name, "-", "")}${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  containers                 = [local.deployment_container]
  diagnostics_enabled        = var.diagnostics_enabled
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

# Event Grid dead-letters get a storage account of their own (D25). Event Grid insists on an account-scoped
# role for the topic identity (D24); on this account that role reaches nothing but dead-letters.
module "deadletter" {
  count                      = var.components.eventgrid ? 1 : 0
  source                     = "../storage"
  name                       = "stdl${replace(var.name, "-", "")}${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  containers                 = [local.deadletter_container]
  diagnostics_enabled        = var.diagnostics_enabled
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

module "messaging" {
  count                      = var.components.servicebus ? 1 : 0
  source                     = "../messaging"
  name                       = "sb-${local.suffixed}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  max_delivery_count         = var.max_delivery_count
  diagnostics_enabled        = var.diagnostics_enabled
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

module "cosmos" {
  count                      = var.components.cosmos ? 1 : 0
  source                     = "../cosmos"
  name                       = "cosmos-${local.suffixed}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  database_name              = "triage"
  embedding_dimensions       = var.embedding_dimensions
  diagnostics_enabled        = var.diagnostics_enabled
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

module "events" {
  count                         = var.components.eventgrid ? 1 : 0
  source                        = "../events"
  name                          = "evgt-${local.suffixed}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  subscription_id               = data.azurerm_client_config.current.subscription_id
  subscription_enabled          = var.notify_subscription_enabled && (var.notify_webhook_url != null || var.components.function_app)
  notify_function_id            = var.components.function_app ? "${module.functionapp[0].id}/functions/notify_ticket" : null
  notify_webhook_url            = var.notify_webhook_url
  deadletter_storage_account_id = module.deadletter[0].account_id
  deadletter_container_name     = module.deadletter[0].container_names[local.deadletter_container]
  role_assignments_enabled      = var.components.rbac
  diagnostics_enabled           = var.diagnostics_enabled
  log_analytics_workspace_id    = var.log_analytics_workspace_id
  tags                          = var.tags
}

module "openai" {
  count                      = var.components.openai ? 1 : 0
  source                     = "../openai"
  name                       = "oai-${local.suffixed}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  chat                       = var.chat_deployment
  embedding                  = var.embedding_deployment
  diagnostics_enabled        = var.diagnostics_enabled
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

module "email" {
  count                      = var.components.email ? 1 : 0
  source                     = "../email"
  name                       = local.suffixed
  resource_group_name        = azurerm_resource_group.this.name
  data_location              = var.email_data_location
  diagnostics_enabled        = var.diagnostics_enabled
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

locals {
  # Model and email settings (D19, D20). Values are endpoints, deployment names and mailbox addresses: no keys.
  openai_settings = var.components.openai ? {
    OPENAI_BASE_URL              = module.openai[0].base_url
    OPENAI_AUTH                  = "entra"
    CHAT_MODEL                   = module.openai[0].chat_deployment
    CHAT_REASONING_EFFORT        = var.chat_reasoning_effort
    TRIAGE_MAX_OUTPUT_TOKENS     = tostring(var.chat_max_output_tokens)
    EMBEDDING_MODEL              = module.openai[0].embedding_deployment
    EMBEDDING_REQUEST_DIMENSIONS = "true"
  } : {}

  email_settings = var.components.email ? {
    EMAIL_TRANSPORT    = "acs"
    ACS_ENDPOINT       = module.email[0].endpoint
    EMAIL_SENDER       = module.email[0].sender_address
    ESCALATION_MAILBOX = var.notify_mailboxes.escalation
    REVIEW_MAILBOX     = var.notify_mailboxes.review
  } : {}

  # Endpoints and names only. The Python settings module reads the same names locally (D6).
  app_settings = merge(
    {
      AZURE_CLIENT_ID = azurerm_user_assigned_identity.app.client_id # DefaultAzureCredential -> this identity

      ServiceBusConnection__fullyQualifiedNamespace = var.components.servicebus ? module.messaging[0].fully_qualified_namespace : ""
      ServiceBusConnection__credential              = "managedidentity"
      ServiceBusConnection__clientId                = azurerm_user_assigned_identity.app.client_id
      TICKETS_QUEUE                                 = var.components.servicebus ? module.messaging[0].queue_name : "tickets"
      TRIAGE_MAX_ATTEMPTS                           = tostring(var.max_delivery_count)

      COSMOS_ENDPOINT         = var.components.cosmos ? module.cosmos[0].endpoint : ""
      COSMOS_DATABASE         = var.components.cosmos ? module.cosmos[0].database_name : "triage"
      COSMOS_KB_CONTAINER     = var.components.cosmos ? module.cosmos[0].knowledge_container_name : "knowledge"
      COSMOS_TRIAGE_CONTAINER = var.components.cosmos ? module.cosmos[0].triage_container_name : "triage"
      EMBEDDING_DIMENSIONS    = tostring(var.embedding_dimensions)

      EVENTGRID_TOPIC_ENDPOINT = var.components.eventgrid ? module.events[0].topic_endpoint : ""
      EVENT_SOURCE             = "/pearlpay/ticket-triage"
    },
    local.openai_settings,
    local.email_settings,
    var.extra_app_settings,
  )

  # What the laptop scripts need to reach the deployed stack as the operator (scripts/azure_settings.py).
  client_settings = merge(
    {
      COSMOS_ENDPOINT         = local.app_settings.COSMOS_ENDPOINT
      COSMOS_DATABASE         = local.app_settings.COSMOS_DATABASE
      COSMOS_KB_CONTAINER     = local.app_settings.COSMOS_KB_CONTAINER
      COSMOS_TRIAGE_CONTAINER = local.app_settings.COSMOS_TRIAGE_CONTAINER
      EMBEDDING_DIMENSIONS    = local.app_settings.EMBEDDING_DIMENSIONS
      TRIAGE_MAX_ATTEMPTS     = local.app_settings.TRIAGE_MAX_ATTEMPTS
    },
    local.openai_settings,
  )
}

# Workspace-based: telemetry lands in log-slz-platform next to the resource logs.
resource "azurerm_application_insights" "this" {
  count                        = var.components.function_app ? 1 : 0
  name                         = "appi-${local.suffixed}"
  resource_group_name          = azurerm_resource_group.this.name
  location                     = azurerm_resource_group.this.location
  application_type             = "other"
  workspace_id                 = var.log_analytics_workspace_id
  local_authentication_enabled = false # ingestion needs Entra (Monitoring Metrics Publisher)
  tags                         = var.tags
}

module "functionapp" {
  count                                  = var.components.function_app ? 1 : 0
  source                                 = "../functionapp"
  name                                   = local.suffixed
  resource_group_name                    = azurerm_resource_group.this.name
  location                               = azurerm_resource_group.this.location
  identity_id                            = azurerm_user_assigned_identity.app.id
  identity_client_id                     = azurerm_user_assigned_identity.app.client_id
  storage_account_name                   = module.storage.account_name
  storage_primary_blob_endpoint          = module.storage.primary_blob_endpoint
  deployment_container_name              = module.storage.container_names[local.deployment_container]
  maximum_instance_count                 = var.function_maximum_instance_count
  application_insights_connection_string = azurerm_application_insights.this[0].connection_string
  app_settings                           = local.app_settings
  diagnostics_enabled                    = var.diagnostics_enabled
  log_analytics_workspace_id             = var.log_analytics_workspace_id
  tags                                   = var.tags

  # The host starts with its identity's data roles already in place (D16)
  depends_on = [azurerm_role_assignment.app, azurerm_cosmosdb_sql_role_assignment.app]
}
